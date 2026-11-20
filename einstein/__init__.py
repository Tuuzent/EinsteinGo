"""爱恩斯坦棋（Einstein würfelt nicht）博弈引擎公共 API。

五个职责与所在模块：
    ① 棋盘状态      state.Position / state.GameState
    ② 合法走法生成  movegen.generate_moves / movegen.resolve_candidates
    ③ 移动执行      transition.apply
    ④ 回合切换      transition.switch_turn（走子换手内联在 apply 中）
    ⑤ 胜负判定      terminal.terminal_after
"""

from __future__ import annotations

from .constants import BLUE, CORNER, DELTAS, MAX_PLY, RED, SIDES, sq_name
from .errors import EngineError, ErrorCode, IllegalMoveError, SyncError
from .move import Move, MoveIntent, parse_move_json, parse_move_text
from .movegen import generate_moves, moves_for_die, resolve_candidates
from .outcome import GameResult, TerminalReason
from .state import GameState, Position, canonical, initial_position, rot180
from .terminal import is_terminal, terminal_after, winner_by_flag
from .transition import apply, pass_turn, switch_turn

__all__ = [
    "BLUE",
    "CORNER",
    "DELTAS",
    "MAX_PLY",
    "RED",
    "SIDES",
    "EngineError",
    "ErrorCode",
    "GameResult",
    "GameState",
    "IllegalMoveError",
    "Move",
    "MoveIntent",
    "Position",
    "SyncError",
    "TerminalReason",
    "apply",
    "canonical",
    "generate_moves",
    "initial_position",
    "is_terminal",
    "moves_for_die",
    "parse_move_json",
    "parse_move_text",
    "pass_turn",
    "resolve_candidates",
    "rot180",
    "sq_name",
    "switch_turn",
    "terminal_after",
    "winner_by_flag",
]

__version__ = "1.0.0"
