"""错误码中文化 + VerifyReport 的六层对账视图。

纯逻辑，不 import tkinter。
"""

from __future__ import annotations

from ..constants import num_of, sq_name
from ..errors import ErrorCode
from ..movegen import resolve_candidates
from ..outcome import TerminalReason

# ---------------- 错误码 -> 中文 ----------------
# 每个 ErrorCode 都必须有独立文案（test_gui_errors_view 会遍历校验）。
ERROR_TEXT: dict[ErrorCode, str] = {
    ErrorCode.MALFORMED_MOVE: "走法格式无法解析（示例：3c1-d2，可带 @骰值）",
    ErrorCode.OUT_OF_BOARD: "坐标超出棋盘（列只能 a–e，行只能 1–5）",
    ErrorCode.NOT_ADJACENT: "只能走一格（横、竖或斜向相邻）",
    ErrorCode.ILLEGAL_DIRECTION: "方向不对：红方只能向右 / 下 / 右下，蓝方只能向左 / 上 / 左上",
    ErrorCode.ILLEGAL_MOVE: "该格不是这枚棋子的可走目标",
    ErrorCode.NOT_YOUR_TURN: "现在不是这一方走棋",
    ErrorCode.NOT_YOUR_PIECE: "那不是你的棋子",
    ErrorCode.PIECE_ALREADY_CAPTURED: "这枚棋子已被吃掉了",
    ErrorCode.SRC_MISMATCH: "起点与该棋子实际所在格不符",
    ErrorCode.DIE_NOT_ROLLED: "请先掷骰再走子",
    ErrorCode.DIE_ALREADY_ROLLED: "本回合已经掷过骰了",
    ErrorCode.DIE_PIECE_MISMATCH: "所选棋子编号不符合本回合骰值",
    ErrorCode.GAME_ALREADY_OVER: "对局已经结束了",
    ErrorCode.CLOCK_FLAG_FALLEN: "本方计时耗尽，判负",
    ErrorCode.SYNC_DESYNC: "走子后对账失败，状态已回滚",
    ErrorCode.HASH_CHAIN_BROKEN: "棋谱哈希链校验失败",
    ErrorCode.REPLAY_OUT_OF_ORDER: "棋谱序号不连续",
    ErrorCode.NO_LEGAL_MOVE: "没有任何合法走法",
}

# 界面层自造的提示码（不对应引擎异常）
UI_TEXT: dict[str, str] = {
    "BUSY": "AI 正在思考，请稍候",
    "NOT_REMOTE_TURN": "现在不是对方的回合，无需对账",
    "ENGINE_ERROR": "搜索过程出错，已回退到你的回合",
    "STALE": "上一步搜索结果已作废",
    "EMPTY": "点到了空格",
    "NO_TARGET": "这枚棋子当前没有可走的目标格",
    "ABANDONED": "本局已放弃",
    "EXPORT_FAILED": "棋谱导出失败",
}


def error_text(code: ErrorCode | str | None) -> str:
    if code is None:
        return "未知错误"
    if isinstance(code, ErrorCode):
        return ERROR_TEXT.get(code, code.value)
    return UI_TEXT.get(code, str(code))


def explain_error(
    code: ErrorCode | str | None,
    *,
    die: int | None = None,
    alive: int | None = None,
    piece: int | None = None,
    src: int | None = None,
    dst: int | None = None,
) -> str:
    """把错误码翻成人话，尽量带上现场信息（骰值、候选编号、格名）。"""
    base = error_text(code)
    if code is ErrorCode.DIE_PIECE_MISMATCH and die and alive is not None:
        cands = resolve_candidates(alive, die)
        if not cands:
            return f"{base}：骰 {die}，已无子可走"
        if len(cands) == 1:
            return f"{base}：骰 {die}，只能走 {cands[0]} 号"
        names = " 或 ".join(f"{n} 号" for n in cands)
        return f"{base}：骰 {die}，可走 {names}"
    if src is not None and src >= 0 and dst is not None and dst >= 0:
        return f"{base}（{sq_name(src)} → {sq_name(dst)}）"
    return base


# ---------------- 六层对账 ----------------
# 引擎的 sync.py 注释写 L0–L4 + 哈希链，界面上一并展示成 6 行，便于向裁判解释。
LAYERS: tuple[tuple[str, str], ...] = (
    ("L0", "前置校验（终局 / 行动方 / 序号 / 骰值）"),
    ("L1", "几何校验（在盘 / 起点 / 邻接 / 方向 / 编号）"),
    ("L2", "走前快照（状态指纹）"),
    ("L3", "执行落子（不可变对象）"),
    ("L4", "走后对账（C1–C8）"),
    ("L5", "哈希链（逐手串联）"),
)

# 失败时按错误码定位到具体层，比"猜第一个失败的检查"可靠
CODE_LAYER: dict[ErrorCode, int] = {
    ErrorCode.GAME_ALREADY_OVER: 0,
    ErrorCode.NOT_YOUR_TURN: 0,
    ErrorCode.REPLAY_OUT_OF_ORDER: 0,
    ErrorCode.DIE_NOT_ROLLED: 0,
    ErrorCode.MALFORMED_MOVE: 1,
    ErrorCode.OUT_OF_BOARD: 1,
    ErrorCode.PIECE_ALREADY_CAPTURED: 1,
    ErrorCode.SRC_MISMATCH: 1,
    ErrorCode.NOT_ADJACENT: 1,
    ErrorCode.ILLEGAL_DIRECTION: 1,
    ErrorCode.DIE_PIECE_MISMATCH: 1,
    ErrorCode.ILLEGAL_MOVE: 1,
    ErrorCode.NOT_YOUR_PIECE: 1,
    ErrorCode.SYNC_DESYNC: 4,
    ErrorCode.HASH_CHAIN_BROKEN: 5,
}


def _items(layer_index: int, checks) -> list[dict]:
    if layer_index == 0:
        mine = [c for c in checks if c.name.startswith("L0")]
    elif layer_index == 1:
        mine = [c for c in checks if c.name.startswith("L1")]
    elif layer_index == 4:
        mine = [c for c in checks if c.name.startswith("C") or "对账" in c.name]
    else:
        mine = []
    return [
        {"name": c.name, "ok": c.ok, "detail": c.detail, "recovered": c.recovered}
        for c in mine
    ]


def _synthetic_items(layer_index: int, rep) -> list[dict]:
    """引擎在某些层不产生 CheckResult（通过时尤其如此），这里补一条说明。

    否则面板上会出现几行空白，看起来像"没校验"；实际是"校验通过但没留下明细"。
    """
    if layer_index == 0:
        return [{"name": "前置校验通过", "ok": True,
                 "detail": f"行动方与骰值匹配 · ply {rep.ply_before}", "recovered": False}]
    if layer_index == 1:
        return [{"name": "几何校验通过", "ok": True,
                 "detail": "起点、邻接、方向、编号与骰值一致", "recovered": False}]
    if layer_index == 2:
        return [{"name": "状态指纹", "ok": True,
                 "detail": "已记录 squares / masks / alive / side / die / zhash",
                 "recovered": False}]
    if layer_index == 3:
        return [{"name": "不可变执行", "ok": True,
                 "detail": "生成新 Position，失败时对原状态零污染",
                 "recovered": False}]
    if layer_index == 5:
        before = f"{rep.hash_before:016x}"
        after = f"{rep.hash_after:016x}" if rep.hash_after is not None else "—"
        return [{"name": "逐手链", "ok": True, "detail": f"{before} → {after}", "recovered": False}]
    return []


def report_to_view(rep, session=None) -> dict:
    """VerifyReport -> 面板可直接渲染的六层结构。"""
    fail_layer = None if rep.ok else CODE_LAYER.get(rep.code, 0)
    rows = []
    for idx, (code, title) in enumerate(LAYERS):
        if fail_layer is None:
            state = "ok" if (idx != 5 or rep.hash_after is not None) else "skip"
        elif idx < fail_layer:
            state = "ok"
        elif idx == fail_layer:
            state = "fail"
        else:
            state = "skip"

        items = _items(idx, rep.checks)
        if state == "skip":
            items = []
        elif not items:
            if state == "ok":
                items = _synthetic_items(idx, rep)
            else:
                items = [{"name": "校验未通过", "ok": False,
                          "detail": rep.message, "recovered": False}]

        note = ""
        if state == "fail":
            note = error_text(rep.code)
        elif any(i["recovered"] for i in items):
            note = "已按「唯一可确定」的维度修正并记录"

        rows.append(
            {
                "layer": code,
                "title": title,
                "state": state,
                "recovered": any(i["recovered"] for i in items),
                "items": items,
                "note": note,
            }
        )

    return {
        "ok": rep.ok,
        "code": rep.code.value if rep.code else None,
        "message": rep.message,
        "recovered": rep.recovered,
        "ply": rep.ply_before,
        "side": "R" if rep.side_before > 0 else "B",
        "die": rep.die_before,
        "hash_before": f"{rep.hash_before:016x}",
        "hash_after": f"{rep.hash_after:016x}" if rep.hash_after is not None else None,
        "chain_tail": session.chain_hash.hex()[:16] if session is not None else "",
        "move": rep.remote_move.to_text() if rep.remote_move else None,
        "raw": rep.format(),
        "layers": rows,
    }


def report_parse_failed(exc, session=None) -> dict:
    """解析阶段就抛异常（accept_remote_move 内部裸调 parse_intent）时的降级视图。"""
    code = getattr(exc, "code", None)
    fail_layer = CODE_LAYER.get(code, 1) if code is not None else 1
    rows = []
    for idx, (layer, title) in enumerate(LAYERS):
        if idx < fail_layer:
            state = "ok"
        elif idx == fail_layer:
            state = "fail"
        else:
            state = "skip"
        rows.append(
            {
                "layer": layer,
                "title": title,
                "state": state,
                "recovered": False,
                "items": [] if state == "skip" else
                [{"name": "解析失败", "ok": False,
                  "detail": str(exc), "recovered": False}],
                "note": error_text(code) if state == "fail" else "",
            }
        )
    return {
        "ok": False,
        "code": code.value if code is not None else "MALFORMED_MOVE",
        "message": str(exc),
        "recovered": False,
        "ply": None,
        "side": None,
        "die": None,
        "hash_before": None,
        "hash_after": None,
        "chain_tail": session.chain_hash.hex()[:16] if session is not None else "",
        "move": None,
        "raw": str(exc),
        "layers": rows,
    }


# ---------------- 搜索与结果文案 ----------------
REASON_TEXT: dict[str, str] = {
    "mcts": "蒙特卡洛树搜索",
    "single": "唯一合法走法",
    "mate": "一步进角，直接取胜",
    "low_time": "剩余时间不足，走启发式",
    "no_move": "无合法走法",
}

TERMINAL_TEXT: dict[TerminalReason, str] = {
    TerminalReason.REACHED_CORNER: "率先到达对方出发区角点",
    TerminalReason.ANNIHILATION: "吃光对方全部棋子",
    TerminalReason.TIMEOUT: "计时耗尽",
    TerminalReason.ADJUDICATION: "安全阀裁决",
}


def result_view(result, human_side: int | None = None) -> dict | None:
    if result is None:
        return None
    winner_name = "红方" if result.winner > 0 else "蓝方"
    human_won = None if human_side is None else (result.winner == human_side)
    return {
        "winner": result.winner,
        "winner_name": winner_name,
        "reason": result.reason.value,
        "reason_text": TERMINAL_TEXT.get(result.reason, result.reason.value),
        "ply": result.ply,
        "text": f"{winner_name}胜 · {TERMINAL_TEXT.get(result.reason, result.reason.value)} · 第 {result.ply} 手",
        "human_won": human_won,
    }


def describe_piece_code(code: int) -> str:
    if code == 0:
        return "空"
    return f"{'红' if code > 0 else '蓝'}{num_of(code)}号"
