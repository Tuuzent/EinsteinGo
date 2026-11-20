"""职责①：合法走法生成（纯函数，不修改入参）。

规则第 3 条的"缺号替代"是本模块的全部复杂度来源，它有三种分支：
    1. 骰值对应的编号棋子仍在盘上 → 只能走它（不允许改用替代）
    2. 该编号已出局            → 可走"小于它的最近一枚"或"大于它的最近一枚"，两侧皆可
    3. 只剩单枚棋子            → 无论骰值都必走它
`resolve_candidates` 把这三种情况统一成一个"候选编号元组"，走法生成再展开方向。

注意分支 2 的读法：不是"全局差值最小"，而是**两侧分别取最近**。
文档原文："假设编号为 4 和 5 的棋子已移出，如果骰子显示为 4，则可以走动编号为 3 或 6 的棋子"——
3 与 4 差 1、6 与 4 差 2，若按全局最小值只会得到 3，与文档矛盾；按两侧最近正好 3 与 6。
"""

from __future__ import annotations

from .constants import NEIGHBORS, NUM_MAX
from .errors import EngineError, ErrorCode
from .move import Move
from .state import Position, find_piece


def resolve_candidates(alive: int, die: int) -> tuple[int, ...]:
    """返回本回合允许走动的己方编号（升序）。alive 为 6-bit mask（bit n = n 号在盘）。

    规则第 3 条 + 文档例子的精确读法：该编号不在盘时，取"小于该数的最近一枚"
    与"大于该数的最近一枚"，**两侧都可以走**（两侧分别取最近，不是全局差值最小）。

    文档原文举例：4、5 号已移出，骰出 4 → 可走 3 或 6。
    若按"全局差值最小"只会得到 3，与文档矛盾；按"两侧最近"正好得到 3 与 6。

    >>> resolve_candidates(0b1111110, 4)      # 全员在盘
    (4,)
    >>> resolve_candidates(0b1001000, 4)      # 只有 3、6 号在盘 → 两侧最近
    (3, 6)
    >>> resolve_candidates(0b100100, 4)       # 只有 2、5 号在盘
    (2, 5)
    """
    if alive == 0:
        return ()
    if alive & (1 << die):
        return (die,)
    lower = next((n for n in range(die - 1, 0, -1) if (alive >> n) & 1), None)
    upper = next((n for n in range(die + 1, NUM_MAX + 1) if (alive >> n) & 1), None)
    if lower is None:
        return (upper,) if upper is not None else ()
    if upper is None:
        return (lower,)
    return (lower, upper)


def generate_from(squares, side: int, alive: int, die: int) -> list[Move]:
    """从裸棋盘数据生成走法（供 Position 与 ScratchBoard 共用，单一事实来源）。"""
    if die == 0:
        raise EngineError(ErrorCode.DIE_NOT_ROLLED, "本回合尚未掷骰，无法生成走法")
    if alive == 0:
        return []
    table = NEIGHBORS[side]
    out: list[Move] = []
    for num in resolve_candidates(alive, die):
        src = find_piece(squares, side * num)
        if src < 0:  # 防御：alive 与棋盘不一致时应尽早暴露
            raise EngineError(
                ErrorCode.PIECE_ALREADY_CAPTURED,
                f"编号 {num} 标记为在盘但棋盘上找不到",
                side=side,
            )
        for dst in table[src]:
            out.append(Move(piece=num, src=src, dst=dst, die=die, captured=squares[dst]))
    return out


def generate_moves(pos: Position, die: int | None = None) -> list[Move]:
    """职责①：给定局面（与可选骰值）返回全部合法走法。

    空列表只可能出现在"本方已全灭"的情形，而那时对局早已终局（见 state 模块注释）。
    """
    d = pos.die if die is None else die
    return generate_from(pos.squares, pos.side, pos.alive(pos.side), d)


def moves_for_die(pos: Position, die: int) -> list[Move]:
    return generate_from(pos.squares, pos.side, pos.alive(pos.side), die)


def has_any_move(pos: Position, die: int) -> bool:
    """比 len(generate_moves(...)) > 0 更快的一步探测（不构造 Move 列表）。"""
    alive = pos.alive(pos.side)
    if alive == 0:
        return False
    table = NEIGHBORS[pos.side]
    for num in resolve_candidates(alive, die):
        src = find_piece(pos.squares, pos.side * num)
        if src >= 0 and table[src]:
            return True
    return False
