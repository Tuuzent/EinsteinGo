"""状态同步层：复制对方走法并做一致性校验。

定位澄清
--------
"复制走法"= 我方维护的棋盘必须与对手/裁判侧完全一致。对手发来走法（棋子编号 + 目标格）后，
本地**校验 + 重放**，而不是把对方棋盘镜像翻转过来。因此本层本质是
"带校验的重放器（validating replayer）"，同时服务三种场景：
    1. 网络/比赛对局（对手走法来自 socket / 文件 / 命令行）
    2. 赛事裁判记录（按棋谱重放）
    3. 断线重连与复盘（从棋谱恢复状态）

五层对账
--------
L0 前置    终局 / 行动方 / ply 连续 / 骰值
L1 几何    棋子在盘 / 起点 / 邻接 / 方向 / 骰值-编号一致性 / 最终合法性总闸
L2 快照    走前完整指纹
L3 执行    直接 apply 生成新对象（不可变 → 失败零污染，天然回滚）
L4 对账    8 项走后断言（C1..C8）
L5 哈希链  逐手串联，任意一手可定位

失败行为：返回**原 state** + 失败报告，不改动对局状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .constants import DELTAS, N_SQUARES, num_of, rc, side_of, sq_name
from .errors import EngineError, ErrorCode, ReplayError, SyncError
from .move import Move
from .movegen import generate_moves, resolve_candidates
from .protocol import chain_step, fingerprint, parse_intent
from .state import GameState, Position, find_piece
from .terminal import terminal_after
from .transition import apply
from .zobrist import full_hash


class SyncMode(str, Enum):
    STRICT = "strict"    # 任何不符立即拒绝（正式比赛默认）
    LENIENT = "lenient"  # 允许对"唯一可确定"的维度做修正并记录


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    recovered: bool = False


@dataclass(frozen=True, slots=True)
class VerifyReport:
    ok: bool
    code: ErrorCode | None
    message: str
    ply_before: int
    side_before: int
    die_before: int
    hash_before: int
    hash_after: int | None
    checks: tuple[CheckResult, ...] = ()
    remote_move: Move | None = None

    @property
    def recovered(self) -> bool:
        return any(c.recovered for c in self.checks)

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise SyncError(self.code or ErrorCode.SYNC_DESYNC, self.message)

    def format(self) -> str:
        lines = [
            f"sync {'OK' if self.ok else 'FAIL'}  ply {self.ply_before} "
            f"side={'R' if self.side_before > 0 else 'B'} die={self.die_before}"
        ]
        if self.ok and self.remote_move is not None:
            lines.append(f"  move {self.remote_move.to_text()}  "
                         f"hash {self.hash_before:016x} -> {self.hash_after:016x}")
        if not self.ok:
            lines.append(f"  error [{self.code.value if self.code else '?'}] {self.message}")
        for c in self.checks:
            mark = "ok " if c.ok else "ERR"
            extra = " (recovered)" if c.recovered else ""
            lines.append(f"  [{mark}] {c.name}: {c.detail}{extra}")
        return "\n".join(lines)


def _report_fail(
    state: GameState,
    code: ErrorCode,
    message: str,
    checks: list[CheckResult],
    move: Move | None = None,
) -> tuple[GameState, VerifyReport]:
    return state, VerifyReport(
        ok=False,
        code=code,
        message=message,
        ply_before=state.ply,
        side_before=state.pos.side,
        die_before=state.pos.die,
        hash_before=state.pos.zhash,
        hash_after=None,
        checks=tuple(checks),
        remote_move=move,
    )


def _post_checks(
    before: Position, after: Position, mv: Move
) -> tuple[list[CheckResult], ErrorCode | None, str]:
    """L4：8 项走后对账。任何一项不过都说明引擎记账错了，两种模式都不容忍。"""
    side = before.side
    checks: list[CheckResult] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append(CheckResult(name, ok, detail))

    add("C1 起点已清空", after.squares[mv.src] == 0, f"{sq_name(mv.src)}={after.squares[mv.src]}")
    add("C2 终点为我方棋子", after.squares[mv.dst] == side * mv.piece,
        f"{sq_name(mv.dst)}={after.squares[mv.dst]}")

    old_my = bin(before.alive(side)).count("1")
    new_my = bin(after.alive(side)).count("1")
    old_op = bin(before.alive(-side)).count("1")
    new_op = bin(after.alive(-side)).count("1")
    d_my, d_op = old_my - new_my, old_op - new_op
    add("C3 子力守恒", d_my in (0, 1) and d_op in (0, 1) and d_my + d_op <= 1,
        f"己方 -{d_my} 对方 -{d_op}")
    flip = bin(before.alive(side) ^ after.alive(side)).count("1")
    add("C3b 仅一个编号位变化", flip <= 1, f"popcount={flip}")

    add("C4 被吃子记录一致", (mv.captured == 0 and after.squares[mv.dst] == side * mv.piece)
        or (mv.captured != 0 and side_of(mv.captured) != 0),
        f"captured={mv.captured}")

    add("C5 已换成对方回合", after.side == -side, f"side={after.side}")
    add("C6 骰值已消耗", after.die == 0, f"die={after.die}")

    changed = [i for i in range(N_SQUARES) if after.squares[i] != before.squares[i]]
    add("C7 仅两格发生变化", set(changed) <= {mv.src, mv.dst}, f"changed={[sq_name(i) for i in changed]}")

    recomputed = full_hash(after.squares, after.side, after.die)
    add("C8 增量哈希未漂移", recomputed == after.zhash, f"{after.zhash:016x} vs {recomputed:016x}")

    for c in checks:
        if not c.ok:
            return checks, ErrorCode.SYNC_DESYNC, f"走后对账失败：{c.name}（{c.detail}）"
    return checks, None, ""


def apply_remote_move(
    state: GameState, remote, mode: SyncMode = SyncMode.STRICT
) -> tuple[GameState, VerifyReport]:
    """把外部走法复制（重放）到本地状态上。

    成功返回 (新 state, ok=True 的报告)；失败返回 (原 state, ok=False 的报告)。
    """
    checks: list[CheckResult] = []
    lenient = mode is SyncMode.LENIENT
    orig = state

    # ---------- 解析 ----------
    try:
        intent = parse_intent(remote)
    except EngineError as exc:
        return _report_fail(orig, exc.code, str(exc), checks)

    # ---------- L0 前置 ----------
    if state.result is not None:
        return _report_fail(orig, ErrorCode.GAME_ALREADY_OVER,
                            f"对局已结束（{state.result.describe()}），拒绝继续复制", checks)

    # 对方回合的骰值由对方宣告（走法自带 @die）：本地尚未掷骰则采纳，随后仍全程校验
    if state.pos.die == 0 and intent.die is not None:
        state = state.with_pos(state.pos.with_die(intent.die))
        checks.append(CheckResult("L0 采纳对方宣告的骰值", True, f"die={intent.die}"))

    side = state.pos.side
    if intent.side is not None and intent.side != side:
        return _report_fail(orig, ErrorCode.NOT_YOUR_TURN,
                            f"声明阵营 {'R' if intent.side > 0 else 'B'} 与当前行动方 "
                            f"{'R' if side > 0 else 'B'} 不符", checks)
    if intent.ply is not None and intent.ply != state.ply + 1:
        return _report_fail(orig, ErrorCode.REPLAY_OUT_OF_ORDER,
                            f"棋谱序号不连续：期望 ply {state.ply + 1}，收到 {intent.ply}", checks)

    die = state.pos.die
    if die == 0:
        return _report_fail(orig, ErrorCode.DIE_NOT_ROLLED,
                            "本地尚未掷骰且走法未携带骰值，无法校验并复制", checks)

    if intent.die is not None and intent.die != die:
        if not lenient:
            return _report_fail(orig, ErrorCode.DIE_PIECE_MISMATCH,
                                f"骰值不同步：本地 {die}，对方 {intent.die}", checks)
        checks.append(CheckResult("L0 骰值差异", True,
                                  f"本地 {die} 覆盖对方 {intent.die}", recovered=True))

    # ---------- L1 几何 ----------
    squares = state.pos.squares
    alive = state.pos.alive(side)

    if not (alive >> intent.piece) & 1:
        return _report_fail(orig, ErrorCode.PIECE_ALREADY_CAPTURED,
                            f"{intent.piece} 号棋子已不在盘上", checks)

    actual_src = find_piece(squares, side * intent.piece)
    if actual_src < 0:  # 与 alive 矛盾，引擎记账错误
        return _report_fail(orig, ErrorCode.PIECE_ALREADY_CAPTURED,
                            f"{intent.piece} 号棋子标记在盘但棋盘上找不到", checks)

    if intent.src is None:
        src = actual_src
        checks.append(CheckResult("L1 起点推断", True,
                                  f"{intent.piece} 号在 {sq_name(actual_src)}"))
    elif intent.src != actual_src:
        if not lenient:
            return _report_fail(orig, ErrorCode.SRC_MISMATCH,
                                f"{intent.piece} 号实际在 {sq_name(actual_src)}，"
                                f"对方声明 {sq_name(intent.src)}", checks)
        src = actual_src
        checks.append(CheckResult("L1 起点修正", True,
                                  f"用实际 {sq_name(actual_src)} 覆盖声明 {sq_name(intent.src)}",
                                  recovered=True))
    else:
        src = actual_src

    dst = intent.dst
    sr, sc = rc(src)
    dr, dc = rc(dst)
    delta = (dr - sr, dc - sc)
    if max(abs(delta[0]), abs(delta[1])) != 1:
        return _report_fail(orig, ErrorCode.NOT_ADJACENT,
                            f"{sq_name(src)} -> {sq_name(dst)} 位移 {delta} 不是一格", checks)
    if delta not in DELTAS[side]:
        return _report_fail(orig, ErrorCode.ILLEGAL_DIRECTION,
                            f"{'红' if side > 0 else '蓝'}方不允许方向 {delta}"
                            f"（{sq_name(src)} -> {sq_name(dst)}）", checks)

    cands = resolve_candidates(alive, die)
    if intent.piece not in cands:
        return _report_fail(orig, ErrorCode.DIE_PIECE_MISMATCH,
                            f"骰值 {die} 下允许的编号是 {cands}，对方走了 {intent.piece}", checks)

    mv = Move(piece=intent.piece, src=src, dst=dst, die=die, captured=squares[dst])

    legal = {m.key(): m for m in generate_moves(state.pos)}
    if mv.key() not in legal:
        return _report_fail(orig, ErrorCode.ILLEGAL_MOVE,
                            f"走法 {mv.to_text()} 不在本地合法走法集内", checks, mv)
    mv = legal[mv.key()]

    # ---------- L2 快照 ----------
    snap = fingerprint(state.pos)

    # ---------- L3 执行 ----------
    new_pos = apply(state.pos, mv)

    # ---------- L4 对账 ----------
    post, code, msg = _post_checks(state.pos, new_pos, mv)
    checks.extend(post)
    if code is not None:
        return _report_fail(orig, code, msg, checks, mv)

    # ---------- L5 哈希链 + 终局 ----------
    chain = chain_step(state.chain_hash, mv, new_pos.zhash)
    result = terminal_after(new_pos, state.ply + 1)
    new_state = state.with_move(mv, new_pos, chain, result)

    after = fingerprint(new_pos)
    diff = [k for k in snap if snap[k] != after[k]]
    checks.append(CheckResult("对账字段差异", set(diff) <= {"squares", "side", "die", "red_mask",
                                                           "blue_mask", "red_alive", "blue_alive",
                                                           "zhash"},
                              f"变化字段={diff}"))

    return new_state, VerifyReport(
        ok=True,
        code=None,
        message="复制成功",
        ply_before=state.ply,
        side_before=state.pos.side,
        die_before=state.pos.die,
        hash_before=state.pos.zhash,
        hash_after=new_pos.zhash,
        checks=tuple(checks),
        remote_move=mv,
    )


def replay(rows: list[dict], mode: SyncMode = SyncMode.STRICT) -> GameState:
    """从棋谱重放整局，逐手校验哈希链。rows[0] 必须是 header（含 squares 与 side）。"""
    if not rows:
        raise ReplayError(ErrorCode.HASH_CHAIN_BROKEN, "空棋谱")
    header = rows[0]
    pos = Position.build(
        header["squares"],
        1 if str(header.get("side", "R")).upper().startswith("R") else -1,
        int(header.get("die", 0)),
    )
    state = GameState(pos=pos, seed=int(header.get("seed", 0)))
    for i, row in enumerate(rows[1:], start=1):
        state, rep = apply_remote_move(state, row, mode)
        if not rep.ok:
            raise ReplayError(
                ErrorCode.HASH_CHAIN_BROKEN,
                f"ply {i} 重放失败: [{rep.code.value if rep.code else '?'}] {rep.message}",
                ply=i,
            )
        expect = row.get("hash_after")
        if expect is not None and int(expect, 16) != state.pos.zhash:
            raise ReplayError(
                ErrorCode.HASH_CHAIN_BROKEN,
                f"ply {i} 哈希不符: 棋谱 {expect} vs 重放 {state.pos.zhash:016x}",
                ply=i,
            )
    return state


def verify_state_equal(a: GameState, b: GameState) -> list[str]:
    """两侧独立重放后的逐字节一致性检查，返回不一致项（空列表=完全一致）。"""
    fa, fb = fingerprint(a.pos), fingerprint(b.pos)
    bad = [k for k in fa if fa[k] != fb[k]]
    if a.ply != b.ply:
        bad.append("ply")
    if a.chain_hash != b.chain_hash:
        bad.append("chain_hash")
    if (a.result.winner if a.result else None) != (b.result.winner if b.result else None):
        bad.append("result")
    return bad


def piece_at(state: GameState, square: int) -> int:
    return state.pos.squares[square]


def describe_piece(code: int) -> str:
    if code == 0:
        return "空"
    return f"{'红' if code > 0 else '蓝'}{num_of(code)}号"
