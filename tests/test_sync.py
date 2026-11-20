"""状态同步层（复制走法）测试 —— 用户核心诉求：一致性 + 非法操作校验。"""

from __future__ import annotations

import pytest

from einstein_go.constants import BLUE, RED, parse_sq
from einstein_go.errors import EngineError, ErrorCode
from einstein_go.move import Move
from einstein_go.movegen import generate_moves
from einstein_go.outcome import GameResult, TerminalReason
from einstein_go.protocol import chain_step
from einstein_go.state import GameState, initial_position
from einstein_go.sync import (
    SyncMode,
    _post_checks,
    apply_remote_move,
    verify_state_equal,
)
from helpers import build_pos, play_random_game


def gs(pos):
    return GameState(pos=pos)


def ok_report(report):
    assert report.ok, report.format()
    return report


def fail_report(report, code):
    assert not report.ok
    assert report.code is code, report.format()
    return report


# ---------------------------------------------------------------- 正常复制
def test_sync_normal_replay():
    pos = initial_position(die=4)
    state = gs(pos)
    legal = generate_moves(pos)
    mv = legal[0]
    new_state, rep = apply_remote_move(state, mv.to_text())
    ok_report(rep)
    assert new_state.ply == 1
    assert new_state.pos.side == -pos.side
    assert new_state.chain_hash != state.chain_hash
    assert new_state.move_log == (mv,)


def test_sync_state_untouched_on_failure():
    state = gs(initial_position(die=4))
    snapshot = (state.pos, state.ply, state.chain_hash)
    _, rep = apply_remote_move(state, "3c1-c2@4")   # 红方 c1 的 3 号不能向左上?
    assert not rep.ok
    assert (state.pos, state.ply, state.chain_hash) == snapshot


def test_sync_two_sides_identical_state():
    """两侧各自独立重放同一走法序列 → 逐字节一致（含哈希链）。

    左边用文本、右边用 JSON 喂入，顺便验证两种序列化等价。
    """
    left = gs(initial_position(die=0))
    right = gs(initial_position(die=0))
    s = play_random_game(seed=42)
    for mv in s.move_log:
        left, rep1 = apply_remote_move(left, mv, SyncMode.STRICT)
        right, rep2 = apply_remote_move(right, mv.to_json(), SyncMode.STRICT)
        ok_report(rep1)
        ok_report(rep2)
        assert verify_state_equal(left, right) == []
    assert left.pos.squares == s.pos.squares
    assert left.pos.zhash == s.pos.zhash
    assert left.chain_hash == s.chain_hash


# ---------------------------------------------------------------- 非法走法
def test_sync_reject_out_of_board():
    state = gs(initial_position(die=3))
    _, rep = apply_remote_move(state, "3c1-f2@3")
    fail_report(rep, ErrorCode.OUT_OF_BOARD)


def test_sync_reject_illegal_direction():
    state = gs(initial_position(die=3))     # 红方 3 号在 c1
    _, rep = apply_remote_move(state, "3c1-b1@3")   # 红方不能向左
    fail_report(rep, ErrorCode.ILLEGAL_DIRECTION)


def test_sync_blue_move_forward():
    """蓝方出发区 1 号在 e3，向左/上/左上合法。"""
    pos = initial_position(die=0).with_side(BLUE).with_die(1)
    new_state, rep = apply_remote_move(gs(pos), "1e3-d3@1")
    ok_report(rep)
    assert new_state.pos.squares[parse_sq("d3")] == -1


def test_sync_reject_blue_illegal_direction():
    """蓝方不能向右（用不贴边的 2 号在 d4 构造，避免越界掩盖方向错误）。"""
    pos = initial_position(die=0).with_side(BLUE).with_die(2)
    _, rep = apply_remote_move(gs(pos), "2d4-e4@2")
    fail_report(rep, ErrorCode.ILLEGAL_DIRECTION)


def test_sync_reject_not_adjacent():
    state = gs(initial_position(die=3))
    _, rep = apply_remote_move(state, "3c1-c3@3")
    fail_report(rep, ErrorCode.NOT_ADJACENT)


def test_sync_reject_captured_piece():
    pos = build_pos(red={1: "a1"}, blue={2: "c3"}, side=RED, die=3)
    _, rep = apply_remote_move(gs(pos), "3a1-b1@3")
    fail_report(rep, ErrorCode.PIECE_ALREADY_CAPTURED)


def test_sync_reject_die_mismatch_strict():
    state = gs(initial_position(die=3))
    _, rep = apply_remote_move(state, "1a1-b1@5", SyncMode.STRICT)
    fail_report(rep, ErrorCode.DIE_PIECE_MISMATCH)


def test_sync_reject_die_piece_mismatch():
    """骰值 3 时可走的是 3 号，对方却走了 1 号。"""
    state = gs(initial_position(die=3))
    _, rep = apply_remote_move(state, "1a1-b1@3")
    fail_report(rep, ErrorCode.DIE_PIECE_MISMATCH)


def test_sync_reject_src_mismatch():
    pos = initial_position(die=3)           # 3 号在 c1
    _, rep = apply_remote_move(gs(pos), "3a1-a2@3")
    fail_report(rep, ErrorCode.SRC_MISMATCH)


def test_sync_reject_not_your_turn():
    state = gs(initial_position(die=3))
    _, rep = apply_remote_move(state, {"piece": 3, "src": "c1", "dst": "d1", "die": 3, "side": "B"})
    fail_report(rep, ErrorCode.NOT_YOUR_TURN)


def test_sync_reject_out_of_order():
    state = gs(initial_position(die=3))
    _, rep = apply_remote_move(state, {"piece": 3, "src": "c1", "dst": "d1", "die": 3, "ply": 5})
    fail_report(rep, ErrorCode.REPLAY_OUT_OF_ORDER)


def test_sync_reject_duplicate_apply():
    """同一手重复投递必须被拒（此时已换手，声明起点与实际不符）。"""
    state = gs(initial_position(die=3))
    new_state, rep = apply_remote_move(state, "3c1-d1@3")
    ok_report(rep)
    _, rep2 = apply_remote_move(new_state, "3c1-d1@3")
    assert not rep2.ok
    assert rep2.code in (ErrorCode.SRC_MISMATCH, ErrorCode.DIE_NOT_ROLLED,
                         ErrorCode.NOT_YOUR_TURN, ErrorCode.PIECE_ALREADY_CAPTURED)

    # 带 ply/side 的棋谱形态能被更精确地识别为乱序
    _, rep3 = apply_remote_move(new_state, {"piece": 3, "dst": "d1", "src": "c1",
                                            "die": 3, "ply": 1, "side": "R"})
    assert not rep3.ok
    assert rep3.code in (ErrorCode.REPLAY_OUT_OF_ORDER, ErrorCode.NOT_YOUR_TURN)


def test_sync_reject_after_game_over():
    state = gs(initial_position(die=3))
    state = state.with_result(GameResult(1, TerminalReason.TIMEOUT, 1))
    _, rep = apply_remote_move(state, "3c1-d1@3")
    fail_report(rep, ErrorCode.GAME_ALREADY_OVER)


# ---------------------------------------------------------------- 起点推断 / 容错
def test_sync_missing_src_inferred():
    state = gs(initial_position(die=3))
    new_state, rep = apply_remote_move(state, {"piece": 3, "dst": "d1", "die": 3})
    ok_report(rep)
    assert new_state.pos.squares[parse_sq("d1")] == 3
    assert not rep.recovered      # 缺省起点是协议允许的形态，不算"修正"


def test_sync_lenient_repairs_wrong_src():
    state = gs(initial_position(die=3))
    new_state, rep = apply_remote_move(state, "3a1-d1@3", SyncMode.LENIENT)
    ok_report(rep)
    assert rep.recovered
    assert new_state.pos.squares[parse_sq("d1")] == 3
    assert new_state.pos.squares[parse_sq("c1")] == 0   # 真正起点 c1 被清空
    assert new_state.pos.squares[parse_sq("a1")] == 1   # 1 号原地未动（没按声明去动 a1）


def test_sync_lenient_never_guesses_move():
    """容错模式绝不"猜一个能走的走法"：不可走就是不可走。"""
    pos = build_pos(red={1: "a1"}, blue={2: "c3"}, side=RED, die=3)
    _, rep = apply_remote_move(gs(pos), "3a1-a2@3", SyncMode.LENIENT)
    assert not rep.ok
    assert rep.code is ErrorCode.PIECE_ALREADY_CAPTURED


# ---------------------------------------------------------------- 走后对账
def test_sync_only_two_squares_change():
    state = gs(initial_position(die=3))
    _, rep = apply_remote_move(state, "3c1-d1@3")
    ok_report(rep)
    names = [c.name for c in rep.checks]
    assert any("C7" in n for n in names)
    assert all(c.ok for c in rep.checks)


def test_sync_material_conservation_violation_detected():
    before = build_pos(red={1: "c3"}, blue={2: "d4"}, side=RED, die=1)
    mv = next(m for m in generate_moves(before) if m.dst == parse_sq("d4"))
    # 伪造一个"走一步却吃掉两个子"的局面（红 1 和蓝 2 都没了）
    forged = before.with_side(-RED).with_die(0)
    checks, code, msg = _post_checks(before, forged, mv)
    assert code is ErrorCode.SYNC_DESYNC
    assert any(not c.ok for c in checks)


def test_sync_report_contains_hashes():
    state = gs(initial_position(die=3))
    new_state, rep = apply_remote_move(state, "3c1-d1@3")
    ok_report(rep)
    assert rep.hash_before == state.pos.zhash
    assert rep.hash_after == new_state.pos.zhash
    assert "OK" in rep.format()


# ---------------------------------------------------------------- 哈希链
def test_hash_chain_detects_tampering():
    from einstein_go.sync import replay

    s = play_random_game(seed=13)
    rows = s.record()
    final = replay(rows)
    assert final.pos.zhash == s.pos.zhash
    assert final.chain_hash == s.chain_hash

    tampered = [dict(r) for r in rows]
    # 改第 2 手的终点，制造哈希链断裂
    tampered[2]["dst"] = "a5"
    with pytest.raises(EngineError) as exc:
        replay(tampered)
    assert exc.value.code is ErrorCode.HASH_CHAIN_BROKEN
    assert exc.value.ctx.get("ply") is not None


def test_chain_step_is_deterministic():
    mv = Move(piece=1, src=0, dst=1, die=1)
    assert chain_step(b"\x00" * 16, mv, 12345) == chain_step(b"\x00" * 16, mv, 12345)
    assert chain_step(b"\x00" * 16, mv, 12345) != chain_step(b"\x00" * 16, mv, 12346)
