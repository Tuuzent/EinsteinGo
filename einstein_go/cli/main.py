"""命令行入口。

    python -m einstein_go.cli play  --red human --blue mcts --nodes 800
    python -m einstein_go.cli play  --red human --blue human          # 双人热座
    python -m einstein_go.cli play  --red mcts  --blue heuristic
    python -m einstein_go.cli match --a mcts --b heuristic --games 7
    python -m einstein_go.cli replay 棋谱.jsonl
    python -m einstein_go.cli demo
"""

from __future__ import annotations

import argparse
import sys

from ..clock import RealTime
from ..constants import RED
from ..match import Match, make_record
from ..players import make_player, play_out
from ..session import GameSession, rebuild_from_record
from ..sync import replay as replay_record
from ..protocol import read_jsonl
from . import render as R
from . import repl

SPEC_HELP = "human / random / heuristic / mcts[:节点数]"


def _build_players(args) -> dict:
    seed = args.seed
    players = {}
    for side, spec in ((RED, args.red), (-RED, args.blue)):
        if spec == "human":
            players[side] = None
        else:
            players[side] = make_player(spec, seed=seed, node_limit=args.nodes,
                                        think_ms=args.think_ms)
    return players


def cmd_play(args) -> int:
    session = GameSession(
        first_player=RED,
        budget_ms=int(args.budget * 1000),
        seed=args.seed,
        time_source=RealTime(),
    )
    players = _build_players(args)
    print(f"爱恩斯坦棋  红={args.red}  蓝={args.blue}  种子={args.seed}  "
          f"每方 {args.budget:.0f}s")
    repl.run(session, players)
    return 0


def cmd_match(args) -> int:
    def runner(game_no: int, first: str):
        a = make_player(args.a, seed=args.seed + game_no, node_limit=args.nodes,
                        think_ms=args.think_ms)
        b = make_player(args.b, seed=args.seed + 1000 + game_no, node_limit=args.nodes,
                        think_ms=args.think_ms)
        red, blue = (a, b) if first == "A" else (b, a)
        session = GameSession(first_player=RED, budget_ms=int(args.budget * 1000),
                              seed=args.seed + game_no, time_source=RealTime())
        print(f"\n=== 第 {game_no} 盘（先手 {first} = 红方） ===")
        play_out(session, {RED: red, -RED: blue})
        print(f"  {session.result.describe()}  共 {session.ply} 手")
        return make_record(game_no, first, session.result, session.ply)

    result = Match(runner, max_games=args.games).play()
    print("\n" + "=" * 46)
    for rec in result.rounds:
        print("  " + rec.describe())
    print("  " + result.summary())
    return 0


def cmd_replay(args) -> int:
    rows = read_jsonl(args.path)
    final = replay_record(rows)
    session = rebuild_from_record(rows)
    print(R.render_board(session))
    print(f"\n  重放 {session.ply} 手  结果: "
          f"{session.result.describe() if session.result else '未终局'}")
    print(f"  哈希链校验通过，链尾 {final.chain_hash.hex()}")
    if args.verbose:
        print(R.render_record(session))
    return 0


def cmd_demo(args) -> int:
    from scripts.demo_game import main as demo_main

    return demo_main(seed=args.seed, nodes=args.nodes, think_ms=args.think_ms)


def cmd_bench(args) -> int:
    from scripts.bench_matrix import main as bench_main

    return bench_main(games=args.games, nodes=args.nodes, seed=args.seed)


def cmd_remote(args) -> int:
    from scripts.match_mode_demo import main as remote_main

    return remote_main(seed=args.seed, nodes=args.nodes, verbose=args.verbose)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="einstein-go", description="EinsteinGo · 爱恩斯坦棋（Einstein würfelt nicht）博弈引擎")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--seed", type=int, default=7)
        sp.add_argument("--budget", type=float, default=240.0, help="每方时间（秒），规则为 240")
        sp.add_argument("--nodes", type=int, default=None, help="MCTS 节点上限（用于快速实验）")
        sp.add_argument("--think-ms", type=int, default=None, help="MCTS 单步时间上限")

    sp = sub.add_parser("play", help="下一局（人类/机机混合）")
    sp.add_argument("--red", default="human", help=SPEC_HELP)
    sp.add_argument("--blue", default="mcts", help=SPEC_HELP)
    common(sp)
    sp.set_defaults(func=cmd_play)

    sp = sub.add_parser("match", help="7 盘 4 胜的轮次")
    sp.add_argument("--a", default="mcts", help=SPEC_HELP)
    sp.add_argument("--b", default="heuristic", help=SPEC_HELP)
    sp.add_argument("--games", type=int, default=7, choices=list(range(1, 8)))
    common(sp)
    sp.set_defaults(func=cmd_match)

    sp = sub.add_parser("replay", help="重放棋谱并校验哈希链")
    sp.add_argument("path")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_replay, seed=7, budget=240.0, nodes=None, think_ms=None)

    sp = sub.add_parser("demo", help="完整演示对局（含逐步打印与哈希链校验）")
    common(sp)
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("bench", help="自对弈基准矩阵")
    sp.add_argument("--games", type=int, default=50)
    sp.add_argument("--nodes", type=int, default=800)
    sp.add_argument("--seed", type=int, default=7)
    sp.set_defaults(func=cmd_bench, budget=240.0, think_ms=None)

    sp = sub.add_parser("remote", help="比赛模式：复制对方走法 + 我方算法决策")
    sp.add_argument("--seed", type=int, default=7)
    sp.add_argument("--nodes", type=int, default=500)
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_remote, budget=240.0, think_ms=None)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:  # pragma: no cover
        print("\n已取消。")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
