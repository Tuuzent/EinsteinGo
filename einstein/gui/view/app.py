"""主窗口：工具栏 + 棋盘 + 错误条 + 右侧面板 / 比赛模式面板。

线程纪律：所有控件操作都在主线程（`after` 轮询），控制器负责把后台结果搬回来。
"""

from __future__ import annotations

import random
import tkinter as tk
from tkinter import messagebox, ttk

from ...constants import BLUE, RED
from ..controller import GameController
from ..logbus import DEFAULT_LOG
from ..model import DIFFICULTY_LABEL, DIFFICULTY_ORDER, GameSetup, Mode, Phase
from . import theme as T
from .board_canvas import BoardCanvas
from .match_panel import MatchPanel
from .side_panel import SidePanel
from .widgets import ErrorBar


class App(tk.Tk):
    def __init__(self, controller: GameController | None = None) -> None:
        super().__init__()
        self.theme = T.Theme(self)
        self.title("爱恩斯坦棋 · Einstein würfelt nicht")
        self.geometry(f"{T.WIN_W}x{T.WIN_H}")
        self.minsize(T.MIN_W, T.MIN_H)
        self.configure(bg=T.WINDOW_BG)

        self.ctl = controller or GameController()
        self._alive = True
        self._poll_id: str | None = None
        self._tick_id: str | None = None
        self._last_phase: str | None = None
        self._last_move_key: tuple | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.report_callback_exception = self._on_callback_error

        self.ctl.new_game(self._setup_from_ui())
        self.render(self.ctl.view())
        self._poll_id = self.after(T.POLL_MS, self._poll)
        self._tick_id = self.after(T.TICK_MS, self._tick)
        DEFAULT_LOG.log("界面已就绪")

    # ---------------- 构建 ----------------
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0, minsize=self.theme.px(T.PANEL_WIDTH))
        self.rowconfigure(0, weight=0)   # 工具栏
        self.rowconfigure(1, weight=1)   # 棋盘
        self.rowconfigure(3, weight=0)   # 比赛模式面板（棋盘下方）

        self._build_toolbar()

        self.board = BoardCanvas(self, self.theme, on_click=self._on_board_click)
        self.board.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=(0, 0))

        self.error_bar = ErrorBar(self, self.theme)
        self.error_bar.grid(row=2, column=0, sticky="ew", padx=(12, 6), pady=(4, 10))

        right = tk.Frame(self, bg=T.PANEL_BG, highlightthickness=1,
                         highlightbackground=T.BORDER)
        right.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(6, 12), pady=(0, 10))
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.side = SidePanel(right, self.theme)
        self.side.grid(row=0, column=0, sticky="nsew")

        self.match = MatchPanel(self, self.theme, on_accept=self._on_accept_remote,
                                on_remote_die=self._on_remote_die)
        self._match_visible = False

    def _build_toolbar(self) -> None:
        th = self.theme
        bar = tk.Frame(self, bg=T.WINDOW_BG)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 8))

        def label(text: str) -> None:
            tk.Label(bar, text=text, bg=T.WINDOW_BG, fg=T.TEXT_DIM,
                     font=th.font_ui_small).pack(side="left", padx=(0, 4))

        label("模式")
        self.mode_var = tk.StringVar(value=Mode.PVE.value)
        for value, text in ((Mode.PVE.value, "人机对弈"), (Mode.MATCH.value, "比赛模式")):
            ttk.Radiobutton(bar, text=text, value=value, variable=self.mode_var,
                            command=self._on_mode_change).pack(side="left", padx=(0, 8))

        label("我方执")
        self.side_var = tk.StringVar(value="red")
        for value, text in (("red", "红"), ("blue", "蓝")):
            ttk.Radiobutton(bar, text=text, value=value, variable=self.side_var,
                            command=self._on_new_game).pack(side="left", padx=(0, 6))

        label("难度")
        self.diff_var = tk.StringVar(value=DIFFICULTY_LABEL["normal"])
        combo = ttk.Combobox(bar, textvariable=self.diff_var, width=6, state="readonly",
                             values=[DIFFICULTY_LABEL[k] for k in DIFFICULTY_ORDER])
        combo.pack(side="left", padx=(0, 10))
        combo.bind("<<ComboboxSelected>>", lambda _e: None)

        ttk.Button(bar, text="新局", width=6, command=self._on_new_game).pack(side="left", padx=2)
        self.roll_btn = ttk.Button(bar, text="掷骰", width=6, command=self._on_roll)
        self.roll_btn.pack(side="left", padx=2)
        self.export_btn = ttk.Button(bar, text="导出棋谱", width=9, command=self._on_export)
        self.export_btn.pack(side="left", padx=2)

        self.status_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.status_var, bg=T.WINDOW_BG, fg=T.TEXT_DIM,
                 font=th.font_ui_small).pack(side="right")

    # ---------------- 设置 ----------------
    def _setup_from_ui(self, seed: int | None = None) -> GameSetup:
        label_to_key = {DIFFICULTY_LABEL[k]: k for k in DIFFICULTY_ORDER}
        return GameSetup(
            mode=Mode(self.mode_var.get()),
            human_side=RED if self.side_var.get() == "red" else BLUE,
            difficulty=label_to_key.get(self.diff_var.get(), "normal"),
            seed=random.randrange(1, 1_000_000) if seed is None else seed,
        )

    # ---------------- 渲染 ----------------
    def render(self, view: dict) -> None:
        if not self._alive:
            return
        try:
            self.board.render(view)
            self.side.render(view)
            if view["mode"] == Mode.MATCH.value:
                self._show_match_panel(True)
                self.match.render(view)
            else:
                self._show_match_panel(False)
            self._sync_buttons(view)
            self._last_phase = view["phase"]
            self.status_var.set(f"种子 {self.ctl.setup.seed} · {view['phase_label']}")
            self._animate_move(view)
            if view.get("error"):
                self.error_bar.show(view["error"]["message"], view["error"]["severity"])
        except tk.TclError:
            pass

    def _animate_move(self, view: dict) -> None:
        """只有"出现了新的一手"才播动画，避免重复渲染时反复抖动。"""
        last = view.get("last_move")
        if not last:
            self._last_move_key = None
            return
        side = int(view.get("side") or 0)
        if side == 0:
            return
        key = (view.get("ply"), last["from"], last["to"], last["piece"])
        if key == self._last_move_key:
            return
        self._last_move_key = key
        mover = -side                       # 走完这一手后已换手
        self.board.animate_move(last["from"], last["to"], mover * int(last["piece"]))

    def _show_match_panel(self, visible: bool) -> None:
        if visible == self._match_visible:
            return
        self._match_visible = visible
        self.side.set_compact(visible)
        if visible:
            self.match.grid(row=3, column=0, sticky="nsew", padx=(12, 6), pady=(0, 10))
        else:
            self.match.grid_remove()

    def _sync_buttons(self, view: dict) -> None:
        can = view["can"]
        try:
            self.roll_btn.configure(state="normal" if can["roll"] else "disabled")
            self.export_btn.configure(state="normal" if can["export"] else "disabled")
        except tk.TclError:
            pass

    # ---------------- 事件 ----------------
    def _on_mode_change(self) -> None:
        if self.mode_var.get() == Mode.MATCH.value:
            self.match.prepare()
        self._on_new_game()

    def _on_new_game(self) -> None:
        self.error_bar.hide()
        if self.mode_var.get() == Mode.MATCH.value:
            self.match.prepare()
        result = self.ctl.new_game(self._setup_from_ui())
        self.render(result["view"])

    def _on_roll(self) -> None:
        self._handle(self.ctl.roll_die())

    def _on_export(self) -> None:
        result = self.ctl.export_record()
        self._handle(result)
        if result["ok"]:
            self.error_bar.show(result["message"], "info")
        elif result["extra"].get("path"):
            messagebox.showerror("导出棋谱", result["message"], parent=self)

    def _on_board_click(self, sq: int | None) -> None:
        if not self._alive:
            return
        view = self.ctl.view()
        if view["phase"] in (Phase.THINKING.value, Phase.GAME_OVER.value):
            return
        if sq is None:
            self.render(self.ctl.clear_selection()["view"])
            return
        selection = view.get("selection")
        if selection:
            for target in selection["targets"]:
                if target["dst"] == sq:
                    self._handle(self.ctl.commit_move(selection["piece"], sq))
                    return
        self._handle(self.ctl.select_square(sq))

    def _on_remote_die(self, die) -> None:
        result = self.ctl.remote_roll() if die is None else self.ctl.declare_remote_die(die)
        self._handle(result)

    def _on_accept_remote(self, text: str) -> None:
        result = self.ctl.accept_remote(text)
        self._handle(result)
        report = result["extra"].get("report")
        if report is not None:
            self.match.flash_result(result["ok"], report.get("message") or "")
        self.render(result["view"])

    def _handle(self, result: dict) -> None:
        self.render(result["view"])
        message = result.get("message") or ""
        severity = result.get("severity") or "none"
        if message and severity in ("info", "warn", "error"):
            self.error_bar.show(message, severity)

    # ---------------- 轮询 ----------------
    def _poll(self) -> None:
        if not self._alive:
            return
        try:
            events = self.ctl.poll()
            if events:
                self.render(self.ctl.view())
        except tk.TclError:
            return
        except Exception as exc:                       # pragma: no cover - 兜底防崩
            DEFAULT_LOG.log(f"轮询异常：{exc}", level="error")
        self._poll_id = self.after(T.POLL_MS, self._poll)

    def _tick(self) -> None:
        if not self._alive:
            return
        try:
            before = self.ctl.phase
            result = self.ctl.tick()
            if self.ctl.phase is not before or not result["ok"]:
                self.render(result["view"])
            else:
                self.side.update_clock(self.ctl.clock_view())
        except tk.TclError:
            return
        except Exception as exc:                       # pragma: no cover
            DEFAULT_LOG.log(f"计时异常：{exc}", level="error")
        self._tick_id = self.after(T.TICK_MS, self._tick)

    # ---------------- 收尾 ----------------
    def _on_callback_error(self, exc_type, exc_value, exc_tb) -> None:  # pragma: no cover
        DEFAULT_LOG.log(f"界面回调异常 {exc_type.__name__}: {exc_value}", level="error")
        try:
            self.error_bar.show(f"界面回调异常：{exc_value}", "error")
        except Exception:
            pass

    def shutdown(self) -> None:
        if not self._alive:
            return
        self._alive = False
        for attr in ("_poll_id", "_tick_id"):
            aid = getattr(self, attr, None)
            if aid is not None:
                try:
                    self.after_cancel(aid)
                except Exception:
                    pass
                setattr(self, attr, None)
        try:
            self.ctl.shutdown()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
