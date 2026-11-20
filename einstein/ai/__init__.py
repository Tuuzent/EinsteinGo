"""AI 子包：启发式评估 + 带机会节点的 MCTS。"""

from __future__ import annotations

from .eval import (
    best_heuristic_move,
    evaluate,
    evaluate_expected,
    evaluate_for_die,
    opponent_win_prob,
    win_in_one,
)
from .mcts import (
    Budget,
    MoveStat,
    NullBank,
    SearchResult,
    allocate_ms,
    backprop,
    choose_move,
    compute_priors,
    search,
)

__all__ = [
    "Budget",
    "MoveStat",
    "NullBank",
    "SearchResult",
    "allocate_ms",
    "backprop",
    "best_heuristic_move",
    "choose_move",
    "compute_priors",
    "evaluate",
    "evaluate_expected",
    "evaluate_for_die",
    "opponent_win_prob",
    "search",
    "win_in_one",
]
