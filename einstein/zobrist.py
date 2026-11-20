"""Zobrist 哈希表（固定种子，跨进程可复现）。

用于三处：Position.zhash（增量维护）、协议层状态对账、置换表 key。
索引约定：Z_PIECE[sq][code + 6]，其中 code == 0 的槽位恒为 0，
这样"某格为空"对哈希零贡献，增量公式可以无条件异或。
"""

from __future__ import annotations

import random

from .constants import N_SQUARES

_SEED = 20261118
_RNG = random.Random(_SEED)

# index = code + 6 -> 0..12
Z_PIECE: tuple[tuple[int, ...], ...] = tuple(
    tuple(0 if code == 0 else _RNG.getrandbits(64) for code in range(-6, 7))
    for _ in range(N_SQUARES)
)

Z_SIDE = _RNG.getrandbits(64)

# index = die -> 0..6，die == 0（未掷骰）零贡献
Z_DIE: tuple[int, ...] = tuple(0 if die == 0 else _RNG.getrandbits(64) for die in range(7))


def full_hash(squares, side: int, die: int) -> int:
    """从零重算哈希。用于校验增量哈希是否漂移。"""
    h = 0
    for i, code in enumerate(squares):
        if code:
            h ^= Z_PIECE[i][code + 6]
    if side < 0:
        h ^= Z_SIDE
    return h ^ Z_DIE[die]
