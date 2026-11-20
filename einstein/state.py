"""棋盘局面（Position）与对局状态（GameState）。

分层理由
--------
Position 是**纯博弈状态**：可搜索、可哈希、无时间概念。ai/* 与 movegen 只认它。
GameState 是**对局状态**：多带 ply、历史、哈希链、结果。只被 session/sync/match/cli 使用。

若把两者合并，MCTS 每个节点都要背一份 history 元组与计时字典，节点一多就爆内存。

棋盘表示
--------
25 长 int tuple 作为唯一权威数据；位图与 alive mask 是派生缓存（构造时算、增量更新）。
不可变带来的收益：MCTS 节点持引用即"快照"，零拷贝、零污染、失败天然回滚。
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    BLUE,
    BLUE_HOME,
    CORNER,
    EMPTY,
    N_SQUARES,
    RED,
    RED_HOME,
    SIDES,
    side_of,
)
from .move import Move
from .outcome import GameResult
from .zobrist import Z_DIE, Z_SIDE, full_hash

ALIVE_BITS = 0
for _n in range(1, 7):
    ALIVE_BITS |= 1 << _n


def find_piece(squares, code: int) -> int:
    """返回某棋码所在格索引，不在盘上返回 -1。"""
    try:
        return squares.index(code)
    except ValueError:
        return -1


def alive_mask(squares, side: int) -> int:
    """从棋盘扫描出某方 alive mask（bit n = n 号仍在盘）。"""
    m = 0
    if side > 0:
        for code in squares:
            if code > 0:
                m |= 1 << code
    else:
        for code in squares:
            if code < 0:
                m |= 1 << -code
    return m


def occup_mask(squares, side: int) -> int:
    m = 0
    if side > 0:
        for i, code in enumerate(squares):
            if code > 0:
                m |= 1 << i
    else:
        for i, code in enumerate(squares):
            if code < 0:
                m |= 1 << i
    return m


@dataclass(frozen=True, slots=True)
class Position:
    """不可变局面。请用 Position.build(...) 或 initial_position(...) 构造。"""

    squares: tuple[int, ...]
    side: int          # 轮到谁行动：+1 红 / -1 蓝
    die: int           # 已掷骰值 1..6；0 表示本回合尚未掷骰
    red_mask: int      # 红方占位位图
    blue_mask: int     # 蓝方占位位图
    red_alive: int     # bit n = 红方 n 号仍在盘
    blue_alive: int
    zhash: int

    # ---------------- 构造 ----------------
    @classmethod
    def build(cls, squares, side: int, die: int = 0) -> "Position":
        sq = tuple(int(c) for c in squares)
        if len(sq) != N_SQUARES:
            raise ValueError(f"squares 长度必须是 {N_SQUARES}，收到 {len(sq)}")
        if side not in (RED, BLUE):
            raise ValueError(f"side 必须是 +1/-1，收到 {side}")
        if not 0 <= die <= 6:
            raise ValueError(f"die 必须在 0..6，收到 {die}")
        return cls(
            sq,
            side,
            die,
            occup_mask(sq, RED),
            occup_mask(sq, BLUE),
            alive_mask(sq, RED),
            alive_mask(sq, BLUE),
            full_hash(sq, side, die),
        )

    # ---------------- 查询 ----------------
    def alive(self, side: int) -> int:
        return self.red_alive if side > 0 else self.blue_alive

    def mask(self, side: int) -> int:
        return self.red_mask if side > 0 else self.blue_mask

    def piece_count(self, side: int) -> int:
        return bin(self.alive(side)).count("1")

    def piece_sq(self, num: int) -> int:
        """当前行动方某编号棋子的位置，不在盘上返回 -1。"""
        return find_piece(self.squares, self.side * num)

    def has_piece_on_corner(self, side: int) -> bool:
        """side 方是否有棋子站在自己的目标角点上（即已经获胜）。"""
        code = self.squares[CORNER[side]]
        return code != EMPTY and side_of(code) == side

    # ---------------- 派生构造（保持哈希一致） ----------------
    def with_die(self, die: int) -> "Position":
        if die == self.die:
            return self
        return Position(
            self.squares,
            self.side,
            die,
            self.red_mask,
            self.blue_mask,
            self.red_alive,
            self.blue_alive,
            self.zhash ^ Z_DIE[self.die] ^ Z_DIE[die],
        )

    def with_side(self, side: int) -> "Position":
        """仅用于轮空。走子换手内联在 transition.apply 里。"""
        if side == self.side:
            return self
        return Position(
            self.squares,
            side,
            self.die,
            self.red_mask,
            self.blue_mask,
            self.red_alive,
            self.blue_alive,
            self.zhash ^ Z_SIDE,
        )

    # ---------------- 序列化 ----------------
    def to_dict(self) -> dict:
        return {
            "squares": list(self.squares),
            "side": "R" if self.side > 0 else "B",
            "die": self.die,
            "zhash": f"{self.zhash:016x}",
        }

    def __str__(self) -> str:
        from .board import render_squares

        return render_squares(self.squares)


def initial_position(
    red_placement: dict[int, int] | None = None,
    blue_placement: dict[int, int] | None = None,
    first_player: int = RED,
    die: int = 0,
) -> Position:
    """开局局面。placement 为 {编号: 格索引}，缺省按出发区格序依次放 1..6。"""
    squares = [EMPTY] * N_SQUARES
    for side, home, placement in (
        (RED, RED_HOME, red_placement),
        (BLUE, BLUE_HOME, blue_placement),
    ):
        placement = default_placement(side) if placement is None else dict(placement)
        if len(placement) != 6 or set(placement) != set(range(1, 7)):
            raise ValueError(f"{side} 方必须摆放 1..6 共 6 枚棋子，收到 {sorted(placement)}")
        if set(placement.values()) != set(home):
            raise ValueError(f"{side} 方棋子必须放满出发区 {sorted(home)}，收到 {sorted(placement.values())}")
        for num, sq in placement.items():
            if squares[sq] != EMPTY:
                raise ValueError(f"格位 {sq} 被重复占用")
            squares[sq] = side * num
    return Position.build(squares, first_player, die)


def default_placement(side: int) -> dict[int, int]:
    home = sorted(RED_HOME if side > 0 else BLUE_HOME)
    return {num: sq for num, sq in zip(range(1, 7), home)}


def rot180(pos: Position) -> Position:
    """中心对称旋转：(r,c) -> (5-r,5-c)，红蓝互换、出发区互映、方向集互映。

    180° 旋转是这套规则的自同构（involution），因此可用于把"评估方"统一成红方。
    """
    sq = [EMPTY] * N_SQUARES
    for i, code in enumerate(pos.squares):
        sq[N_SQUARES - 1 - i] = -code
    return Position.build(sq, -pos.side, pos.die)


def canonical(pos: Position, player: int) -> Position:
    """把 player 视角规范化为红方视角，使评估只有一套代码路径。"""
    return pos if player > 0 else rot180(pos)


@dataclass(frozen=True, slots=True)
class GameState:
    """一次对局的可持久化状态。计时器不在此处（由 GameSession 持有，避免双写）。"""

    pos: Position
    ply: int = 0
    move_log: tuple[Move, ...] = ()
    result: GameResult | None = None
    chain_hash: bytes = b"\x00" * 16
    seed: int = 0

    @property
    def side(self) -> int:
        return self.pos.side

    @property
    def finished(self) -> bool:
        return self.result is not None

    def to_position(self) -> Position:
        """交给 AI / 规则层的纯博弈状态。"""
        return self.pos

    def with_move(self, move: Move, new_pos: Position, chain_hash: bytes, result: GameResult | None) -> "GameState":
        return GameState(
            pos=new_pos,
            ply=self.ply + 1,
            move_log=self.move_log + (move,),
            result=result,
            chain_hash=chain_hash,
            seed=self.seed,
        )

    def with_result(self, result: GameResult) -> "GameState":
        return GameState(
            pos=self.pos,
            ply=self.ply,
            move_log=self.move_log,
            result=result,
            chain_hash=self.chain_hash,
            seed=self.seed,
        )

    def with_pos(self, pos: Position) -> "GameState":
        """只换局面（例如掷骰后写入骰值），保留历史与结果。"""
        return GameState(
            pos=pos,
            ply=self.ply,
            move_log=self.move_log,
            result=self.result,
            chain_hash=self.chain_hash,
            seed=self.seed,
        )

    def header(self) -> dict:
        return {
            "ply": 0,
            "side": "R" if self.pos.side > 0 else "B",
            "squares": list(self.pos.squares),
            "die": self.pos.die,
            "zhash": f"{self.pos.zhash:016x}",
            "seed": self.seed,
        }


def check_alive_consistency(pos: Position) -> None:
    """调试用：alive 缓存必须与棋盘一致，否则说明增量维护有 bug。"""
    for side in SIDES:
        expect = alive_mask(pos.squares, side)
        actual = pos.alive(side)
        if expect != actual:
            raise AssertionError(
                f"alive mask 漂移 side={side} expect={expect:#b} actual={actual:#b} squares={pos.squares}"
            )
