"""错误码中文化与六层对账视图测试。"""

from __future__ import annotations

import pytest

from einstein.constants import parse_sq
from einstein.errors import EngineError, ErrorCode
from einstein.gui.errors_view import (
    CODE_LAYER,
    ERROR_TEXT,
    LAYERS,
    REASON_TEXT,
    TERMINAL_TEXT,
    error_text,
    explain_error,
    report_parse_failed,
    report_to_view,
    result_view,
)
from einstein.outcome import GameResult, TerminalReason
from einstein.state import GameState, initial_position
from einstein.sync import SyncMode, apply_remote_move


def gs(die: int = 3) -> GameState:
    return GameState(pos=initial_position(die=die))


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_error_code_has_chinese_message(code):
    text = ERROR_TEXT.get(code)
    assert text is not None, f"{code} 缺少中文文案"
    assert text != code.value
    assert any("\u4e00" <= ch <= "\u9fff" for ch in text), f"{code} 的文案不含中文"


def test_unknown_code_degrades_gracefully():
    assert error_text(None) == "未知错误"
    assert error_text("SOME_NEW_CODE") == "SOME_NEW_CODE"


def test_explain_error_targets_the_culprit_number():
    alive = 0b1111110
    msg = explain_error(ErrorCode.DIE_PIECE_MISMATCH, die=4, alive=alive, piece=5)
    assert "骰 4" in msg and "4 号" in msg


def test_explain_error_single_candidate():
    msg = explain_error(ErrorCode.DIE_PIECE_MISMATCH, die=6, alive=0b100, piece=1)
    assert "只能走 2 号" in msg


def test_explain_error_lists_both_sides():
    msg = explain_error(ErrorCode.DIE_PIECE_MISMATCH, die=4, alive=0b1001000, piece=1)
    assert "3 号" in msg and "6 号" in msg


def test_explain_error_appends_squares():
    msg = explain_error(ErrorCode.ILLEGAL_DIRECTION, src=parse_sq("c1"), dst=parse_sq("b1"))
    assert "c1" in msg and "b1" in msg


def test_ok_report_has_six_layers_all_ok():
    state = gs(3)
    new_state, rep = apply_remote_move(state, "3c1-d1@3", SyncMode.STRICT)
    assert rep.ok
    view = report_to_view(rep, new_state)
    assert [row["layer"] for row in view["layers"]] == ["L0", "L1", "L2", "L3", "L4", "L5"]
    assert [row["state"] for row in view["layers"]] == ["ok"] * 6
    assert view["hash_before"] != view["hash_after"]
    assert view["chain_tail"]
    assert view["move"] == "3c1-d1@3"
    # 每层都有可渲染的条目
    assert all(row["items"] for row in view["layers"])


def test_l0_failure_marks_later_layers_skipped():
    state = gs(3)
    _, rep = apply_remote_move(state, {"piece": 3, "src": "c1", "dst": "d1", "die": 3, "side": "B"})
    assert not rep.ok and rep.code is ErrorCode.NOT_YOUR_TURN
    view = report_to_view(rep)
    states = [row["state"] for row in view["layers"]]
    assert states == ["fail", "skip", "skip", "skip", "skip", "skip"]
    assert view["layers"][0]["note"]


def test_l1_failure_marks_only_l0_ok():
    state = gs(3)
    _, rep = apply_remote_move(state, "1a1-b1@3")          # 3 号才是本回合可走的
    assert not rep.ok
    view = report_to_view(rep)
    states = [row["state"] for row in view["layers"]]
    assert states[0] == "ok" and states[1] == "fail"
    assert all(s == "skip" for s in states[2:])


def test_malformed_report_marks_parse_layer():
    state = gs(3)
    try:
        apply_remote_move(state, "zzz")
    except EngineError as exc:                              # apply_remote_move 内部包住了
        pytest.fail("apply_remote_move 不应抛异常")
    _, rep = apply_remote_move(state, "zzz")
    assert not rep.ok and rep.code is ErrorCode.MALFORMED_MOVE
    view = report_to_view(rep)
    assert view["layers"][1]["state"] == "fail"


def test_report_parse_failed_helper():
    exc = EngineError(ErrorCode.MALFORMED_MOVE, "无法解析的走法: 'zzz'")
    view = report_parse_failed(exc, None)
    assert view["ok"] is False
    assert view["code"] == "MALFORMED_MOVE"
    assert len(view["layers"]) == 6
    assert view["layers"][1]["state"] == "fail"
    assert view["layers"][2]["state"] == "skip"


def test_sync_desync_maps_to_layer_4():
    assert CODE_LAYER[ErrorCode.SYNC_DESYNC] == 4
    assert CODE_LAYER[ErrorCode.HASH_CHAIN_BROKEN] == 5
    for code, layer in CODE_LAYER.items():
        assert 0 <= layer <= 5, code


def test_result_view():
    res = GameResult(1, TerminalReason.REACHED_CORNER, 23)
    view = result_view(res, human_side=1)
    assert view["winner_name"] == "红方"
    assert view["human_won"] is True
    assert "第 23 手" in view["text"]
    assert view["reason_text"] == TERMINAL_TEXT[TerminalReason.REACHED_CORNER]
    assert result_view(None) is None
    assert result_view(res, human_side=-1)["human_won"] is False


def test_reason_text_covers_all_reasons():
    for reason in ("mcts", "single", "mate", "low_time", "no_move"):
        assert REASON_TEXT[reason]
    for reason in TerminalReason:
        assert TERMINAL_TEXT[reason]


def test_layers_shape():
    assert len(LAYERS) == 6
    assert [code for code, _ in LAYERS] == ["L0", "L1", "L2", "L3", "L4", "L5"]
