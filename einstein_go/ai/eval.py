"""启发式评估与战术工具。

评估公式：``evaluate = tanh(EVAL_SCALE * Σ w_k * f_k)``，值域 (-1, 1)，0 为均势。
用 tanh 而不是 clamp：0 附近近似线性（保留排序信号），两端饱和（防止单个特征爆炸主导）。

与 MCTS 的关系（不是二选一）
---------------------------
1. 截断叶子的估值（max_depth / rollout 超限）
2. 扩展时的走法排序先验（PUCT 的 P）
3. 极短时间 / 只有单个合法走法时的直接决策
4. 自对弈基线（HeuristicPlayer），用于验证搜索确实带来增益
"""

from __future__ import annotations

import math

from ..config import DEFAULT_WEIGHTS, EVAL_SCALE, TERMINAL_VALUE
from ..constants import CORNER
from ..movegen import generate_moves
from ..state import Position
from ..terminal import terminal_after
from . import features as F


def evaluate_squares(squares: tuple[int, ...], player: int, weights=None) -> float:
    w = DEFAULT_WEIGHTS if weights is None else weights
    f = F.compute(squares, player)
    s = 0.0
    for key, weight in w.items():
        s += weight * f[key]
    return math.tanh(EVAL_SCALE * s)


def evaluate(pos: Position, player: int, weights=None) -> float:
    """静态评估（与骰值无关，已内置 6 个骰面的期望）。调用方需先排除终局。"""
    return evaluate_squares(pos.squares, player, weights)


def evaluate_for_die(pos: Position, player: int, die: int, weights=None) -> float:
    """骰值条件评估：把 mobility / win1 / lose1 换成该骰面下的确定值。"""
    w = DEFAULT_WEIGHTS if weights is None else weights
    f = dict(F.compute(pos.squares, player))
    my_mob = F.mobility_for_die(pos.squares, player, die)
    op_mob = F.mobility_for_die(pos.squares, -player, die)
    f["mobility"] = F._clip((my_mob - op_mob) / 3.0)
    f["win1"] = 1.0 if F.can_enter_corner_for_die(pos.squares, player, die) else 0.0
    f["lose1"] = 1.0 if F.can_enter_corner_for_die(pos.squares, -player, die) else 0.0
    s = 0.0
    for key, weight in w.items():
        s += weight * f[key]
    return math.tanh(EVAL_SCALE * s)


def evaluate_expected(pos: Position, player: int, weights=None) -> float:
    """对 6 个骰面分别估值再平均，消骰运噪声。成本是 evaluate 的 6 倍。"""
    total = 0.0
    for die in range(1, 7):
        total += evaluate_for_die(pos, player, die, weights)
    return total / 6.0


# ---------------- 战术工具 ----------------
def win_in_one(pos: Position):
    """当前行动方在已知骰值下能否一手进角，能则返回该走法。"""
    if pos.die == 0:
        return None
    corner = CORNER[pos.side]
    for mv in generate_moves(pos):
        if mv.dst == corner:
            return mv
    return None


def opponent_win_prob(pos: Position) -> float:
    """假如下一步换成对手走，对手进角的概率（1/6 加权）。"""
    return F.side_stats(pos.squares, -pos.side).win1


def lead_piece_square(pos: Position, side: int) -> int:
    return F.side_stats(pos.squares, side).lead_sq


def terminal_value_after(pos: Position, mover: int) -> float:
    """走完一手后，从 mover 视角的终局值（+1 胜 / 0 未终局）。"""
    res = terminal_after(pos)
    if res is None:
        return 0.0
    return TERMINAL_VALUE if res.winner == mover else -TERMINAL_VALUE


def best_heuristic_move(pos: Position, weights=None):
    """纯启发式选点（时间不足时的降级路径，也用作先验基线）。

    顺序：①能一手进角 ②不送对手进角 ③评估值最高 ④走法编码字典序最小。
    """
    moves = generate_moves(pos)
    if not moves:
        return None
    if len(moves) == 1:
        return moves[0]
    mover = pos.side
    best = None
    best_key = None
    win = win_in_one(pos)
    if win is not None:
        return win
    for mv in moves:
        child = _apply(pos, mv)
        res = terminal_after(child, 1)
        if res is not None:
            score = TERMINAL_VALUE if res.winner == mover else -TERMINAL_VALUE
        else:
            score = evaluate(child, mover, weights)
        key = (score, -mv.piece, -mv.src, -mv.dst)
        if best_key is None or key > best_key:
            best_key, best = key, mv
    return best


def _apply(pos: Position, mv):
    from ..transition import apply

    return apply(pos, mv)
