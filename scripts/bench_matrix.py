"""自对弈基准矩阵：胜负率 / 平均手数 / 每步耗时 / 非法走法次数。

用 VirtualTime + node_limit，所以**不 sleep**，几十局秒级跑完。
通过门槛（验收线）：
    illegal == 0
    mcts vs random    胜率 >= 0.90
    mcts vs heuristic 胜率 >= 0.60
    平均每步 <= 1000 ms
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from einstein_go.clock import VirtualTime
from einstein_go.constants import RED
from einstein_go.players import make_player
from einstein_go.session import GameSession


@dataclass
class Row:
    label: str
    games: int
    wins_a: int
    avg_plies: float
    avg_ms: float
    max_ms: float
    illegal: int
    timeouts: int

    @property
    def win_rate(self) -> float:
        return self.wins_a / self.games if self.games else 0.0

    def format(self) -> str:
        return (f"{self.label:<22} {self.games:>5} {self.win_rate:>9.2f} "
                f"{self.avg_plies:>9.1f} {self.avg_ms:>9.0f} {self.max_ms:>7.0f} "
                f"{self.illegal:>8} {self.timeouts:>9}")


HEADER = (f"{'matrix':<22} {'games':>5} {'win_rate':>9} {'avg_plies':>9} "
          f"{'avg_ms':>9} {'max_ms':>7} {'illegal':>8} {'timeouts':>9}")


def run_matchup(spec_a: str, spec_b: str, games: int, nodes: int, seed: int) -> Row:
    wins_a = 0
    plies: list[int] = []
    per_move_ms: list[float] = []
    illegal = 0
    timeouts = 0

    for g in range(games):
        a_is_red = g % 2 == 0
        a = make_player(spec_a, seed=seed + g, node_limit=nodes)
        b = make_player(spec_b, seed=seed + 5000 + g, node_limit=nodes)
        session = GameSession(first_player=RED, seed=seed + g, time_source=VirtualTime())
        players = {RED: (a if a_is_red else b), -RED: (b if a_is_red else a)}
        try:
            while not session.finished:
                side = session.side
                session.roll()
                player = players[side]
                t0 = time.monotonic()
                move = player.choose_move(session)
                per_move_ms.append((time.monotonic() - t0) * 1000.0)
                session.play(move)
        except Exception as exc:  # 非法走法 / 引擎异常都算失败
            illegal += 1
            print(f"  [fail] game {g}: {type(exc).__name__}: {exc}")
            continue

        if session.result.reason.value == "timeout":
            timeouts += 1
        plies.append(session.ply)
        winner_is_a = (session.result.winner == RED) == a_is_red
        if winner_is_a:
            wins_a += 1

    label = f"{spec_a} vs {spec_b}"
    return Row(
        label=label,
        games=games,
        wins_a=wins_a,
        avg_plies=statistics.fmean(plies) if plies else 0.0,
        avg_ms=statistics.fmean(per_move_ms) if per_move_ms else 0.0,
        max_ms=max(per_move_ms) if per_move_ms else 0.0,
        illegal=illegal,
        timeouts=timeouts,
    )


def main(games: int = 30, nodes: int = 600, seed: int = 7) -> int:
    matchups = [
        ("random", "random"),
        ("heuristic", "random"),
        ("mcts", "random"),
        ("mcts", "heuristic"),
        ("heuristic", "heuristic"),
    ]
    print(HEADER)
    rows = []
    for a, b in matchups:
        row = run_matchup(a, b, games, nodes, seed)
        rows.append(row)
        print(row.format())
        sys.stdout.flush()

    print()
    checks = []
    for row in rows:
        checks.append((f"{row.label} illegal==0", row.illegal == 0, row.illegal))
        checks.append((f"{row.label} avg_ms<=1000", row.avg_ms <= 1000, round(row.avg_ms)))
    for row in rows:
        if row.label == "mcts vs random":
            checks.append(("mcts vs random 胜率>=0.90", row.win_rate >= 0.90, round(row.win_rate, 3)))
        if row.label == "mcts vs heuristic":
            checks.append(("mcts vs heuristic 胜率>=0.60", row.win_rate >= 0.60, round(row.win_rate, 3)))
        if row.label.startswith("mcts"):
            checks.append((f"{row.label} 平均手数 15..50", 15 <= row.avg_plies <= 50, round(row.avg_plies, 1)))

    ok = True
    for name, passed, value in checks:
        flag = "PASS" if passed else "FAIL"
        print(f"  [{flag}] {name}  实际={value}")
        ok = ok and passed
    print("\n基准结论:", "全部通过" if ok else "存在未达标项")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="爱恩斯坦棋自对弈基准")
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--nodes", type=int, default=600)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    sys.exit(main(args.games, args.nodes, args.seed))
