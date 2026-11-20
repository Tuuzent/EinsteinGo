"""桌面界面子包。

铁律：本文件**只允许**写 docstring。
任何对 `view/*` 的 import 都会把 tkinter 拖进依赖链，导致在**没有 tkinter 的解释器**上
（例如本机 PATH 里的那个 WorkBuddy 内置 Python）连 `import einstein_go.gui.controller` 都失败，
pytest 直接崩。这条约束由 tests/test_gui_import_guard.py 固化。
"""

from __future__ import annotations
