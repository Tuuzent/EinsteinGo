"""控制器：把引擎会话包成「界面可直接渲染的视图模型 + 动作结果」。

硬约束
------
1. **不 import tkinter**。整个模块必须能在无 tkinter 的解释器上被 pytest 跑通。
2. **会话只归主线程**。后台 worker 只拿不可变快照（Position / 配置 / 毫秒 / Event），
   算完把结果塞进 Queue，由主线程 `poll()` 落子。
3. **非法走法绝不进 `session.play()`**。`play()` 先 `clock.stop_turn()` 再校验，
   非法走法会让本回合时钟提前停走且保留骰值 —— 等于白送无限思考时间。
   所以先查本回合缓存好的合法走法索引，未命中只做无副作用诊断。
"""

from __future__ import annotations

import queue
import random
import threading
from typing import Callable

from ..constants import RED, SIDE_NAME, num_of, side_of, sq_name
from ..errors import EngineError, ErrorCode
from ..move import Move
from ..movegen import resolve_candidates
from ..ai import mcts
from ..session import GameSession
from ..state import find_piece
from ..sync import SyncMode, apply_remote_move, verify_state_equal
from . import errors_view as EV
from .logbus import DEFAULT_LOG, LogBus
from .model import (
    DIFFICULTY_LABEL,
    SIDE_LABEL,
    Mode,
    Phase,
    GameSetup,
    build_cells,
    resolve_config,
)
from .record_io import export_record as _export_record
from .thinker import Thinker

POLL_HINT_MS = 30


class GameController:
    # ---------------- 构造 ----------------
    def __init__(
        self,
        setup: GameSetup | None = None,
        *,
        time_source=None,
        die_source: Callable[[], int] | None = None,
        thinker: Thinker | None = None,
        async_think: bool = True,
        logger: LogBus | None = None,
    ) -> None:
        self._setup = setup or GameSetup()
        self._time_source = time_source
        self._die_source = die_source
        self._thinker = thinker or Thinker()
        self._async = async_think
        self._log = logger or DEFAULT_LOG

        self._session: GameSession | None = None
        self._cfg = resolve_config(self._setup.difficulty, self._setup.seed)
        self._phase = Phase.GAME_OVER
        self._selection: dict | None = None
        self._last_move: Move | None = None
        self._last_search: mcts.SearchResult | None = None
        self._capture_flash: tuple[int, int] | None = None
        self._notice: tuple[str, str, str] | None = None
        self._match_report: dict | None = None
        self._legal_cache: dict | None = None

        self._token = 0
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue = queue.Queue()
        self._cancel: threading.Event | None = None
        self._alive = True

    # ---------------- 只读 ----------------
    @property
    def session(self) -> GameSession | None:
        return self._session

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def setup(self) -> GameSetup:
        return self._setup

    @property
    def config(self):
        return self._cfg

    def is_busy(self) -> bool:
        return self._phase is Phase.THINKING

    def clock_view(self) -> dict:
        """轻量时钟快照，给界面每 200ms 刷新用（不重建 25 格视图）。"""
        return self._clock_view()

    # ---------------- 结果包装 ----------------
    def _result(self, ok: bool, code=None, message: str = "", severity: str = "none",
                extra: dict | None = None) -> dict:
        return {
            "ok": ok,
            "code": code.value if isinstance(code, ErrorCode) else (str(code) if code else None),
            "message": message,
            "severity": severity,
            "view": self.view(),
            "extra": extra or {},
        }

    def _ok(self, message: str = "", severity: str = "none", extra: dict | None = None) -> dict:
        return self._result(True, None, message, severity, extra)

    def _fail(self, code, message: str = "", severity: str = "error",
              extra: dict | None = None) -> dict:
        text = message or EV.error_text(code)
        if severity in ("error", "warn"):
            tag = code.value if isinstance(code, ErrorCode) else code
            self._log.log(f"拒绝操作 [{tag}] {text}", level="warn")
        return self._result(False, code, text, severity, extra)

    # ---------------- 生命周期 ----------------
    def new_game(self, setup: GameSetup | None = None) -> dict:
        self._cancel_think()
        self._token += 1
        self._queue = queue.Queue()
        if setup is not None:
            self._setup = setup
        self._cfg = resolve_config(self._setup.difficulty, self._setup.seed)
        self._session = GameSession(
            first_player=RED,
            budget_ms=self._setup.budget_ms,
            seed=self._setup.seed,
            time_source=self._time_source,
            die_source=self._die_source,
        )
        self._selection = None
        self._last_move = None
        self._last_search = None
        self._capture_flash = None
        self._match_report = None
        self._notice = None
        self._legal_cache = None
        self._log.log(
            f"新局 · {self._setup.mode.label} · 我方执{SIDE_LABEL[self._setup.human_side]} · "
            f"难度{DIFFICULTY_LABEL[self._setup.difficulty]} · seed={self._setup.seed}"
        )
        self._enter_turn()
        return self._ok()

    def shutdown(self) -> None:
        """幂等：停线程、取消搜索、丢队列。窗口关闭时调用。"""
        self._alive = False
        self._cancel_think()
        self._token += 1
        self._log.log("界面关闭")

    # ---------------- 回合调度 ----------------
    def _enter_turn(self) -> None:
        self._selection = None
        self._legal_cache = None
        s = self._session
        if s is None or s.finished:
            self._phase = Phase.GAME_OVER
            return

        if s.side != self._setup.human_side:
            if self._setup.mode is Mode.MATCH:
                self._phase = Phase.MATCH_WAIT
                return
            self._phase = Phase.THINKING
            self._begin_think()
            return

        if self._setup.mode is Mode.MATCH and self._setup.auto_reply:
            self._phase = Phase.THINKING
            self._begin_think()
            return

        self._phase = Phase.HUMAN_TURN
        if self._setup.auto_roll and s.die == 0:
            self._do_roll()

    def _begin_think(self) -> None:
        s = self._session
        if s is None or s.finished:
            self._phase = Phase.GAME_OVER
            return
        if s.die == 0:
            self._do_roll()
        if s.finished:
            self._phase = Phase.GAME_OVER
            return
        self._start_think()

    def _do_roll(self) -> int:
        s = self._session
        if s is None:
            return 0
        try:
            die = s.roll()
            self._log.log(f"掷骰 ply {s.ply + 1} {'R' if s.side > 0 else 'B'} → {die}")
            return die
        except EngineError as exc:
            if exc.code is ErrorCode.CLOCK_FLAG_FALLEN:
                self._phase = Phase.GAME_OVER
                self._notice = ("error", exc.code.value, "本方计时耗尽，判负")
            else:
                self._notice = ("warn", exc.code.value, str(exc))
            self._log.log(f"掷骰失败 [{exc.code.value}] {exc}", level="warn")
            return 0

    # ---------------- 人类动作 ----------------
    def roll_die(self) -> dict:
        if self._phase is Phase.THINKING:
            return self._fail("BUSY", severity="warn")
        s = self._session
        if s is None or s.finished:
            return self._fail(ErrorCode.GAME_ALREADY_OVER, severity="warn")
        if s.die != 0:
            return self._fail(ErrorCode.DIE_ALREADY_ROLLED, severity="warn")
        die = self._do_roll()
        if self._phase is Phase.GAME_OVER:
            return self._fail(ErrorCode.CLOCK_FLAG_FALLEN)
        return self._ok(f"掷出 {die}", extra={"die": die})

    def select_square(self, sq: int) -> dict:
        if self._phase is Phase.THINKING:
            return self._fail("BUSY", severity="warn")
        s = self._session
        if s is None or s.finished:
            return self._fail(ErrorCode.GAME_ALREADY_OVER, severity="warn")
        if not 0 <= sq < 25:
            return self._fail(ErrorCode.OUT_OF_BOARD, severity="warn")
        if not self._can_control(s.side):
            return self._fail(ErrorCode.NOT_YOUR_TURN, severity="warn",
                              extra={"selectable": False, "reason": "NOT_YOUR_TURN"})

        code = s.pos.squares[sq]
        if code == 0:
            self._selection = None
            return self._ok("", extra={"selectable": False, "reason": "EMPTY"})
        if side_of(code) != s.side:
            self._selection = None
            if self._in_remote_turn():
                return self._ok(f"现在轮到对方：点{SIDE_LABEL[s.side]}方棋子替他走",
                                severity="info",
                                extra={"selectable": False, "reason": "NOT_ACTING_SIDE"})
            return self._ok("那是对方的棋子", severity="info",
                            extra={"selectable": False, "reason": "NOT_YOUR_PIECE"})
        if s.die == 0:
            self._selection = None
            if self._in_remote_turn():
                return self._fail("REMOTE_DIE_REQUIRED",
                                  "先选对方骰值（1–6），再点对方棋子代走",
                                  severity="warn",
                                  extra={"selectable": False, "reason": "REMOTE_DIE_REQUIRED"})
            return self._fail(ErrorCode.DIE_NOT_ROLLED, "先掷骰再走子", severity="warn",
                              extra={"selectable": False, "reason": "DIE_NOT_ROLLED"})

        piece = num_of(code)
        alive = s.pos.alive(s.side)
        cands = resolve_candidates(alive, s.die)
        if piece not in cands:
            self._selection = None
            msg = EV.explain_error(ErrorCode.DIE_PIECE_MISMATCH, die=s.die, alive=alive, piece=piece)
            return self._fail(ErrorCode.DIE_PIECE_MISMATCH, msg,
                              extra={"selectable": False, "reason": "NOT_IN_CANDIDATES"})

        moves = [m for m in self._legal_index().values() if m.piece == piece]
        if not moves:
            self._selection = None
            return self._ok("这枚棋子当前没有可走的目标格", severity="info",
                            extra={"selectable": False, "reason": "NO_TARGET"})

        moves.sort(key=lambda m: m.dst)
        target_map = {m.dst: m.captured for m in moves}
        self._selection = {
            "piece": piece,
            "src": sq,
            "targets": [
                {"dst": m.dst, "name": sq_name(m.dst), "captured": m.captured}
                for m in moves
            ],
            "target_map": target_map,
        }
        return self._ok("", extra={
            "selectable": True,
            "piece": piece,
            "src": sq,
            "targets": self._selection["targets"],
            "reason": "",
        })

    def clear_selection(self) -> dict:
        self._selection = None
        return self._ok()

    def commit_move(self, piece: int, dst: int) -> dict:
        if self._phase is Phase.THINKING:
            return self._fail("BUSY", "AI 正在思考，暂不能落子", severity="warn")
        s = self._session
        if s is None or s.finished:
            return self._fail(ErrorCode.GAME_ALREADY_OVER, severity="warn")
        if s.die == 0:
            return self._fail(ErrorCode.DIE_NOT_ROLLED, severity="warn")
        if not 0 <= dst < 25:
            return self._fail(ErrorCode.OUT_OF_BOARD)
        if not self._can_control(s.side):
            return self._fail(ErrorCode.NOT_YOUR_TURN, "现在不是能操作的回合", severity="warn")

        src = find_piece(s.pos.squares, s.side * piece)
        mv = self._legal_index().get((piece, src, dst))
        if mv is None:
            return self._diagnose(piece, src, dst)

        if self._in_remote_turn():
            # 代替对方走子：仍然构造成走法文本，交给同步层六层对账，语义与粘贴一致
            self._log.log(f"棋盘代走 {mv.to_compact()}")
            return self._apply_remote(mv.to_compact())

        mover = s.side
        s.play(mv)                     # 到这里必然成功，时钟只被正确扣一次
        self._log.log(f"落子 {mv.to_compact()}（ply {s.ply}）")
        self._after_move(mv, mover)
        return self._ok()

    def _diagnose(self, piece: int, src: int, dst: int) -> dict:
        """非法走法的无副作用诊断：只在不可变状态上试算，绝不调用 session.play。"""
        s = self._session
        if s.die == 0:
            return self._fail(ErrorCode.DIE_NOT_ROLLED, severity="warn")
        alive = s.pos.alive(s.side)
        if src < 0:
            return self._fail(ErrorCode.PIECE_ALREADY_CAPTURED)
        if piece not in resolve_candidates(alive, s.die):
            msg = EV.explain_error(ErrorCode.DIE_PIECE_MISMATCH, die=s.die, alive=alive, piece=piece)
            return self._fail(ErrorCode.DIE_PIECE_MISMATCH, msg)

        probe = Move(piece=piece, src=src, dst=dst, die=s.die, captured=s.pos.squares[dst])
        _, rep = apply_remote_move(s.state, probe, SyncMode.LENIENT)
        code = rep.code or ErrorCode.ILLEGAL_MOVE
        return self._fail(code, EV.explain_error(code, die=s.die, alive=alive,
                                                piece=piece, src=src, dst=dst))

    # ---------------- 回合推进 ----------------
    def _in_remote_turn(self) -> bool:
        """比赛模式下轮到对方（可直接在棋盘上替他走）。"""
        return self._setup.mode is Mode.MATCH and self._phase is Phase.MATCH_WAIT

    def _can_control(self, side: int) -> bool:
        """当前能否操作 side 这一方的棋子。"""
        if side == self._setup.human_side:
            return self._phase is Phase.HUMAN_TURN
        return self._in_remote_turn()

    def _after_move(self, mv: Move, mover: int) -> None:
        self._legal_cache = None
        self._selection = None
        self._last_move = mv
        self._capture_flash = (mv.dst, mv.captured) if mv.captured else None
        self._enter_turn()

    # ---------------- AI ----------------
    def ai_think(self, auto: bool = False) -> dict:
        if self._phase is Phase.THINKING:
            return self._fail("BUSY", severity="warn")
        s = self._session
        if s is None or s.finished:
            return self._fail(ErrorCode.GAME_ALREADY_OVER, severity="warn")
        if s.side != self._setup.human_side:
            return self._fail(ErrorCode.NOT_YOUR_TURN, severity="warn")
        self._phase = Phase.THINKING
        self._begin_think()
        return self._ok()

    def _start_think(self) -> None:
        s = self._session
        if s is None:
            return
        self._token += 1
        token = self._token
        self._cancel = threading.Event()
        cancel = self._cancel
        pos = s.pos                                # 不可变快照
        ms = s.remaining_ms(s.side)                # 标量快照
        ply = s.ply
        cfg = self._cfg
        self._log.log(f"AI 开始搜索 ply {ply + 1} cfg(think<={cfg.max_think_ms}ms, "
                      f"nodes={cfg.node_limit})")

        if not self._async:
            try:
                res = self._thinker.think(pos, ms, cfg, ply, None)
            except BaseException as exc:            # noqa: BLE001 - 同步模式也要兜住
                self._on_think_error(token, exc)
                return
            self._apply_think_result(token, res)
            return

        worker = threading.Thread(
            target=_worker,
            args=(token, self._thinker, pos, ms, cfg, ply, cancel, self._queue),
            name=f"einstein-mcts-{token}",
            daemon=True,
        )
        self._thread = worker
        worker.start()

    def _cancel_think(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
        worker = self._thread
        if worker is not None and worker.is_alive():
            worker.join(timeout=0.6)
        self._thread = None
        self._cancel = None

    def poll(self) -> list[dict]:
        """主线程每 ~30ms 调一次：把后台结果落子。"""
        events: list[dict] = []
        while True:
            try:
                token, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            if token != self._token:
                events.append({"kind": "stale"})
                continue
            if isinstance(payload, BaseException):
                self._on_think_error(token, payload)
                events.append({"kind": "ai_error"})
                continue
            ev = self._apply_think_result(token, payload)
            if ev:
                events.append(ev)
        return events

    def _on_think_error(self, token: int, exc: BaseException) -> None:
        if token != self._token:
            return
        self._notice = ("error", "ENGINE_ERROR", f"搜索异常：{exc}")
        self._log.log(f"搜索异常 {type(exc).__name__}: {exc}", level="error")
        if self._session is not None and not self._session.finished:
            self._phase = Phase.HUMAN_TURN

    def _apply_think_result(self, token: int, res) -> dict | None:
        if token != self._token or res is None:
            return {"kind": "stale"}
        s = self._session
        if s is None or s.finished or s.die == 0:
            return {"kind": "stale"}
        if res.move is None:
            self._notice = ("error", "NO_LEGAL_MOVE", "AI 没有拿到合法走法")
            self._phase = Phase.HUMAN_TURN
            return {"kind": "ai_error"}
        legal = {m.key(): m for m in s.legal_moves()}
        mv = legal.get(res.move.key())
        if mv is None:
            self._notice = ("error", "ILLEGAL_MOVE", f"AI 给出非法走法 {res.move.to_text()}")
            self._phase = Phase.HUMAN_TURN
            self._log.log(f"AI 非法走法 {res.move.to_text()}", level="error")
            return {"kind": "ai_error"}

        self._last_search = res
        mover = s.side
        s.play(mv)
        self._log.log(
            f"AI 落子 {mv.to_compact()} sims={res.sims} {res.elapsed_ms}ms reason={res.reason}"
        )
        self._after_move(mv, mover)
        return {"kind": "ai_done", "move": mv.to_compact(), "search": res}

    # ---------------- 比赛模式 ----------------
    def declare_remote_die(self, die: int) -> dict:
        """为对方声明本回合骰值（对方掷出几就选几）。

        这是"直接在棋盘上替对方走棋"的前置步骤：骰值确定后，对方的棋子才可点。
        允许在未走子前改口（对方报错了点数）。
        """
        if self._phase is Phase.THINKING:
            return self._fail("BUSY", severity="warn")
        s = self._session
        if s is None or s.finished:
            return self._fail(ErrorCode.GAME_ALREADY_OVER, severity="warn")
        if self._phase is not Phase.MATCH_WAIT:
            return self._fail("NOT_REMOTE_TURN", "现在不是对方的回合", severity="warn")
        if not 1 <= int(die) <= 6:
            return self._fail(ErrorCode.MALFORMED_MOVE, f"骰值必须是 1–6，收到 {die}")

        die = int(die)
        if s.pos.die == die:
            return self._ok(f"对方骰值 {die}", extra={"die": die})
        if s.pos.die == 0:
            s.declare_remote_die(die)          # 引擎的正式入口
        else:
            # 对方改口：还没走子，直接换掉待走骰值
            s.state = s.state.with_pos(s.pos.with_die(die))
        self._legal_cache = None
        self._selection = None
        self._log.log(f"对方骰值设为 {die}")
        return self._ok(f"对方骰值 {die}", extra={"die": die})

    def remote_roll(self) -> dict:
        """替对方随机掷一次骰子（省去问对方点数）。"""
        if self._phase is not Phase.MATCH_WAIT:
            return self._fail("NOT_REMOTE_TURN", severity="warn")
        die = random.randint(1, 6)
        return self.declare_remote_die(die)

    def accept_remote(self, text: str) -> dict:
        if self._phase is Phase.THINKING:
            return self._fail("BUSY", severity="warn")
        s = self._session
        if s is None or s.finished:
            return self._fail(ErrorCode.GAME_ALREADY_OVER, severity="warn")
        if self._phase is not Phase.MATCH_WAIT:
            return self._fail("NOT_REMOTE_TURN", severity="warn")
        return self._apply_remote(text)

    def _apply_remote(self, text: str) -> dict:
        """对方走法的统一落地点：无论来自棋盘代点还是文本框粘贴，都走这条六层对账路径。"""
        s = self._session
        self._log.log(f"收到对方走法 {text!r}")
        try:
            _, rep = s.accept_remote_move(text, self._setup.sync_mode)
        except EngineError as exc:
            report = EV.report_parse_failed(exc, s)
            self._match_report = report
            self._log.log(f"对账失败（解析）[{exc.code.value}] {exc}", level="warn")
            return self._fail(exc.code, EV.explain_error(exc.code),
                              extra={"report": report})

        report = EV.report_to_view(rep, s)
        self._match_report = report
        if not rep.ok:
            self._log.log(f"对账失败 [{report['code']}] {rep.message}", level="warn")
            return self._fail(rep.code or "SYNC_DESYNC", EV.error_text(rep.code),
                              extra={"report": report})

        mv = rep.remote_move
        self._legal_cache = None
        self._selection = None
        self._last_move = mv
        self._capture_flash = (mv.dst, mv.captured) if (mv and mv.captured) else None
        self._log.log(f"复制成功 {mv.to_compact() if mv else '?'} · 六层对账全部通过")
        self._enter_turn()
        return self._ok("复制成功", severity="none", extra={"report": report})

    def to_send_text(self) -> str:
        s = self._session
        if s is None or not s.move_log:
            return ""
        return s.move_log[-1].to_compact()

    # ---------------- 计时 / 导出 ----------------
    def tick(self) -> dict:
        s = self._session
        if s is None or s.finished:
            if self._phase is not Phase.GAME_OVER:
                self._phase = Phase.GAME_OVER
            return self._ok()
        if s.clock.ticking and s.clock.is_flag_fallen(s.side):
            s.check_timeout()
            self._phase = Phase.GAME_OVER
            self._notice = ("error", ErrorCode.CLOCK_FLAG_FALLEN.value, "本方计时耗尽，判负")
            self._log.log("计时耗尽，判负", level="warn")
            return self._fail(ErrorCode.CLOCK_FLAG_FALLEN, "本方计时耗尽，判负")
        return self._ok()

    def export_record(self, path=None) -> dict:
        result = _export_record(self._session, path)
        if result["ok"]:
            self._log.log(result["message"])
            return self._ok(result["message"], extra=result)
        self._log.log(result["message"], level="error")
        return self._fail("EXPORT_FAILED", result["message"], extra=result)

    # ---------------- 内部工具 ----------------
    def _legal_index(self) -> dict:
        if self._legal_cache is None:
            s = self._session
            if s is None or s.finished or s.die == 0:
                self._legal_cache = {}
            else:
                self._legal_cache = {m.key(): m for m in s.legal_moves()}
        return self._legal_cache

    def _clock_view(self) -> dict:
        s = self._session
        if s is None:
            return {"red_ms": 0, "blue_ms": 0, "red_text": "0:00", "blue_text": "0:00", "ticking": 0}
        snap = s.clock.snapshot()
        return {
            "red_ms": snap["red_ms"],
            "blue_ms": snap["blue_ms"],
            "red_text": _mmss(snap["red_ms"]),
            "blue_text": _mmss(snap["blue_ms"]),
            "ticking": snap["ticking"] or 0,
        }

    def _captured_view(self) -> dict:
        s = self._session
        if s is None:
            return {"red": [], "blue": []}
        pos = s.pos
        return {
            "red": [n for n in range(1, 7) if not (pos.red_alive >> n) & 1],
            "blue": [n for n in range(1, 7) if not (pos.blue_alive >> n) & 1],
        }

    def _cells(self) -> list[dict]:
        s = self._session
        if s is None:
            return build_cells([0] * 25)
        pos = s.pos
        sel = self._selection or {}
        targets = sel.get("target_map", {})
        last_from = self._last_move.src if self._last_move else -1
        last_to = self._last_move.dst if self._last_move else -1
        cap_sq = self._capture_flash[0] if self._capture_flash else -1
        cap_code = self._capture_flash[1] if self._capture_flash else 0
        return build_cells(
            pos.squares,
            side=pos.side,
            candidates=resolve_candidates(pos.alive(pos.side), pos.die) if pos.die else (),
            selected_src=sel.get("src", -1),
            targets=targets,
            last_from=last_from,
            last_to=last_to,
            capture_sq=cap_sq,
            capture_code=cap_code,
        )

    def _candidates_view(self) -> list[dict]:
        res = self._last_search
        if res is None or not res.root_stats:
            return []
        stats = list(res.root_stats[:3])
        top = max(1, stats[0].visits)
        return [
            {
                "text": st.move.to_compact(),
                "visits": st.visits,
                "q": st.q,
                "prior": st.prior,
                "share": min(1.0, st.visits / top),
                "is_choice": idx == 0,
            }
            for idx, st in enumerate(stats)
        ]

    def _search_view(self) -> dict | None:
        res = self._last_search
        if res is None:
            return None
        return {
            "reason": res.reason,
            "reason_text": EV.REASON_TEXT.get(res.reason, res.reason),
            "nodes": res.nodes,
            "sims": res.sims,
            "elapsed_ms": res.elapsed_ms,
            "depth": res.depth_max,
        }

    def _record_view(self) -> list[dict]:
        s = self._session
        if s is None:
            return []
        out = []
        for row in s.record()[1:]:
            out.append({
                "ply": row["ply"],
                "side": row["side"],
                "text": f"{row['ply']:>3}. {row['side']} {row['piece']}{row['src']}-{row['dst']}@{row['die']}",
            })
        return out

    def view(self) -> dict:
        s = self._session
        if s is None:
            return {
                "phase": Phase.GAME_OVER.value, "phase_label": "未开始",
                "mode": self._setup.mode.value, "mode_label": self._setup.mode.label,
                "human_side": self._setup.human_side,
                "side": RED, "side_name": "红", "acting_side": RED, "remote_turn": False,
                "die": 0, "needs_roll": False,
                "ply": 0, "result": None, "clock": self._clock_view(),
                "cells": self._cells(), "selection": None, "last_move": None,
                "candidates": [], "search": None,
                "match": {"report": None, "send_text": "", "can_accept": False,
                          "remote_die": 0, "can_board_control": False, "awaiting_die": False},
                "captured": {"red": [], "blue": []}, "record": [],
                "error": None, "can": {"select": False, "commit": False, "roll": False,
                                       "think": False, "accept": False, "remote_die": False,
                                       "export": False, "new_game": True},
            }

        pos = s.pos
        die = pos.die
        needs_roll = self._phase is Phase.HUMAN_TURN and die == 0
        result = EV.result_view(s.result, self._setup.human_side)
        selection = None
        if self._selection:
            selection = {
                "piece": self._selection["piece"],
                "src": self._selection["src"],
                "targets": list(self._selection["targets"]),
            }
        last_move = None
        if self._last_move is not None:
            mv = self._last_move
            last_move = {
                "piece": mv.piece,
                "from": mv.src,
                "to": mv.dst,
                "text": mv.to_compact(),
                "captured": mv.captured,
                "captured_text": EV.describe_piece_code(mv.captured) if mv.captured else "",
            }

        remote_turn = self._in_remote_turn()
        can_select = die != 0 and (self._phase is Phase.HUMAN_TURN or remote_turn)
        return {
            "phase": self._phase.value,
            "phase_label": self._phase.label,
            "mode": self._setup.mode.value,
            "mode_label": self._setup.mode.label,
            "human_side": self._setup.human_side,
            "side": pos.side,
            "side_name": SIDE_NAME[pos.side],
            "acting_side": pos.side,
            "remote_turn": remote_turn,
            "die": die,
            "needs_roll": needs_roll,
            "ply": s.ply,
            "result": result,
            "clock": self._clock_view(),
            "cells": self._cells(),
            "selection": selection,
            "last_move": last_move,
            "candidates": self._candidates_view(),
            "search": self._search_view(),
            "match": {
                "report": self._match_report,
                "send_text": self.to_send_text(),
                "can_accept": self._phase is Phase.MATCH_WAIT,
                "remote_die": die,
                "can_board_control": can_select and remote_turn,
                "awaiting_die": remote_turn and die == 0,
            },
            "captured": self._captured_view(),
            "record": self._record_view(),
            "error": (
                {"code": self._notice[1], "message": self._notice[2], "severity": self._notice[0]}
                if self._notice else None
            ),
            "can": {
                "select": can_select,
                "commit": can_select,
                "roll": needs_roll,
                "think": False,
                "accept": self._phase is Phase.MATCH_WAIT,
                "remote_die": self._phase is Phase.MATCH_WAIT,
                "export": s.ply > 0,
                "new_game": True,
            },
        }

    # ---------------- 调试 ----------------
    def assert_in_sync(self, other_state) -> list[str]:
        """与另一侧状态逐字节比对（比赛模式演示 / 测试用）。"""
        if self._session is None:
            return ["no-session"]
        return verify_state_equal(self._session.state, other_state)


# ---------------- 模块级 worker ----------------
def _worker(token: int, thinker: Thinker, pos, ms: int, cfg, ply: int,
            cancel: threading.Event, q: queue.Queue) -> None:
    """后台线程：只碰不可变快照，结果/异常都塞回队列。"""
    try:
        q.put((token, thinker.think(pos, ms, cfg, ply, cancel)))
    except BaseException as exc:      # noqa: BLE001 - 线程内异常必须带回主线程
        q.put((token, exc))


def _mmss(ms: int) -> str:
    total = max(0, int(ms) // 1000)
    return f"{total // 60}:{total % 60:02d}"

