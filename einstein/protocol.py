"""协议层：棋谱行、JSON 走法、状态指纹与哈希链。

哈希链设计
----------
每手把「走法 + 走后 zhash」串进 blake2b：
    chain_0 = CHAIN_ROOT
    chain_i = blake2b(chain_{i-1} || "piece:src>dst@die|zhash")
好处：整局任意一手都能被独立校验。只比"最终哈希"时，坏了只知道坏了；
比哈希链时能定位到具体 ply。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .constants import sq_name
from .errors import EngineError, ErrorCode
from .move import Move, MoveIntent, parse_move_json, parse_move_text
from .state import Position

CHAIN_ROOT = b"\x00" * 16


def chain_step(prev: bytes, mv: Move, zhash: int) -> bytes:
    payload = f"{mv.piece}:{mv.src}>{mv.dst}@{mv.die}|{zhash:016x}".encode("utf-8")
    return hashlib.blake2b(prev + payload, digest_size=16).digest()


def hex_hash(h: int) -> str:
    return f"{h:016x}"


def fingerprint(pos: Position) -> dict:
    """状态指纹：用于走前/走后对账与跨进程一致性比较。"""
    return {
        "squares": pos.squares,
        "side": pos.side,
        "die": pos.die,
        "red_mask": pos.red_mask,
        "blue_mask": pos.blue_mask,
        "red_alive": pos.red_alive,
        "blue_alive": pos.blue_alive,
        "zhash": pos.zhash,
    }


def move_row(ply: int, side: int, mv: Move, zh_before: int, zh_after: int, chain: bytes) -> dict:
    return {
        "ply": ply,
        "side": "R" if side > 0 else "B",
        "piece": mv.piece,
        "src": sq_name(mv.src),
        "dst": sq_name(mv.dst),
        "die": mv.die,
        "captured": mv.captured,
        "hash_before": hex_hash(zh_before),
        "hash_after": hex_hash(zh_after),
        "chain": chain.hex(),
    }


def parse_intent(remote) -> MoveIntent:
    """把三种来源（MoveIntent / str / dict）统一解析成 MoveIntent。"""
    if isinstance(remote, MoveIntent):
        return remote
    if isinstance(remote, Move):
        return MoveIntent(
            piece=remote.piece, dst=remote.dst, src=remote.src, die=remote.die, raw=remote.to_text()
        )
    if isinstance(remote, str):
        return parse_move_text(remote)
    if isinstance(remote, dict):
        return parse_move_json(remote)
    raise EngineError(
        ErrorCode.MALFORMED_MOVE, f"不支持的走法来源类型: {type(remote).__name__}"
    )


def write_jsonl(path: str | Path, rows: list[dict]) -> None:
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_jsonl(path: str | Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]
