"""控制器测试（零 tkinter，用 FakeTime + 固定骰值做到完全确定）。"""

from __future__ import annotations

import time

import pytest

from einstein.clock import FakeTime
from einstein.constants import BLUE, NEIGHBORS, RED, parse_sq, sq_name
from einstein.gui.controller import GameController
from einstein.gui.model import GameSetup, Mode, Phase
from einstein.gui.thinker import HeuristicThinker
from einstein.movegen import generate_moves, resolve_candidates
from einstein.outcome import GameResult, TerminalReason
from einstein.protocol import read_jsonl
from einstein.sync import replay


# ---------------------------------------------------------------- 工具
class SlowThinker(HeuristicThinker):
    """故意慢一点，用于验证「思考中禁止操作」与轮询落子。"""

    def __init__(self, delay: float = 0.12) -> None:
        self.delay = delay
        self.calls = 0

    def think(self, pos, remaining_ms, cfg, ply, cancel=None):
        self.calls += 1
        t0 = time.monotonic()
        while time.monotonic() - t0 < self.delay:
            if cancel is not None and cancel.is_set():
                break
            time.sleep(0.005)
        return super().think(pos, remaining_ms, cfg, ply, cancel)


def make(**kw):
    """人机对弈：默认人类执红、骰值恒为 3、同步思考。"""
    kw.setdefault("human_side", RED)
    kw.setdefault("seed", 1)
    ft = FakeTime()
    ctl = GameController(GameSetup(**kw), time_source=ft,
                         die_source=lambda: 3, async_think=False)
    ctl.new_game()
    return ctl, ft


def make_match(**kw):
    """比赛模式：我方执蓝，因此对方（红）先走 → 进入 MATCH_WAIT。"""
    kw.setdefault("human_side", BLUE)
    kw.setdefault("seed", 5)
    ft = FakeTime()
    ctl = GameController(GameSetup(mode=Mode.MATCH, **kw), time_source=ft,
                         die_source=lambda: 2, async_think=False)
    ctl.new_game()
    return ctl, ft


def wait_idle(ctl, timeout: float = 3.0) -> None:
    end = time.monotonic() + timeout
    while ctl.phase is Phase.THINKING and time.monotonic() < end:
        ctl.poll()
        time.sleep(0.005)
    ctl.poll()


# ---------------------------------------------------------------- 开局
def test_new_game_pve_human_red_enters_human_turn():
    ctl, _ = make()
    assert ctl.phase is Phase.HUMAN_TURN
    assert ctl.view()["ply"] == 0
    assert ctl.session is not None


def test_view_has_25_cells():
    ctl, _ = make()
    view = ctl.view()
    assert len(view["cells"]) == 25
    assert view["mode"] == "pve"
    assert view["human_side"] == RED
    assert view["can"]["select"] is True


def test_auto_roll_sets_die_and_starts_clock():
    ctl, ft = make()
    view = ctl.view()
    assert view["die"] == 3
    assert view["needs_roll"] is False
    assert ctl.session.clock.ticking is True
    ft.advance(1500)
    assert ctl.session.remaining_ms() == 240_000 - 1500


def test_deferred_roll_keeps_die_zero():
    ctl, _ = make(auto_roll=False)
    view = ctl.view()
    assert view["die"] == 0
    assert view["needs_roll"] is True
    assert view["can"]["roll"] is True
    assert view["can"]["commit"] is False
    r = ctl.roll_die()
    assert r["ok"] and ctl.view()["die"] == 3
    assert ctl.roll_die()["ok"] is False        # 双掷闸门


# ---------------------------------------------------------------- 选子
def test_select_empty_square_not_selectable():
    ctl, _ = make()
    r = ctl.select_square(parse_sq("c3"))        # 中立空格
    assert r["ok"] is True
    assert r["extra"]["selectable"] is False
    assert r["extra"]["reason"] == "EMPTY"
    assert r["severity"] == "none"


def test_select_opponent_piece_not_selectable():
    ctl, _ = make()
    r = ctl.select_square(parse_sq("e5"))       # 蓝方 1 号在 e3，先点个空的
    assert r["extra"]["selectable"] is False
    r = ctl.select_square(parse_sq("e3"))       # 蓝方棋子
    assert r["ok"] is True
    assert r["extra"]["reason"] == "NOT_YOUR_PIECE"
    assert r["severity"] == "info"


def test_select_piece_not_in_candidates_reports_hint():
    ctl, _ = make()                              # 骰 3，3 号在盘
    r = ctl.select_square(parse_sq("a1"))       # 1 号
    assert r["ok"] is False
    assert r["code"] == "DIE_PIECE_MISMATCH"
    assert "骰 3" in r["message"] and "只能走 3 号" in r["message"]


def test_select_own_piece_targets_match_movegen():
    ctl, _ = make()
    pos = ctl.session.pos
    r = ctl.select_square(parse_sq("c1"))        # 红方 3 号
    assert r["extra"]["selectable"] is True
    got = {t["dst"] for t in r["extra"]["targets"]}
    expect = {m.dst for m in generate_moves(pos) if m.piece == 3}
    assert got == expect
    assert ctl.view()["selection"]["src"] == parse_sq("c1")


def test_clear_selection():
    ctl, _ = make()
    ctl.select_square(parse_sq("c1"))
    assert ctl.view()["selection"] is not None
    ctl.clear_selection()
    assert ctl.view()["selection"] is None


# ---------------------------------------------------------------- 走子
def test_commit_valid_move():
    ctl, _ = make()
    mv = next(m for m in ctl.session.legal_moves() if m.piece == 3)
    r = ctl.commit_move(3, mv.dst)
    assert r["ok"] is True
    log = ctl.session.move_log
    assert log[0].piece == 3 and log[0].dst == mv.dst
    assert ctl.view()["ply"] == 2               # 人类一手 + 同步 AI 一手
    assert ctl.view()["last_move"]["text"] == log[-1].to_compact()


def test_commit_illegal_target_does_not_touch_clock():
    """核心守门：非法走法绝不能进 session.play（它会先停表扣时）。"""
    ctl, ft = make()
    assert ctl.session.clock.ticking is True
    before = ctl.session.remaining_ms()

    r = ctl.commit_move(3, parse_sq("e5"))       # 3 号在 c1，e5 显然不是一格
    assert r["ok"] is False
    assert r["code"] == "NOT_ADJACENT"

    ft.advance(1000)
    assert ctl.session.clock.ticking is True, "非法走法把时钟提前停掉了"
    assert ctl.session.remaining_ms() == before - 1000
    assert ctl.view()["ply"] == 0


@pytest.mark.parametrize(
    "dst,expect",
    [("e5", "NOT_ADJACENT"), ("b1", "ILLEGAL_DIRECTION"), ("a3", "NOT_ADJACENT")],
)
def test_commit_illegal_maps_to_sync_codes(dst, expect):
    ctl, _ = make()
    r = ctl.commit_move(3, parse_sq(dst))
    assert r["ok"] is False
    assert r["code"] == expect, r
    assert ctl.view()["ply"] == 0


def test_commit_without_roll():
    ctl, _ = make(auto_roll=False)
    r = ctl.commit_move(3, parse_sq("d1"))
    assert r["ok"] is False
    assert r["code"] == "DIE_NOT_ROLLED"


def test_commit_after_game_over():
    ctl, ft = make(budget_ms=1000)
    ft.advance(2000)
    ctl.tick()
    assert ctl.phase is Phase.GAME_OVER
    r = ctl.commit_move(3, parse_sq("d1"))
    assert r["ok"] is False
    assert r["code"] == "GAME_ALREADY_OVER"


def test_tick_flags_timeout():
    ctl, ft = make(budget_ms=1000)
    ft.advance(1500)
    r = ctl.tick()
    assert r["ok"] is False
    assert r["code"] == "CLOCK_FLAG_FALLEN"
    assert ctl.phase is Phase.GAME_OVER
    assert ctl.view()["result"]["reason"] == "timeout"


# ---------------------------------------------------------------- 异步思考
def test_thinking_blocks_human_actions():
    ft = FakeTime()
    slow = SlowThinker(0.15)
    ctl = GameController(GameSetup(human_side=BLUE, seed=2), time_source=ft,
                         die_source=lambda: 2, thinker=slow, async_think=True)
    ctl.new_game()
    assert ctl.phase is Phase.THINKING
    r = ctl.commit_move(1, parse_sq("e4"))
    assert r["ok"] is False and r["code"] == "BUSY"
    assert ctl.select_square(parse_sq("e5"))["code"] == "BUSY"
    wait_idle(ctl)
    assert ctl.phase is Phase.HUMAN_TURN
    assert ctl.view()["ply"] == 1


def test_poll_applies_ai_move_once():
    ft = FakeTime()
    ctl = GameController(GameSetup(human_side=BLUE, seed=2), time_source=ft,
                         die_source=lambda: 2, thinker=SlowThinker(0.05), async_think=True)
    ctl.new_game()
    wait_idle(ctl)
    ply = ctl.view()["ply"]
    assert ply == 1
    assert ctl.poll() == []                     # 第二遍不该再落子
    assert ctl.view()["ply"] == ply


def test_stale_token_is_discarded():
    ctl, _ = make()
    ctl._queue.put((ctl._token + 99, None))
    events = ctl.poll()
    assert events and events[0]["kind"] == "stale"
    assert ctl.view()["ply"] == 0


def test_new_game_cancels_running_search():
    ft = FakeTime()
    slow = SlowThinker(3.0)
    ctl = GameController(GameSetup(human_side=BLUE, seed=2), time_source=ft,
                         die_source=lambda: 2, thinker=slow, async_think=True)
    ctl.new_game()
    assert ctl.phase is Phase.THINKING
    t0 = time.monotonic()
    ctl.new_game()                               # 立刻开新局，旧搜索必须被取消
    elapsed = time.monotonic() - t0
    assert elapsed < 1.5, f"取消耗时 {elapsed:.2f}s，太久了"
    assert ctl.phase is Phase.THINKING or ctl.view()["ply"] in (0, 1)


# ---------------------------------------------------------------- 比赛模式
def test_match_starts_waiting_for_remote():
    ctl, _ = make_match()
    assert ctl.phase is Phase.MATCH_WAIT
    view = ctl.view()
    assert view["match"]["can_accept"] is True
    assert view["remote_turn"] is True
    # 对方回合并未设定骰值：还不能在棋盘上代走
    assert view["can"]["select"] is False
    assert view["match"]["awaiting_die"] is True


def test_match_board_control_asks_for_die_first():
    ctl, _ = make_match()
    r = ctl.select_square(parse_sq("a1"))          # 红方 1 号，是对方棋子
    assert r["ok"] is False
    assert r["code"] == "REMOTE_DIE_REQUIRED"
    assert "骰值" in r["message"]


def test_match_board_control_selects_opponent_piece_after_die():
    ctl, _ = make_match()
    assert ctl.declare_remote_die(3)["ok"] is True
    view = ctl.view()
    assert view["die"] == 3
    assert view["can"]["select"] is True
    assert view["match"]["can_board_control"] is True

    r = ctl.select_square(parse_sq("c1"))          # 红方 3 号
    assert r["extra"]["selectable"] is True
    got = {t["dst"] for t in r["extra"]["targets"]}
    expect = {m.dst for m in generate_moves(ctl.session.pos) if m.piece == 3}
    assert got == expect


def test_match_board_control_commit_runs_six_layers():
    ctl, _ = make_match()
    ctl.declare_remote_die(3)
    sel = ctl.select_square(parse_sq("c1"))["extra"]
    dst = sel["targets"][0]["dst"]
    r = ctl.commit_move(sel["piece"], dst)
    assert r["ok"] is True, r["message"]
    report = r["extra"]["report"]
    assert [row["layer"] for row in report["layers"]] == ["L0", "L1", "L2", "L3", "L4", "L5"]
    assert all(row["state"] == "ok" for row in report["layers"])
    # 代走与粘贴走的是同一条路径：先复制成功，再由我方 AI 回应
    assert ctl.view()["ply"] == 2
    assert ctl.phase is Phase.MATCH_WAIT


def test_match_board_control_rejects_illegal_target():
    ctl, _ = make_match()
    ctl.declare_remote_die(3)
    sel = ctl.select_square(parse_sq("c1"))["extra"]
    ply_before = ctl.view()["ply"]
    r = ctl.commit_move(sel["piece"], parse_sq("e5"))     # 太远
    assert r["ok"] is False
    assert r["code"] == "NOT_ADJACENT"
    assert ctl.view()["ply"] == ply_before


def test_match_die_can_be_changed_before_moving():
    ctl, _ = make_match()
    ctl.declare_remote_die(3)
    r = ctl.declare_remote_die(5)
    assert r["ok"] is True
    assert ctl.view()["die"] == 5


def test_match_remote_roll_is_in_range():
    ctl, _ = make_match()
    r = ctl.remote_roll()
    assert r["ok"] is True
    assert 1 <= ctl.view()["die"] <= 6


def test_match_clicking_own_piece_hints_acting_side():
    ctl, _ = make_match()
    ctl.declare_remote_die(3)
    r = ctl.select_square(parse_sq("e5"))          # 蓝方 6 号，是我方棋子
    assert r["ok"] is True
    assert r["extra"]["reason"] == "NOT_ACTING_SIDE"
    assert "红方棋子" in r["message"]


def test_match_die_rejected_outside_remote_turn():
    ctl, _ = make_match()
    ctl.declare_remote_die(3)
    sel = ctl.select_square(parse_sq("c1"))["extra"]
    ctl.commit_move(sel["piece"], sel["targets"][0]["dst"])
    # 已经回到 wait（对方回合作答完后仍是 wait），但若在对局结束时声明则应拒绝
    ctl._session.state = ctl._session.state.with_result(
        GameResult(1, TerminalReason.REACHED_CORNER, 9))
    r = ctl.declare_remote_die(4)
    assert r["ok"] is False and r["code"] == "GAME_ALREADY_OVER"


def test_accept_remote_ok_has_six_layers():
    ctl, _ = make_match()
    mv = generate_moves(ctl.session.pos, 3)[0]
    r = ctl.accept_remote(mv.to_compact())
    assert r["ok"] is True, r["message"]
    report = r["extra"]["report"]
    assert [row["layer"] for row in report["layers"]] == ["L0", "L1", "L2", "L3", "L4", "L5"]
    assert all(row["state"] == "ok" for row in report["layers"])
    assert report["hash_after"] != report["hash_before"]
    # 复制完轮到我方：同步 AI 已回应，回到等待对方
    assert ctl.phase is Phase.MATCH_WAIT
    assert ctl.view()["ply"] == 2


def test_accept_remote_malformed_returns_error_not_raise():
    ctl, _ = make_match()
    r = ctl.accept_remote("zzz")
    assert r["ok"] is False
    assert r["code"] == "MALFORMED_MOVE"
    report = r["extra"]["report"]
    assert len(report["layers"]) == 6
    assert report["layers"][1]["state"] == "fail"


def test_accept_remote_wrong_piece_marks_geometry_layer():
    ctl, _ = make_match()
    pos = ctl.session.pos
    alive = pos.alive(pos.side)
    cands = resolve_candidates(alive, 3)
    other = next(n for n in range(1, 7) if (alive >> n) & 1 and n not in cands)
    src = pos.squares.index(pos.side * other)
    dst = NEIGHBORS[pos.side][src][0]
    r = ctl.accept_remote(f"{other}{sq_name(src)}{sq_name(dst)}@3")
    assert r["ok"] is False
    assert r["code"] == "DIE_PIECE_MISMATCH"
    layers = r["extra"]["report"]["layers"]
    assert layers[0]["state"] == "ok"
    assert layers[1]["state"] == "fail"
    assert all(row["state"] == "skip" for row in layers[2:])


def test_accept_remote_rejected_outside_match_wait():
    ctl, _ = make()                              # PVE，不是 MATCH_WAIT
    r = ctl.accept_remote("3c1d1@3")
    assert r["ok"] is False and r["code"] == "NOT_REMOTE_TURN"


def test_to_send_text_is_our_last_move():
    ctl, _ = make_match()
    mv = generate_moves(ctl.session.pos, 3)[0]
    ctl.accept_remote(mv.to_compact())
    text = ctl.to_send_text()
    assert text and text == ctl.session.move_log[-1].to_compact()


# ---------------------------------------------------------------- 导出与收尾
def test_export_record_roundtrip(tmp_path):
    ctl, _ = make()
    mv = next(m for m in ctl.session.legal_moves() if m.piece == 3)
    ctl.commit_move(3, mv.dst)
    out = tmp_path / "rec.jsonl"
    r = ctl.export_record(out)
    assert r["ok"] is True, r["message"]
    assert r["extra"]["verified"] is True

    rows = read_jsonl(out)
    replayed = replay(rows)
    # 棋谱不含"下回合刚掷出的骰值"，比对时两边都归零
    assert replayed.pos.with_die(0) == ctl.session.pos.with_die(0)
    assert replayed.chain_hash == ctl.session.chain_hash


def test_export_record_before_any_move(tmp_path):
    ctl, _ = make()
    r = ctl.export_record(tmp_path / "empty.jsonl")
    assert r["ok"] is False


def test_shutdown_is_idempotent():
    ctl, _ = make()
    ctl.shutdown()
    ctl.shutdown()
    assert ctl.phase is Phase.HUMAN_TURN   # 只停线程，不改局面
