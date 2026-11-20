"""棋谱导出：复用引擎的 jsonl 格式，并在导出后立刻重放自检哈希链。

自检很值：一手棋谱写坏（比如时间戳/编码问题）会在导出的当下就暴露，
而不是等对手拿去重放时才发现。
"""

from __future__ import annotations

import time
from pathlib import Path

from ..protocol import read_jsonl, write_jsonl
from ..sync import replay, verify_state_equal

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_record_path(seed: int = 0, output_dir: str | Path | None = None,
                        now: float | None = None) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
    base = Path(output_dir) if output_dir else PROJECT_ROOT / "output"
    return base / f"gui_record_{stamp}_seed{seed}.jsonl"


def export_record(session, path: str | Path | None = None, *, verify: bool = True) -> dict:
    """把 session.record() 写成 jsonl；返回 {ok, path, rows, verified, message}。"""
    if session is None:
        return {"ok": False, "path": None, "rows": 0, "verified": False,
                "message": "还没有对局，无法导出"}
    rows = session.record()
    if len(rows) <= 1:
        return {"ok": False, "path": None, "rows": 0, "verified": False,
                "message": "还没有走过任何一手，无法导出"}

    target = Path(path) if path else default_record_path(getattr(session, "seed", 0))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(target, rows)
    except OSError as exc:
        return {"ok": False, "path": str(target), "rows": 0, "verified": False,
                "message": f"写入失败：{exc}"}

    if not verify:
        return {"ok": True, "path": str(target), "rows": len(rows) - 1, "verified": False,
                "message": f"已导出 {len(rows) - 1} 手到 {target.name}"}

    try:
        replayed = replay(read_jsonl(target))
    except Exception as exc:                      # ReplayError / OSError 都算失败
        return {"ok": False, "path": str(target), "rows": len(rows) - 1, "verified": False,
                "message": f"导出后自检失败：{exc}"}

    # 棋谱只记录"走法"，不含下一回合刚掷出的骰值；比对前把待走骰值归零，
    # 否则 live 侧 die=3、replay 侧 die=0，zhash 必然对不上。
    live = session.state.with_pos(session.pos.with_die(0))
    bad = verify_state_equal(live, replayed)
    if bad:
        return {"ok": False, "path": str(target), "rows": len(rows) - 1, "verified": False,
                "message": f"导出后自检不一致：{bad}"}

    return {"ok": True, "path": str(target), "rows": len(rows) - 1, "verified": True,
            "message": f"已导出 {len(rows) - 1} 手，哈希链自检通过 · {target.name}"}
