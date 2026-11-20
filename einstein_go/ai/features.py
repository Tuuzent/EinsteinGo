"""特征计算（全部 O(1) / O(6)，无搜索）。

关键设计：特征**不依赖骰值**，而是把 6 个骰面的结果聚合成"概率/期望"。
这样叶子评估只需算一次，且 evaluate 天然对 180° 旋转对称 —— 不需要把局面
旋转成"评估方是红方"再做分支判断，从根本上消灭"蓝方 max/min 写反"这类 bug。

代价：叶子评估对骰运不那么敏感。用 evaluate_expected（对 6 个骰面分别估值再平均）
可以在需要时补回这一层信息。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..config import FAR_DIST
from ..constants import CORNER, dist_to_corner
from ..movegen import generate_from
from ..state import alive_mask, find_piece

MAX_MOBILITY_PER_SIDE = 18  # 6 个骰面 x 最多 3 个走法


@dataclass(frozen=True, slots=True)
class SideStats:
    count: int          # 在盘子数
    d1: int             # 最靠前棋子到角点的距离
    d2: int             # 次靠前棋子距离（无第二枚时取 FAR_DIST）
    dsum: int           # 全部距离之和
    mobility: int       # 6 个骰面下合法走法总数
    win1: float         # 下一手进角概率（0..1）
    lead_sq: int        # 最靠前棋子所在格，-1 表示无子


def _empty_stats() -> SideStats:
    return SideStats(0, FAR_DIST, FAR_DIST, FAR_DIST * 6, 0, 0.0, -1)


@lru_cache(maxsize=1 << 18)
def side_stats(squares: tuple[int, ...], side: int) -> SideStats:
    alive = alive_mask(squares, side)
    if alive == 0:
        return _empty_stats()

    dists: list[int] = []
    lead_sq = -1
    lead_d = FAR_DIST + 1
    for num in range(1, 7):
        if not (alive >> num) & 1:
            continue
        sq = find_piece(squares, side * num)
        d = dist_to_corner(side, sq)
        dists.append(d)
        if d < lead_d:
            lead_d, lead_sq = d, sq
    dists.sort()

    mobility = 0
    win1_hits = 0
    corner = CORNER[side]
    for die in range(1, 7):
        moves = generate_from(squares, side, alive, die)
        mobility += len(moves)
        for mv in moves:
            if mv.dst == corner:
                win1_hits += 1
                break

    return SideStats(
        count=len(dists),
        d1=dists[0],
        d2=dists[1] if len(dists) > 1 else FAR_DIST,
        dsum=sum(dists),
        mobility=mobility,
        win1=win1_hits / 6.0,
        lead_sq=lead_sq,
    )


@lru_cache(maxsize=1 << 17)
def can_hit_prob(squares: tuple[int, ...], side: int, target: int) -> float:
    """side 方"下一手能踩到 target 格"的骰面概率。target < 0 直接返回 0。"""
    if target < 0:
        return 0.0
    alive = alive_mask(squares, side)
    if alive == 0:
        return 0.0
    hits = 0
    for die in range(1, 7):
        for mv in generate_from(squares, side, alive, die):
            if mv.dst == target:
                hits += 1
                break
    return hits / 6.0


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else (hi if x > hi else x)


def compute(squares: tuple[int, ...], player: int) -> dict[str, float]:
    """返回 8 个归一化特征（评估方视角，值域均为 [-1,1]）。"""
    me = side_stats(squares, player)
    op = side_stats(squares, -player)
    return {
        "dist": _clip((op.d1 - me.d1) / 4.0),
        "dist2": _clip((op.d2 - me.d2) / 4.0),
        "material": _clip((me.count - op.count) / 6.0),
        "mobility": _clip((me.mobility - op.mobility) / MAX_MOBILITY_PER_SIDE),
        "lose1": op.win1,
        "risk": can_hit_prob(squares, -player, me.lead_sq),
        "win1": me.win1,
        "structure": _clip((op.dsum - me.dsum) / 24.0),
    }


def mobility_for_die(squares: tuple[int, ...], side: int, die: int) -> int:
    alive = alive_mask(squares, side)
    if alive == 0:
        return 0
    return len(generate_from(squares, side, alive, die))


def can_enter_corner_for_die(squares: tuple[int, ...], side: int, die: int) -> bool:
    alive = alive_mask(squares, side)
    if alive == 0:
        return False
    corner = CORNER[side]
    return any(mv.dst == corner for mv in generate_from(squares, side, alive, die))


def clear_cache() -> None:
    side_stats.cache_clear()
    can_hit_prob.cache_clear()


def cache_info() -> dict:
    return {"side_stats": side_stats.cache_info(), "can_hit_prob": can_hit_prob.cache_info()}
