"""一键跑完整演示对局（等价于 python scripts/demo_game.py）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.demo_game import cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli())
