"""对局结果（无依赖模块，供 state / terminal 共同引用，避免循环 import）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TerminalReason(str, Enum):
    REACHED_CORNER = "reached_corner"   # 到达对方出发区角点
    ANNIHILATION = "annihilation"       # 吃光对方全部棋子
    TIMEOUT = "timeout"                 # 本方计时耗尽（超时判负）
    ADJUDICATION = "adjudication"       # MAX_PLY 安全阀（本规则集下不可达）


@dataclass(frozen=True, slots=True)
class GameResult:
    """最终结果。winner 只可能是 +1 / -1 —— 结构上排除和棋。"""

    winner: int
    reason: TerminalReason
    ply: int = 0
    detail: str = ""

    def __post_init__(self) -> None:
        if self.winner not in (1, -1):
            raise ValueError(f"winner must be +1 or -1 (no draws allowed), got {self.winner!r}")

    @property
    def loser(self) -> int:
        return -self.winner

    def describe(self) -> str:
        side = "红方" if self.winner > 0 else "蓝方"
        return f"{side}胜（{self.reason.value}，第 {self.ply} 手）"
