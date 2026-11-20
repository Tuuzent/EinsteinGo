"""终端渲染：棋盘 + 一行状态摘要。"""

from __future__ import annotations

from ..board import render_squares, side_label
from ..constants import RED, parse_sq, sq_name


def seconds(ms: int) -> str:
    return f"{ms / 1000:.1f}s"


def render_board(session, indent: str = "  ") -> str:
    return render_squares(session.pos.squares, indent)


def status_line(session) -> str:
    side = session.side
    die = session.die
    die_txt = str(die) if die else "-"
    return (
        f"ply {session.ply:>3}  {side_label(side)}  骰子: {die_txt}  "
        f"红 {seconds(session.remaining_ms(RED))} / 蓝 {seconds(session.remaining_ms(-RED))}  "
        f"zhash {session.pos.zhash:016x}"
    )


def legal_text(session, limit: int = 12) -> str:
    try:
        moves = session.legal_moves()
    except Exception:  # 未掷骰时不报错，只提示
        return "（尚未掷骰）"
    if not moves:
        return "（无合法走法）"
    shown = [m.to_text() for m in moves[:limit]]
    more = f" …共 {len(moves)} 种" if len(moves) > limit else ""
    return "  ".join(shown) + more


def render(session, indent: str = "  ") -> str:
    return "\n".join([render_board(session, indent), "  " + status_line(session)])


def piece_positions(session) -> str:
    parts = []
    for i, code in enumerate(session.pos.squares):
        if code:
            parts.append(f"{sq_name(i)}={'R' if code > 0 else 'B'}{abs(code)}")
    return " ".join(parts)


def render_search(result) -> str:
    if result is None:
        return ""
    head = (f"  AI: {result.reason} 节点={result.nodes} 模拟={result.sims} "
            f"{result.elapsed_ms}ms")
    if not result.root_stats:
        return head
    lines = [head]
    for st in result.top(3):
        lines.append(f"     {st.move.to_text()}  n={st.visits}  q={st.q:+.3f}")
    return "\n".join(lines)


def render_record(session, limit: int | None = None) -> str:
    from ..move import Move
    from ..protocol import format_record_line

    rows = session.record()[1:]
    rows = rows if limit is None else rows[-limit:]
    lines = []
    for r in rows:
        mv = Move(piece=r["piece"], src=parse_sq(r["src"]), dst=parse_sq(r["dst"]),
                  die=r["die"], captured=r["captured"])
        side = 1 if r["side"] == "R" else -1
        lines.append(format_record_line(r["ply"], side, mv))
    return "\n".join("  " + line for line in lines)
