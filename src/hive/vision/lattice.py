"""Hex lattice math of the vision pipeline: hex positions, motions and board comparison.

Axial coordinates map to the table plane, lattice frames differ by rigid motions, and
boards are compared up to those motions. A photo shows the board in an unknown frame: the
camera may be rotated by any angle and the hive may lie anywhere. Fitting a lattice to a
photo gives axial coordinates in its own frame, which differ from the engine coordinates
by one of six rotations and a translation (a `LatticeTransform`). Mirror images do not
occur, because a camera does not mirror the table.

The table plane uses x to the east and y to the south, like image coordinates of a table
seen from above with north up, so the map from the plane to a photo keeps orientation.
The distance between neighbouring hex centres is 1.
"""

import math
from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import Self

from hive.engine.grid import Coordinate

SQRT3 = math.sqrt(3)


def axial_to_plane(coord: Coordinate) -> tuple[float, float]:
    """Get the centre of a hex in the table plane.

    Args:
        coord: The axial coordinate `(q, r)`, as in the engine.

    Returns:
        The centre `(x, y)` with x to the east and y to the south.
    """
    q, r = coord

    return q + r / 2, SQRT3 / 2 * r


def plane_to_axial(x: float, y: float) -> tuple[float, float]:
    """Get the fractional axial coordinate of a point in the table plane.

    Args:
        x: The position to the east.
        y: The position to the south.

    Returns:
        The fractional axial coordinate `(q, r)`.
    """
    r = 2 * y / SQRT3

    return x - r / 2, r


def round_axial(q: float, r: float) -> Coordinate:
    """Round a fractional axial coordinate to the hex that contains it.

    Args:
        q: The fractional column.
        r: The fractional row.

    Returns:
        The axial coordinate of the nearest hex centre.
    """
    s = -q - r
    rounded_q, rounded_r, rounded_s = round(q), round(r), round(s)
    error_q, error_r, error_s = (
        abs(rounded_q - q),
        abs(rounded_r - r),
        abs(rounded_s - s),
    )

    if error_q > error_r and error_q > error_s:
        rounded_q = -rounded_r - rounded_s
    elif error_r > error_s:
        rounded_r = -rounded_q - rounded_s

    return rounded_q, rounded_r


def rotate_axial(coord: Coordinate, steps: int) -> Coordinate:
    """Rotate an axial coordinate around the origin in steps of 60 degrees.

    One step turns east `(1, 0)` into south-east `(0, 1)`, clockwise on screen.

    Args:
        coord: The axial coordinate.
        steps: The number of 60 degree steps; any integer.

    Returns:
        The rotated coordinate.
    """
    q, r = coord

    for _ in range(steps % 6):
        q, r = -r, q + r

    return q, r


@dataclass(frozen=True, slots=True)
class LatticeTransform:
    """A rigid motion of the hex lattice: a rotation around the origin, then a shift.

    Attributes:
        rotation: The number of 60 degree steps, between 0 and 5.
        translation: The axial offset added after rotating.
    """

    rotation: int
    translation: Coordinate

    def apply(self, coord: Coordinate) -> Coordinate:
        """Move a coordinate.

        Args:
            coord: The axial coordinate in the source frame.

        Returns:
            The axial coordinate in the target frame.
        """
        q, r = rotate_axial(coord=coord, steps=self.rotation)

        return q + self.translation[0], r + self.translation[1]

    def inverse(self) -> "LatticeTransform":
        """Get the motion that undoes this one.

        Returns:
            The inverse transform.
        """
        rotation = -self.rotation % 6
        q, r = rotate_axial(coord=self.translation, steps=rotation)

        return LatticeTransform(rotation=rotation, translation=(-q, -r))

    @classmethod
    def identity(cls) -> Self:
        """Get the motion that changes nothing.

        Returns:
            The identity transform.
        """
        return cls(rotation=0, translation=(0, 0))


def canonical_board[V: Hashable](
    board: Mapping[Coordinate, V],
) -> tuple[tuple[Coordinate, V], ...]:
    """Get a form of a board that is equal for boards that are rigid motions of another.

    Args:
        board: The value per coordinate, for example the stack as a tuple of pieces.

    Returns:
        The smallest of the six rotations, each translated so its smallest coordinate is
        the origin, as sorted `(coordinate, value)` pairs.
    """
    if not board:
        return ()

    forms = []

    for steps in range(6):
        rotated = {
            rotate_axial(coord=coord, steps=steps): value
            for coord, value in board.items()
        }
        origin_q, origin_r = min(rotated)
        forms.append(
            tuple(
                sorted(
                    ((q - origin_q, r - origin_r), value)
                    for (q, r), value in rotated.items()
                )
            )
        )

    return min(forms, key=repr)


def board_symmetries[V](board: Mapping[Coordinate, V]) -> list[LatticeTransform]:
    """Find the rigid motions that map a board onto itself, values included.

    Args:
        board: The value per coordinate.

    Returns:
        The motions, always including the identity.
    """
    if not board:
        return [LatticeTransform.identity()]

    symmetries = []
    target_origin = min(board)

    for steps in range(6):
        rotated = {
            rotate_axial(coord=coord, steps=steps): value
            for coord, value in board.items()
        }
        origin = min(rotated)
        translation = (target_origin[0] - origin[0], target_origin[1] - origin[1])
        transform = LatticeTransform(rotation=steps, translation=translation)

        if all(
            board.get(transform.apply(coord)) == value for coord, value in board.items()
        ):
            symmetries.append(transform)

    return symmetries
