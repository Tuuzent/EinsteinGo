"""桌面界面入口。

    python run_ui.py              # 打开窗口
    python run_ui.py --self-test  # 只跑控制器，不需要 tkinter（用于排查环境）

DPI 感知必须在 Tk() 之前设置，否则 125%/150% 缩放下整个窗口会被位图拉伸变糊。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def enable_dpi_awareness() -> None:
    """Windows 专用，失败静默（非 Windows / 已设置过都不影响）。"""
    try:
        import ctypes
    except Exception:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # PROCESS_SYSTEM_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _self_test() -> int:
    """不需要 tkinter：验证引擎 + 控制器链路是否正常。"""
    from einstein_go.gui.controller import GameController
    from einstein_go.gui.model import GameSetup

    ctl = GameController(GameSetup(seed=7), async_think=False)
    ctl.new_game()
    view = ctl.view()
    print(f"[self-test] phase={view['phase']} cells={len(view['cells'])} die={view['die']}")
    print(f"[self-test] can={view['can']}")
    ok = view["phase"] == "human_turn" and len(view["cells"]) == 25
    print("[self-test] OK" if ok else "[self-test] FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in args:
        return _self_test()

    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("[EinsteinGo] 当前解释器没有 tkinter，无法打开桌面界面：")
        print("          ", sys.executable)
        print("           请安装 python.org 官方版本并勾选『tcl/tk and IDLE』，")
        print("           或直接双击 start_ui.bat（它会自动挑选合适的解释器）。")
        return 2

    enable_dpi_awareness()
    # MCTS 是纯 Python 计算，会长时间持 GIL；缩短切换间隔让界面更跟手（代价约 3–5%）
    sys.setswitchinterval(0.002)

    from einstein_go.gui.view.app import App

    app = App()
    # 自动化冒烟用：例如 EINSTEIN_UI_AUTOCLOSE_MS=4000 让窗口 4 秒后自己关掉
    import os

    autoclose = os.environ.get("EINSTEIN_UI_AUTOCLOSE_MS", "").strip()
    if autoclose.isdigit():
        app.after(int(autoclose), app.shutdown)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            app.shutdown()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        try:
            import tkinter.messagebox as mb

            mb.showerror("EinsteinGo", "启动失败，详见控制台。")
        except Exception:
            pass
        sys.exit(1)
