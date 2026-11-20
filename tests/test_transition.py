"""职责②③④：移动执行、吃子、回合切换、状态不可变性的测试。"""

from __future__ import annotations

import pytest

from einstein_go.constants import CORNER, parse_sq
from einstein_go.movegen import generate_moves
from einstein_go.state import Position, canonical, check_alive_consistency, initial_position
from einstein_go.transition import ScratchBoard, apply, pass_turn, switch_turn
from einstein_go.zobrist import full_hash
from helpers import build_pos, play_random_game, random_positions


def test_move_to_empty():
    pos = build_pos(red={1: "a1"}, side=1, die=1)
    mv = next(m for m in generate_moves(pos) if m.dst == parse_sq("b1"))
    new = apply(pos, mv)
    assert new.squares[parse_sq("b1")] == 1
    assert new.squares[parse_sq("a1")] == 0
    assert new.side == -1
    assert new.die == 0
    assert new.red_alive == pos.red_alive


def test_capture_opponent():
    pos = build_pos(red={1: "c3"}, blue={2: "d4"}, side=1, die=1)
    mv = next(m for m in generate_moves(pos) if m.dst == parse_sq("d4"))
    new = apply(pos, mv)
    assert new.squares[parse_sq("d4")] == 1
    assert new.blue_alive == 0
    assert new.piece_count(1) == 1


def test_capture_own_piece_clears_captured_number():
    """R1 守门：吃己方子时清的是**被吃者**的编号位，不是移动方的。"""
    pos = build_pos(red={1: "c3", 2: "d4"}, side=1, die=1)
    assert pos.red_alive == (1 << 1) | (1 << 2)
    mv = next(m for m in generate_moves(pos) if m.dst == parse_sq("d4"))
    new = apply(pos, mv)
    assert new.red_alive == 1 << 1          # 2 号被吃，1 号仍在
    assert new.red_alive & (1 << 1)
    assert not new.red_alive & (1 << 2)
    assert new.squares[parse_sq("d4")] == 1
    assert new.has_piece_on_corner(1) is False


def test_alive_mask_cleared_only_on_capture():
    total_captures = 0
    s = play_random_game(seed=5)
    # 逐步重放，统计 alive 位变化次数与吃子次数
    pos = initial_position()
    changes = 0
    for mv in s.move_log:
        prev = pos
        pos = apply(pos, mv)
        diff = bin(prev.red_alive ^ pos.red_alive).count("1") + \
            bin(prev.blue_alive ^ pos.blue_alive).count("1")
        changes += diff
        if mv.captured:
            total_captures += 1
        assert diff <= 1, "一步最多清掉一个编号位"
    assert changes == total_captures


def test_piece_count_conservation():
    for pos in random_positions(count=10, max_plies=25, seed=8):
        before = pos.piece_count(1) + pos.piece_count(-1)
        for die in range(1, 7):
            for mv in generate_moves(pos, die):
                new = apply(pos, mv)
                after = new.piece_count(1) + new.piece_count(-1)
                assert before - after in (0, 1)
                assert new.piece_count(pos.side) >= 1


def test_zhash_incremental_equals_full():
    for pos in random_positions(count=12, max_plies=30, seed=9):
        assert pos.zhash == full_hash(pos.squares, pos.side, pos.die)
        for die in range(1, 7):
            for mv in generate_moves(pos, die):
                new = apply(pos, mv)
                assert new.zhash == full_hash(new.squares, new.side, new.die)


def test_apply_does_not_mutate_input():
    pos = initial_position(die=2)
    snapshot = (pos.squares, pos.side, pos.die, pos.zhash, pos.red_alive, pos.blue_alive)
    for mv in generate_moves(pos):
        apply(pos, mv)
    assert (pos.squares, pos.side, pos.die, pos.zhash, pos.red_alive, pos.blue_alive) == snapshot


def test_switch_turn_clears_die():
    pos = initial_position(die=5)
    after = switch_turn(pos)
    assert after.die == 0
    assert after.side == -pos.side
    assert after.squares == pos.squares
    assert after.zhash == full_hash(after.squares, after.side, 0)


def test_pass_turn_same_as_switch_turn():
    pos = initial_position(die=4)
    assert pass_turn(pos) == switch_turn(pos)


def test_make_unmake_equivalence():
    """ScratchBoard 与不可变 Position 必须逐步全字段一致（两份位运算实现的守门）。"""
    for seed in range(20):
        s = play_random_game(seed=seed)
        pos = initial_position()
        board = ScratchBoard(pos)
        for mv in s.move_log:
            board.make(mv)
            expect = apply(pos, mv)
            got = board.to_position()
            assert (got.squares, got.side, got.die, got.red_mask, got.blue_mask,
                    got.red_alive, got.blue_alive, got.zhash) == (
                expect.squares, expect.side, expect.die, expect.red_mask, expect.blue_mask,
                expect.red_alive, expect.blue_alive, expect.zhash)
            board.unmake()
            assert board.to_position() == pos
            board.make(mv)
            pos = expect


def test_scratchboard_winner():
    pos = build_pos(red={1: "d5"}, side=1, die=1)
    board = ScratchBoard(pos)
    mv = next(m for m in board.moves() if m.dst == CORNER[1])
    board.make(mv)
    assert board.winner() == 1

    pos = build_pos(red={1: "c3"}, blue={2: "d4"}, side=1, die=1)
    board = ScratchBoard(pos)
    mv = next(m for m in board.moves() if m.dst == parse_sq("d4"))
    board.make(mv)
    assert board.winner() == 1   # 吃光蓝方


def test_apply_rejects_illegal():
    from einstein_go.move import Move

    pos = build_pos(red={1: "a1"}, side=1, die=1)
    wrong_src = Move(piece=1, src=parse_sq("a5"), dst=parse_sq("b5"), die=1, captured=0)
    with pytest.raises(AssertionError):
        apply(pos, wrong_src)

    wrong_captured = Move(piece=1, src=parse_sq("a1"), dst=parse_sq("b1"), die=1, captured=-6)
    with pytest.raises(AssertionError):
        apply(pos, wrong_captured)


def test_alive_bits_cover_all_numbers():
    pos = initial_position()
    for side in (1, -1):
        assert pos.alive(side) == 0b1111110
        assert pos.piece_count(side) == 6
    assert bin(pos.red_mask).count("1") == 6
    assert pos.red_mask & pos.blue_mask == 0
    assert bin(pos.red_mask | pos.blue_mask).count("1") == 12


def test_position_build_validates():
    with pytest.raises(ValueError):
        Position.build([0] * 24, 1)
    with pytest.raises(ValueError):
        Position.build([0] * 25, 2)
    with pytest.raises(ValueError):
        Position.build([0] * 25, 1, 7)


def test_alive_cache_never_drifts():
    """debug 助手：alive 缓存必须与棋盘一致（覆盖整局与中途抽查）。"""
    for seed in range(5):
        s = play_random_game(seed=seed)
        pos = initial_position()
        check_alive_consistency(pos)
        for mv in s.move_log:
            pos = apply(pos, mv)
            check_alive_consistency(pos)


def test_canonical_normalizes_perspective():
    from einstein_go.state import rot180

    pos = initial_position()
    assert canonical(pos, 1) is pos                     # 红方视角：原样
    flipped = canonical(pos, -1)
    assert flipped == rot180(pos)
    assert canonical(flipped, -1) == pos                # 再旋转一次回到原点
