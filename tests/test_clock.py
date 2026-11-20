"""计时器测试（全部用 FakeTime，不依赖真实 sleep）。"""

from __future__ import annotations

import pytest

from einstein.clock import Clock, FakeTime, TimeBank, VirtualTime
from einstein.constants import BLUE, RED
from einstein.errors import EngineError, ErrorCode
from einstein.movegen import generate_moves
from einstein.outcome import TerminalReason
from einstein.session import GameSession


def test_deduct_on_stop_turn():
    t = FakeTime()
    clock = Clock(10_000, t)
    clock.start_turn(RED)
    t.advance(1500)
    assert clock.remaining(RED) == 8500       # 走时中实时反映（供界面显示）
    assert clock.stop_turn() == 1500
    assert clock.remaining(RED) == 8500       # 停表后固化
    assert clock.remaining(BLUE) == 10_000


def test_flag_falls_at_zero():
    t = FakeTime()
    clock = Clock(1000, t)
    clock.start_turn(RED)
    t.advance(999)
    assert not clock.is_flag_fallen(RED)
    t.advance(1)
    assert clock.is_flag_fallen(RED)
    clock.stop_turn()
    assert clock.remaining(RED) == 0


def test_negative_clamped_to_zero():
    t = FakeTime()
    clock = Clock(1000, t)
    clock.start_turn(RED)
    t.advance(5000)
    clock.stop_turn()
    assert clock.remaining(RED) == 0


def test_reset_between_games():
    t = FakeTime()
    clock = Clock(240_000, t)
    clock.start_turn(RED)
    t.advance(60_000)
    clock.stop_turn()
    assert clock.remaining(RED) == 180_000
    clock.reset()
    assert clock.remaining(RED) == 240_000
    assert clock.remaining(BLUE) == 240_000
    assert not clock.ticking


def test_roll_starts_clock():
    t = FakeTime()
    s = GameSession(seed=1, time_source=t)
    assert not s.clock.ticking
    s.roll(3)
    assert s.clock.ticking
    t.advance(2000)
    assert s.remaining_ms() == 238_000


def test_play_deducts_exactly_once():
    t = FakeTime()
    s = GameSession(seed=1, time_source=t)
    s.roll(3)
    t.advance(1200)
    mv = generate_moves(s.pos)[0]
    s.play(mv)
    assert s.remaining_ms(RED) == 240_000 - 1200
    assert not s.clock.ticking


def test_timeout_loses():
    t = FakeTime()
    s = GameSession(seed=1, time_source=t, budget_ms=1000)
    s.roll(3)
    t.advance(1500)
    with pytest.raises(EngineError) as exc:
        s.play(generate_moves(s.pos)[0])
    assert exc.value.code is ErrorCode.CLOCK_FLAG_FALLEN
    assert s.result is not None
    assert s.result.winner == BLUE
    assert s.result.reason is TerminalReason.TIMEOUT


def test_check_timeout_api():
    t = FakeTime()
    s = GameSession(seed=1, time_source=t, budget_ms=1000)
    s.roll(3)
    t.advance(2000)
    assert s.check_timeout()
    assert s.result.winner == BLUE


def test_time_bank_is_read_only():
    t = FakeTime()
    clock = Clock(5000, t)
    bank = TimeBank(clock, RED)
    clock.start_turn(RED)
    t.advance(1000)
    assert bank.remaining_ms() == 4000
    assert bank.now_ms() == 1000
    assert not hasattr(bank, "stop_turn")


def test_virtual_clock_charges_by_sims():
    v = VirtualTime(ms_per_sim=0.5)
    v.charge_sims(100)
    assert v.now_ms() == 50


def test_budget_reset_uses_new_value():
    clock = Clock(1000)
    clock.reset(2000)
    assert clock.budget_ms == 2000
    assert clock.remaining(RED) == 2000
