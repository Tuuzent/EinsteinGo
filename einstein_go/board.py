"""棋盘渲染与格名工具（纯数据层，不感知 Position 的时间/历史字段）。

渲染器只接受一个长度 25 的棋子编码序列，因此既可用于 Position，
也可用于回放/调试时的裸棋盘。
"""

from __future__ import annotations

from .constants import BLUE, BOARD_SIZE, EMPTY, RED


def cell_text(code: int) -> str:
    if code == EMPTY:
        return " ."
    tag = "R" if code > 0 else "B"
    return f"{tag}{abs(code)}"


def to_rows(squares) -> list[list[str]]:
    """扁平 25 序列 -> 5 行 x 5 列的单元格文本。"""
    return [[cell_text(squares[r * BOARD_SIZE + c]) for c in range(BOARD_SIZE)] for r in range(BOARD_SIZE)]


def render_squares(squares, indent: str = "  ") -> str:
    cols = "abcde"
    header = f"{indent}  " + " ".join(f"{ch:^2}" for ch in cols)
    lines = [header]
    for r, row in enumerate(to_rows(squares), start=1):
        lines.append(f"{indent}{r} " + " ".join(f"{cell:>2}" for cell in row))
    return "\n".join(lines)


def side_label(side: int) -> str:
    return "红(R)" if side == RED else ("蓝(B)" if side == BLUE else "?")
