"""集中配置：评估权重、搜索参数、时间分配。

权重改动请只改这里，并跑 scripts/bench_matrix.py 回归（禁止散落在 ai/* 里）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# 启发式权重。正 = 对我方有利。
DEFAULT_WEIGHTS: dict[str, float] = {
    "dist": 1.20,       # 最靠前棋子距离差（主线赛跑）
    "dist2": 0.30,      # 第二梯队距离差（多线进攻更难防）
    "material": 0.50,   # 子力差
    "mobility": 0.20,   # 骰面适配度差
    "lose1": -2.60,     # 对手下一手进角概率（近似致命，绝对值必须压过 dist）
    "risk": -0.90,      # 领头子被吃概率
    "win1": 2.00,       # 我方下一手进角概率（打折：对手先走一手）
    "structure": 0.10,  # 距离和差（防抖）
}

EVAL_SCALE = 1.6   # tanh 前的放大系数

# 终局值与启发式值的尺度衔接：终局略高于饱和评估，保证严格排序
TERMINAL_VALUE = 1.0
FAR_DIST = 9       # 某方无子时的距离占位值

DEFAULT_BUDGET_MS = 4 * 60 * 1000  # 每方 4 分钟/盘


@dataclass(frozen=True, slots=True)
class SearchConfig:
    """MCTS 参数。给定 seed + 相同局面 + node_limit，结果完全可复现。"""

    seed: int = 0
    c_puct: float = 1.4          # 决策节点探索系数
    use_prior: bool = True       # 关闭后退化为经典 UCT
    tau: float = 0.18            # 先验 softmax 温度
    p_min: float = 0.02          # 先验下限（保证每个走法都有被探索的机会）
    max_depth: int = 60          # 树深上限，超过则用启发式截断
    max_rollout_ply: int = 40    # 单次 rollout 步数上限
    node_limit: int | None = None  # 节点数硬上限（单测/基准用）
    time_check_every: int = 64   # 每 N 次模拟检查一次时间
    safety_ms: int = 30          # 预留安全余量
    min_think_ms: int = 60       # 低于此值放弃搜索，直接走启发式
    max_think_ms: int = 3000     # 单步思考上限
    rollout_greedy_p: float = 0.6  # rollout 中走"最贪心"走法的概率
    est_moves_left: int = 20     # 时间分配的预估剩余手数下限

    def with_node_limit(self, n: int | None) -> "SearchConfig":
        return replace(self, node_limit=n)


@dataclass(frozen=True, slots=True)
class EvalWeights:
    table: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    scale: float = EVAL_SCALE

    def get(self, key: str) -> float:
        return self.table.get(key, 0.0)


DEFAULT_EVAL_WEIGHTS = EvalWeights()
