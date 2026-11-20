"""GUI 纯数据层测试：难度预设、开局设置、25 格视图模型。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from einstein.config import SearchConfig
from einstein.constants import BLUE, BLUE_HOME, CORNER, RED, RED_HOME, parse_sq
from einstein.gui.model import (
    DIFFICULTY_ORDER,
    DIFFICULTY_SPEC,
    GameSetup,
    Mode,
    Phase,
    build_cells,
    resolve_config,
)
from einstein.state import initial_position
from helpers import build_pos


@pytest.mark.parametrize("name", DIFFICULTY_ORDER)
def test_difficulty_presets_are_valid_search_configs(name):
    cfg = resolve_config(name, seed=5)
    assert isinstance(cfg, SearchConfig)
    assert cfg.seed == 5
    assert cfg.max_think_ms == DIFFICULTY_SPEC[name]["max_think_ms"]
    # frozen slots：只能 replace，不能 setattr
    assert replace(cfg, node_limit=1).node_limit == 1
    with pytest.raises(Exception):
        cfg.max_think_ms = 1  # noqa: F841  - 必须抛（FrozenInstanceError）


def test_resolve_config_rejects_unknown():
    with pytest.raises(ValueError):
        resolve_config("insane")


def test_setup_defaults_and_remote_side():
    st = GameSetup()
    assert st.mode is Mode.PVE
    assert st.human_side == RED
    assert st.remote_side == BLUE
    assert replace(st, human_side=BLUE).remote_side == RED


def test_setup_validation():
    with pytest.raises(ValueError):
        GameSetup(human_side=0)
    with pytest.raises(ValueError):
        GameSetup(difficulty="nope")
    with pytest.raises(ValueError):
        GameSetup(budget_ms=10)


def test_phase_and_mode_labels():
    assert Phase.HUMAN_TURN.label == "轮到你走"
    assert Mode.PVE.label == "人机对弈"
    assert Mode.MATCH.label == "比赛模式"


def test_build_cells_covers_all_25_squares():
    cells = build_cells(initial_position().squares)
    assert len(cells) == 25
    assert [c["i"] for c in cells] == list(range(25))
    assert len({c["name"] for c in cells}) == 25
    assert cells[0]["name"] == "a1"
    assert cells[24]["name"] == "e5"
    assert cells[7]["row"] == 2 and cells[7]["col"] == 3     # h1 -> b2? 索引 7 = (2,3)
    assert cells[7]["name"] == "c2"


def test_build_cells_marks_home_zones():
    cells = build_cells(initial_position().squares)
    for i in range(25):
        if i in RED_HOME:
            assert cells[i]["zone"] == "red_home"
        elif i in BLUE_HOME:
            assert cells[i]["zone"] == "blue_home"
        else:
            assert cells[i]["zone"] == "neutral"
    assert cells[parse_sq("c3")]["zone"] == "neutral"


def test_build_cells_marks_target_corners():
    cells = build_cells(initial_position().squares)
    assert cells[CORNER[RED]]["corner_of"] == RED      # e5 是红方的目标
    assert cells[CORNER[BLUE]]["corner_of"] == BLUE    # a1 是蓝方的目标
    assert cells[parse_sq("c3")]["corner_of"] is None


def test_build_cells_piece_fields():
    pos = build_pos(red={3: "c1"}, blue={2: "d4"}, side=RED, die=3)
    cells = build_cells(pos.squares, side=RED, candidates=(3,))
    c1 = cells[parse_sq("c1")]
    assert c1["code"] == 3 and c1["num_text"] == "3" and c1["side"] == RED
    assert c1["playable"] is True
    d4 = cells[parse_sq("d4")]
    assert d4["code"] == -2 and d4["side"] == BLUE and d4["num_text"] == "2"
    assert d4["playable"] is False


def test_build_cells_selection_and_targets():
    cells = build_cells(
        initial_position().squares, side=RED, candidates=(3,),
        selected_src=parse_sq("c1"), targets={parse_sq("d1"): 0, parse_sq("d2"): -4},
    )
    assert cells[parse_sq("c1")]["selected"] is True
    d1, d2 = cells[parse_sq("d1")], cells[parse_sq("d2")]
    assert d1["target"] is True and d1["target_capture"] == 0
    assert d2["target"] is True and d2["target_capture"] == -4


def test_build_cells_last_move_and_capture_flash():
    cells = build_cells(
        initial_position().squares, side=RED,
        last_from=parse_sq("c1"), last_to=parse_sq("d1"),
        capture_sq=parse_sq("d1"), capture_code=-4,
    )
    assert cells[parse_sq("c1")]["last_from"] is True
    assert cells[parse_sq("d1")]["last_to"] is True
    assert cells[parse_sq("d1")]["capture_flash"] == -4
    assert cells[parse_sq("a1")]["capture_flash"] == 0


def test_build_cells_side_switches_playable():
    pos = build_pos(red={3: "c1"}, blue={2: "d4"}, side=BLUE, die=2)
    cells = build_cells(pos.squares, side=BLUE, candidates=(2,))
    assert cells[parse_sq("d4")]["playable"] is True
    assert cells[parse_sq("c1")]["playable"] is False
