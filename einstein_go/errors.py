"""错误码与异常类型。

每个错误码都标注了"谁在什么时机抛"，防止校验责任漂移：
    解析层（protocol）  只抛格式类：MALFORMED_MOVE / OUT_OF_BOARD
    规则层（movegen）    只抛状态类：DIE_NOT_ROLLED
    同步层（sync）       抛校验类：NOT_YOUR_TURN / SRC_MISMATCH / ... / SYNC_DESYNC
    会话层（session）    抛对局状态类：GAME_ALREADY_OVER / DIE_ALREADY_ROLLED / CLOCK_FLAG_FALLEN
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    # ---- 格式与边界 ----
    MALFORMED_MOVE = "MALFORMED_MOVE"                # 文本/JSON 无法解析
    OUT_OF_BOARD = "OUT_OF_BOARD"                    # 坐标不在 1..5 之内
    NOT_ADJACENT = "NOT_ADJACENT"                    # 位移不是恰好一格
    ILLEGAL_DIRECTION = "ILLEGAL_DIRECTION"          # 位移方向不属于本方走子方向集
    ILLEGAL_MOVE = "ILLEGAL_MOVE"                    # 走法不在合法集内（引擎内部契约被破坏）
    # ---- 身份 ----
    NOT_YOUR_TURN = "NOT_YOUR_TURN"                  # 行动方不匹配
    NOT_YOUR_PIECE = "NOT_YOUR_PIECE"                # 起点上的棋子不是本方
    PIECE_ALREADY_CAPTURED = "PIECE_ALREADY_CAPTURED"  # 该编号棋子已不在盘上
    SRC_MISMATCH = "SRC_MISMATCH"                    # 声明的起点与该编号棋子实际位置不符
    # ---- 骰子 ----
    DIE_NOT_ROLLED = "DIE_NOT_ROLLED"                # 尚未掷骰就要求生成走法
    DIE_ALREADY_ROLLED = "DIE_ALREADY_ROLLED"        # 同一回合重复掷骰（防双掷闸门）
    DIE_PIECE_MISMATCH = "DIE_PIECE_MISMATCH"        # 所选编号不符合"最近编号"规则
    # ---- 对局状态 ----
    GAME_ALREADY_OVER = "GAME_ALREADY_OVER"
    CLOCK_FLAG_FALLEN = "CLOCK_FLAG_FALLEN"
    # ---- 协议 / 一致性 ----
    SYNC_DESYNC = "SYNC_DESYNC"                      # 走后对账失败
    HASH_CHAIN_BROKEN = "HASH_CHAIN_BROKEN"          # 棋谱重放对不上哈希链
    REPLAY_OUT_OF_ORDER = "REPLAY_OUT_OF_ORDER"      # ply 序号不连续
    NO_LEGAL_MOVE = "NO_LEGAL_MOVE"                  # 期望有走法却拿到空列表


class EngineError(Exception):
    """引擎统一异常。携带结构化错误码与上下文，便于协议层原样回传。"""

    def __init__(self, code: ErrorCode, message: str = "", **ctx: object) -> None:
        self.code = code
        self.message = message or code.value
        self.ctx = ctx
        super().__init__(f"[{code.value}] {self.message}")

    def to_dict(self) -> dict:
        return {"code": self.code.value, "message": self.message, "ctx": dict(self.ctx)}


class IllegalMoveError(EngineError):
    """外部走法非法（校验失败）。"""


class SyncError(EngineError):
    """状态同步失败。"""


class ReplayError(EngineError):
    """棋谱重放失败。"""
