"""赛制轮次管理：每轮最多 7 盘，先胜 4 盘者获胜，轮流先手。

规则第 8 条：甲方第 1、4、5 盘先手，乙方第 2、3、6、7 盘先手。
先手方执红（假设 A10）。

7 盘 4 胜结构上不会出现平局：3:3 时第 7 盘的胜者必为 4:3。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .constants import RED
from .outcome import GameResult, TerminalReason

A = "A"
B = "B"

# 盘号 -> 先手方
FIRST_PLAYER_OF_GAME: dict[int, str] = {
    1: A, 2: B, 3: B, 4: A, 5: A, 6: B, 7: B,
}

MAX_GAMES = 7
NEEDED_WINS = 4


@dataclass(frozen=True, slots=True)
class GameRecord:
    game_no: int
    first_player: str
    winner_side: int
    reason: TerminalReason
    plies: int = 0

    @property
    def color_of_a(self) -> int:
        return RED if self.first_player == A else -RED

    @property
    def winner_name(self) -> str:
        return A if self.winner_side == self.color_of_a else B

    def describe(self) -> str:
        return (f"第 {self.game_no} 盘 先手={self.first_player} "
                f"胜方={self.winner_name}（{self.reason.value}，{self.plies} 手）")


@dataclass(frozen=True, slots=True)
class MatchResult:
    rounds: tuple[GameRecord, ...]
    wins_a: int
    wins_b: int

    @property
    def games_played(self) -> int:
        return len(self.rounds)

    @property
    def winner(self) -> str | None:
        if self.wins_a >= NEEDED_WINS:
            return A
        if self.wins_b >= NEEDED_WINS:
            return B
        return None

    def summary(self) -> str:
        head = f"总比分 {self.wins_a}:{self.wins_b}（共 {self.games_played} 盘）"
        tail = f"胜方 {self.winner}" if self.winner else "未决出（不应发生）"
        return head + " · " + tail


Runner = Callable[[int, str], GameRecord]


class Match:
    """轮次驱动。runner(game_no, first_player) 负责真正打一盘并返回结果。"""

    def __init__(
        self,
        runner: Runner,
        max_games: int = MAX_GAMES,
        needed_wins: int = NEEDED_WINS,
    ) -> None:
        if not 1 <= max_games <= MAX_GAMES:
            raise ValueError(f"max_games 必须在 1..{MAX_GAMES}")
        if not 1 <= needed_wins <= max_games:
            raise ValueError("needed_wins 必须落在 1..max_games")
        self.runner = runner
        self.max_games = max_games
        self.needed_wins = needed_wins

    def play(self) -> MatchResult:
        rounds: list[GameRecord] = []
        wins_a = wins_b = 0
        for game_no in range(1, self.max_games + 1):
            if wins_a >= self.needed_wins or wins_b >= self.needed_wins:
                break
            first = FIRST_PLAYER_OF_GAME.get(game_no, A)
            rec = self.runner(game_no, first)
            if rec.game_no != game_no:
                raise ValueError(f"runner 回报的盘号 {rec.game_no} 与请求的 {game_no} 不符")
            if rec.winner_side not in (1, -1):
                raise ValueError(f"winner_side 必须是 +1/-1，收到 {rec.winner_side}")
            rounds.append(rec)
            if rec.winner_name == A:
                wins_a += 1
            else:
                wins_b += 1
        return MatchResult(tuple(rounds), wins_a, wins_b)


def make_record(game_no: int, first_player: str, result: GameResult, plies: int) -> GameRecord:
    return GameRecord(
        game_no=game_no,
        first_player=first_player,
        winner_side=result.winner,
        reason=result.reason,
        plies=plies,
    )
