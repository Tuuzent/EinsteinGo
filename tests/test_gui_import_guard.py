"""铁律测试：控制器链路绝不允许把 tkinter 拖进依赖链。

本机 PATH 里的 Python（WorkBuddy 内置 3.13）**没有 tkinter**，而 pytest 就跑在它上面。
一旦哪个纯逻辑模块顺手 import 了 tkinter，整套控制器测试会直接崩 —— 这条测试把约束固化。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

GUARD_SNIPPET = """
import sys
import einstein.gui.controller
import einstein.gui.model
import einstein.gui.errors_view
import einstein.gui.thinker
import einstein.gui.record_io
import einstein.gui.logbus
bad = sorted(m for m in sys.modules if m.split('.')[0] in ('tkinter', '_tkinter'))
assert not bad, bad
print('TK-FREE-OK')
"""


def test_controller_chain_is_tk_free():
    proc = subprocess.run(
        [sys.executable, "-c", GUARD_SNIPPET],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "TK-FREE-OK" in proc.stdout


def test_gui_package_init_only_documents():
    text = (ROOT / "einstein" / "gui" / "__init__.py").read_text(encoding="utf-8")
    for forbidden in ("import tkinter", "from .view", "from einstein.gui.view", "import .view"):
        assert forbidden not in text, f"einstein/gui/__init__.py 不允许出现 {forbidden!r}"


def test_view_subpackage_is_separate():
    """视图层单独成包，纯逻辑模块不得反向依赖它。

    只看真正的 import 语句（docstring 里会提到"不 import tkinter"这类说明文字）。
    """
    for name in ("controller.py", "model.py", "errors_view.py", "thinker.py", "record_io.py", "logbus.py"):
        for lineno, line in enumerate(
            (ROOT / "einstein" / "gui" / name).read_text(encoding="utf-8").splitlines(), 1
        ):
            stmt = line.strip()
            if stmt.startswith(("import tkinter", "from tkinter")):
                pytest.fail(f"{name}:{lineno} 引入了 tkinter：{stmt}")
            if stmt.startswith(("from .view", "import .view", "from einstein.gui.view")):
                pytest.fail(f"{name}:{lineno} 反向依赖视图层：{stmt}")
