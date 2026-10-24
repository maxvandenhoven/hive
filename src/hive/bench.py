"""Perft and benchmarks for the engine.

Perft walks the full game tree from a position to a fixed depth and counts the leaf
positions. The counts depend only on the rules, so they prove correctness against
reference engines, and the time taken measures raw engine speed.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hive.engine.rules import Rules
from hive.engine.state import GameState, Move, PieceType, Player


def perft(state: GameState, rules: Rules, depth: int) -> int:
    """Count the leaf positions of the game tree from a state to a fixed depth.

    A finished game has no moves, so it counts as a leaf at depth zero and contributes
    nothing at greater depths. This matches the reference engines.

    Args:
        state: The game state to start from. It is modified during the walk, but
            restored before returning.
        rules: The rules that generate the moves.
        depth: The number of plies to walk.

    Returns:
        The number of positions reached after exactly `depth` plies.
    """
    if depth == 0:
        return 1

    if rules.is_finished(state):
        return 0

    count = 0
    for move in rules.legal_moves(state):
        state.apply_move(move)
        count += perft(state, rules, depth - 1)
        state.undo_move(move)
    return count


def divide(state: GameState, rules: Rules, depth: int) -> list[tuple[Move | None, int]]:
    """Count the leaf positions below each legal move of a state.

    Comparing these counts with a reference localises a perft mismatch to one move.

    Args:
        state: The game state to start from. It is modified during the walk, but
            restored before returning.
        rules: The rules that generate the moves.
        depth: The number of plies to walk, including the first move. Must be at least
            one.

    Returns:
        Each legal move with the perft count of the position after it at `depth - 1`,
        in the order of `legal_moves`. Empty if the game is finished.

    Raises:
        ValueError: If `depth` is less than one.
    """
    if depth < 1:
        msg = f"The divide depth must be at least `1`, but got `{depth}`."
        raise ValueError(msg)

    if rules.is_finished(state):
        return []

    counts: list[tuple[Move | None, int]] = []
    for move in rules.legal_moves(state):
        state.apply_move(move)
        counts.append((move, perft(state, rules, depth - 1)))
        state.undo_move(move)
    return counts


@dataclass(frozen=True, slots=True)
class PerftResult:
    """The result of a timed perft run.

    Attributes:
        depth: The number of plies walked.
        nodes: The number of leaf positions counted.
        seconds: The wall clock time the walk took.
    """

    depth: int
    nodes: int
    seconds: float

    @property
    def nodes_per_second(self) -> float:
        """Get the number of leaf positions counted per second.

        Returns:
            `nodes` divided by `seconds`, or `0.0` if no time was measured.
        """
        return self.nodes / self.seconds if self.seconds > 0 else 0.0


def timed_perft(state: GameState, rules: Rules, depth: int) -> PerftResult:
    """Run perft and measure how long it takes.

    Args:
        state: The game state to start from. It is modified during the walk, but
            restored before returning.
        rules: The rules that generate the moves.
        depth: The number of plies to walk.

    Returns:
        The depth, node count and wall clock time of the walk.
    """
    start = time.perf_counter()
    nodes = perft(state, rules, depth)
    seconds = time.perf_counter() - start
    return PerftResult(depth=depth, nodes=nodes, seconds=seconds)


@dataclass(frozen=True, slots=True)
class PerftPosition:
    """A named perft position with reference counts.

    Attributes:
        name: The name of the position, for example `start`.
        moves: The moves that lead to the position from the initial state.
        counts: The reference perft count per depth.
        legal_moves: The reference legal moves of the position, or `None` if only the
            counts are known.
    """

    name: str
    moves: list[Move | None]
    counts: dict[int, int]
    legal_moves: list[Move | None] | None = None

    def state(self, rules: Rules) -> GameState:
        """Create the game state of the position by replaying its moves.

        Args:
            rules: The rules the moves are checked against.

        Returns:
            The game state after all moves.

        Raises:
            IllegalMoveError: If a move is not legal under `rules`.
        """
        state = rules.create_initial_state()
        for move in self.moves:
            rules.apply_checked_move(state, move)
        return state


@dataclass(frozen=True, slots=True)
class PerftSuite:
    """A set of perft positions with the rules their reference counts were made with.

    Attributes:
        rules: The rules matching the reference engine.
        positions: The positions, in file order.
    """

    rules: Rules
    positions: list[PerftPosition]

    @classmethod
    def load(cls, path: Path) -> "PerftSuite":
        """Load a perft suite from a JSON file.

        The file holds a `rules` object with `Rules` field values (except
        `piece_counts`, which keeps its default, and with `starting_player` as a player
        name) and a list of `positions`, each with a `name`, a `moves` list, `counts`
        keyed by depth and optionally `legal_moves`. A move is either `null` (a pass) or
        `{"piece": "ant", "from": [q, r] | null, "to": [q, r]}`.

        Args:
            path: The path of the JSON file.

        Returns:
            The suite described by the file.

        Raises:
            ValueError: If the file has an unknown piece type or player.
        """
        data = json.loads(path.read_text())

        rules_data = dict(data["rules"])
        if "starting_player" in rules_data:
            rules_data["starting_player"] = _decode_player(rules_data["starting_player"])
        rules = Rules(**rules_data)

        positions = [
            PerftPosition(
                name=position["name"],
                moves=[_decode_move(move) for move in position["moves"]],
                counts={int(depth): count for depth, count in position["counts"].items()},
                legal_moves=(
                    [_decode_move(move) for move in position["legal_moves"]]
                    if "legal_moves" in position
                    else None
                ),
            )
            for position in data["positions"]
        ]
        return cls(rules=rules, positions=positions)

    def position(self, name: str) -> PerftPosition:
        """Get a position by name.

        Args:
            name: The name of the position.

        Returns:
            The position with the given name.

        Raises:
            KeyError: If no position has the given name.
        """
        for position in self.positions:
            if position.name == name:
                return position

        msg = f"Unknown perft position `{name}`."
        raise KeyError(msg)


def _decode_player(name: str) -> Player:
    """Decode a player from its lower case name.

    Raises:
        ValueError: If the player is unknown.
    """
    try:
        return Player[name.upper()]
    except KeyError as e:
        msg = f"Unknown player `{name}`."
        raise ValueError(msg) from e


def _decode_move(data: dict[str, Any] | None) -> Move | None:
    """Decode a move from its JSON form, where `None` is a pass.

    Raises:
        ValueError: If the piece type is unknown.
    """
    if data is None:
        return None

    try:
        piece_type = PieceType[data["piece"].upper()]
    except KeyError as e:
        msg = f"Unknown piece type `{data['piece']}`."
        raise ValueError(msg) from e

    source = data["from"]
    target = data["to"]
    return Move(
        piece_type=piece_type,
        source_coord=None if source is None else (source[0], source[1]),
        target_coord=(target[0], target[1]),
    )
