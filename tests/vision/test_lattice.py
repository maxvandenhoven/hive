import random

import pytest

from hive.engine.grid import HEX_DIRECTIONS
from hive.vision.lattice import (
    LatticeTransform,
    axial_to_plane,
    board_symmetries,
    canonical_board,
    plane_to_axial,
    rotate_axial,
    round_axial,
)


def test_plane_round_trip_and_rounding() -> None:
    rng = random.Random(0)

    for _ in range(200):
        coord = (rng.randint(-9, 9), rng.randint(-9, 9))
        x, y = axial_to_plane(coord)

        assert plane_to_axial(x, y) == pytest.approx(coord)
        assert round_axial(*plane_to_axial(x + rng.uniform(-0.4, 0.4), y)) == coord


def test_neighbours_are_one_apart_and_south_is_positive() -> None:
    for direction in HEX_DIRECTIONS:
        x, y = axial_to_plane(direction)

        assert x**2 + y**2 == pytest.approx(1.0)

    assert axial_to_plane((0, 1))[1] > 0
    assert axial_to_plane((0, -1))[1] < 0


def test_rotation_cycles_through_the_directions() -> None:
    assert [rotate_axial(coord=(1, 0), steps=k) for k in range(6)] == [
        (1, 0),
        (0, 1),
        (-1, 1),
        (-1, 0),
        (0, -1),
        (1, -1),
    ]
    assert rotate_axial(coord=(3, -2), steps=6) == (3, -2)
    assert rotate_axial(coord=(3, -2), steps=-1) == rotate_axial(coord=(3, -2), steps=5)


def test_transform_inverse_undoes_it() -> None:
    rng = random.Random(1)

    for _ in range(50):
        transform = LatticeTransform(
            rotation=rng.randrange(6),
            translation=(rng.randint(-5, 5), rng.randint(-5, 5)),
        )
        coord = (rng.randint(-5, 5), rng.randint(-5, 5))

        assert transform.inverse().apply(transform.apply(coord)) == coord


def test_canonical_board_ignores_rigid_motions_but_not_mirrors() -> None:
    board = {(0, 0): "a", (1, 0): "b", (1, -1): "c", (2, -1): "d"}
    moved = {
        LatticeTransform(rotation=4, translation=(7, -3)).apply(coord): value
        for coord, value in board.items()
    }
    mirrored = {(-q - r, r): value for (q, r), value in board.items()}

    assert canonical_board(moved) == canonical_board(board)
    assert canonical_board(mirrored) != canonical_board(board)
    assert canonical_board({}) == ()


@pytest.mark.parametrize(
    ("board", "count"),
    [
        ({(0, 0): "a"}, 6),
        ({(0, 0): "a", (1, 0): "b"}, 1),
        ({(0, 0): "a", (1, 0): "a"}, 2),
        ({}, 1),
    ],
)
def test_board_symmetries(board: dict[tuple[int, int], str], count: int) -> None:
    symmetries = board_symmetries(board)

    assert len(symmetries) == count

    for symmetry in symmetries:
        assert {symmetry.apply(coord): value for coord, value in board.items()} == board
