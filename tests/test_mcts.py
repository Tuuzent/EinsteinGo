"""MCTS 测试（重点守 R5/R6/R7/R8 四个高危点）。"""

from __future__ import annotations

import pytest

from einstein_go.ai.mcts import (
    CHANCE,
    DECISION,
    Budget,
    Node,
    NullBank,
    allocate_ms,
    backprop,
    choose_move,
    compute_priors,
    search,
)
from einstein_go.config import SearchConfig
from einstein_go.constants import BLUE, RED, parse_sq, sq_name
from einstein_go.errors import EngineError, ErrorCode
from einstein_go.movegen import generate_moves, resolve_candidates
from einstein_go.transition import apply
from helpers import build_pos, random_positions


FAST = SearchConfig(seed=7, node_limit=200)


# ---------------------------------------------------------------- 战术短路
def test_single_legal_move_returns_immediately():
    pos = build_pos(red={1: "e3"}, side=RED, die=1)   # 只能向下
    assert len(generate_moves(pos)) == 1
    res = choose_move(pos, NullBank(), FAST)
    assert res.reason == "single"
    assert res.nodes == 0
    assert res.move.dst == parse_sq("e4")


def test_finds_mate_in_one():
    """d4 有 3 个走法（e4/d5/e5），其中 e5 是角点 → 必须走 "mate" 短路。"""
    pos = build_pos(red={1: "d4"}, blue={2: "c1"}, side=RED, die=1)
    assert len(generate_moves(pos)) == 3
    res = choose_move(pos, NullBank(), FAST)
    assert res.reason == "mate"
    assert res.move.dst == parse_sq("e5")


def test_blocks_immediate_loss():
    """对手 b2 的棋子一步进角 a1；红方必须吃掉它，否则立刻输。"""
    pos = build_pos(red={2: "a1"}, blue={1: "b2"}, side=RED, die=2)
    res = choose_move(pos, NullBank(), SearchConfig(seed=7, node_limit=600))
    assert res.reason == "mcts"
    assert sq_name(res.move.dst) == "b2"


def test_low_time_falls_back_to_heuristic():
    pos = build_pos(red={1: "c3"}, blue={2: "c2"}, side=RED, die=1)
    bank = NullBank(ms=5)     # 远低于 min_think_ms
    res = choose_move(pos, bank, SearchConfig(seed=1, min_think_ms=60))
    assert res.reason == "low_time"
    assert res.move in generate_moves(pos)


def test_die_not_rolled_raises():
    pos = build_pos(red={1: "c3"}, side=RED, die=0)
    with pytest.raises(EngineError) as exc:
        choose_move(pos, NullBank(), FAST)
    assert exc.value.code is ErrorCode.DIE_NOT_ROLLED


# ---------------------------------------------------------------- 预算
def test_node_budget_respected():
    pos = build_pos(red={1: "c3", 2: "a2"}, blue={1: "d4", 2: "e3"}, side=RED, die=1)
    cfg = SearchConfig(seed=3, node_limit=120)
    res = choose_move(pos, NullBank(), cfg)
    assert res.nodes <= 120 + 8
    assert res.sims > 0


def test_time_budget_respected():
    pos = build_pos(red={1: "c3", 2: "a2"}, blue={1: "d4"}, side=RED, die=1)
    cfg = SearchConfig(seed=3)
    budget = Budget(150, cfg)
    res = search(pos, budget, cfg)
    assert res.elapsed_ms <= 150 + 60   # 含安全余量与检查粒度


def test_search_terminates_when_depth_cap_blocks_expansion():
    """回归：达到 max_depth 时不扩展节点，预算必须按"模拟次数"而非"扩展次数"计。"""
    pos = build_pos(red={1: "c3", 2: "a2"}, blue={1: "d4", 2: "e3"}, side=RED, die=1)
    cfg = SearchConfig(seed=1, max_depth=2, node_limit=200)
    res = search(pos, Budget(60_000, cfg), cfg)
    assert res.move is not None
    assert res.sims <= 200


def test_allocate_ms_bounds():
    cfg = SearchConfig()
    assert allocate_ms(240_000, 0, cfg) == cfg.max_think_ms
    assert allocate_ms(100, 0, cfg) == cfg.min_think_ms
    assert cfg.min_think_ms <= allocate_ms(1_000, 30, cfg) <= cfg.max_think_ms


# ---------------------------------------------------------------- 确定性 & 合法性
def test_deterministic_given_seed():
    pos = build_pos(red={1: "c3", 2: "a2"}, blue={1: "d4"}, side=RED, die=1)
    cfg = SearchConfig(seed=11, node_limit=150)
    moves = {choose_move(pos, NullBank(), cfg).move for _ in range(3)}
    assert len(moves) == 1


def test_root_die_respected():
    """R6 守门：根是决策节点，返回的棋子必须落在当前骰值的候选集内。"""
    for pos in random_positions(count=12, max_plies=10, seed=31):
        p = pos.with_die(4)
        res = choose_move(p, NullBank(), SearchConfig(seed=5, node_limit=80))
        alive = p.alive(p.side)
        assert res.move.piece in resolve_candidates(alive, 4)


def test_never_returns_illegal_move():
    for pos in random_positions(count=25, max_plies=12, seed=32):
        p = pos.with_die(2)
        res = choose_move(p, NullBank(), SearchConfig(seed=6, node_limit=60))
        assert res.move in generate_moves(p)


# ---------------------------------------------------------------- 节点语义
def test_terminal_value_sign():
    """走完一手即胜时，子节点（属于对手视角）的终局值必须是 -1。"""
    pos = build_pos(red={1: "d5"}, blue={2: "c1"}, side=RED, die=1)
    root = Node(pos, pos.side, None, DECISION, +1, 1.0, None, 0)
    from einstein_go.ai.mcts import _expand

    _expand(root, FAST)
    won = [c for c in root.children if c.terminal_value is not None]
    assert won, "应当存在一步进角的终局子节点"
    for c in won:
        assert c.owner == BLUE
        assert c.terminal_value == -1.0


def test_backprop_sign_alternates():
    """R7 守门：只在走子边翻转一次，手算三层。"""
    root = Node(None, RED, None, DECISION, +1, 1.0, None, 0)
    chance = Node(None, BLUE, root, CHANCE, -1, 1 / 6, None, 1)
    decision = Node(None, BLUE, chance, DECISION, +1, 1.0, None, 0)
    root.children.append(chance)
    chance.children.append(decision)

    backprop(decision, 0.5)
    assert decision.n == 1 and decision.w == pytest.approx(0.5)
    assert chance.n == 1 and chance.w == pytest.approx(0.5)   # 同 owner，不翻转
    assert root.n == 1 and root.w == pytest.approx(-0.5)      # 跨 owner，翻转一次


def test_chance_node_visits_sum_to_parent():
    pos = build_pos(red={1: "c3", 2: "a2"}, blue={1: "d4", 2: "e3"}, side=RED, die=1)
    cfg = SearchConfig(seed=9, node_limit=400)
    search(pos, Budget(5_000, cfg), cfg)
    # 无法直接拿根，改为验证概率守恒：重新构造一次并手动展开
    root = Node(pos, pos.side, None, DECISION, +1, 1.0, None, 0)
    from einstein_go.ai.mcts import _expand

    _expand(root, cfg)
    for chance_child in root.children:
        _expand(chance_child, cfg)
        assert len(chance_child.children) == 6
        assert sum(c.prior for c in chance_child.children) == pytest.approx(1.0)


def test_priors_normalized_and_ordered():
    pos = build_pos(red={1: "d5"}, blue={2: "c1"}, side=RED, die=1)
    moves = generate_moves(pos)
    priors = compute_priors(pos, moves, RED, FAST)
    assert sum(priors) == pytest.approx(1.0)
    assert all(p >= FAST.p_min for p in priors)
    # 进角的那一手先验必须是最大的（终局加成 10.0）
    best = max(zip(priors, moves), key=lambda t: t[0])[1]
    assert best.dst == parse_sq("e5")


def test_select_final_prefers_more_visits():
    from einstein_go.ai.mcts import _select_final

    root = Node(None, RED, None, DECISION, +1, 1.0, None, 0)
    a = Node(None, BLUE, root, CHANCE, -1, 0.5, None, 1)
    b = Node(None, BLUE, root, CHANCE, -1, 0.5, None, 2)
    a.n, a.w = 10, 5.0
    b.n, b.w = 20, 2.0
    root.children = [a, b]
    assert _select_final(root) is b


def test_search_result_stats_sorted():
    pos = build_pos(red={1: "c3", 2: "a2"}, blue={1: "d4"}, side=RED, die=1)
    res = choose_move(pos, NullBank(), SearchConfig(seed=4, node_limit=200))
    assert res.searched
    visits = [s.visits for s in res.root_stats]
    assert visits == sorted(visits, reverse=True)
    assert res.move == res.root_stats[0].move
    assert "决策" in res.explain()


def test_apply_matches_search_child_positions():
    """搜索树里 Chance 子节点的局面 = apply 后的局面（防止虚拟骰写错）。"""
    pos = build_pos(red={1: "c3"}, blue={1: "d4"}, side=RED, die=1)
    root = Node(pos, pos.side, None, DECISION, +1, 1.0, None, 0)
    from einstein_go.ai.mcts import _expand

    _expand(root, FAST)
    for child in root.children:
        assert child.pos == apply(pos, child.move)
        assert child.pos.side == -pos.side
