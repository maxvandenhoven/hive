"""Perft parity against the reference counts in `tests/data/perft/base.json`.

Counts up to `SHALLOW_NODES` leaves run in `make test`. Larger counts up to `MAX_DEPTH`
are marked `slow`, and deeper counts are kept as data only, since they take hours. The
engine counts of positions without deeper reference counts run the same way, so a speedup
that changes the move generation of a large hive fails as well.
"""

from pathlib import Path
from typing import Any

import pytest

from hive.bench import PerftPosition, PerftSuite, perft
from hive.engine.grid import Coordinate
from hive.engine.state import Move, PieceType

type MoveKey = tuple[PieceType, Coordinate | None, Coordinate] | None

SUITE = PerftSuite.load(Path(__file__).parents[1] / "data" / "perft" / "base.json")
SHALLOW_NODES = 1_000_000
MAX_DEPTH = 7


def count_params() -> list[Any]:
    """Build one parameter per position and depth, marking large counts as slow."""
    params = []

    for position in SUITE.positions:
        counts = position.engine_counts | position.counts

        for depth, count in sorted(counts.items()):
            if depth > MAX_DEPTH:
                continue

            marks = [pytest.mark.slow] if count > SHALLOW_NODES else []
            param_id = f"{position.name}-{depth}"
            params.append(pytest.param(position, depth, count, id=param_id, marks=marks))

    return params


def move_key(move: Move | None) -> MoveKey:
    """Get a hashable key for a move, since `Move` is not hashable."""
    if move is None:
        return None

    return (move.piece_type, move.source_coord, move.target_coord)


@pytest.mark.parametrize(("position", "depth", "count"), count_params())
def test_perft_matches_reference(position: PerftPosition, depth: int, count: int) -> None:
    state = position.state(SUITE.rules)

    assert perft(state=state, rules=SUITE.rules, depth=depth) == count


@pytest.mark.parametrize(
    "position",
    [
        pytest.param(position, id=position.name)
        for position in SUITE.positions
        if position.legal_moves is not None
    ],
)
def test_legal_moves_match_reference(position: PerftPosition) -> None:
    assert position.legal_moves is not None
    state = position.state(SUITE.rules)

    moves = [move_key(move) for move in SUITE.rules.legal_moves(state)]
    expected = [move_key(move) for move in position.legal_moves]

    assert len(moves) == len(set(moves))
    assert set(moves) == set(expected)
