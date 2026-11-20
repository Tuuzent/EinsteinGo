"""可复现随机源。

搜索内部的"虚拟骰"必须用独立派生的 RNG，绝不能碰对局 RNG，
否则同一棋谱在不同搜索预算下会产生不同的对局走向（不可复现）。
"""

from __future__ import annotations

import random

_TAG_SALT = {
    "rollout": 0xA1,
    "tie": 0xB2,
    "bench": 0xC3,
}


def derive(seed: int, tag: str) -> random.Random:
    """从 (seed, tag) 派生一个确定性 Random。字符串种子在 CPython 下跨版本稳定。"""
    return random.Random(f"einstein:{seed}:{tag}")


def tie_break(seed: int, salt: int) -> int:
    """确定性伪随机 tie-break 值。"""
    return random.Random(f"einstein:{seed}:tie:{salt}").getrandbits(32)
