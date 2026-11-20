"""职责⑤：胜负判定的测试。"""

from __future__ import annotations

import pytest

from einstein_go.constants import parse_sq
from einstein_go.errors import EngineError, ErrorCode
from einstein_go.movegen import generate_moves
from einstein_go.outcome import GameResult, TerminalReason
from einstein_go.session import GameSession
from einstein_go.state import initial_position
from einstein_go.terminal import adjudicate, is_terminal, terminal_after, winner_by_flag
from einstein_go.transition import apply
from helpers import build_pos, play_random_game


def _apply_dst(pos, dst_name: str):
    dst = parse_sq(dst_name)
    mv = next(m for m in generate_moves(pos) if m.dst == dst)
    return apply(pos, mv)


def test_red_reaches_corner():
    pos = build_pos(red={1: "d5"}, side=1, die=1)
    new = _apply_dst(pos, "e5")
    res = terminal_after(new, 1)
    assert res is not None
    assert res.winner == 1
    assert res.reason is TerminalReason.REACHED_CORNER


def test_blue_reaches_corner():
    pos = build_pos(blue={1: "b2"}, side=-1, die=1)
    new = _apply_dst(pos, "a1")
    res = terminal_after(new, 1)
    assert res is not None and res.winner == -1
    assert res.reason is TerminalReason.REACHED_CORNER


def test_corner_priority_over_annihilation():
    """一手同时"进角 + 吃光对方"时，reason 固定为 REACHED_CORNER。"""
    pos = build_pos(red={1: "d5"}, blue={2: "e5"}, side=1, die=1)
    new = _apply_dst(pos, "e5")
    assert new.blue_alive == 0
    res = terminal_after(new, 1)
    assert res.winner == 1
    assert res.reason is TerminalReason.REACHED_CORNER


def test_annihilation():
    pos = build_pos(red={1: "c3"}, blue={2: "d4"}, side=1, die=1)
    new = _apply_dst(pos, "d4")
    res = terminal_after(new, 1)
    assert res is not None and res.winner == 1
    assert res.reason is TerminalReason.ANNIHILATION


def test_annihilation_by_blue():
    pos = build_pos(red={2: "c3"}, blue={1: "d4"}, side=-1, die=1)
    new = _apply_dst(pos, "c3")
    res = terminal_after(new, 1)
    assert res.winner == -1
    assert res.reason is TerminalReason.ANNIHILATION


def test_not_terminal_with_one_piece_left():
    pos = build_pos(red={1: "a1"}, blue={2: "c3"}, side=1, die=1)
    new = _apply_dst(pos, "b1")
    assert terminal_after(new, 1) is None
    assert not is_terminal(new)


def test_eating_own_last_piece_is_not_loss():
    """吃己方子导致自己只剩 1 枚仍不算输（只有被吃光才输）。"""
    pos = build_pos(red={1: "c3", 2: "d4"}, blue={3: "e3"}, side=1, die=1)
    new = _apply_dst(pos, "d4")
    assert new.piece_count(1) == 1
    assert terminal_after(new, 1) is None


def test_never_draw_across_random_games():
    for seed in range(120):
        s = play_random_game(seed=seed)
        assert s.result is not None, f"seed {seed} 未终局"
        assert s.result.winner in (1, -1)
        assert s.result.reason in (TerminalReason.REACHED_CORNER,
                                   TerminalReason.ANNIHILATION)


def test_games_terminate_within_bound():
    """红方每步使 r+c 至少 +1，单方走子 <= 42，故 ply <= 84。"""
    for seed in range(120):
        s = play_random_game(seed=seed)
        assert s.ply <= 84, f"seed {seed} ply={s.ply} 超出理论上界"


def test_game_result_rejects_draw():
    with pytest.raises(ValueError):
        GameResult(0, TerminalReason.REACHED_CORNER, 1)


def test_timeout_result():
    res = winner_by_flag(1, 30)
    assert res.winner == -1
    assert res.reason is TerminalReason.TIMEOUT
    assert winner_by_flag(-1).winner == 1


def test_terminal_blocks_play():
    s = GameSession(seed=0)
    s.state = s.state.with_result(winner_by_flag(1))
    with pytest.raises(EngineError) as exc:
        s.roll()
    assert exc.value.code is ErrorCode.GAME_ALREADY_OVER


def test_adjudicate_is_deterministic_and_decisive():
    pos = initial_position()
    a = adjudicate(pos, 300)
    b = adjudicate(pos, 300)
    assert a == b
    assert a.winner in (1, -1)
    assert a.reason is TerminalReason.ADJUDICATION


def test_is_terminal_matches_terminal_after():
    for seed in range(20):
        s = play_random_game(seed=seed)
        pos = s.pos
        expect = is_terminal(pos)
        # 用"谁刚走完"重构：pos.side 是下一手行动方
        res = terminal_after(pos, s.ply)
        assert expect == (res is not None)
        if res is not None:
            assert res.winner == s.result.winner
