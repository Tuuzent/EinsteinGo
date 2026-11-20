"""棋盘常量、坐标、方向表与棋子编码。

全局唯一坐标约定（禁止在其他模块重复定义）：
    row 自上而下 1..5，col 自左而右 1..5，均为 1-based；
    扁平索引 i = (row - 1) * 5 + (col - 1)，范围 0..24；
    格名 = 列字母 a..e + 行数字 1..5，例如 (1,1) == "a1"，(5,5) == "e5"。

棋子编码（单 int，阵营判断免费）：
    0        = 空格
    +1 .. +6 = 红方 1..6 号
    -1 .. -6 = 蓝方 1..6 号
因此 code > 0 即红、code < 0 即蓝、abs(code) 即编号，省掉所有 color 分支。
"""

from __future__ import annotations

BOARD_SIZE = 5
N_SQUARES = BOARD_SIZE * BOARD_SIZE

EMPTY = 0
RED = 1
BLUE = -1
SIDES = (RED, BLUE)

SIDE_NAME = {RED: "R", BLUE: "B"}
NAME_SIDE = {"R": RED, "B": BLUE}

NUM_MIN = 1
NUM_MAX = 6

# 一格见方的三个走子方向（row, col 增量）。红方向右/下/右下，蓝方对称。
DELTAS = {
    RED: ((0, 1), (1, 0), (1, 1)),
    BLUE: ((0, -1), (-1, 0), (-1, -1)),
}

# 出发区：角上 6 格三角（标准 Einstein würfelt nicht 布局）
#   红方 (1,1) (1,2) (1,3) (2,1) (2,2) (3,1)，即 row + col <= 4
#   蓝方为中心对称镜像            即 row + col >= 8
RED_HOME = frozenset(
    (row - 1) * BOARD_SIZE + (col - 1)
    for row in range(1, BOARD_SIZE + 1)
    for col in range(1, BOARD_SIZE + 1)
    if row + col <= 4
)
BLUE_HOME = frozenset(N_SQUARES - 1 - i for i in RED_HOME)

# 双方各自的胜利角点：率先到达"对方出发区的角点"者获胜
CORNER = {RED: (5 - 1) * BOARD_SIZE + (5 - 1), BLUE: (1 - 1) * BOARD_SIZE + (1 - 1)}

# 安全阀：正常对局远达不到（见 state 模块中"必然终局"的证明）
MAX_PLY = 300


def idx(row: int, col: int) -> int:
    """(row, col) -> 扁平索引，1-based。"""
    return (row - 1) * BOARD_SIZE + (col - 1)


def rc(i: int) -> tuple[int, int]:
    """扁平索引 -> (row, col)，1-based。"""
    return i // BOARD_SIZE + 1, i % BOARD_SIZE + 1


_COLS = "abcde"


def sq_name(i: int) -> str:
    """扁平索引 -> 格名，例如 0 -> "a1"，24 -> "e5"。"""
    row, col = rc(i)
    return f"{_COLS[col - 1]}{row}"


def parse_sq(name: str) -> int:
    """格名 -> 扁平索引。非法名抛 ValueError（由调用方翻译成 ErrorCode）。"""
    if len(name) != 2:
        raise ValueError(f"bad square name: {name!r}")
    col_ch, row_ch = name[0].lower(), name[1]
    if col_ch not in _COLS or row_ch not in "12345":
        raise ValueError(f"bad square name: {name!r}")
    return idx(int(row_ch), _COLS.index(col_ch) + 1)


def in_board(row: int, col: int) -> bool:
    return 1 <= row <= BOARD_SIZE and 1 <= col <= BOARD_SIZE


def side_of(code: int) -> int:
    """棋子编码 -> 阵营（空格返回 0）。"""
    if code == 0:
        return 0
    return RED if code > 0 else BLUE


def num_of(code: int) -> int:
    """棋子编码 -> 编号（空格返回 0）。"""
    return abs(code)


def code_of(side: int, num: int) -> int:
    """(阵营, 编号) -> 棋子编码。"""
    return side * num


def dist_to_corner(side: int, i: int) -> int:
    """某方棋子到己方目标角点的最短步数（切比雪夫距离，闭式精确解）。

    因为允许斜走且可以踩在任意棋子上（吃子而非被阻挡），棋盘上不存在阻挡物，
    所以最短步数就是切比雪夫距离；红方 row/col 单调不减、蓝方单调不增，
    每步最多各 +1，对角步同时 +1，故下界可达。
    """
    row, col = rc(i)
    if side == RED:
        return max(BOARD_SIZE - row, BOARD_SIZE - col)
    return max(row - 1, col - 1)


def _build_neighbors(side: int) -> tuple[tuple[int, ...], ...]:
    """预计算每格的合法目标格（已过滤越界），供走法生成热路径 O(1) 取用。"""
    table = []
    for i in range(N_SQUARES):
        row, col = rc(i)
        dsts = []
        for dr, dc in DELTAS[side]:
            nr, nc = row + dr, col + dc
            if in_board(nr, nc):
                dsts.append(idx(nr, nc))
        table.append(tuple(dsts))
    return tuple(table)


NEIGHBORS = {side: _build_neighbors(side) for side in SIDES}

# bit n 对应编号 n（n = 1..6），bit 0 恒为 0，方便 (alive >> n) & 1
ALL_ALIVE = 0b1111110
