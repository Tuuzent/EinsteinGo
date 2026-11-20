"""对局会话：一次对局的门面（掷骰 / 走子 / 计时 / 终局 / 棋谱）。

掷骰归属（R8 高危点，唯一契约）
------------------------------
`GameSession.roll()` 是**唯一**的掷骰入口，`die != 0` 时抛 DIE_ALREADY_ROLLED。
AI 层绝不掷骰，只接受"骰值已就位"的局面。这样才不会有"AI 掷一次 + 驱动层再掷一次"，
导致实际使用的骰值与日志/对手视图不一致 —— 这是最难查的一类 bug。

内部走法也走一遍状态同步层（apply_remote_move），因此正常对局每一手都有完整对账。
"""

from __future__ import annotations

import random

from .clock import Clock, DEFAULT_BUDGET_MS, TimeBank, TimeSource
from .constants import MAX_PLY, RED
from .errors import EngineError, ErrorCode, IllegalMoveError
from .move import Move, MoveIntent
from .movegen import generate_moves
from .protocol import move_row, parse_intent
from .state import GameState, Position, initial_position
from .sync import SyncMode, VerifyReport, apply_remote_move
from .terminal import adjudicate, winner_by_flag


class GameSession:
    """一局棋。所有会改动状态的方法都返回/更新 self.state。"""

    def __init__(
        self,
        first_player: int = RED,
        budget_ms: int = DEFAULT_BUDGET_MS,
        seed: int = 0,
        time_source: TimeSource | None = None,
        red_placement: dict[int, int] | None = None,
        blue_placement: dict[int, int] | None = None,
        die_source=None,
        state: GameState | None = None,
    ) -> None:
        self.seed = seed
        self._rng = random.Random(seed)
        self._die_source = die_source or (lambda: self._rng.randint(1, 6))
        if state is None:
            pos = initial_position(red_placement, blue_placement, first_player)
            state = GameState(pos=pos, seed=seed)
        self.state = state
        self.clock = Clock(budget_ms, time_source)
        self._record: list[dict] = [state.header()]

    # ---------------- 只读 ----------------
    @property
    def pos(self) -> Position:
        return self.state.pos

    @property
    def side(self) -> int:
        return self.state.pos.side

    @property
    def die(self) -> int:
        return self.state.pos.die

    @property
    def ply(self) -> int:
        return self.state.ply

    @property
    def result(self):
        return self.state.result

    @property
    def chain_hash(self) -> bytes:
        return self.state.chain_hash

    @property
    def move_log(self) -> tuple:
        return self.state.move_log

    @property
    def finished(self) -> bool:
        return self.state.result is not None

    def bank(self, side: int | None = None) -> TimeBank:
        return TimeBank(self.clock, self.side if side is None else side)

    def legal_moves(self) -> list[Move]:
        return generate_moves(self.state.pos)

    def board_text(self) -> str:
        return str(self.state.pos)

    def record(self) -> list[dict]:
        return list(self._record)

    # ---------------- 掷骰 ----------------
    def roll(self, die: int | None = None) -> int:
        """回合开始掷骰。die 参数仅供测试/协议注入固定骰值。"""
        if self.finished:
            raise EngineError(ErrorCode.GAME_ALREADY_OVER, self.state.result.describe())
        if self.pos.die != 0:
            raise EngineError(
                ErrorCode.DIE_ALREADY_ROLLED, f"本回合已掷出 {self.pos.die}，禁止重复掷骰"
            )
        side = self.side
        if self.clock.is_flag_fallen(side):
            self.state = self.state.with_result(winner_by_flag(side, self.ply))
            raise EngineError(ErrorCode.CLOCK_FLAG_FALLEN, "本方时间已耗尽")
        value = self._die_source() if die is None else int(die)
        if not 1 <= value <= 6:
            raise ValueError(f"骰值必须是 1..6，收到 {value}")
        self.state = self.state.with_pos(self.pos.with_die(value))
        self.clock.start_turn(side)
        return value

    # ---------------- 走子 ----------------
    def play(self, move: Move) -> GameState:
        if self.finished:
            raise EngineError(ErrorCode.GAME_ALREADY_OVER, self.state.result.describe())
        side = self.side
        if self.pos.die == 0:
            raise EngineError(ErrorCode.DIE_NOT_ROLLED, "本回合尚未掷骰")
        if self.clock.is_flag_fallen(side):
            self.state = self.state.with_result(winner_by_flag(side, self.ply))
            raise EngineError(ErrorCode.CLOCK_FLAG_FALLEN, "本方时间已耗尽，判负")

        self.clock.stop_turn()
        zh_before = self.pos.zhash
        new_state, report = apply_remote_move(self.state, move, SyncMode.STRICT)
        if not report.ok:
            raise IllegalMoveError(
                report.code or ErrorCode.ILLEGAL_MOVE, report.message, ply=self.ply
            )
        self.state = new_state
        self._record.append(
            move_row(self.ply, side, report.remote_move, zh_before, self.pos.zhash, self.state.chain_hash)
        )
        self._finalize(side)
        return self.state

    def play_intent(self, remote, mode: SyncMode = SyncMode.LENIENT) -> tuple[GameState, VerifyReport]:
        """人类输入路径：解析 → 校验 → 应用，失败不抛异常而是返回报告。"""
        if self.finished:
            raise EngineError(ErrorCode.GAME_ALREADY_OVER, self.state.result.describe())
        side = self.side
        if self.pos.die == 0:
            raise EngineError(ErrorCode.DIE_NOT_ROLLED, "本回合尚未掷骰")
        self.clock.stop_turn()
        zh_before = self.pos.zhash
        new_state, report = apply_remote_move(self.state, remote, mode)
        if report.ok:
            self.state = new_state
            self._record.append(
                move_row(self.ply, side, report.remote_move, zh_before, self.pos.zhash,
                         self.state.chain_hash)
            )
            self._finalize(side)
        return self.state, report

    # ---------------- 比赛模式：复制对方走法 ----------------
    def declare_remote_die(self, die: int) -> None:
        """对方宣告骰值（我方为他方代持的骰面）。不启动我方计时。"""
        if not 1 <= die <= 6:
            raise ValueError(f"骰值必须是 1..6，收到 {die}")
        if self.pos.die != 0 and self.pos.die != die:
            raise EngineError(ErrorCode.DIE_ALREADY_ROLLED, f"已有骰值 {self.pos.die}，与宣告 {die} 冲突")
        self.state = self.state.with_pos(self.pos.with_die(die))

    def accept_remote_move(self, remote, mode: SyncMode = SyncMode.STRICT) -> tuple[GameState, VerifyReport]:
        """比赛模式核心：对方走子 → 复制到我方棋盘 → 校验一致性。

        若本地尚未有骰值而对方走法带了 @die，则先采纳该骰值（对方宣告）。
        """
        if self.finished:
            raise EngineError(ErrorCode.GAME_ALREADY_OVER, self.state.result.describe())
        intent = parse_intent(remote)
        if self.pos.die == 0 and isinstance(intent, MoveIntent) and intent.die is not None:
            self.declare_remote_die(intent.die)
        zh_before = self.pos.zhash
        new_state, report = apply_remote_move(self.state, intent, mode)
        if report.ok:
            side = self.side
            self.state = new_state
            self._record.append(
                move_row(self.ply, side, report.remote_move, zh_before, self.pos.zhash,
                         self.state.chain_hash)
            )
            self._finalize(side)
        return self.state, report

    # ---------------- 计时 ----------------
    def check_timeout(self) -> bool:
        """外部主动探活（例如 AI 思考超时）。返回是否已判负。"""
        if self.finished:
            return True
        if self.clock.ticking and self.clock.is_flag_fallen(self.side):
            self.state = self.state.with_result(winner_by_flag(self.side, self.ply))
            self.clock.stop_turn()
            return True
        return False

    def remaining_ms(self, side: int | None = None) -> int:
        return self.clock.remaining(self.side if side is None else side)

    # ---------------- 内部 ----------------
    def _finalize(self, mover: int) -> None:
        if self.state.result is not None:
            return
        # 落子即胜优先于旗倒（假设 A16）：只有"未取胜却已超时"才判负
        if self.clock.is_flag_fallen(mover):
            self.state = self.state.with_result(winner_by_flag(mover, self.ply))
            return
        if self.ply >= MAX_PLY:  # 防御性安全阀，本规则集下不可达（ply <= 84）
            self.state = self.state.with_result(adjudicate(self.pos, self.ply))

    def summary(self) -> str:
        r = self.state.result
        if r is None:
            return (f"进行中 ply={self.ply} side={'R' if self.side > 0 else 'B'} die={self.die} "
                    f"clock=R{self.clock.remaining(1)}/B{self.clock.remaining(-1)}")
        return f"结束 {r.describe()}"


def rebuild_from_record(rows: list[dict], mode: SyncMode = SyncMode.STRICT) -> GameSession:
    """从棋谱恢复会话（断线重连 / 复盘）。"""
    from .sync import replay

    final = replay(rows, mode)
    session = GameSession(state=final)
    session._record = list(rows)
    return session
