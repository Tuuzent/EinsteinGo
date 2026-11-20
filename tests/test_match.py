"""赛制轮次测试：先手序列、提前终止、比分。"""

from __future__ import annotations

import pytest

from einstein.constants import RED
from einstein.match import (
    FIRST_PLAYER_OF_GAME,
    A,
    B,
    GameRecord,
    Match,
    make_record,
)
from einstein.outcome import GameResult, TerminalReason


def fake_runner(pattern: str):
    """pattern[i] == 'A' 或 'B'，表示第 i+1 盘胜方。"""

    def runner(game_no: int, first: str) -> GameRecord:
        winner_name = pattern[game_no - 1]
        color_a = RED if first == A else -RED
        winner_side = color_a if winner_name == A else -color_a
        return make_record(game_no, first,
                           GameResult(winner_side, TerminalReason.REACHED_CORNER, 20), 20)

    return runner


def test_first_player_sequence():
    assert [FIRST_PLAYER_OF_GAME[i] for i in range(1, 8)] == [A, B, B, A, A, B, B]


def test_early_stop_at_four():
    res = Match(fake_runner("AAAA")).play()
    assert res.games_played == 4
    assert (res.wins_a, res.wins_b) == (4, 0)
    assert res.winner == A


def test_four_one_plays_five():
    res = Match(fake_runner("ABAAA")).play()
    assert res.games_played == 5
    assert (res.wins_a, res.wins_b) == (4, 1)


def test_four_two_plays_six():
    res = Match(fake_runner("ABABAA")).play()
    assert res.games_played == 6
    assert (res.wins_a, res.wins_b) == (4, 2)


def test_four_three_plays_seven():
    res = Match(fake_runner("ABABABA")).play()
    assert res.games_played == 7
    assert (res.wins_a, res.wins_b) == (4, 3)


def test_b_win():
    res = Match(fake_runner("BBBB")).play()
    assert res.games_played == 4
    assert res.winner == B


def test_no_extra_game_after_win():
    calls = []

    def runner(game_no, first):
        calls.append(game_no)
        first_name = "A" if game_no <= 4 else "B"
        color_a = RED if first == A else -RED
        return make_record(game_no, first,
                           GameResult(color_a, TerminalReason.REACHED_CORNER, 15), 15)

    res = Match(runner).play()
    assert calls == [1, 2, 3, 4]
    assert res.winner == A


def test_score_sum_equals_games():
    for pattern in ("AAAA", "ABAAA", "ABABAA", "ABABABA", "BBBB"):
        res = Match(fake_runner(pattern)).play()
        assert res.wins_a + res.wins_b == res.games_played


def test_color_of_a_alternates_with_first_player():
    rec_first_a = make_record(1, A, GameResult(1, TerminalReason.REACHED_CORNER), 10)
    rec_first_b = make_record(2, B, GameResult(-1, TerminalReason.REACHED_CORNER), 10)
    assert rec_first_a.color_of_a == RED
    assert rec_first_b.color_of_a == -RED
    # 先手方执红：
    assert rec_first_a.winner_name == A
    assert rec_first_b.winner_name == A   # 蓝方赢 = B 先手却输，A 胜


def test_match_validates_args():
    with pytest.raises(ValueError):
        Match(fake_runner("AAAA"), max_games=8)
    with pytest.raises(ValueError):
        Match(fake_runner("AAAA"), max_games=3, needed_wins=4)


def test_runner_mismatch_detected():
    def bad_runner(game_no, first):
        return make_record(99, first, GameResult(1, TerminalReason.REACHED_CORNER), 1)

    with pytest.raises(ValueError):
        Match(bad_runner).play()
