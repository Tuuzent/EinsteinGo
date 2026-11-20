"""各类对局者与对局驱动。

Player 只需要一个方法：choose_move(session) -> Move。
- 绝不能在这里掷骰（掷骰由 GameSession.roll 唯一负责，R8）
- 绝不能返回合法集之外的走法（MCTSPlayer 返回前做一次成员校验）
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from dataclasses import replace as _replace

from .ai import mcts
from .ai.eval import best_heuristic_move
from .config import SearchConfig
from .constants import MAX_PLY
from .errors import EngineError, ErrorCode
from .move import Move


class Player:
    name = "player"

    def choose_move(self, session) -> Move:  # pragma: no cover - 抽象
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.name}>"


@dataclass
class RandomPlayer(Player):
    seed: int = 0
    name: str = "random"
    _rng: random.Random = field(default_factory=random.Random, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def choose_move(self, session) -> Move:
        moves = session.legal_moves()
        if not moves:
            raise EngineError(ErrorCode.NO_LEGAL_MOVE, "没有合法走法")
        return self._rng.choice(moves)


@dataclass
class HeuristicPlayer(Player):
    name: str = "heuristic"

    def choose_move(self, session) -> Move:
        mv = best_heuristic_move(session.pos)
        if mv is None:
            raise EngineError(ErrorCode.NO_LEGAL_MOVE, "没有合法走法")
        return mv


@dataclass
class MCTSPlayer(Player):
    name: str = "mcts"
    cfg: SearchConfig = field(default_factory=SearchConfig)
    last: mcts.SearchResult | None = field(default=None, repr=False)

    def choose_move(self, session) -> Move:
        legal = {m.key() for m in session.legal_moves()}
        result = mcts.choose_move(session.pos, session.bank(), self.cfg, session.ply)
        self.last = result
        if result.move is None:
            raise EngineError(ErrorCode.NO_LEGAL_MOVE, "MCTS 未能给出走法")
        if result.move.key() not in legal:  # 最后一道闸门
            raise EngineError(
                ErrorCode.ILLEGAL_MOVE,
                f"MCTS 返回了非法走法 {result.move.to_text()}",
            )
        return result.move


def make_player(spec: str, *, seed: int = 0, node_limit: int | None = None,
                think_ms: int | None = None) -> Player:
    """工厂：'random' / 'heuristic' / 'mcts' / 'mcts:2000'（节点上限）。"""
    base, _, arg = spec.partition(":")
    base = base.strip().lower()
    if base == "random":
        return RandomPlayer(seed=seed + 1)
    if base == "heuristic":
        return HeuristicPlayer()
    if base == "mcts":
        cfg = SearchConfig(seed=seed, node_limit=node_limit)
        if arg:
            cfg = _replace(cfg, node_limit=int(arg))
        if think_ms is not None:
            cfg = _replace(cfg, min_think_ms=0, max_think_ms=think_ms)
        return MCTSPlayer(cfg=cfg)
    raise ValueError(f"未知的对局者类型: {spec!r}（可选 random / heuristic / mcts[:节点数]）")


def play_out(session, players: dict[int, Player], on_move=None) -> object:
    """把一局下完。players 以阵营 (+1/-1) 为键。"""
    guard = 0
    while not session.finished:
        guard += 1
        if session.ply > MAX_PLY or guard > MAX_PLY * 2:
            raise RuntimeError("对局未能终局，疑似循环（规则内核可能有 bug）")
        side = session.side
        die = session.roll()
        player = players[side]
        move = player.choose_move(session)
        session.play(move)
        if on_move is not None:
            on_move(session, side, die, move)
    return session
