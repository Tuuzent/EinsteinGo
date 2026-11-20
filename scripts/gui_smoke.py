"""GUI 冒烟测试（不依赖 pytest）。

本机有两套解释器：
    python   → WorkBuddy 内置，**有 pytest、无 tkinter**
    py -3    → 系统安装版，**有 tkinter、无 pytest**

所以控制器用 `python -m pytest` 跑，界面用本脚本跑：
    py -3 scripts/gui_smoke.py

没有桌面会话（Windows 服务 / Session 0）时抛 TclError，脚本降级为 SKIP 并返回 0 ——
不假装通过，也不阻塞。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("SKIP: 当前解释器没有 tkinter")
        return 0

    from einstein.constants import parse_sq
    from einstein.gui.view.app import App

    try:
        app = App()
    except tk.TclError as exc:
        print("SKIP: 没有可用的图形会话：", exc)
        return 0

    try:
        app.update_idletasks()
        canvas = app.board
        total = len(canvas.find_all())
        pieces = len(canvas.find_withtag("piece"))
        bg = len(canvas.find_withtag("bg"))
        assert total >= 60, f"canvas item 太少：{total}"
        assert pieces >= 20, f"棋子没画出来：{pieces}"
        assert bg >= 30, f"底板没画出来：{bg}"

        ctl = app.ctl
        view = ctl.view()
        playable = [c for c in view["cells"] if c["playable"]]
        if playable:
            ctl.select_square(playable[0]["i"])
            app.render(ctl.view())
            app.update_idletasks()
            hl = len(canvas.find_withtag("hl"))
            assert hl >= 1, "选中后没有高亮层"

        # 行棋动画：手动触发一帧，确认 fly 层建出了棋子块 + 数字
        canvas.animate_move(parse_sq("a1"), parse_sq("b1"), 1, duration_ms=800)
        app.update_idletasks()
        app.update()
        fly = len(canvas.find_withtag("fly"))
        assert fly == 2, f"飞行动画图元数不对：{fly}"
        canvas._cancel_fly()
        canvas._flush()

        # 骰子：每个点数必须画对 pip 数
        dice = app.side.dice
        for value in range(1, 7):
            dice.set_value(value, animate=False)
            pips = sum(1 for i in dice.find_all() if dice.type(i) == "oval")
            assert pips == value, f"骰子 {value} 画了 {pips} 个点"

        print(f"GUI SMOKE OK  items={total} pieces={pieces} bg={bg} "
              f"hl={hl if playable else 0} fly={fly} dice_ok=6")
        return 0
    finally:
        app.shutdown()


if __name__ == "__main__":
    sys.exit(main())
