"""比赛模式演示：对方走子 → 我方校验并复制 → 我方算法决策回应。

模拟真实对局：双方各自持有一副棋盘，靠"走法消息"同步。
本脚本把对方做成一个独立会话（红方，先手），我方是另一个会话（蓝方）。
每传一手都做三件事：

    1. 对方在自己棋盘上落子，把走法文本（含 @骰值）发过来
    2. 我方 accept_remote_move → 五层对账 → 复制到本地棋盘
    3. 断言两侧棋盘**逐字节一致**（squares / side / die / 指纹 / 哈希链）

最后整局比对哈希链，任何一手不一致都会立刻定位到具体 ply。

运行：
    python scripts/match_mode_demo.py
    python scripts/match_mode_demo.py --nodes 800 -v
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from einstein_go.board import side_label
from einstein_go.clock import RealTime
from einstein_go.constants import RED
from einstein_go.players import make_player
from einstein_go.session import GameSession
from einstein_go.sync import SyncMode, verify_state_equal


def assert_in_sync(me: GameSession, opp: GameSession, ply: int) -> None:
    bad = verify_state_equal(me.state, opp.state)
    if bad:
        raise SystemExit(f"✗ ply {ply} 两侧状态不一致: {bad}")
    if (me.pos.squares, me.pos.side, me.pos.die) != (opp.pos.squares, opp.pos.side, opp.pos.die):
        raise SystemExit(f"✗ ply {ply} 棋盘逐字节不一致")


def main(seed: int = 7, nodes: int | None = 500, verbose: bool = False) -> int:
    # 开局只依赖出发区摆放（确定性），两侧各自独立的骰子随机流
    opp = GameSession(first_player=RED, seed=seed, time_source=RealTime())
    me = GameSession(first_player=RED, seed=seed + 1, time_source=RealTime())
    assert_in_sync(me, opp, 0)

    my_player = make_player("mcts", seed=seed, node_limit=nodes)
    opp_player = make_player("heuristic", seed=seed + 1)

    print(f"比赛模式演示  我方={side_label(-RED)}(MCTS, nodes={nodes})  "
          f"对方={side_label(RED)}(启发式)  种子={seed}")
    print(f"开局一致性 ✓  开局 zhash={me.pos.zhash:016x}")

    while not me.finished:
        ply = me.ply + 1

        if me.side == RED:
            # ---------- 对方回合：他自己掷骰、自己走，然后把走法发过来 ----------
            die = opp.roll()
            mv = opp_player.choose_move(opp)
            opp.play(mv)
            message = mv.to_compact()            # 形如 "4a1b2@3"，自带骰值
            print(f"\n[ply {ply}] 对方(R) 掷骰 {die} → 发来走法 {message}")
            if verbose:
                print(opp.pos)

            _, report = me.accept_remote_move(message, SyncMode.STRICT)
            print(f"  复制并校验: {'成功' if report.ok else '失败'}")
            if verbose or not report.ok:
                print("  " + report.format().replace("\n", "\n  "))
            if not report.ok:
                return 2
            assert_in_sync(me, opp, ply)
            print(f"  两侧状态一致 ✓  zhash={me.pos.zhash:016x}")
        else:
            # ---------- 我方回合：掷骰 → 我方算法决策 → 把走法发给对方 ----------
            die = me.roll()
            mv = my_player.choose_move(me)
            me.play(mv)
            print(f"\n[ply {ply}] 我方(B) 掷骰 {die} → 决策 {mv.to_compact()}")
            search = getattr(my_player, "last", None)
            if search is not None and search.searched:
                print(f"  MCTS: {search.sims} 次模拟 / {search.elapsed_ms}ms")
                for st in search.top(3):
                    print(f"    {st}")
            if verbose:
                print(me.pos)

            _, rep = opp.accept_remote_move(mv.to_compact(), SyncMode.STRICT)
            if not rep.ok:
                print("  ✗ 对方侧复制失败:\n  " + rep.format().replace("\n", "\n  "))
                return 3
            assert_in_sync(me, opp, ply)
            print(f"  两侧状态一致 ✓  zhash={me.pos.zhash:016x}")

    result = me.result
    print("\n" + "=" * 52)
    print(f"对局结束: {result.describe()}  共 {me.ply} 手")
    print(f"我方 哈希链尾 {me.chain_hash.hex()}")
    print(f"对方 哈希链尾 {opp.chain_hash.hex()}")
    if me.chain_hash != opp.chain_hash:
        print("✗ 整局哈希链不一致")
        return 4
    print("整局哈希链一致 ✓  HASH CHAIN OK")
    return 0


def cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description="爱恩斯坦棋比赛模式演示（复制对方走法）")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--nodes", type=int, default=500)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    return main(args.seed, args.nodes, args.verbose)


if __name__ == "__main__":
    sys.exit(cli())
