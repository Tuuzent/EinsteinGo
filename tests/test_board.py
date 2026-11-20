"""棋盘常量、坐标、方向表、渲染的测试。"""

from __future__ import annotations

import pytest

from einstein.board import render_squares, to_rows
from einstein.constants import (
    BLUE_HOME,
    CORNER,
    DELTAS,
    N_SQUARES,
    NEIGHBORS,
    RED_HOME,
    SIDES,
    dist_to_corner,
    idx,
    in_board,
    parse_sq,
    rc,
    sq_name,
)
from einstein.state import initial_position, rot180


def test_board_shape():
    assert N_SQUARES == 25
    assert len({sq_name(i) for i in range(N_SQUARES)}) == 25


def test_square_name_roundtrip():
    for i in range(N_SQUARES):
        assert parse_sq(sq_name(i)) == i
    assert sq_name(0) == "a1"
    assert sq_name(24) == "e5"


def test_invalid_square_raises():
    for bad in ("", "a", "a6", "f1", "aa", "11"):
        with pytest.raises(ValueError):
            parse_sq(bad)


def test_home_regions():
    assert len(RED_HOME) == 6
    assert len(BLUE_HOME) == 6
    assert not (RED_HOME & BLUE_HOME)
    assert BLUE_HOME == {N_SQUARES - 1 - i for i in RED_HOME}
    assert {sq_name(i) for i in sorted(RED_HOME)} == {"a1", "b1", "c1", "a2", "b2", "a3"}
    assert {sq_name(i) for i in sorted(BLUE_HOME)} == {"e5", "d5", "c5", "e4", "d4", "e3"}


def test_corner_mapping():
    assert CORNER[1] == idx(5, 5) == 24
    assert CORNER[-1] == idx(1, 1) == 0
    assert CORNER[1] in BLUE_HOME      # 红方的目标角点落在蓝方出发区
    assert CORNER[-1] in RED_HOME


@pytest.mark.parametrize("side", SIDES)
def test_neighbors_in_board_and_one_step(side):
    for sq in range(N_SQUARES):
        r, c = rc(sq)
        for dst in NEIGHBORS[side][sq]:
            dr, dc = rc(dst)
            assert in_board(dr, dc)
            assert (dr - r, dc - c) in DELTAS[side]


def test_neighbors_extremes():
    assert len(NEIGHBORS[1][idx(1, 1)]) == 3       # 红方 a1：右/下/右下
    assert NEIGHBORS[1][idx(5, 5)] == ()           # 红方已在目标角点（终局）
    assert NEIGHBORS[-1][idx(1, 1)] == ()          # 蓝方已在目标角点（终局）
    assert len(NEIGHBORS[-1][idx(5, 5)]) == 3      # 蓝方出发角点：上/左/左上
    # 红方 (5,3)：只能向右
    assert NEIGHBORS[1][idx(5, 3)] == (idx(5, 4),)
    # 红方 (2,5)：只能向下
    assert NEIGHBORS[1][idx(2, 5)] == (idx(3, 5),)


def test_distance_closed_form_matches_bfs():
    """切比雪夫闭式解必须与 BFS 最短路完全一致（这条守门规则 R2 的替代方案）。"""
    from collections import deque

    for side in SIDES:
        target = CORNER[side]
        dist = {target: 0}
        q = deque([target])
        while q:
            cur = q.popleft()
            for nxt in range(N_SQUARES):
                if nxt in dist:
                    continue
                if cur in NEIGHBORS[side][nxt]:   # nxt 一步能到 cur
                    dist[nxt] = dist[cur] + 1
                    q.append(nxt)
        for sq in range(N_SQUARES):
            assert dist_to_corner(side, sq) == dist[sq], (side, sq_name(sq))


def test_rot180_involution():
    pos = initial_position()
    twice = rot180(rot180(pos))
    assert twice.squares == pos.squares
    assert twice.side == pos.side
    assert twice.zhash == pos.zhash
    # 旋转后红子变蓝子
    once = rot180(pos)
    assert all(a == -b for a, b in zip(once.squares, reversed(pos.squares)))


def test_render():
    text = render_squares(initial_position().squares)
    assert "R1" in text and "B6" in text
    assert text.count("\n") == 5
    rows = to_rows(initial_position().squares)
    assert len(rows) == 5 and all(len(r) == 5 for r in rows)
