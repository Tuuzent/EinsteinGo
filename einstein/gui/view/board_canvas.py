"""棋盘 Canvas：分层绘制、坐标换算、点击映射。

分层 tag（**禁止 delete("all")**，否则高亮/动画会被连带清掉）：
    bg     底板：格底、棋盘外框、行列标、角标   —— 仅几何变化时重建
    mark   上一步 from/to 底色
    hl     选中环 + 合法目标圆点/红环
    piece  棋子（圆角块 + 数字）
    hud    思考中 / 终局横幅
    fx     被吃闪烁、终局角脉冲            —— 自删，不参与整层重建

重绘前会 after_cancel 掉所有动画，避免旧回调 itemconfig 一个已不存在的 item。
"""

from __future__ import annotations

import time
import tkinter as tk

from . import theme as T
from .widgets import round_rect_points


class BoardCanvas(tk.Canvas):
    def __init__(self, master, theme: T.Theme, on_click=None) -> None:
        super().__init__(master, bg=T.WINDOW_BG, highlightthickness=0, bd=0,
                         width=1, height=1)
        self.theme = theme
        self.on_click = on_click
        self._view: dict | None = None
        self._dirty = False
        self._geom: tuple[int, int, int] | None = None
        self.cell = 60
        self.ox = 0
        self.oy = 0
        self._anim_ids: list[str] = []
        self._capture_key: tuple | None = None
        self._pulse_id: str | None = None
        self._pulse_on = False
        self._fly: dict | None = None
        self._fly_after: str | None = None
        self._fly_shape: int | None = None
        self._fly_text: int | None = None
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", self._on_resize)

    # ---------------- 外部接口 ----------------
    def _on_resize(self, _event=None) -> None:
        """窗口缩放后必须重算 layout，否则棋盘会一直停在初始的极小尺寸。"""
        if not self._dirty:
            self._dirty = True
            self.after_idle(self._flush)

    def render(self, view: dict) -> None:
        self._view = view
        if not self._dirty:
            self._dirty = True
            self.after_idle(self._flush)

    def square_at(self, x: int, y: int) -> int | None:
        c = (x - self.ox) // self.cell
        r = (y - self.oy) // self.cell
        if 0 <= r < 5 and 0 <= c < 5:
            return int(r) * 5 + int(c)
        return None

    # ---------------- 布局 ----------------
    def _relayout(self) -> None:
        th = self.theme
        w = max(self.winfo_width(), 1)
        h = max(self.winfo_height(), 1)
        ml, mt = th.px(T.M_LEFT), th.px(T.M_TOP)
        mr, mb = th.px(T.M_RIGHT), th.px(T.M_BOTTOM)
        cell = int(min((w - ml - mr) / 5.0, (h - mt - mb) / 5.0))
        cell = max(th.px(T.CELL_MIN), cell)
        self.cell = cell
        self.ox = ml + max(0, (w - ml - mr - 5 * cell) // 2)
        self.oy = mt + max(0, (h - mt - mb - 5 * cell) // 2)

    def _xy(self, sq: int) -> tuple[int, int, int, int]:
        r, c = divmod(sq, 5)
        x0 = self.ox + c * self.cell
        y0 = self.oy + r * self.cell
        return x0, y0, x0 + self.cell, y0 + self.cell

    # ---------------- 重绘 ----------------
    def _flush(self) -> None:
        self._dirty = False
        view = self._view
        if view is None:
            return
        self._cancel_anims()
        self._relayout()
        geom = (self.cell, self.ox, self.oy)
        if geom != self._geom:
            self._geom = geom
            self.delete("bg")
            self._draw_bg()

        self.delete("mark")
        self.delete("hl")
        self.delete("piece")
        self.delete("hud")
        self.delete("fx")

        self._draw_last_move(view)
        self._draw_highlights(view)
        self._draw_pieces(view)
        self.tag_raise("hl")          # 目标描边压在棋子上，否则吃子目标看不见
        self._draw_hud(view)
        self._maybe_capture_fx(view)
        self._maybe_corner_pulse(view)
        if self._fly is not None:
            # 底板（bg）在几何变化时会重建并盖住一切，飞行棋必须每帧重新置顶
            self.tag_raise("fly")

    def _cancel_anims(self) -> None:
        for aid in self._anim_ids:
            try:
                self.after_cancel(aid)
            except Exception:
                pass
        self._anim_ids.clear()
        self._pulse_id = None

    # ---------------- 底板 ----------------
    def _draw_bg(self) -> None:
        th, cell = self.theme, self.cell
        x0, y0 = self.ox, self.oy
        x1, y1 = x0 + 5 * cell, y0 + 5 * cell

        self.create_rectangle(x0 - th.px(3), y0 - th.px(3), x1 + th.px(3), y1 + th.px(3),
                              fill=T.BOARD_FRAME, outline="", tags=("bg",))
        self.create_rectangle(x0, y0, x1, y1, fill=T.CELL_LIGHT, outline="", tags=("bg",))

        for sq in range(25):
            r, c = divmod(sq, 5)
            cx0, cy0, cx1, cy1 = self._xy(sq)
            base = T.CELL_LIGHT if (r + c) % 2 == 0 else T.CELL_DARK
            cell_meta = self._cell_meta(sq)
            if cell_meta:
                if cell_meta["zone"] == "red_home":
                    base = T.HOME_RED
                elif cell_meta["zone"] == "blue_home":
                    base = T.HOME_BLUE
            self.create_rectangle(cx0, cy0, cx1, cy1, fill=base, outline="", tags=("bg",))
            self.create_rectangle(cx0, cy0, cx1, cy1, fill="", outline=T.CELL_LINE,
                                  tags=("bg",))

        # 行列标
        lbl_font = th.label_font(cell)
        for r in range(5):
            cy = y0 + (r + 0.5) * cell
            self.create_text(x0 - th.px(10), cy, anchor="e", text=str(r + 1),
                             fill=T.TEXT_DIM, font=lbl_font, tags=("bg",))
        for c in range(5):
            cx = x0 + (c + 0.5) * cell
            self.create_text(cx, y1 + th.px(8), anchor="n", text="abcde"[c],
                             fill=T.TEXT_DIM, font=lbl_font, tags=("bg",))

        # 目标角点标记（红方目标是 e5，蓝方目标是 a1）
        for sq, side in ((24, 1), (0, -1)):
            cx0, cy0, cx1, cy1 = self._xy(sq)
            color = T.CORNER_OF_RED if side > 0 else T.CORNER_OF_BLUE
            size = max(8, cell // 4)
            if side > 0:      # e5 在棋盘右下
                pts = [cx1, cy1 - size, cx1, cy1, cx1 - size, cy1]
            else:             # a1 在棋盘左上
                pts = [cx0, cy0 + size, cx0, cy0, cx0 + size, cy0]
            self.create_polygon(*pts, fill=color, outline="", tags=("bg",))
            self.create_rectangle(cx0, cy0, cx1, cy1, fill="", outline=color,
                                  width=th.px(2), tags=("bg",))

    def _cell_meta(self, sq: int) -> dict | None:
        view = self._view
        if not view or not view.get("cells"):
            return None
        return view["cells"][sq]

    # ---------------- 各层 ----------------
    def _draw_last_move(self, view: dict) -> None:
        for key in ("last_from", "last_to"):
            for meta in view["cells"]:
                if meta.get(key):
                    x0, y0, x1, y1 = self._xy(meta["i"])
                    self.create_rectangle(x0 + 1, y0 + 1, x1 - 1, y1 - 1,
                                          fill=T.LAST_MOVE, outline="", tags=("mark",))

    def _draw_highlights(self, view: dict) -> None:
        th = self.theme
        for meta in view["cells"]:
            if meta.get("selected"):
                x0, y0, x1, y1 = self._xy(meta["i"])
                inset = th.px(3)
                self.create_rectangle(x0 + inset, y0 + inset, x1 - inset, y1 - inset,
                                      outline=T.SELECT_RING, width=th.px(3), tags=("hl",))
            if meta.get("target"):
                x0, y0, x1, y1 = self._xy(meta["i"])
                if meta.get("target_capture"):
                    # 可吃目标用"描边整格"，不能用中心圆点——那会被棋子盖住、也挡数字
                    inset = th.px(3)
                    self.create_rectangle(x0 + inset, y0 + inset, x1 - inset, y1 - inset,
                                          outline=T.TARGET_CAP, width=th.px(3), tags=("hl",))
                else:
                    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                    radius = max(6, int(self.cell * 0.11))
                    self.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                                     fill=T.TARGET_DOT, outline="", tags=("hl",))

    def _draw_pieces(self, view: dict) -> None:
        th = self.theme
        cell = self.cell
        font = th.board_font(cell)
        inset = max(6, int(cell * 0.10))
        radius = int(cell * 0.16)
        shadow = th.px(2)
        for meta in view["cells"]:
            code = meta["code"]
            if not code:
                continue
            fly = self._fly
            if fly is not None and meta["i"] == fly["to"] and code == fly["code"]:
                continue          # 正在飞的那一枚交给 fly 层画，避免重影
            x0, y0, x1, y1 = self._xy(meta["i"])
            red = code > 0
            faded = meta["side"] == view["side"] and not meta["playable"]
            if red:
                fill = T.RED_FILL_DIM if faded else T.RED_FILL
                edge = T.RED_EDGE_DIM if faded else T.RED_EDGE
                text_color = T.RED_EDGE_DIM if faded else T.RED_TEXT
            else:
                fill = T.BLUE_FILL_DIM if faded else T.BLUE_FILL
                edge = T.BLUE_EDGE_DIM if faded else T.BLUE_EDGE
                text_color = T.BLUE_EDGE_DIM if faded else T.BLUE_TEXT

            self.create_polygon(
                *round_rect_points(x0 + inset + shadow, y0 + inset + shadow,
                                   x1 - inset + shadow, y1 - inset + shadow, radius),
                fill="#000000", outline="", stipple="gray12", smooth=True, tags=("piece",),
            )
            self.create_polygon(
                *round_rect_points(x0 + inset, y0 + inset, x1 - inset, y1 - inset, radius),
                fill=fill, outline=edge, width=th.px(2), smooth=True, tags=("piece",),
            )
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=meta["num_text"],
                             fill=text_color, font=font, tags=("piece",))

    def _draw_hud(self, view: dict) -> None:
        th = self.theme
        x0, y0 = self.ox, self.oy
        x1, y1 = x0 + 5 * self.cell, y0 + 5 * self.cell
        phase = view["phase"]
        if phase == "thinking":
            # 摆在棋盘上方的留白里，避免遮住第一行棋子
            band_h = th.px(20)
            top = max(0, y0 - band_h - th.px(4))
            self.create_rectangle(x0, top, x1, top + band_h, fill=T.INFO_BG, outline="",
                                  stipple="gray50", tags=("hud",))
            self.create_text((x0 + x1) / 2, top + band_h / 2, text="AI 正在思考…",
                             fill=T.INFO_FG, font=th.font_ui_small, tags=("hud",))
        elif phase == "game_over" and view.get("result"):
            band_h = th.px(40)
            cy = (y0 + y1) / 2
            self.create_rectangle(x0, cy - band_h / 2, x1, cy + band_h / 2,
                                  fill="#ffffff", outline="", stipple="gray25", tags=("hud",))
            self.create_text((x0 + x1) / 2, cy, text=view["result"]["text"],
                             fill=T.TEXT_MAIN, font=th.font_subtitle, tags=("hud",))

    # ---------------- 特效 ----------------
    def _maybe_capture_fx(self, view: dict) -> None:
        for meta in view["cells"]:
            if meta.get("capture_flash"):
                key = (meta["i"], view["ply"])
                if key == self._capture_key:
                    return
                self._capture_key = key
                x0, y0, x1, y1 = self._xy(meta["i"])
                item = self.create_oval(x0 + 2, y0 + 2, x1 - 2, y1 - 2,
                                        outline=T.CAPTURE_FX, width=self.theme.px(4),
                                        tags=("fx",))
                self._flash(item, 0)
                return

    def _flash(self, item: int, step: int) -> None:
        """被吃闪烁：只改这一条 item 的描边色，6 步后自删。"""
        if step >= 6:
            try:
                self.delete(item)
            except tk.TclError:
                pass
            return
        color = T.CAPTURE_FX if step % 2 == 0 else "#f6b8b2"
        try:
            self.itemconfig(item, outline=color)
        except tk.TclError:
            return
        self._anim_ids.append(self.after(110, lambda: self._flash(item, step + 1)))

    def _maybe_corner_pulse(self, view: dict) -> None:
        if view["phase"] != "game_over" or not view.get("result"):
            return
        winner = view["result"]["winner"]
        sq = 24 if winner > 0 else 0
        x0, y0, x1, y1 = self._xy(sq)
        color = T.CORNER_OF_RED if winner > 0 else T.CORNER_OF_BLUE
        item = self.create_rectangle(x0, y0, x1, y1, outline=color,
                                     width=self.theme.px(3), tags=("fx",))

        def pulse(state: bool) -> None:
            try:
                self.itemconfig(item, width=self.theme.px(4 if state else 2))
            except tk.TclError:
                return
            self._pulse_id = self.after(420, lambda: pulse(not state))
            self._anim_ids.append(self._pulse_id)

        pulse(True)

    # ---------------- 行棋动画 ----------------
    def animate_move(self, from_sq: int, to_sq: int, code: int, duration_ms: int = 250) -> None:
        """让一枚棋子从 from 滑到 to。飞行期间该格由 fly 层独占绘制。"""
        if not code or from_sq < 0 or to_sq < 0 or from_sq == to_sq or self._view is None:
            return
        self._cancel_fly()
        self._fly = {
            "code": int(code),
            "from": int(from_sq),
            "to": int(to_sq),
            "t0": time.monotonic(),
            "dur": max(0.06, duration_ms / 1000.0),
        }
        self._flush()                 # 先按新状态重绘（to 格被跳过）
        self._build_fly()
        self._step_fly()

    def _build_fly(self) -> None:
        fly = self._fly
        if fly is None:
            return
        th, cell = self.theme, self.cell
        x0, y0, x1, y1 = self._xy(fly["from"])
        inset = max(6, int(cell * 0.10))
        radius = int(cell * 0.16)
        red = fly["code"] > 0
        self._fly_shape = self.create_polygon(
            *round_rect_points(x0 + inset, y0 + inset, x1 - inset, y1 - inset, radius),
            fill=T.RED_FILL if red else T.BLUE_FILL,
            outline=T.RED_EDGE if red else T.BLUE_EDGE,
            width=th.px(2), smooth=True, tags=("fly",),
        )
        self._fly_text = self.create_text(
            (x0 + x1) / 2, (y0 + y1) / 2, text=str(abs(fly["code"])),
            fill=T.RED_TEXT if red else T.BLUE_TEXT,
            font=th.board_font(cell), tags=("fly",),
        )
        self.tag_raise("fly")

    def _step_fly(self) -> None:
        fly = self._fly
        if fly is None:
            return
        cell = self.cell
        p = min(1.0, (time.monotonic() - fly["t0"]) / fly["dur"])
        ease = 1.0 - (1.0 - p) ** 3            # ease-out：起步快、落点稳
        ax0, ay0, ax1, ay1 = self._xy(fly["from"])
        bx0, by0, bx1, by1 = self._xy(fly["to"])
        x0 = ax0 + (bx0 - ax0) * ease
        y0 = ay0 + (by0 - ay0) * ease
        x1 = ax1 + (bx1 - ax1) * ease
        y1 = ay1 + (by1 - ay1) * ease
        # 中段略微放大，做出"抬起"的感觉
        base = max(6, int(cell * 0.10))
        lift = 1.0 - 0.14 * (1.0 - abs(ease * 2.0 - 1.0))
        inset = int(base * lift)
        radius = int(cell * 0.16)
        try:
            self.coords(self._fly_shape,
                        *round_rect_points(x0 + inset, y0 + inset,
                                           x1 - inset, y1 - inset, radius))
            self.coords(self._fly_text, (x0 + x1) / 2, (y0 + y1) / 2)
        except tk.TclError:
            self._fly = None
            self._fly_after = None
            return
        if p < 1.0:
            self._fly_after = self.after(16, self._step_fly)
        else:
            self._fly = None
            self._fly_after = None
            self.delete("fly")
            self._flush()                       # 落地后按最终状态重绘

    def _cancel_fly(self) -> None:
        if self._fly_after is not None:
            try:
                self.after_cancel(self._fly_after)
            except Exception:
                pass
            self._fly_after = None
        if self._fly is not None:
            self._fly = None
            try:
                self.delete("fly")
            except tk.TclError:
                pass

    # ---------------- 事件 ----------------
    def _on_click(self, event) -> None:
        if self.on_click is not None:
            self.on_click(self.square_at(event.x, event.y))
