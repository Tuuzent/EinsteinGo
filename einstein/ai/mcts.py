"""带机会节点（chance node）的 MCTS。

树结构
------
    Decision(我方, 骰值已掷出)  --move-->  Chance(对手回合, 骰值未知)  --die d-->  Decision(对手, d)  --move--> …

**根节点必然是 Decision，根下面没有 Chance**（R6 高危点）：我方回合掷骰后才决策，
若在根上再插一层机会节点，等于把"自己的骰子"平均掉，棋力会明显退化。

符号约定（R7 高危点）
--------------------
每个节点存**自己 owner 视角**的价值，negamax 翻转只在"走子边"发生一次：
    Decision 是 Chance 的子 → owner 相同 → edge_sign = +1
    Chance 是 Decision 的子 → owner 相反 → edge_sign = -1
回传时：node.w += v; v *= node.edge_sign; node = node.parent。

机会节点
--------
树内**枚举 6 个骰面**（无方差、分支只有 6、能发现"某骰面对我不利"），
rollout 内**采样单骰**（省成本）。这是两种模式的正确组合。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from ..config import TERMINAL_VALUE, SearchConfig
from ..constants import dist_to_corner
from ..errors import EngineError, ErrorCode
from ..move import Move
from ..movegen import generate_moves
from ..state import Position
from ..terminal import terminal_after
from ..transition import ScratchBoard, apply
from .eval import best_heuristic_move, evaluate, win_in_one
from .rng import derive

DECISION = 0
CHANCE = 1
PRIOR_CHANCE = 1.0 / 6.0


# ---------------------------------------------------------------- 节点
class Node:
    __slots__ = ("pos", "owner", "parent", "children", "n", "w", "prior",
                 "edge_sign", "kind", "move", "rank", "expanded", "terminal_value")

    def __init__(self, pos, owner, parent, kind, edge_sign, prior, move, rank):
        self.pos = pos
        self.owner = owner
        self.parent = parent
        self.children: list[Node] = []
        self.n = 0
        self.w = 0.0
        self.prior = prior
        self.edge_sign = edge_sign
        self.kind = kind
        self.move = move
        self.rank = rank
        self.expanded = False
        self.terminal_value: float | None = None

    @property
    def q(self) -> float:
        return self.w / self.n if self.n else 0.0

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        kind = "D" if self.kind == DECISION else "C"
        label = self.move.to_text() if self.move else f"die{self.rank}"
        return f"<{kind} {label} n={self.n} q={self.q:+.3f}>"


# ---------------------------------------------------------------- 预算
class Budget:
    """时间 / 迭代次数双阈值，取先到者。时间函数可注入（测试用 FakeTime）。

    迭代上限用 **sims**（每次模拟都 +1）而不是 nodes（只有扩展才 +1）：
    搜索循环里"命中终局"和"达到深度上限"两条路径都不扩展节点，若用 nodes 计数，
    这两条路径会让上限永不触发 —— 在虚拟时钟下就是死循环。

    `cancel` 是给交互式前端留的取消通道（threading.Event 或任何带 `is_set()` 的对象）。
    设过之后 `expired()` 立刻为真，搜索在下一次判定时停下并返回当前最优。
    引擎自身不用它，纯 Python 计算无法被抢占，只能靠这个协作式检查点提前退出。
    """

    __slots__ = ("deadline", "node_limit", "sims", "nodes", "_now", "check_every", "allot_ms", "_cancel")

    def __init__(self, allot_ms: int, cfg: SearchConfig, now: Callable[[], int] | None = None,
                 cancel=None):
        self._now = now or (lambda: time.monotonic_ns() // 1_000_000)
        self.allot_ms = allot_ms
        self.deadline = self._now() + max(1, allot_ms - cfg.safety_ms)
        self.node_limit = cfg.node_limit
        self.check_every = max(1, cfg.time_check_every)
        self.sims = 0
        self.nodes = 0
        self._cancel = cancel

    def cancelled(self) -> bool:
        return self._cancel is not None and self._cancel.is_set()

    def expired(self) -> bool:
        if self._cancel is not None and self._cancel.is_set():
            return True
        if self.node_limit is not None and self.sims >= self.node_limit:
            return True
        if self.sims % self.check_every == 0 and self._now() >= self.deadline:
            return True
        return False


class NullBank:
    """没有计时器时的替代（单测/基准用）：剩余时间固定，但"现在几点"用真实时钟。"""

    __slots__ = ("_ms",)

    def __init__(self, ms: int = 60_000):
        self._ms = ms

    def remaining_ms(self) -> int:
        return self._ms

    def now_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000


# ---------------------------------------------------------------- 结果
@dataclass(frozen=True, slots=True)
class MoveStat:
    move: Move
    visits: int
    q: float
    prior: float

    def __str__(self) -> str:
        return f"{self.move.to_text()} n={self.visits} q={self.q:+.3f} p={self.prior:.3f}"


@dataclass(frozen=True, slots=True)
class SearchResult:
    move: Move | None
    nodes: int
    sims: int
    elapsed_ms: int
    reason: str
    root_stats: tuple[MoveStat, ...] = ()
    depth_max: int = 0

    @property
    def searched(self) -> bool:
        return self.reason == "mcts"

    def top(self, k: int = 3) -> list[MoveStat]:
        return list(self.root_stats[:k])

    def explain(self) -> str:
        lines = [f"决策: {self.move.to_text() if self.move else '无'} "
                 f"（策略={self.reason} 节点={self.nodes} 模拟={self.sims} 耗时={self.elapsed_ms}ms）"]
        for st in self.top(5):
            lines.append(f"  {st}")
        return "\n".join(lines)


# ---------------------------------------------------------------- 先验
def _rank_move(mv: Move) -> int:
    return mv.piece * 10000 + mv.src * 100 + mv.dst


def compute_priors(pos: Position, moves: list[Move], owner: int, cfg: SearchConfig) -> list[float]:
    """用启发式给走法打先验（softmax）。先验只影响"先探索谁"，不影响最终值。"""
    scores: list[float] = []
    for mv in moves:
        child = apply(pos, mv)
        res = terminal_after(child, 1)
        if res is not None:
            scores.append(10.0 if res.winner == owner else -10.0)
        else:
            scores.append(evaluate(child, owner))
    mx = max(scores)
    ex = [math.exp((s - mx) / max(1e-6, cfg.tau)) for s in scores]
    z = sum(ex) or 1.0
    ps = [max(cfg.p_min, e / z) for e in ex]
    total = sum(ps)
    return [p / total for p in ps]


# ---------------------------------------------------------------- 扩展
def _expand(node: Node, cfg: SearchConfig) -> None:
    if node.kind == DECISION:
        pos = node.pos
        moves = generate_moves(pos)
        if not moves:  # 轮空（本规则集不可达，防御性处理）
            node.expanded = True
            node.terminal_value = evaluate(pos, node.owner)
            return
        priors = compute_priors(pos, moves, node.owner, cfg) if cfg.use_prior else \
            [1.0 / len(moves)] * len(moves)
        for mv, p in zip(moves, priors):
            child_pos = apply(pos, mv)
            child = Node(child_pos, -node.owner, node, CHANCE, -1, p, mv, _rank_move(mv))
            res = terminal_after(child_pos, 1)
            if res is not None:
                child.terminal_value = TERMINAL_VALUE if res.winner == child.owner else -TERMINAL_VALUE
            node.children.append(child)
        node.expanded = True
    else:
        for die in range(1, 7):
            child_pos = node.pos.with_die(die)
            node.children.append(
                Node(child_pos, node.owner, node, DECISION, +1, PRIOR_CHANCE, None, die)
            )
        node.expanded = True


def _select(node: Node, cfg: SearchConfig) -> Node:
    """选子节点。

    决策节点：PUCT，`exploit = edge_sign * ch.q` —— 子节点存的是**它自己 owner 视角**的值，
    决策节点的子（Chance 节点）owner 相反，必须先翻回本节点视角再比较。
    漏掉这一步等于"替对手挑最优走法"（这是实现这种博弈时最常见的符号错误）。

    机会节点：骰面均匀且已知，故用**轮转均衡**（选访问次数最少者）而非 UCB ——
    这样 6 个骰面被等频采样，node.q = w/n 就是期望值的无偏估计；
    用 UCB 反而会偏向"对行棋方有利的那个骰面"，把估计值往上抬。

    用 (score, -rank) 全序键保证确定性。
    """
    if node.kind == CHANCE:
        return min(node.children, key=lambda ch: (ch.n, ch.rank))

    n = node.n
    sqrt_n = math.sqrt(n)
    if cfg.use_prior:
        c = cfg.c_puct
        best, best_key = None, None
        for ch in node.children:
            score = ch.edge_sign * ch.q + c * ch.prior * sqrt_n / (1 + ch.n)
            key = (score, -ch.rank)
            if best_key is None or key > best_key:
                best_key, best = key, ch
        return best
    log_n = math.log(n + 1)
    best, best_key = None, None
    for ch in node.children:
        score = ch.edge_sign * ch.q + 1.41 * math.sqrt(log_n / (ch.n + 1e-9))
        key = (score, -ch.rank)
        if best_key is None or key > best_key:
            best_key, best = key, ch
    return best


# ---------------------------------------------------------------- rollout
def _rollout(pos: Position, owner: int, cfg: SearchConfig, rng) -> float:
    board = ScratchBoard(pos)
    depth = 0
    while depth < cfg.max_rollout_ply:
        board.die = rng.randint(1, 6)
        moves = board.moves()
        if not moves:
            board.flip()
            depth += 1
            continue
        if len(moves) == 1:
            mv = moves[0]
        elif rng.random() < cfg.rollout_greedy_p:
            side = board.side
            mv = min(moves, key=lambda m: (dist_to_corner(side, m.dst), _rank_move(m)))
        else:
            mv = moves[rng.randrange(len(moves))]
        board.make(mv)
        winner = board.winner()
        if winner is not None:
            return TERMINAL_VALUE if winner == owner else -TERMINAL_VALUE
        depth += 1
    return evaluate(board.to_position(), owner)


def backprop(node: Node | None, value: float) -> None:
    """回传统计。value 是 node.owner 视角的值，沿父链按 edge_sign 逐层翻转。"""
    while node is not None:
        node.n += 1
        node.w += value
        value *= node.edge_sign
        node = node.parent


# ---------------------------------------------------------------- 主搜索
def search(pos: Position, budget: Budget, cfg: SearchConfig) -> SearchResult:
    if pos.die == 0:
        raise EngineError(ErrorCode.DIE_NOT_ROLLED, "MCTS 要求骰值已就位（AI 不掷骰）")
    t0 = budget._now()
    moves = generate_moves(pos)
    if len(moves) <= 1:  # 战术短路
        return SearchResult(moves[0] if moves else None, 0, 0, 0,
                            "single" if moves else "no_move", (), 0)

    rng = derive(cfg.seed, "rollout")
    root = Node(pos, pos.side, None, DECISION, +1, 1.0, None, 0)
    _expand(root, cfg)
    budget.nodes += 1
    depth_max = 1

    while not budget.expired():
        node = root
        depth = 0
        while node.expanded and node.terminal_value is None:
            node = _select(node, cfg)
            depth += 1
            if depth >= cfg.max_depth:
                break

        if node.terminal_value is not None:
            value = node.terminal_value
        elif depth >= cfg.max_depth:
            value = evaluate(node.pos, node.owner)
        else:
            _expand(node, cfg)
            budget.nodes += 1
            depth_max = max(depth_max, depth)
            if not node.children:
                value = evaluate(node.pos, node.owner)
            else:
                node = _select(node, cfg)
                depth += 1
                depth_max = max(depth_max, depth)
                if node.terminal_value is not None:
                    value = node.terminal_value
                else:
                    value = _rollout(node.pos, node.owner, cfg, rng)

        backprop(node, value)
        budget.sims += 1
    best = _select_final(root)
    stats = tuple(
        sorted(
            (MoveStat(c.move, c.n, c.edge_sign * c.q, c.prior) for c in root.children),
            key=lambda s: (-s.visits, -s.q, _rank_move(s.move)),
        )
    )
    return SearchResult(
        move=best.move if best else None,
        nodes=budget.nodes,
        sims=budget.sims,
        elapsed_ms=budget._now() - t0,
        reason="mcts",
        root_stats=stats,
        depth_max=depth_max,
    )


def _select_final(root: Node) -> Node | None:
    """最终选择：①访问数最多 ②根视角 Q 最高 ③走法编码字典序最小（确定性）。"""
    if not root.children:
        return None
    return max(root.children, key=lambda c: (c.n, c.edge_sign * c.q, -c.rank))


# ---------------------------------------------------------------- 对外入口
def allocate_ms(remaining_ms: int, ply: int, cfg: SearchConfig) -> int:
    """单步思考预算 = 剩余时间 / 预估剩余手数，带上下限。"""
    moves_left = max(cfg.est_moves_left, 40 - ply)
    raw = remaining_ms / moves_left
    return int(min(cfg.max_think_ms, max(cfg.min_think_ms, raw)))


def choose_move(pos: Position, bank=None, cfg: SearchConfig | None = None, ply: int = 0,
                cancel=None) -> SearchResult:
    """完整决策入口：战术短路 → 时间不足降级 → MCTS。

    `cancel` 可选，仅给交互式前端用于"用户点了新局/关窗"时提前退出搜索；
    不传时行为与以往完全一致。
    """
    cfg = cfg or SearchConfig()
    if pos.die == 0:
        raise EngineError(ErrorCode.DIE_NOT_ROLLED, "AI 不掷骰：调用前必须由驱动层掷骰")
    moves = generate_moves(pos)
    if not moves:
        return SearchResult(None, 0, 0, 0, "no_move")
    if len(moves) == 1:
        return SearchResult(moves[0], 0, 0, 0, "single")

    mate = win_in_one(pos)
    if mate is not None:
        return SearchResult(mate, 0, 0, 0, "mate")

    bank = bank or NullBank()
    remaining = bank.remaining_ms()
    now = getattr(bank, "now_ms", None)

    if remaining < cfg.min_think_ms:
        mv = best_heuristic_move(pos)
        return SearchResult(mv, 0, 0, 0, "low_time")

    allot = allocate_ms(remaining, ply, cfg)
    budget = Budget(allot, cfg, now, cancel=cancel)
    return search(pos, budget, cfg)
