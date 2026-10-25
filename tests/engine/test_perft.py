"""Perft parity against the reference counts in `tests/data/perft/base.json`.

Counts up to `_SHALLOW_NODES` leaves run in `make test`. Larger counts up to `_MAX_DEPTH`
are marked `slow`, and deeper counts are kept as data only, since they take hours.
"""

from pathlib import Path
from typing import Any

import pytest

from hive.bench import PerftPosition, PerftSuite, perft
from hive.engine.grid import Coordinate
from hive.engine.state import Move, PieceType

type MoveKey = tuple[PieceType, Coordinate | None, Coordinate] | None

_SUITE = PerftSuite.load(Path(__file__).parents[1] / "data" / "perft" / "base.json")
_SHALLOW_NODES = 1_000_000
_MAX_DEPTH = 7


def _count_params() -> list[Any]:
    """Build one parameter per position and depth, marking large counts as slow."""
    params = []

    for position in _SUITE.positions:
        for depth, count in sorted(position.counts.items()):
            if depth > _MAX_DEPTH:
                continue

            marks = [pytest.mark.slow] if count > _SHALLOW_NODES else []
            param_id = f"{position.name}-{depth}"
            params.append(pytest.param(position, depth, count, id=param_id, marks=marks))

    return params


def _move_key(move: Move | None) -> MoveKey:
    """Get a hashable key for a move, since `Move` is not hashable."""
    if move is None:
        return None

    return (move.piece_type, move.source_coord, move.target_coord)


@pytest.mark.parametrize(("position", "depth", "count"), _count_params())
def test_perft_matches_reference(position: PerftPosition, depth: int, count: int) -> None:
    state = position.state(_SUITE.rules)

    assert perft(state, _SUITE.rules, depth) == count


@pytest.mark.parametrize(
    "position",
    [
        pytest.param(position, id=position.name)
        for position in _SUITE.positions
        if position.legal_moves is not None
    ],
)
def test_legal_moves_match_reference(position: PerftPosition) -> None:
    assert position.legal_moves is not None
    state = position.state(_SUITE.rules)

    moves = [_move_key(move) for move in _SUITE.rules.legal_moves(state)]
    expected = [_move_key(move) for move in position.legal_moves]

    assert len(moves) == len(set(moves))
    assert set(moves) == set(expected)
