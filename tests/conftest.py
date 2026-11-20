"""pytest 共享夹具。"""

from __future__ import annotations

import pytest

import helpers
from helpers import build_pos, play_random_game, random_positions

__all__ = ["build_pos", "play_random_game", "random_positions"]


@pytest.fixture
def pos_factory():
    return build_pos


@pytest.fixture
def start_pos():
    from einstein.state import initial_position

    return initial_position()


@pytest.fixture
def fake_time():
    from einstein.clock import FakeTime

    return FakeTime()


@pytest.fixture
def samples():
    """一批随机合法局面。"""
    return helpers.random_positions(count=25, max_plies=15, seed=11)


@pytest.fixture
def finished_games():
    """几局已结束的随机对局。"""
    return [play_random_game(seed=s) for s in range(6)]
