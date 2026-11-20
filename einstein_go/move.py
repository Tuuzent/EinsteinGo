"""走法数据模型与序列化。

分两层的理由：
    Move        引擎内部走法，由 movegen 产出，必然合法（已解析、已校验）。
    MoveIntent  协议层原始走法，来自外部，不可信：src / die 可能缺失、可能越界。
混成一层会导致"信任外部输入"的校验层级混乱。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .constants import N_SQUARES, NUM_MAX, NUM_MIN, idx, sq_name
from .errors import ErrorCode, EngineError


@dataclass(frozen=True, slots=True, order=True)
class Move:
    """引擎内部走法。frozen + order 自动获得 __eq__ / __hash__ / __lt__。"""

    piece: int       # 己方编号 1..6
    src: int         # 起点扁平索引 0..24
    dst: int         # 终点扁平索引 0..24
    die: int         # 决策时的骰值 1..6
    captured: int = 0  # 目标格原棋码，0 表示目标是空格

    def key(self) -> tuple[int, int, int]:
        """确定性 tie-break 用的全序键（字典序最小者优先）。"""
        return (self.piece, self.src, self.dst)

    def to_text(self) -> str:
        return f"{self.piece}{sq_name(self.src)}-{sq_name(self.dst)}@{self.die}"

    def to_compact(self) -> str:
        return f"{self.piece}{sq_name(self.src)}{sq_name(self.dst)}@{self.die}"

    def to_json(self) -> dict:
        return {
            "piece": self.piece,
            "src": sq_name(self.src),
            "dst": sq_name(self.dst),
            "die": self.die,
            "captured": self.captured,
        }

    def __str__(self) -> str:
        return self.to_text()


@dataclass(frozen=True, slots=True)
class MoveIntent:
    """协议层原始走法（不可信）。"""

    piece: int
    dst: int
    src: int | None = None
    die: int | None = None
    side: int | None = None       # 声明自己属于哪一方
    ply: int | None = None        # 声明的半步序号（用于乱序检测）
    raw: str = ""                 # 原始文本，便于错误报告

    def to_json(self) -> dict:
        d = {"piece": self.piece, "dst": sq_name(self.dst)}
        if self.src is not None:
            d["src"] = sq_name(self.src)
        if self.die is not None:
            d["die"] = self.die
        if self.side is not None:
            d["side"] = "R" if self.side > 0 else "B"
        if self.ply is not None:
            d["ply"] = self.ply
        return d


_MOVE_RE = re.compile(
    r"^\s*(\d)\s*([A-Za-z])\s*(\d)\s*(?:[-<>]\s*)?([A-Za-z])\s*(\d)\s*(?:@\s*(\d))?\s*$"
)
_COMPACT_RE = re.compile(r"^\s*(\d)\s*([A-Za-z])(\d)([A-Za-z])(\d)\s*(?:@\s*(\d))?\s*$")


def _square_from_parts(col_ch: str, row_ch: str, raw: str) -> int:
    col_ch = col_ch.lower()
    if col_ch not in "abcde" or row_ch not in "12345":
        raise EngineError(
            ErrorCode.OUT_OF_BOARD,
            f"坐标越界: {col_ch}{row_ch}",
            raw=raw,
        )
    return idx(int(row_ch), "abcde".index(col_ch) + 1)


def parse_move_text(text: str) -> MoveIntent:
    """解析人读走法文本。

    支持：``4a1-b1@3`` / ``4a1b1@3`` / ``4a1>b1`` / 全角字符（NFKC 归一化）。
    解析失败逐级抛出 MALFORMED_MOVE / OUT_OF_BOARD，不做静默修正。
    """
    if not isinstance(text, str):
        raise EngineError(ErrorCode.MALFORMED_MOVE, f"走法必须是字符串，收到 {type(text).__name__}")
    norm = unicodedata.normalize("NFKC", text).strip()
    m = _MOVE_RE.match(norm) or _COMPACT_RE.match(norm)
    if not m:
        raise EngineError(ErrorCode.MALFORMED_MOVE, f"无法解析的走法: {text!r}", raw=text)
    piece = int(m.group(1))
    src = _square_from_parts(m.group(2), m.group(3), text)
    dst = _square_from_parts(m.group(4), m.group(5), text)
    die_raw = m.group(6)
    if not (NUM_MIN <= piece <= NUM_MAX):
        raise EngineError(ErrorCode.MALFORMED_MOVE, f"棋子编号必须是 1..6，收到 {piece}", raw=text)
    die = None
    if die_raw is not None:
        die = int(die_raw)
        if not (NUM_MIN <= die <= NUM_MAX):
            raise EngineError(ErrorCode.MALFORMED_MOVE, f"骰值必须是 1..6，收到 {die}", raw=text)
    return MoveIntent(piece=piece, src=src, dst=dst, die=die, raw=text)


def parse_move_json(obj: dict) -> MoveIntent:
    """解析 JSON 走法：``{"piece":3,"dst":"b2","src":"a2","die":4,"ply":5,"side":"R"}``。"""
    if not isinstance(obj, dict):
        raise EngineError(ErrorCode.MALFORMED_MOVE, "JSON 走法必须是对象")
    try:
        piece = int(obj["piece"])
        dst_s = str(obj["dst"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EngineError(ErrorCode.MALFORMED_MOVE, f"JSON 走法缺少必要字段: {exc}", raw=str(obj)) from exc
    src_s = obj.get("src")
    src = None
    if src_s is not None:
        src = _square_from_parts(str(src_s)[0], str(src_s)[1:], str(obj))
    dst = _square_from_parts(str(dst_s)[0], str(dst_s)[1:], str(obj))
    die = obj.get("die")
    die = None if die is None else int(die)
    side_raw = obj.get("side")
    side = None
    if isinstance(side_raw, str):
        side = 1 if side_raw.upper().startswith("R") else -1
    elif isinstance(side_raw, int) and side_raw in (1, -1):
        side = side_raw
    ply = obj.get("ply")
    ply = None if ply is None else int(ply)
    if not (NUM_MIN <= piece <= NUM_MAX):
        raise EngineError(ErrorCode.MALFORMED_MOVE, f"棋子编号必须是 1..6，收到 {piece}", raw=str(obj))
    if die is not None and not (NUM_MIN <= die <= NUM_MAX):
        raise EngineError(ErrorCode.MALFORMED_MOVE, f"骰值必须是 1..6，收到 {die}", raw=str(obj))
    return MoveIntent(piece=piece, dst=dst, src=src, die=die, side=side, ply=ply, raw=str(obj))


def format_record_line(ply: int, side: int, move: Move) -> str:
    """棋谱行：``  5. B 2 b5-b4 @6``。"""
    return f"{ply:>3}. {'R' if side > 0 else 'B'} {move.to_compact()}"


def all_squares() -> range:
    return range(N_SQUARES)
