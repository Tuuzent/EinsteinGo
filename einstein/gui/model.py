"""GUI 的纯数据层：模式/阶段枚举、开局设置、难度预设、25 格视图模型。

本模块**不 import tkinter**，可被 pytest 在内置解释器上直接跑。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..config import SearchConfig
from ..constants import BLUE, BLUE_HOME, CORNER, N_SQUARES, RED, RED_HOME, num_of, rc, side_of, sq_name
from ..sync import SyncMode


class Mode(str, Enum):
    PVE = "pve"        # 人机对弈
    MATCH = "match"    # 比赛模式：复制对方走法 + 我方算法回应

    @property
    def label(self) -> str:
        return "人机对弈" if self is Mode.PVE else "比赛模式"


class Phase(str, Enum):
    HUMAN_TURN = "human_turn"    # 人类可操作（die 可能为 0 = 待掷骰）
    THINKING = "thinking"        # 后台搜索中
    MATCH_WAIT = "match_wait"    # 比赛模式：等对方走法文本
    GAME_OVER = "game_over"

    @property
    def label(self) -> str:
        return {
            Phase.HUMAN_TURN: "轮到你走",
            Phase.THINKING: "AI 正在思考",
            Phase.MATCH_WAIT: "对方回合",
            Phase.GAME_OVER: "对局结束",
        }[self]


SIDE_LABEL = {RED: "红", BLUE: "蓝"}


@dataclass(frozen=True, slots=True)
class GameSetup:
    """一次开局的全部参数。frozen，改动一律用 dataclasses.replace。"""

    mode: Mode = Mode.PVE
    human_side: int = RED          # PVE：人类执方；MATCH：我方执方
    difficulty: str = "normal"
    budget_ms: int = 240_000
    seed: int = 0
    auto_roll: bool = True         # 进入回合自动掷骰（推荐）
    sync_mode: SyncMode = SyncMode.STRICT
    auto_reply: bool = True        # MATCH：复制成功后自动让我方 AI 回应

    def __post_init__(self) -> None:
        if self.human_side not in (RED, BLUE):
            raise ValueError(f"human_side 必须是 +1/-1，收到 {self.human_side}")
        if self.difficulty not in DIFFICULTY_SPEC:
            raise ValueError(f"未知难度 {self.difficulty!r}，可选 {tuple(DIFFICULTY_SPEC)}")
        if not 1_000 <= self.budget_ms <= 3_600_000:
            raise ValueError("budget_ms 需在 1s..1h 之间")

    @property
    def remote_side(self) -> int:
        """比赛模式里对方的执方（永远是我方的对面）。"""
        return -self.human_side


# ---------------- 难度预设 ----------------
# 只调 max_think_ms 与 node_limit：前者决定 UI 的响应性上限，后者让"轻松"档也很快。
# min_think_ms 保持默认 60，避免在剩余时间极少时仍强行搜索。
DIFFICULTY_SPEC: dict[str, dict] = {
    "easy": {"max_think_ms": 400, "node_limit": 800},
    "normal": {"max_think_ms": 900, "node_limit": 4000},
    "hard": {"max_think_ms": 1800, "node_limit": None},
}

DIFFICULTY_LABEL = {"easy": "轻松", "normal": "普通", "hard": "认真"}
DIFFICULTY_ORDER = ("easy", "normal", "hard")


def resolve_config(difficulty: str, seed: int = 0) -> SearchConfig:
    """难度名 -> SearchConfig。全项目唯一的构造入口（SearchConfig 是 frozen slots，不能改字段）。"""
    if difficulty not in DIFFICULTY_SPEC:
        raise ValueError(f"未知难度 {difficulty!r}")
    return SearchConfig(seed=seed, **DIFFICULTY_SPEC[difficulty])


# ---------------- 25 格视图模型 ----------------
def build_cells(
    squares,
    *,
    side: int = RED,
    candidates: tuple[int, ...] = (),
    selected_src: int = -1,
    targets: dict[int, int] | None = None,
    last_from: int = -1,
    last_to: int = -1,
    capture_sq: int = -1,
    capture_code: int = 0,
) -> list[dict]:
    """把 25 长棋码序列展开成 25 个纯标量 dict，供视图层零推断地绘制。

    targets: {目标格索引: 该格上的棋码(0=空)}，用于区分"空格圆点"与"可吃红环"。
    """
    targets = targets or {}
    cells: list[dict] = []
    for i in range(N_SQUARES):
        code = squares[i]
        r, c = rc(i)
        if i in RED_HOME:
            zone = "red_home"
        elif i in BLUE_HOME:
            zone = "blue_home"
        else:
            zone = "neutral"
        num = num_of(code)
        own = code != 0 and side_of(code) == side
        cells.append(
            {
                "i": i,
                "name": sq_name(i),
                "row": r,
                "col": c,
                "code": code,
                "num_text": str(num) if num else "",
                "side": side_of(code),
                "empty": code == 0,
                "zone": zone,
                "corner_of": RED if i == CORNER[RED] else (BLUE if i == CORNER[BLUE] else None),
                "selected": i == selected_src,
                "target": i in targets,
                "target_capture": targets.get(i, 0),
                "last_from": i == last_from,
                "last_to": i == last_to,
                "capture_flash": capture_code if i == capture_sq else 0,
                "playable": own and (num in candidates if candidates else False),
            }
        )
    return cells
