"""自对弈/端到端测试。"""

from __future__ import annotations

import pytest

from einstein.clock import VirtualTime
from einstein.constants import RED
from einstein.players import make_player, play_out
from einstein.session import GameSession
from einstein.sync import replay, verify_state_equal


def _play(spec_a: str, spec_b: str, games: int, nodes: int, seed: int = 7):
    wins_a = 0
    plies = []
    for g in range(games):
        a_is_red = g % 2 == 0
        a = make_player(spec_a, seed=seed + g, node_limit=nodes)
        b = make_player(spec_b, seed=seed + 500 + g, node_limit=nodes)
        s = GameSession(first_player=RED, seed=seed + g, time_source=VirtualTime())
        play_out(s, {RED: a if a_is_red else b, -RED: b if a_is_red else a})
        plies.append(s.ply)
        if (s.result.winner == RED) == a_is_red:
            wins_a += 1
    return wins_a, wins_a / games, plies


def test_selfplay_smoke_all_terminate():
    """机机对局必须全部终局且手数在理论界内（<= 84）。"""
    for spec in ("random", "heuristic", "mcts:80"):
        _, _, plies = _play(spec, spec, games=2, nodes=80)
        for p in plies:
            assert 5 <= p <= 84


def test_selfplay_hash_chain_replays():
    a = make_player("mcts", seed=1, node_limit=120)
    b = make_player("heuristic", seed=2)
    s = GameSession(first_player=RED, seed=1, time_source=VirtualTime())
    play_out(s, {RED: a, -RED: b})
    final = replay(s.record())
    assert verify_state_equal(s.state, final) == []


@pytest.mark.slow
def test_mcts_beats_random():
    wins, rate, plies = _play("mcts", "random", games=10, nodes=400)
    assert rate >= 0.7, f"mcts vs random 胜率 {rate}"
    assert sum(plies) / len(plies) <= 40


@pytest.mark.slow
def test_mcts_beats_heuristic():
    wins, rate, plies = _play("mcts", "heuristic", games=10, nodes=400)
    assert rate >= 0.5, f"mcts vs heuristic 胜率 {rate}"


@pytest.mark.slow
def test_no_illegal_move_in_200_games():
    """200 局随机对局，逐手校验非法走法次数必须为 0。"""
    count = 0
    for seed in range(200):
        s = GameSession(seed=seed, time_source=VirtualTime())
        while not s.finished:
            s.roll()
            moves = s.legal_moves()
            assert moves, "出现无走法的非终局局面"
            s.play(moves[seed % len(moves)])
            count += 1
    assert count > 2000
