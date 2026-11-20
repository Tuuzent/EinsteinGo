"""交互式对局循环：双人热座 / 人机 / 机机。

人类输入的校验是**无副作用**的：先在状态副本上跑一遍 apply_remote_move，
只有校验通过才调用 session.play 正式落子（这样重试不会重复扣时）。
"""

from __future__ import annotations

import sys

from ..board import side_label
from ..constants import RED
from ..session import GameSession
from ..sync import SyncMode, apply_remote_move
from . import render as R

COMMANDS = {
    "h": "帮助",
    "help": "帮助",
    "b": "重绘棋盘",
    "board": "重绘棋盘",
    "m": "列出本回合合法走法",
    "moves": "列出本回合合法走法",
    "r": "查看棋谱",
    "record": "查看棋谱",
    "q": "退出",
    "quit": "退出",
}


def _prompt(session, players) -> str | None:
    side = session.side
    human = players.get(side) is None
    print()
    print(f"--- 第 {session.ply + 1} 手 · {side_label(side)}"
          f"{'（人类）' if human else ''} ---")
    print(R.render_board(session))
    die = session.roll()
    print(f"  掷骰: {die}    剩余 红 {R.seconds(session.remaining_ms(RED))} / "
          f"蓝 {R.seconds(session.remaining_ms(-RED))}")
    print(f"  可走: {R.legal_text(session)}")
    return None


def _human_move(session, players):
    while True:
        try:
            raw = input("  走法（如 3c1-d2 或 3c1d2，h 帮助）> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  已中断。")
            raise SystemExit(0) from None
        if not raw:
            continue
        low = raw.lower()
        if low in ("q", "quit"):
            raise SystemExit(0)
        if low in ("h", "help"):
            print("  命令: h 帮助 / b 重绘 / m 合法走法 / r 棋谱 / q 退出")
            continue
        if low in ("b", "board"):
            print(R.render_board(session))
            continue
        if low in ("m", "moves"):
            print("  " + R.legal_text(session, limit=40))
            continue
        if low in ("r", "record"):
            print(R.render_record(session))
            continue
        _, report = apply_remote_move(session.state, raw, SyncMode.LENIENT)
        if not report.ok:
            print(f"  ✗ 非法走法 [{report.code.value if report.code else '?'}] {report.message}")
            continue
        return report.remote_move


def run(session: GameSession, players: dict, verbose: bool = True, echo_search: bool = True) -> GameSession:
    """players: {+1: Player|None, -1: Player|None}，None 表示人类。"""
    while not session.finished:
        side = session.side
        player = players.get(side)
        _prompt(session, players)
        if player is None:
            move = _human_move(session, players)
        else:
            move = player.choose_move(session)
            if echo_search and getattr(player, "last", None) is not None:
                print(R.render_search(player.last))
        session.play(move)
        print(f"  → {move.to_text()}")
    _finish(session)
    return session


def _finish(session: GameSession) -> None:
    print()
    print(R.render_board(session))
    result = session.result
    print(f"  对局结束：{result.describe()}")
    print(f"  共 {session.ply} 手，哈希链尾 {session.chain_hash.hex()[:16]}")


def run_silent(session: GameSession, players: dict) -> GameSession:
    """无输出的机机对局（基准用）。"""
    while not session.finished:
        player = players[session.side]
        session.roll()
        session.play(player.choose_move(session))
    return session


def main(argv=None) -> int:  # pragma: no cover - 由 cli.main 调用
    from .main import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
