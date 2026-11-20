"""日志总线：控制台 + 内存环形缓冲 + 可选文件。

GUI 里不裸 print —— 一是要同时喂给界面上的"日志"面板，二是 cp936 控制台在遇到
✓/✗/→ 这类字符时会抛 UnicodeEncodeError 把整个进程带崩。

本模块不 import tkinter：worker 线程往这里写是安全的，界面面板在主线程读 `lines()`。
"""

from __future__ import annotations

import sys
import time
from collections import deque
from pathlib import Path

DEFAULT_CAPACITY = 400


class LogBus:
    def __init__(self, capacity: int = DEFAULT_CAPACITY, echo: bool = True,
                 path: str | Path | None = None) -> None:
        self._lines: deque[str] = deque(maxlen=capacity)
        self._echo = echo
        self._path = Path(path) if path else None
        self._file_error_reported = False

    # ---------------- 写 ----------------
    def log(self, message: str, *, level: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {level:<5} {message}"
        self._lines.append(line)
        if self._echo:
            self._print(line)
        if self._path is not None:
            self._append_file(line)

    def _print(self, line: str) -> None:
        stream = sys.stdout
        if stream is None:          # pythonw 或控制台被关掉
            return
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            try:
                print(line.encode("ascii", "replace").decode("ascii"), flush=True)
            except Exception:
                pass
        except Exception:
            pass

    def _append_file(self, line: str) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            if not self._file_error_reported:
                self._file_error_reported = True
                self._print(f"[warn ] 日志文件写入失败：{self._path}")

    # ---------------- 读 ----------------
    def lines(self, limit: int | None = None) -> list[str]:
        items = list(self._lines)
        return items if limit is None else items[-limit:]

    def text(self, limit: int | None = None) -> str:
        return "\n".join(self.lines(limit))

    def clear(self) -> None:
        self._lines.clear()

    def __len__(self) -> int:
        return len(self._lines)


DEFAULT_LOG = LogBus()
