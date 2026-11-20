"""测试辅助函数（不依赖 pytest，测试文件可直接 import）。"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from einstein_go.constants import RED, parse_sq  # noqa: E402
from einstein_go.movegen import generate_moves  # noqa: E402
from einstein_go.session import GameSession  # noqa: E402
from einstein_go.state import Position  # noqa: E402
from einstein_go.transition import apply  # noqa: E402


def build_pos(red: dict[int, str] | None = None, blue: dict[int, str] | None = None,
              side: int = RED, die: int = 0) -> Position:
    """按 {编号: 格名} 在空格盘上构造局面（规则边界测试用）。"""
    squares = [0] * 25
    for num, name in (red or {}).items():
        sq = parse_sq(name)
        assert squares[sq] == 0, f"{name} 已被占用"
        squares[sq] = num
    for num, name in (blue or {}).items():
        sq = parse_sq(name)
        assert squares[sq] == 0, f"{name} 已被占用"
        squares[sq] = -num
    return Position.build(squares, side, die)


def play_random_game(seed: int = 0, max_plies: int = 80, die_seed: int | None = None) -> GameSession:
    """下完一整局随机棋。"""
    r = random.Random(seed if die_seed is None else die_seed)
    s = GameSession(seed=seed)
    while not s.finished and s.ply < max_plies:
        s.roll(r.randint(1, 6))
        moves = generate_moves(s.pos)
        if not moves:
            break
        s.play(r.choice(moves))
    return s


def random_positions(count: int = 50, max_plies: int = 20, seed: int = 1):
    """随机合法局面样本（由随机对局产生，保证可达）。"""
    out = []
    for g in range(count):
        r = random.Random(seed + g)
        s = GameSession(seed=seed + g)
        for _ in range(max_plies):
            if s.finished:
                break
            s.roll(r.randint(1, 6))
            moves = generate_moves(s.pos)
            if not moves:
                break
            s.play(r.choice(moves))
            out.append(s.pos)
    return out


def first_legal(pos: Position):
    moves = generate_moves(pos)
    assert moves, "该局面没有合法走法"
    return moves[0]


def apply_first(pos: Position) -> Position:
    return apply(pos, first_legal(pos))
