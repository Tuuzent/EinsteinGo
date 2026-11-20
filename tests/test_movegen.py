"""职责①：合法走法生成的测试（规则边界在这里集中覆盖）。"""

from __future__ import annotations

import pytest

from einstein.constants import CORNER, idx, parse_sq, sq_name
from einstein.errors import EngineError, ErrorCode
from einstein.movegen import generate_moves, has_any_move, resolve_candidates
from einstein.state import initial_position
from helpers import build_pos, random_positions


def mask(*nums: int) -> int:
    m = 0
    for n in nums:
        m |= 1 << n
    return m


@pytest.mark.parametrize(
    "nums,die,expect",
    [
        ((1, 2, 3, 4, 5, 6), 4, (4,)),        # 精确编号在盘 → 只能走它
        ((3, 6), 4, (3, 6)),                  # 文档例子：4、5 已出局，骰 4 可走 3 或 6
        ((2, 5), 4, (2, 5)),
        ((3, 5), 4, (3, 5)),
        ((1, 2), 4, (2,)),                    # 没有更大的 → 只有下侧最近
        ((5, 6), 4, (5,)),                    # 没有更小的 → 只有上侧最近
        ((2,), 6, (2,)),                      # 只剩单枚 → 必走它
        ((4,), 4, (4,)),
        ((1, 4, 6), 5, (4, 6)),               # 两侧各自最近
        ((6,), 1, (6,)),
        ((1,), 6, (1,)),
    ],
)
def test_resolve_candidates(nums, die, expect):
    assert resolve_candidates(mask(*nums), die) == expect


def test_resolve_candidates_empty():
    assert resolve_candidates(0, 3) == ()


def test_exact_piece_only_ignores_alternatives():
    """R2 守门：4 号在盘时，即使 3、5 也在盘，也只能走 4 号。"""
    pos = build_pos(red={1: "a1", 2: "a2", 3: "a3", 4: "b1", 5: "b2", 6: "b3"}, side=1, die=4)
    pieces = {m.piece for m in generate_moves(pos)}
    assert pieces == {4}


def test_fallback_two_sides():
    pos = build_pos(red={3: "a1", 6: "a2"}, side=1, die=4)
    assert {m.piece for m in generate_moves(pos)} == {3, 6}


def test_fallback_single_piece_any_die():
    pos = build_pos(red={2: "c3"}, side=1, die=5)
    moves = generate_moves(pos)
    assert {m.piece for m in moves} == {2}
    assert len(moves) == 3  # c3 的右/下/右下


def test_red_center_three_moves():
    pos = build_pos(red={1: "c3"}, side=1, die=1)
    dsts = {sq_name(m.dst) for m in generate_moves(pos)}
    assert dsts == {"d3", "c4", "d4"}


def test_blue_center_three_moves():
    pos = build_pos(blue={1: "c3"}, side=-1, die=1)
    dsts = {sq_name(m.dst) for m in generate_moves(pos)}
    assert dsts == {"b3", "c2", "b2"}


def test_red_edge_single_move():
    pos = build_pos(red={1: "e3"}, side=1, die=1)   # 最右列，只能向下
    assert [sq_name(m.dst) for m in generate_moves(pos)] == ["e4"]
    pos = build_pos(red={1: "c5"}, side=1, die=1)   # 最下行，只能向右
    assert [sq_name(m.dst) for m in generate_moves(pos)] == ["d5"]


def test_blue_edge_single_move():
    pos = build_pos(blue={1: "a3"}, side=-1, die=1)
    assert [sq_name(m.dst) for m in generate_moves(pos)] == ["a2"]
    pos = build_pos(blue={1: "c1"}, side=-1, die=1)
    assert [sq_name(m.dst) for m in generate_moves(pos)] == ["b1"]


def test_direction_never_wrong_side():
    """红方绝不出现向左/向上的走法（R4 守门）。"""
    pos = build_pos(red={1: "c3"}, side=1, die=1)
    for mv in generate_moves(pos):
        assert mv.dst > mv.src or mv.dst == mv.src + 5 or mv.dst == mv.src + 6
        assert sq_name(mv.dst) in {"d3", "c4", "d4"}
    pos = build_pos(blue={1: "c3"}, side=-1, die=1)
    for mv in generate_moves(pos):
        assert sq_name(mv.dst) in {"b3", "c2", "b2"}


def test_captured_field():
    pos = build_pos(red={1: "c3"}, blue={2: "d4"}, side=1, die=1)
    moves = {sq_name(m.dst): m for m in generate_moves(pos)}
    assert moves["d4"].captured == -2
    assert moves["d3"].captured == 0
    # 吃己方子也要记录 captured
    pos = build_pos(red={1: "c3", 2: "d4"}, side=1, die=1)
    moves = {sq_name(m.dst): m for m in generate_moves(pos)}
    assert moves["d4"].captured == 2


def test_die_zero_raises():
    pos = build_pos(red={1: "a1"}, side=1, die=0)
    with pytest.raises(EngineError) as exc:
        generate_moves(pos)
    assert exc.value.code is ErrorCode.DIE_NOT_ROLLED


def test_generate_is_pure():
    pos = initial_position(die=3)
    before = (pos.squares, pos.zhash, pos.side, pos.die)
    generate_moves(pos)
    assert (pos.squares, pos.zhash, pos.side, pos.die) == before


def test_no_legal_move_when_annihilated():
    pos = build_pos(red={}, blue={1: "c3"}, side=1, die=1)
    assert generate_moves(pos) == []
    assert not has_any_move(pos, 1)


def test_pass_unreachable_in_canonical_rules():
    """本规则集下"无合法走法"不可达：任何非终局在盘棋子恒有 >=1 目标格。"""
    for pos in random_positions(count=40, max_plies=18, seed=3):
        if pos.has_piece_on_corner(1) or pos.has_piece_on_corner(-1):
            continue
        for die in range(1, 7):
            assert generate_moves(pos, die), f"{pos} die={die} 无走法"


def test_initial_position_full_home():
    pos = initial_position()
    for n in range(1, 7):
        assert pos.squares.index(n) in {parse_sq(s) for s in
                                        ("a1", "b1", "c1", "a2", "b2", "a3")}
        assert pos.squares.index(-n) in {parse_sq(s) for s in
                                         ("e5", "d5", "c5", "e4", "d4", "e3")}


def test_corner_square_reachable_in_one_from_adjacent():
    pos = build_pos(red={1: "d5"}, side=1, die=1)
    moves = generate_moves(pos)
    assert any(m.dst == CORNER[1] for m in moves)
    assert any(m.dst == idx(5, 5) for m in moves)
