"""配色、字体与像素缩放。

本模块只依赖 tkinter.font 做字体探测，不创建控件；`Theme` 在 App 构造时实例化一次。
所有像素常量都是 96DPI 下的逻辑值，绘制前一律过 `Theme.px()`。
"""

from __future__ import annotations

import tkinter.font as tkfont

# ---------------- 配色（浅色 + 棋盘质感） ----------------
WINDOW_BG = "#f4f1ea"
PANEL_BG = "#fbfaf7"
CARD_BG = "#fffdf8"
BORDER = "#ddd4c4"

BOARD_FRAME = "#8a7a63"
CELL_LIGHT = "#f2e6d0"
CELL_DARK = "#e9dabc"
CELL_LINE = "#d8c8ab"
HOME_RED = "#efcfc6"
HOME_BLUE = "#d3dded"
CORNER_OF_RED = "#b8443a"
CORNER_OF_BLUE = "#35608c"

RED_FILL = "#c8544f"
RED_EDGE = "#99372f"
RED_TEXT = "#fffaf5"
BLUE_FILL = "#4b78b0"
BLUE_EDGE = "#2f5279"
BLUE_TEXT = "#f7fbff"

RED_FILL_DIM = "#d8a8a3"
RED_EDGE_DIM = "#bd8781"
BLUE_FILL_DIM = "#a7bdd7"
BLUE_EDGE_DIM = "#7e9bbc"

SELECT_RING = "#e2a03c"
TARGET_DOT = "#4f9a6a"
TARGET_CAP = "#cf5b4e"
LAST_MOVE = "#f9ecc6"
CAPTURE_FX = "#e05a4e"
DIM_PIECE = "#b9b2a4"

TEXT_MAIN = "#2e2a24"
TEXT_DIM = "#7b7266"
TEXT_INV = "#ffffff"

OK_GREEN = "#2f7d4f"
OK_BG = "#eaf5ee"
WARN_AMBER = "#9a6510"
WARN_BG = "#fdf6e3"
ERR_RED = "#b3261e"
ERR_BG = "#fdecea"
INFO_BG = "#eef2f7"
INFO_FG = "#3c5a78"

BAR_TRACK = "#e8e2d6"
BAR_FILL = "#6f8fac"
BAR_CHOSEN = "#2f7d4f"

STATE_COLOR = {"ok": OK_GREEN, "fail": ERR_RED, "skip": TEXT_DIM, "recovered": WARN_AMBER}

# ---------------- 布局常量（96DPI 逻辑像素） ----------------
M_LEFT, M_TOP, M_RIGHT, M_BOTTOM = 34, 28, 12, 30
PANEL_WIDTH = 336
WIN_W, WIN_H = 980, 820
MIN_W, MIN_H = 900, 740
CELL_MIN = 48

POLL_MS = 30
TICK_MS = 200
RESIZE_THROTTLE_MS = 30
ERROR_HIDE_MS = 2600


class Theme:
    """DPI 缩放 + 字体回退链。字体分三档，避免 Consolas 里混中文导致宽度暴涨。"""

    def __init__(self, root) -> None:
        self.root = root
        try:
            self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        except Exception:
            self.scale = 1.0
        families = set()
        try:
            families = {f.lower() for f in tkfont.families(root)}
        except Exception:
            pass

        ui = self._first(families, ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Arial"))
        mono = self._first(families, ("Consolas", "Cascadia Mono", "Courier New", "TkFixedFont"))
        self.ui = ui
        self.mono = mono

        self.font_ui = (ui, 10)
        self.font_ui_small = (ui, 9)
        self.font_ui_bold = (ui, 10, "bold")
        self.font_title = (ui, 14, "bold")
        self.font_subtitle = (ui, 11, "bold")
        self.font_big = (ui, 22, "bold")
        self.font_mono = (mono, 9)
        self.font_mono_small = (mono, 8)
        self.board_font_base = self._first(families, ("Segoe UI", "Arial", "TkDefaultFont"))
        # Tk 的 scaling：让"点"为单位的字随 DPI 放大
        try:
            root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
        except Exception:
            pass

    @staticmethod
    def _first(families: set[str], candidates: tuple[str, ...]) -> str:
        for name in candidates:
            if name.lower() in families:
                return name
        return candidates[-1]

    def px(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def board_font(self, cell: int):
        size = max(11, int(cell * 0.36))
        return (self.board_font_base, size, "bold")

    def label_font(self, cell: int):
        size = max(8, int(cell * 0.20))
        return (self.board_font_base, size)
