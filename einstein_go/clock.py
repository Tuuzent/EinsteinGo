"""计时器：每方 4 分钟/盘（规则第 8 条）。

时间源可注入，这是让"不 sleep 也能测计时"的关键：
    RealTime     真实单调时钟（对局用）
    FakeTime     手动推进（单测用）
    VirtualTime  由节点数折算（自对弈基准用，200 局秒级跑完）

语义（假设 A7）：只计本方「掷骰 → 落子」这段时间，不含对手思考。
"""

from __future__ import annotations

import time

from .constants import BLUE, RED

DEFAULT_BUDGET_MS = 4 * 60 * 1000  # 240000 ms


class TimeSource:
    def now_ms(self) -> int:  # pragma: no cover - 抽象
        raise NotImplementedError


class RealTime(TimeSource):
    """单调时钟，不受系统时间调整影响。"""

    def now_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000


class FakeTime(TimeSource):
    """测试用：只有显式 advance 才走时间。"""

    __slots__ = ("_now",)

    def __init__(self, start_ms: int = 0) -> None:
        self._now = start_ms

    def now_ms(self) -> int:
        return self._now

    def advance(self, ms: int) -> None:
        if ms < 0:
            raise ValueError("advance 必须非负")
        self._now += ms


class VirtualTime(TimeSource):
    """基准用：把"计算量"折算成时间流逝，避免真实等待。"""

    __slots__ = ("_now", "_rate_ms_per_sim")

    def __init__(self, start_ms: int = 0, ms_per_sim: float = 0.25) -> None:
        self._now = start_ms
        self._rate_ms_per_sim = ms_per_sim

    def now_ms(self) -> int:
        return self._now

    def charge_sims(self, sims: int) -> None:
        self._now += int(sims * self._rate_ms_per_sim)


class Clock:
    """双人棋钟。"""

    def __init__(self, budget_ms: int = DEFAULT_BUDGET_MS, time_source: TimeSource | None = None) -> None:
        self.budget_ms = budget_ms
        self.time_source = time_source or RealTime()
        self._remaining = {RED: budget_ms, BLUE: budget_ms}
        self._turn_side: int | None = None
        self._turn_start: int | None = None
        self._last_elapsed = 0

    # ---------------- 查询 ----------------
    def remaining(self, side: int) -> int:
        base = self._remaining[side]
        if self._turn_side == side and self._turn_start is not None:
            return max(0, base - (self.time_source.now_ms() - self._turn_start))
        return base

    def is_flag_fallen(self, side: int) -> bool:
        return self.remaining(side) <= 0

    @property
    def last_elapsed_ms(self) -> int:
        return self._last_elapsed

    @property
    def ticking(self) -> bool:
        return self._turn_start is not None

    # ---------------- 回合 ----------------
    def start_turn(self, side: int) -> None:
        """掷骰即开始计本方时间。重复调用视为同回合重启（不应发生）。"""
        if self._turn_start is not None:
            self.stop_turn()
        self._turn_side = side
        self._turn_start = self.time_source.now_ms()

    def stop_turn(self) -> int:
        """落子即停止计并扣除。返回本回合耗时。"""
        if self._turn_start is None or self._turn_side is None:
            return 0
        elapsed = max(0, self.time_source.now_ms() - self._turn_start)
        self._remaining[self._turn_side] = max(0, self._remaining[self._turn_side] - elapsed)
        self._turn_side = None
        self._turn_start = None
        self._last_elapsed = elapsed
        return elapsed

    def reset(self, budget_ms: int | None = None) -> None:
        """新一局：双方时间重置。"""
        if budget_ms is not None:
            self.budget_ms = budget_ms
        self._remaining = {RED: self.budget_ms, BLUE: self.budget_ms}
        self._turn_side = None
        self._turn_start = None
        self._last_elapsed = 0

    def snapshot(self) -> dict:
        return {
            "red_ms": self.remaining(RED),
            "blue_ms": self.remaining(BLUE),
            "ticking": self._turn_side,
        }


class TimeBank:
    """给 AI 的只读时间代理：AI 只能读，不能扣（防止搜索层偷偷改时间）。"""

    __slots__ = ("_clock", "_side")

    def __init__(self, clock: Clock, side: int) -> None:
        self._clock = clock
        self._side = side

    def remaining_ms(self) -> int:
        return self._clock.remaining(self._side)

    def now_ms(self) -> int:
        return self._clock.time_source.now_ms()
