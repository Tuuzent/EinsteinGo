"""测试对局流程：完整跑一局，逐步打印棋盘/骰值/走法/状态哈希，收尾校验整局哈希链。

运行：
    python scripts/demo_game.py
    python run_demo.py --seed 7 --nodes 1200
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):  # 允许直接 python scripts/demo_game.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from einstein_go.board import render_squares
from einstein_go.clock import RealTime
from einstein_go.constants import RED
from einstein_go.errors import EngineError
from einstein_go.players import make_player
from einstein_go.session import GameSession
from einstein_go.sync import replay, verify_state_equal


def main(seed: int = 7, nodes: int | None = 800, think_ms: int | None = None,
         red: str = "mcts", blue: str = "heuristic", verbose: bool = True) -> int:
    session = GameSession(first_player=RED, seed=seed, time_source=RealTime())
    players = {
        RED: make_player(red, seed=seed, node_limit=nodes, think_ms=think_ms),
        -RED: make_player(blue, seed=seed + 1, node_limit=nodes, think_ms=think_ms),
    }

    if verbose:
        print("=" * 52)
        print(f"爱恩斯坦棋演示对局  种子={seed}  红={red}  蓝={blue}")
        print("=" * 52)

    while not session.finished:
        side = session.side
        if verbose:
            print()
            print(render_squares(session.pos.squares))
        die = session.roll()
        if verbose:
            print(f"[ply {session.ply + 1}] side={'R' if side > 0 else 'B'} die={die}  "
                  f"clock=R{session.remaining_ms(RED)}/B{session.remaining_ms(-RED)}")
        player = players[side]
        move = player.choose_move(session)
        session.play(move)
        if verbose:
            search = getattr(player, "last", None)
            extra = f"  ({search.sims} sims)" if search is not None and search.searched else ""
            print(f"  move {move.to_compact()}  hash={session.pos.zhash:016x}  "
                  f"chain={session.chain_hash.hex()[:12]}{extra}")

    result = session.result
    print()
    print(render_squares(session.pos.squares))
    print(f"RESULT winner={'R' if result.winner > 0 else 'B'} "
          f"reason={result.reason.value} plies={session.ply}")

    # ---- 整局重放 + 哈希链校验 ----
    rows = session.record()
    final = replay(rows)
    bad = verify_state_equal(session.state, final)
    if bad:
        print(f"HASH CHAIN FAILED: {bad}")
        return 1
    print(f"HASH CHAIN OK  链尾 {final.chain_hash.hex()}")

    out = Path(__file__).resolve().parent.parent / "output"
    out.mkdir(exist_ok=True)
    path = out / f"demo_seed{seed}.jsonl"
    from einstein_go.protocol import write_jsonl

    write_jsonl(path, rows)
    print(f"棋谱已写入 {path}")
    return 0


def cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description="爱恩斯坦棋演示对局")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--nodes", type=int, default=800)
    ap.add_argument("--think-ms", type=int, default=None)
    ap.add_argument("--red", default="mcts")
    ap.add_argument("--blue", default="heuristic")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)
    try:
        return main(args.seed, args.nodes, args.think_ms, args.red, args.blue,
                    verbose=not args.quiet)
    except EngineError as exc:  # pragma: no cover
        print(f"引擎错误: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(cli())
