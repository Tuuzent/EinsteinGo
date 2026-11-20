"""职责⑤：胜负判定。

三类终局 + 一个安全阀：
    REACHED_CORNER  率先到达对方出发区角点（红方到 e5，蓝方到 a1）
    ANNIHILATION    吃光对方全部棋子
    TIMEOUT         本方计时耗尽（超时判负）
    ADJUDICATION    MAX_PLY 安全阀（本规则集下不可达）

判定顺序固定为「先看 mover 是否进角，再看对方是否被吃光」。一手同时满足两者时
reason 记 REACHED_CORNER —— winner 相同，固定顺序只为让日志与测试不抖动。

无和棋的结构性保证：
    GameResult.__post_init__ 拒绝 winner == 0；且本规则集下对局必然终局
    （红方每步使 r+c 至少 +1，一枚棋子最多 7 次移动就必须踩到 (5,5) 获胜，
    否则中途被吃；故单方走子数 <= 42，全局 ply <= 84）。
"""

from __future__ import annotations

from .constants import RED, dist_to_corner
from .outcome import GameResult, TerminalReason
from .state import Position


def terminal_after(new_pos: Position, ply: int = 0) -> GameResult | None:
    """在 transition.apply 之后调用。new_pos.side 已是下一手行动方。"""
    mover = -new_pos.side
    if new_pos.has_piece_on_corner(mover):
        return GameResult(mover, TerminalReason.REACHED_CORNER, ply)
    if new_pos.alive(-mover) == 0:
        return GameResult(mover, TerminalReason.ANNIHILATION, ply)
    if new_pos.alive(mover) == 0:  # 防御：走子方不可能把自己吃光，但保住无和棋契约
        return GameResult(-mover, TerminalReason.ANNIHILATION, ply)
    return None


def winner_by_flag(flagged_side: int, ply: int = 0) -> GameResult:
    """超时判负：flagged_side 输。"""
    return GameResult(-flagged_side, TerminalReason.TIMEOUT, ply, detail=f"side {flagged_side} 超时")


def adjudicate(pos: Position, ply: int = 0) -> GameResult:
    """MAX_PLY 安全阀的确定性裁决：①最靠前棋子距离 ②子力 ③红方。

    正常对局 ply <= 84，永不触发（见模块注释的证明）。
    """
    def key(side: int) -> tuple[int, int]:
        alive = pos.alive(side)
        nums = [n for n in range(1, 7) if (alive >> n) & 1]
        if not nums:
            return (99, 99)
        d = min(dist_to_corner(side, pos.squares.index(side * n)) for n in nums)
        return (d, -len(nums))

    red, blue = key(RED), key(-RED)
    winner = RED if red < blue else -RED
    return GameResult(winner, TerminalReason.ADJUDICATION, ply, detail=f"red={red} blue={blue}")


def is_terminal(pos: Position) -> bool:
    """不构造结果的快速判定。"""
    return (
        pos.has_piece_on_corner(RED)
        or pos.has_piece_on_corner(-RED)
        or pos.alive(RED) == 0
        or pos.alive(-RED) == 0
    )

