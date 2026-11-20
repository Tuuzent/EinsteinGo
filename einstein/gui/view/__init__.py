"""tkinter 视图层。**仅本目录允许 import tkinter**。

纯逻辑（controller / model / errors_view / thinker / record_io / logbus）一律不得反向依赖这里，
否则在没有 tkinter 的解释器上连控制器测试都跑不起来。
"""

from __future__ import annotations
