"""决策器：把「算一手」抽象成一个可替换对象，便于无线程测试。

为什么不用 GameSession + MCTSPlayer：`MCTSPlayer.choose_move(session)` 会读 `session.legal_moves()`
和 `session.bank()`，在后台线程里就**碰到了会话对象**，违反"会话只归主线程"的约定。
这里的 think() 只接收不可变快照（Position / 配置 / 毫秒数 / 取消事件），线程安全边界清晰。
"""

from __future__ import annotations

from ..ai import mcts
from ..ai.eval import best_heuristic_move
from ..config import SearchConfig
from ..state import Position


class Thinker:
    """默认决策器：与引擎 `mcts.choose_move` 完全同一条路径。"""

    name = "mcts"

    def think(self, pos: Position, remaining_ms: int, cfg: SearchConfig,
              ply: int, cancel=None) -> mcts.SearchResult:
        # NullBank = 「这个局面下还剩多少毫秒」的快照，不让 worker 碰真实棋钟
        return mcts.choose_move(pos, mcts.NullBank(remaining_ms), cfg, ply, cancel=cancel)


class HeuristicThinker(Thinker):
    """不算树，只走启发式。用于对照与"零耗电"回归。"""

    name = "heuristic"

    def think(self, pos, remaining_ms, cfg, ply, cancel=None) -> mcts.SearchResult:
        mv = best_heuristic_move(pos)
        return mcts.SearchResult(mv, 0, 0, 0, "single" if mv is not None else "no_move")


class ScriptedThinker(Thinker):
    """按预设顺序返回走法，测试用。用完则回退到启发式。"""

    name = "scripted"

    def __init__(self, moves=None) -> None:
        self._queue = list(moves or [])

    def think(self, pos, remaining_ms, cfg, ply, cancel=None) -> mcts.SearchResult:
        while self._queue:
            mv = self._queue.pop(0)
            if mv is None:
                continue
            return mcts.SearchResult(mv, 0, 0, 0, "single")
        mv = best_heuristic_move(pos)
        return mcts.SearchResult(mv, 0, 0, 0, "single" if mv is not None else "no_move")
