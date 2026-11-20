"""比赛模式面板：粘贴对方走法 → 六层对账 → 复制我方走法。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as T
from .widgets import SectionTitle

STATE_TEXT = {"ok": "通过", "fail": "失败", "skip": "跳过"}


class MatchPanel(tk.Frame):
    def __init__(self, master, theme: T.Theme, on_accept, on_remote_die=None) -> None:
        super().__init__(master, bg=T.PANEL_BG)
        self.theme = theme
        self._on_accept = on_accept
        self._on_remote_die = on_remote_die

        SectionTitle(self, theme, "比赛模式 · 复制对方走法").pack(fill="x", padx=10, pady=(4, 2))

        row = tk.Frame(self, bg=T.PANEL_BG)
        row.pack(fill="x", padx=10)
        self.var = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.var, font=theme.font_mono)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _e: self._accept())
        ttk.Button(row, text="粘贴", width=5, command=self._paste).pack(side="left", padx=(4, 0))
        self.accept_btn = ttk.Button(row, text="校验", width=6, command=self._accept)
        self.accept_btn.pack(side="left", padx=(4, 0))

        # ---- 对方骰值：定好点数才能直接在棋盘上替对方走 ----
        die_row = tk.Frame(self, bg=T.PANEL_BG)
        die_row.pack(fill="x", padx=10, pady=(4, 0))
        tk.Label(die_row, text="对方骰值", bg=T.PANEL_BG, fg=T.TEXT_DIM,
                 font=theme.font_ui_small).pack(side="left")
        self._die_buttons: list[ttk.Button] = []
        for n in range(1, 7):
            btn = ttk.Button(die_row, text=str(n), width=2,
                             command=lambda n=n: self._pick_die(n))
            btn.pack(side="left", padx=(2, 0))
            self._die_buttons.append(btn)
        self._random_btn = ttk.Button(die_row, text="随机", width=4, command=self._pick_random)
        self._random_btn.pack(side="left", padx=(6, 0))
        self.die_state = tk.Label(die_row, text="", bg=T.PANEL_BG, fg=T.TEXT_DIM,
                                  font=theme.font_ui_small)
        self.die_state.pack(side="right")

        self.status = tk.Label(self, text="等待对方走法", anchor="w", bg=T.PANEL_BG,
                               fg=T.TEXT_DIM, font=theme.font_ui_small,
                               wraplength=theme.px(300), justify="left")
        self.status.pack(fill="x", padx=10, pady=(2, 4))

        # ---- 六层对账 ----
        layers_box = tk.Frame(self, bg=T.CARD_BG, highlightthickness=1,
                              highlightbackground=T.BORDER)
        layers_box.pack(fill="x", padx=10)
        self._rows: list[dict] = []
        for _ in range(6):
            line = tk.Frame(layers_box, bg=T.CARD_BG)
            line.pack(fill="x", padx=8, pady=1)
            dot = tk.Label(line, text="●", bg=T.CARD_BG, fg=T.TEXT_DIM,
                           font=theme.font_ui_small)
            dot.pack(side="left")
            title = tk.Label(line, text="", anchor="w", bg=T.CARD_BG, fg=T.TEXT_DIM,
                             font=theme.font_ui_small)
            title.pack(side="left", padx=(4, 0))
            state = tk.Label(line, text="", anchor="e", bg=T.CARD_BG, fg=T.TEXT_DIM,
                             font=theme.font_ui_small)
            state.pack(side="right")
            self._rows.append({"dot": dot, "title": title, "state": state})

        # ---- 详情 ----
        self.detail = tk.Text(self, height=3, width=1, bg=T.CARD_BG, fg=T.TEXT_MAIN,
                              font=theme.font_mono_small, bd=0, wrap="word",
                              highlightthickness=1, highlightbackground=T.BORDER,
                              state="disabled")
        self.detail.pack(fill="x", padx=10, pady=(4, 4))
        self.detail.tag_configure("ok", foreground=T.OK_GREEN)
        self.detail.tag_configure("fail", foreground=T.ERR_RED)
        self.detail.tag_configure("skip", foreground=T.TEXT_DIM)
        self.detail.tag_configure("head", foreground=T.TEXT_MAIN)

        # ---- 我方走法 ----
        send = tk.Frame(self, bg=T.PANEL_BG)
        send.pack(fill="x", padx=10, pady=(0, 10))
        tk.Label(send, text="我方走法", bg=T.PANEL_BG, fg=T.TEXT_DIM,
                 font=theme.font_ui_small).pack(side="left")
        self.send_label = tk.Label(send, text="—", bg=T.PANEL_BG, fg=T.TEXT_MAIN,
                                   font=theme.font_mono)
        self.send_label.pack(side="left", padx=6)
        ttk.Button(send, text="复制", width=5,
                   command=self._copy_send).pack(side="right")
        self._send_text = ""

    # ---------------- 动作 ----------------
    def _pick_die(self, die: int) -> None:
        if self._on_remote_die is not None:
            self._on_remote_die(die)

    def _pick_random(self) -> None:
        if self._on_remote_die is not None:
            self._on_remote_die(None)

    def _accept(self) -> None:
        text = self.var.get().strip()
        if not text:
            return
        self._on_accept(text)

    def _paste(self) -> None:
        try:
            text = self.clipboard_get()
        except Exception:
            return
        self.var.set(text.strip())
        self.entry.focus_set()

    def _copy_send(self) -> None:
        if not self._send_text:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._send_text)
            self.status.configure(text=f"已复制我方走法 {self._send_text}", fg=T.OK_GREEN)
        except tk.TclError:
            pass

    def prepare(self, text: str = "") -> None:
        """新一局 / 切到比赛模式时调用。"""
        self.var.set(text)
        self._render_report(None)
        self.send_label.configure(text="—")
        self._send_text = ""
        self.status.configure(text="等待对方走法", fg=T.TEXT_DIM)
        self.die_state.configure(text="")

    # ---------------- 渲染 ----------------
    def render(self, view: dict) -> None:
        match = view.get("match") or {}
        can = bool(match.get("can_accept"))
        try:
            self.accept_btn.configure(state="normal" if can else "disabled")
            self.entry.configure(state="normal" if can else "disabled")
        except tk.TclError:
            return
        can_die = bool((view.get("can") or {}).get("remote_die"))
        for btn in self._die_buttons:
            btn.configure(state="normal" if can_die else "disabled")
        self._random_btn.configure(state="normal" if can_die else "disabled")
        die = int(match.get("remote_die") or 0)
        if can_die and die == 0:
            self.die_state.configure(text="未设定 · 先选点数", fg=T.WARN_AMBER)
        elif can_die:
            self.die_state.configure(text=f"当前 {die} · 可直接点棋盘代走", fg=T.OK_GREEN)
        else:
            self.die_state.configure(text="", fg=T.TEXT_DIM)

        send_text = match.get("send_text") or ""
        self._send_text = send_text
        self.send_label.configure(text=send_text or "—")
        self._render_report(match.get("report"))
        if can and self.status.cget("text").startswith("已复制"):
            pass

    def _render_report(self, report: dict | None) -> None:
        layers = (report or {}).get("layers") or []
        for idx, row in enumerate(self._rows):
            if idx >= len(layers):
                row["title"].configure(text="等待校验")
                row["state"].configure(text="")
                row["dot"].configure(fg=T.TEXT_DIM)
                continue
            layer = layers[idx]
            state = layer["state"]
            color = {"ok": T.OK_GREEN, "fail": T.ERR_RED}.get(state, T.TEXT_DIM)
            row["title"].configure(text=f"{layer['layer']}  {layer['title']}")
            row["state"].configure(text=STATE_TEXT.get(state, state), fg=color)
            row["dot"].configure(fg=color)

        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if report is None:
            self.detail.insert("end", "把对手的走法粘进上方输入框，例如 4a1b2@3\n"
                                      "（带 @骰值 时连骰子一起校验；不带也能走，起点与骰值会从本地反查）")
        else:
            head = f"对账 {'通过' if report['ok'] else '失败'}"
            if report.get("code"):
                head += f" · {report['code']}"
            self.detail.insert("end", head + "\n", "ok" if report["ok"] else "fail")
            if report.get("move"):
                self.detail.insert("end", f"走法 {report['move']}\n", "head")
            if report.get("hash_before"):
                tail = report.get("chain_tail") or ""
                self.detail.insert("end",
                                   f"哈希 {report['hash_before']} → {report.get('hash_after') or '—'}"
                                   f"  链尾 {tail}\n", "head")
            for layer in layers:
                if layer["state"] == "skip":
                    continue
                self.detail.insert("end", f"\n[{layer['layer']}] {layer['title']}\n", "head")
                for item in layer["items"]:
                    tag = "ok" if item["ok"] else "fail"
                    mark = "✓" if item["ok"] else "✗"
                    self.detail.insert("end", f"  {mark} {item['name']}：{item['detail']}\n", tag)
                if layer.get("note"):
                    self.detail.insert("end", f"    {layer['note']}\n",
                                       "fail" if layer["state"] == "fail" else "skip")
        self.detail.configure(state="disabled")

    def flash_result(self, ok: bool, message: str) -> None:
        self.status.configure(text=message, fg=T.OK_GREEN if ok else T.ERR_RED)
        if ok:
            self.var.set("")
