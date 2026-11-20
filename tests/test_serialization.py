"""走法序列化与解析的测试。"""

from __future__ import annotations

import pytest

from einstein.constants import parse_sq, sq_name
from einstein.errors import EngineError, ErrorCode
from einstein.move import Move, MoveIntent, parse_move_json, parse_move_text


@pytest.mark.parametrize("text", ["4a1-b1@3", "4a1b1@3", "4a1>b1@3", " 4 a1 - b1 @ 3 "])
def test_parse_text_variants(text):
    intent = parse_move_text(text)
    assert intent.piece == 4
    assert intent.src == parse_sq("a1")
    assert intent.dst == parse_sq("b1")
    assert intent.die == 3


def test_parse_without_die():
    intent = parse_move_text("2c3-d4")
    assert intent.die is None
    assert intent.piece == 2


def test_fullwidth_tolerance():
    intent = parse_move_text("４ａ１－ｂ１＠３")
    assert (intent.piece, intent.src, intent.dst, intent.die) == (4, parse_sq("a1"), parse_sq("b1"), 3)


@pytest.mark.parametrize("bad", ["", "xyz", "1a1", "a1-b1", "0a1-b1", "7a1-b1", "1a1-b1@9"])
def test_malformed_raises(bad):
    with pytest.raises(EngineError) as exc:
        parse_move_text(bad)
    assert exc.value.code is ErrorCode.MALFORMED_MOVE


@pytest.mark.parametrize("bad", ["1f1-a2", "1a1-a6", "1a0-a1"])
def test_out_of_board_raises(bad):
    with pytest.raises(EngineError) as exc:
        parse_move_text(bad)
    assert exc.value.code is ErrorCode.OUT_OF_BOARD


def test_move_text_roundtrip():
    for piece in range(1, 7):
        for src in range(25):
            for dst in range(25):
                if src == dst:
                    continue
                mv = Move(piece=piece, src=src, dst=dst, die=piece, captured=0)
                back = parse_move_text(mv.to_text())
                assert (back.piece, back.src, back.dst, back.die) == (piece, src, dst, piece)
                compact = parse_move_text(mv.to_compact())
                assert (compact.piece, compact.src, compact.dst) == (piece, src, dst)


def test_move_json_roundtrip():
    mv = Move(piece=3, src=parse_sq("c1"), dst=parse_sq("d2"), die=3, captured=-5)
    data = mv.to_json()
    back = parse_move_json(data)
    assert (back.piece, back.src, back.dst, back.die) == (3, parse_sq("c1"), parse_sq("d2"), 3)


def test_move_json_optional_fields():
    intent = parse_move_json({"piece": 2, "dst": "b2", "ply": 5, "side": "B"})
    assert intent.src is None
    assert intent.die is None
    assert intent.ply == 5
    assert intent.side == -1


def test_json_missing_fields():
    with pytest.raises(EngineError) as exc:
        parse_move_json({"dst": "b2"})
    assert exc.value.code is ErrorCode.MALFORMED_MOVE


def test_move_hashable_and_ordered():
    a = Move(piece=1, src=0, dst=1, die=1, captured=0)
    b = Move(piece=1, src=0, dst=1, die=1, captured=0)
    assert a == b and hash(a) == hash(b)
    assert len({a, b}) == 1
    c = Move(piece=1, src=0, dst=5, die=1, captured=0)
    assert a < c
    assert a.key() == (1, 0, 1)


def test_intent_repr_and_json():
    intent = MoveIntent(piece=2, dst=parse_sq("b2"), src=parse_sq("a2"), die=4)
    data = intent.to_json()
    assert data["piece"] == 2 and data["dst"] == "b2"
    assert sq_name(parse_sq("b2")) == "b2"
