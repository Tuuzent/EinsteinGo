"""职责②③④：移动执行（吃子）、回合切换。

`apply` 一次完成四件事，缺一不可（这是 R5 高危点）：
    1. 棋子从 src 移到 dst
    2. 若 dst 原本有棋子（含己方棋子）则移出该子
    3. 行动方翻转
    4. 骰值清零（骰子已消耗）

吃子真值表（R1 高危点：清的是**被吃者**的编号位，不是移动方的）：
    captured == 0        → 双方 alive 不变
    captured 属本方      → 本方 alive 清 bit(num_of(captured))
    captured 属对方      → 对方 alive 清 bit(num_of(captured))
移动方的编号位永不清除 —— 它只是换了格子，仍在盘上。
"""

from __future__ import annotations

from .constants import BLUE, RED, num_of, side_of
from .move import Move
from .movegen import generate_from
from .state import Position
from .zobrist import Z_DIE, Z_PIECE, Z_SIDE


def _advance(
    side: int,
    src: int,
    dst: int,
    captured: int,
    red_mask: int,
    blue_mask: int,
    red_alive: int,
    blue_alive: int,
) -> tuple[int, int, int, int]:
    """计算走子后的 (red_mask, blue_mask, red_alive, blue_alive)。

    apply 与 ScratchBoard.make 共用同一份位运算逻辑，杜绝两份实现漂移。
    """
    src_bit = 1 << src
    dst_bit = 1 << dst
    if side > 0:
        my_mask = (red_mask & ~src_bit) | dst_bit
        op_mask = blue_mask
        my_alive = red_alive
        op_alive = blue_alive
    else:
        my_mask = (blue_mask & ~src_bit) | dst_bit
        op_mask = red_mask
        my_alive = blue_alive
        op_alive = red_alive

    if captured:
        if side_of(captured) == side:
            # 吃掉己方子：dst 格被"移动过来的这枚"占住（occupancy 不变），
            # 只是被吃的那个编号从盘上消失。**不能清 dst 位**，否则跳跃的棋子会凭空消失。
            my_alive &= ~(1 << num_of(captured))
        else:
            op_mask &= ~dst_bit
            op_alive &= ~(1 << num_of(captured))

    if side > 0:
        return my_mask, op_mask, my_alive, op_alive
    return op_mask, my_mask, op_alive, my_alive


def apply(pos: Position, mv: Move) -> Position:
    """执行一步走法，返回全新 Position。不改动入参（不可变状态天然回滚）。"""
    side = pos.side
    code = side * mv.piece
    if pos.squares[mv.src] != code:
        raise AssertionError(
            f"走法起点不符: 期望 {code} 在 {mv.src}，实际 {pos.squares[mv.src]}"
        )
    if pos.squares[mv.dst] != mv.captured:
        raise AssertionError(
            f"走法 captured 字段不符: 期望 {pos.squares[mv.dst]}，实际 {mv.captured}"
        )
    if mv.captured == code:
        raise AssertionError("同一枚棋子不能吃自己")

    squares = list(pos.squares)
    squares[mv.dst] = squares[mv.src]
    squares[mv.src] = 0
    new_squares = tuple(squares)

    rm, bm, ra, ba = _advance(
        side, mv.src, mv.dst, mv.captured,
        pos.red_mask, pos.blue_mask, pos.red_alive, pos.blue_alive,
    )

    # 增量哈希：移出 src、覆盖 dst 原内容、写入 dst 新内容、翻转行动方、清骰值
    zh = (
        pos.zhash
        ^ Z_PIECE[mv.src][code + 6]
        ^ Z_PIECE[mv.dst][mv.captured + 6]
        ^ Z_PIECE[mv.dst][code + 6]
        ^ Z_SIDE
        ^ Z_DIE[pos.die]
    )
    return Position(new_squares, -side, 0, rm, bm, ra, ba, zh)


def switch_turn(pos: Position) -> Position:
    """仅用于轮空：不改盘面、弃掉骰值、翻转行动方。

    注意：本规则集下轮空不可达（任何非终局在盘棋子恒有合法目标格），
    此函数是防御性代码，同时也是变体规则（如禁止吃己方子、加墙）的挂点。
    """
    return pos.with_side(-pos.side).with_die(0)


def pass_turn(pos: Position) -> Position:
    """轮空（语义与 switch_turn 相同，命名区分意图）。"""
    return switch_turn(pos)


class ScratchBoard:
    """可逆的可变棋盘，只用于 rollout 热路径；不进 MCTS 树。

    与 Position 的等价性由 tests/test_transition.py::test_make_unmake_equivalence
    在大量随机对局上逐步全字段对账保证。
    """

    __slots__ = ("sq", "side", "die", "red_mask", "blue_mask", "red_alive", "blue_alive", "_undo")

    def __init__(self, pos: Position) -> None:
        self.sq = list(pos.squares)
        self.side = pos.side
        self.die = pos.die
        self.red_mask = pos.red_mask
        self.blue_mask = pos.blue_mask
        self.red_alive = pos.red_alive
        self.blue_alive = pos.blue_alive
        self._undo: list[tuple] = []

    # ---- 属性 ----
    def mask(self, side: int) -> int:
        return self.red_mask if side > 0 else self.blue_mask

    def alive(self, side: int) -> int:
        return self.red_alive if side > 0 else self.blue_alive

    # ---- 走法 ----
    def moves(self, die: int | None = None) -> list[Move]:
        d = self.die if die is None else die
        return generate_from(self.sq, self.side, self.alive(self.side), d)

    # ---- 执行 / 撤销 ----
    def make(self, mv: Move) -> None:
        side = self.side
        self._undo.append(
            (mv.src, mv.dst, mv.captured, self.red_mask, self.blue_mask,
             self.red_alive, self.blue_alive, self.side, self.die)
        )
        self.sq[mv.dst] = self.sq[mv.src]
        self.sq[mv.src] = 0
        self.red_mask, self.blue_mask, self.red_alive, self.blue_alive = _advance(
            side, mv.src, mv.dst, mv.captured,
            self.red_mask, self.blue_mask, self.red_alive, self.blue_alive,
        )
        self.side = -side
        self.die = 0

    def unmake(self) -> None:
        src, dst, cap, rm, bm, ra, ba, side, die = self._undo.pop()
        self.sq[src] = self.sq[dst]
        self.sq[dst] = cap
        self.red_mask, self.blue_mask, self.red_alive, self.blue_alive = rm, bm, ra, ba
        self.side = side
        self.die = die

    def flip(self) -> None:
        """轮空：只翻转行动方并弃骰。"""
        self.side = -self.side
        self.die = 0

    # ---- 终局 ----
    def winner(self) -> int | None:
        """返回胜方（+1/-1），未终局返回 None。顺序与 terminal.terminal_after 一致。"""
        from .constants import CORNER

        if self.sq[CORNER[RED]] > 0:
            return RED
        if self.sq[CORNER[BLUE]] < 0:
            return BLUE
        if self.red_alive == 0:
            return BLUE
        if self.blue_alive == 0:
            return RED
        return None

    def to_position(self) -> Position:
        return Position.build(self.sq, self.side, self.die)
