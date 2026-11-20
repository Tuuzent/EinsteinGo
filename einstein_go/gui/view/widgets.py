"""可复用的小部件：圆角矩形、错误条、候选条、结果卡、骰子。"""

from __future__ import annotations

import random
import time
import tkinter as tk

from . import theme as T


def round_rect_points(x0: float, y0: float, x1: float, y1: float, r: float) -> list[float]:
    """圆角矩形的顶点序列，配合 create_polygon(smooth=True) 使用。

    每个角放三个点（其中两个重合在原角上），Tk 的样条会自动把角磨圆。
    """
    r = max(0.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    return [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]


class ErrorBar(tk.Label):
    """棋盘下方的提示条。始终占位（只改文字与底色），避免布局跳动。

    点错类提示一律走这里，不弹 messagebox —— 模态框会打断下一次点击。
    """

    def __init__(self, master, theme: T.Theme) -> None:
        super().__init__(
            master, text=" ", anchor="w", padx=10, height=1,
            bg=T.WINDOW_BG, fg=T.TEXT_DIM, font=theme.font_ui,
        )
        self._after: str | None = None
        self._repeat = 0

    def show(self, message: str, severity: str = "error") -> None:
        if not message:
            return
        bg, fg = {
            "error": (T.ERR_BG, T.ERR_RED),
            "warn": (T.WARN_BG, T.WARN_AMBER),
            "info": (T.INFO_BG, T.INFO_FG),
        }.get(severity, (T.OK_BG, T.OK_GREEN))
        if self._after is not None and self._repeat:
            self._repeat += 1
            suffix = f"  ·+{self._repeat}"
        else:
            self._repeat = 0
            suffix = ""
        self.configure(text=message + suffix, bg=bg, fg=fg)
        self._restart()

    def _restart(self) -> None:
        self._cancel()
        self._after = self.after(T.ERROR_HIDE_MS, self.hide)

    def _cancel(self) -> None:
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def hide(self) -> None:
        self._cancel()
        self._repeat = 0
        try:
            self.configure(text=" ", bg=T.WINDOW_BG, fg=T.TEXT_DIM)
        except tk.TclError:
            pass

    def destroy(self) -> None:
        self._cancel()
        super().destroy()


class CandidateBars(tk.Canvas):
    """AI 前三候选：走法文本 + 访问数 + 先验浅条 + 访问数深条 + Q 值。

    必须用 Canvas 而不是 ttk.Progressbar：要三条同尺度对比，还要在条上叠文字。
    """

    ROW_H = 48

    def __init__(self, master, theme: T.Theme) -> None:
        self.theme = theme
        super().__init__(
            master, bg=T.CARD_BG, highlightthickness=0, bd=0,
            width=1, height=theme.px(self.ROW_H * 3),
        )

    def render(self, candidates: list[dict], search: dict | None) -> None:
        self.delete("all")
        w = max(self.winfo_width(), 200)
        pad = self.theme.px(6)
        if not candidates:
            reason = (search or {}).get("reason_text", "")
            hint = reason or "尚无搜索记录（AI 走一手后显示前三候选）"
            self.create_text(pad, self.theme.px(6), anchor="nw", text=hint,
                             fill=T.TEXT_DIM, font=self.theme.font_ui)
            self.configure(height=self.theme.px(26))
            return

        bar_h = self.theme.px(9)
        row_h = self.theme.px(self.ROW_H)
        x0, x1 = pad, w - pad
        for idx, cand in enumerate(candidates):
            top = idx * row_h + self.theme.px(6)
            text_y = top
            bar_y = top + self.theme.px(17)
            color = T.BAR_CHOSEN if cand["is_choice"] else T.BAR_FILL
            self.create_text(x0, text_y, anchor="nw", text=cand["text"],
                             fill=T.TEXT_MAIN, font=self.theme.font_mono)
            self.create_text(x1, text_y, anchor="ne", text=f"n={cand['visits']}",
                             fill=T.TEXT_DIM, font=self.theme.font_mono_small)
            span = max(1, x1 - x0)
            self.create_rectangle(x0, bar_y, x0 + int(span * max(0.0, min(1.0, cand["prior"]))),
                                  bar_y + bar_h, fill=T.BAR_TRACK, outline="")
            self.create_rectangle(x0, bar_y, x0 + int(span * max(0.0, min(1.0, cand["share"]))),
                                  bar_y + bar_h, fill=color, outline="")
            q = cand["q"]
            self.create_text(x1, bar_y + bar_h + self.theme.px(1), anchor="ne",
                             text=f"Q {q:+.2f}", font=self.theme.font_ui_small,
                             fill=T.OK_GREEN if q > 0 else (T.ERR_RED if q < 0 else T.TEXT_DIM))
        self.configure(height=row_h * len(candidates) + self.theme.px(6))


class ResultCard(tk.Frame):
    """终局面板内结果卡（不用模态窗，避免 grab_set + 嵌套 mainloop 的焦点陷阱）。"""

    def __init__(self, master, theme: T.Theme) -> None:
        self.theme = theme
        super().__init__(master, bg=T.CARD_BG, highlightthickness=1,
                         highlightbackground=T.BORDER)
        self._strip = tk.Frame(self, bg=T.OK_GREEN, width=theme.px(5))
        self._strip.pack(side="left", fill="y")
        body = tk.Frame(self, bg=T.CARD_BG)
        body.pack(side="left", fill="both", expand=True, padx=theme.px(10), pady=theme.px(8))
        self._title = tk.Label(body, text="", anchor="w", bg=T.CARD_BG,
                               fg=T.TEXT_MAIN, font=theme.font_subtitle)
        self._title.pack(fill="x")
        self._detail = tk.Label(body, text="", anchor="w", bg=T.CARD_BG,
                                fg=T.TEXT_DIM, font=theme.font_ui_small, justify="left")
        self._detail.pack(fill="x")

    def render(self, result: dict | None) -> None:
        try:
            if not result:
                self._title.configure(text="")
                self._detail.configure(text="")
                self._strip.configure(bg=T.BORDER)
                return
            if result.get("human_won") is True:
                self._strip.configure(bg=T.OK_GREEN)
            elif result.get("human_won") is False:
                self._strip.configure(bg=T.ERR_RED)
            else:
                self._strip.configure(bg=T.TEXT_DIM)
            self._title.configure(text=result["text"])
            self._detail.configure(text="点『新局』再来一盘，或『导出棋谱』保存本局")
        except tk.TclError:
            pass


class SectionTitle(tk.Label):
    def __init__(self, master, theme: T.Theme, text: str) -> None:
        super().__init__(master, text=text, anchor="w", bg=T.PANEL_BG,
                         fg=T.TEXT_DIM, font=theme.font_ui_small)


class DiceView(tk.Canvas):
    """骰子。滚动时快速换面 + 轻微抖动，最后停在目标点数。

    用 Canvas 画而不是换字符：点数阵（pip）比数字更像骰子，也便于做滚动动画。
    """

    SIZE = 54
    # 3x3 网格下标 -> 该点数需要点亮的格
    PIPS = {
        1: (4,),
        2: (0, 8),
        3: (0, 4, 8),
        4: (0, 2, 6, 8),
        5: (0, 2, 4, 6, 8),
        6: (0, 2, 3, 5, 6, 8),
    }
    SPIN_SECONDS = 0.38
    FRAME_MS = 52

    def __init__(self, master, theme: T.Theme) -> None:
        self.theme = theme
        self.size = theme.px(self.SIZE)
        super().__init__(master, width=self.size, height=self.size,
                         bg=T.PANEL_BG, highlightthickness=0, bd=0)
        self._value = 0
        self._target = 0
        self._deadline = 0.0
        self._after: str | None = None
        self._draw()

    # ---------------- 对外 ----------------
    def set_value(self, value: int, animate: bool = True) -> None:
        value = max(0, min(6, int(value or 0)))
        if value == self._target:          # 目标没变：不要打断正在跑的滚动
            return
        self._target = value
        self._cancel()
        if not animate or value == 0:
            self._value = value
            self._draw()
            return
        self._deadline = time.monotonic() + self.SPIN_SECONDS
        self._spin()

    @property
    def value(self) -> int:
        return self._value

    def destroy(self) -> None:
        self._cancel()
        super().destroy()

    # ---------------- 动画 ----------------
    def _cancel(self) -> None:
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _spin(self) -> None:
        if time.monotonic() >= self._deadline:
            self._value = self._target
            self._after = None
            self._draw()
            return
        face = random.randint(1, 6)
        if face == self._value:
            face = face % 6 + 1
        self._value = face
        self._draw(jitter=random.choice((-1, 0, 1)))
        self._after = self.after(self.FRAME_MS, self._spin)

    # ---------------- 绘制 ----------------
    def _draw(self, jitter: int = 0) -> None:
        self.delete("all")
        th, size = self.theme, self.size
        pad = th.px(2)
        self.create_polygon(
            *round_rect_points(pad, pad, size - pad, size - pad, th.px(9)),
            fill=T.CARD_BG, outline=T.BORDER, width=th.px(1),
        )
        if self._value == 0:
            self.create_text(size / 2, size / 2, text="—",
                             fill=T.TEXT_DIM, font=th.font_ui)
            return

        pad_pip = size * 0.24
        span = size - 2 * pad_pip
        step = span / 2.0
        r = max(2.0, size * 0.072)
        color = T.TEXT_MAIN
        for cell in self.PIPS[self._value]:
            row, col = divmod(cell, 3)
            cx = pad_pip + col * step + jitter
            cy = pad_pip + row * step + jitter
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")
