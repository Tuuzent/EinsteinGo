"""启发式评估测试。"""

from __future__ import annotations

import math

from einstein.ai.eval import (
    best_heuristic_move,
    evaluate,
    evaluate_expected,
    evaluate_for_die,
    opponent_win_prob,
    win_in_one,
)
from einstein.ai import features as F
from einstein.config import DEFAULT_WEIGHTS
from einstein.constants import BLUE, RED, parse_sq, sq_name
from einstein.movegen import generate_moves
from einstein.state import initial_position, rot180
from helpers import build_pos, random_positions


def test_initial_position_is_balanced():
    pos = initial_position()
    assert abs(evaluate(pos, RED)) < 1e-9
    assert abs(evaluate(pos, BLUE)) < 1e-9


def test_eval_range():
    for pos in random_positions(count=15, max_plies=12, seed=21):
        for side in (RED, BLUE):
            v = evaluate(pos, side)
            assert -1.0 < v < 1.0


def test_eval_mirror_invariance():
    """R4 守门：评估对 180° 旋转必须严格对称。"""
    for pos in random_positions(count=10, max_plies=10, seed=22):
        assert abs(evaluate(pos, RED) - evaluate(rot180(pos), BLUE)) < 1e-12
        assert abs(evaluate(pos, BLUE) - evaluate(rot180(pos), RED)) < 1e-12


def test_eval_prefers_closer_piece():
    """只改变红方棋子的位置，评估必须偏向更接近 e5 的那一手。"""
    far = build_pos(red={1: "b2"}, blue={1: "c1"}, side=RED, die=1)
    near = build_pos(red={1: "d4"}, blue={1: "c1"}, side=RED, die=1)
    assert evaluate(near, RED) > evaluate(far, RED)


def test_eval_prefers_more_material():
    six = build_pos(red={1: "a1", 2: "b1", 3: "c1", 4: "a2", 5: "b2", 6: "a3"},
                    blue={1: "e5", 2: "d5", 3: "c5", 4: "e4", 5: "d4"}, side=RED, die=1)
    assert evaluate(six, RED) > 0


def test_eval_penalizes_opponent_win_in_one():
    # 蓝方 1 号在 b2，一步就能到 a1 获胜
    pos = build_pos(red={1: "c3"}, blue={1: "b2"}, side=RED, die=1)
    assert opponent_win_prob(pos) == 1.0
    assert evaluate(pos, RED) < -0.3


def test_eval_rewards_own_win_in_one():
    pos = build_pos(red={1: "d5"}, blue={1: "c1"}, side=RED, die=1)
    assert evaluate(pos, RED) > 0.3


def test_features_keys_and_ranges():
    pos = initial_position()
    f = F.compute(pos.squares, RED)
    assert set(f) == set(DEFAULT_WEIGHTS)
    for k, v in f.items():
        assert -1.0 <= v <= 1.0, k


def test_evaluate_expected_is_mean_of_dice():
    pos = build_pos(red={1: "c3"}, blue={2: "c2"}, side=RED, die=1)
    manual = sum(evaluate_for_die(pos, RED, d) for d in range(1, 7)) / 6.0
    assert abs(evaluate_expected(pos, RED) - manual) < 1e-12


def test_win_in_one_detects_corner_move():
    pos = build_pos(red={1: "d5"}, side=RED, die=1)
    mv = win_in_one(pos)
    assert mv is not None and mv.dst == parse_sq("e5")


def test_win_in_one_none_when_unrolled():
    pos = build_pos(red={1: "d5"}, side=RED, die=0)
    assert win_in_one(pos) is None


def test_best_heuristic_move_returns_legal():
    for pos in random_positions(count=8, max_plies=8, seed=23):
        p = pos.with_die(3)
        mv = best_heuristic_move(p)
        assert mv is not None
        assert mv in generate_moves(p)


def test_best_heuristic_move_takes_mate():
    pos = build_pos(red={1: "d5"}, blue={2: "c1"}, side=RED, die=1)
    mv = best_heuristic_move(pos)
    assert mv.dst == parse_sq("e5")


def test_best_heuristic_prefers_capture_of_leader():
    """能吃掉对手领头子时优先吃（防守价值）。"""
    pos = build_pos(red={2: "a1"}, blue={1: "b2"}, side=RED, die=2)
    mv = best_heuristic_move(pos)
    assert sq_name(mv.dst) == "b2"


def test_eval_deterministic():
    pos = build_pos(red={1: "c3", 2: "a2"}, blue={1: "d4"}, side=RED, die=2)
    assert evaluate(pos, RED) == evaluate(pos, RED)
    assert math.isfinite(evaluate(pos, RED))
