"""右侧面板：局面状态、双方时钟、AI 候选条、棋谱。"""

from __future__ import annotations

import tkinter as tk

from . import theme as T
from .widgets import CandidateBars, DiceView, ResultCard, SectionTitle

PHASE_COLOR = {
    "human_turn": T.OK_GREEN,
    "thinking": T.INFO_FG,
    "match_wait": T.WARN_AMBER,
    "game_over": T.TEXT_DIM,
}


class SidePanel(tk.Frame):
    def __init__(self, master, theme: T.Theme) -> None:
        super().__init__(master, bg=T.PANEL_BG)
        self.theme = theme
        self._record_count = -1

        # ---- 结果卡（终局才显示内容）----
        self.result_card = ResultCard(self, theme)
        self._result_shown = False

        # ---- 阶段 + 骰子 ----
        head = tk.Frame(self, bg=T.PANEL_BG)
        head.pack(fill="x", padx=10, pady=(6, 0))
        self.phase_label = tk.Label(head, text="", anchor="w", bg=T.PANEL_BG,
                                    fg=T.TEXT_MAIN, font=theme.font_title)
        self.phase_label.pack(side="left")
        self.dice = DiceView(head, theme)
        self.dice.pack(side="right", pady=(0, 2))

        self.hint_label = tk.Label(self, text="", anchor="w", bg=T.PANEL_BG,
                                   fg=T.TEXT_DIM, font=theme.font_ui_small,
                                   wraplength=theme.px(300), justify="left")
        self.hint_label.pack(fill="x", padx=10)

        # ---- 时钟 ----
        clock = tk.Frame(self, bg=T.CARD_BG, highlightthickness=1,
                         highlightbackground=T.BORDER)
        clock.pack(fill="x", padx=10, pady=(8, 4))
        self.red_clock = tk.Label(clock, text="红 4:00", anchor="w", bg=T.CARD_BG,
                                  fg=T.RED_FILL, font=theme.font_ui_bold)
        self.red_clock.pack(side="left", padx=10, pady=6)
        self.blue_clock = tk.Label(clock, text="蓝 4:00", anchor="e", bg=T.CARD_BG,
                                   fg=T.BLUE_FILL, font=theme.font_ui)
        self.blue_clock.pack(side="right", padx=10, pady=6)

        # ---- 局面信息 ----
        self.info_label = tk.Label(self, text="", anchor="w", bg=T.PANEL_BG,
                                   fg=T.TEXT_DIM, font=theme.font_ui_small,
                                   wraplength=theme.px(300), justify="left")
        self.info_label.pack(fill="x", padx=10, pady=(2, 6))

        # ---- AI ----
        SectionTitle(self, theme, "AI 决策").pack(fill="x", padx=10)
        self.ai_label = tk.Label(self, text="尚无搜索记录", anchor="w", bg=T.PANEL_BG,
                                 fg=T.TEXT_DIM, font=theme.font_ui_small,
                                 wraplength=theme.px(300), justify="left")
        self.ai_label.pack(fill="x", padx=10)
        self.bars = CandidateBars(self, theme)
        self.bars.pack(fill="x", padx=10, pady=(2, 8))

        # ---- 棋谱 ----
        self._record_title = SectionTitle(self, theme, "棋谱")
        self._record_title.pack(fill="x", padx=10)
        wrap = tk.Frame(self, bg=T.PANEL_BG)
        self._record_wrap = wrap
        wrap.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._compact = False
        self.record = tk.Text(wrap, height=6, width=1, bg=T.CARD_BG, fg=T.TEXT_MAIN,
                              font=theme.font_mono, bd=1, relief="flat",
                              highlightthickness=1, highlightbackground=T.BORDER,
                              wrap="none", state="disabled")
        self.record.pack(side="left", fill="both", expand=True)
        bar = tk.Scrollbar(wrap, command=self.record.yview)
        bar.pack(side="right", fill="y")
        self.record.configure(yscrollcommand=bar.set)

    def set_compact(self, compact: bool) -> None:
        """比赛模式下棋盘下方已经有对账面板，右栏收起棋谱，避免两边互相挤压。"""
        if compact == self._compact:
            return
        self._compact = compact
        if compact:
            self._record_title.pack_forget()
            self._record_wrap.pack_forget()
        else:
            self._record_title.pack(fill="x", padx=10)
            self._record_wrap.pack(fill="both", expand=True, padx=10, pady=(2, 10))

    # ---------------- 渲染 ----------------
    def render(self, view: dict) -> None:
        phase = view["phase"]
        self.phase_label.configure(text=view.get("phase_label", ""),
                                   fg=PHASE_COLOR.get(phase, T.TEXT_MAIN))
        self.dice.set_value(view.get("die") or 0)
        self.hint_label.configure(text=_hint(view))
        self.update_clock(view["clock"])
        self.info_label.configure(text=_info(view))
        self._render_result(view.get("result"))
        self._render_ai(view)
        self._render_record(view)

    def _render_result(self, result: dict | None) -> None:
        """没有结果时整块收起，否则会留一个空白框占位。"""
        self.result_card.render(result)
        if result and not self._result_shown:
            self.result_card.pack(fill="x", padx=10, pady=(10, 4), before=self.phase_label.master)
            self._result_shown = True
        elif not result and self._result_shown:
            self.result_card.pack_forget()
            self._result_shown = False

    def update_clock(self, clock: dict) -> None:
        ticking = clock.get("ticking") or 0
        bold, plain = self.theme.font_ui_bold, self.theme.font_ui
        try:
            self.red_clock.configure(text=f"红 {clock['red_text']}",
                                     font=bold if ticking > 0 else plain)
            self.blue_clock.configure(text=f"蓝 {clock['blue_text']}",
                                      font=bold if ticking < 0 else plain)
        except tk.TclError:
            pass

    def _render_ai(self, view: dict) -> None:
        search = view.get("search")
        if search:
            self.ai_label.configure(
                text=(f"{search['reason_text']} · 模拟 {search['sims']} · "
                      f"节点 {search['nodes']} · {search['elapsed_ms']}ms · 深度 {search['depth']}"),
                fg=T.TEXT_DIM,
            )
        else:
            self.ai_label.configure(text="", fg=T.TEXT_DIM)
        self.bars.render(view.get("candidates") or [], search)

    def _render_record(self, view: dict) -> None:
        rows = view.get("record") or []
        if len(rows) == self._record_count:
            return
        self._record_count = len(rows)
        self.record.configure(state="normal")
        self.record.delete("1.0", "end")
        for row in rows:
            self.record.insert("end", row["text"] + "\n")
        self.record.configure(state="disabled")
        self.record.see("end")


def _hint(view: dict) -> str:
    phase = view["phase"]
    if phase == "game_over":
        return ""
    if phase == "thinking":
        return "后台线程搜索中，棋盘暂不可操作"
    if phase == "match_wait":
        if view.get("die"):
            return "点对方的棋子替他走（绿点=可走目标）"
        return "先选对方骰值（1–6），再点对方棋子代走"
    if view.get("needs_roll"):
        return "点『掷骰』开始本回合"
    if view.get("selection"):
        sel = view["selection"]
        return f"已选 {sel['piece']} 号，点绿点走子（红圈=可吃）"
    human = view.get("human_side")
    your_turn = view["side"] == human
    if your_turn:
        return "点自己的棋子，再点高亮目标"
    return ""


def _info(view: dict) -> str:
    side_cn = "红" if view["side"] > 0 else "蓝"
    parts = [f"第 {view['ply']} 手 · 轮到{side_cn}方"]
    cap = view.get("captured") or {}
    red_out = cap.get("red") or []
    blue_out = cap.get("blue") or []
    if red_out:
        parts.append("红方已出局 " + "、".join(str(n) for n in red_out) + " 号")
    if blue_out:
        parts.append("蓝方已出局 " + "、".join(str(n) for n in blue_out) + " 号")
    last = view.get("last_move")
    if last:
        tail = f"，吃掉 {last['captured_text']}" if last.get("captured") else ""
        parts.append(f"上一手 {last['text']}{tail}")
    return "\n".join(parts)
