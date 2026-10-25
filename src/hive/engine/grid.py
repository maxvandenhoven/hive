from functools import cache

from pydantic import StrictInt

type Coordinate = tuple[StrictInt, StrictInt]
"""An axial coordinate `(q, r)` representing a position on the hex grid.

The first element `q` represents the column and the second element `r` represents the row
in the axial coordinate system. Together they uniquely identify a hexagonal cell in the
"pointy top" orientation. The JSON form is a `[q, r]` list of integers; `StrictInt` only
affects reading JSON, where it rejects strings and booleans.
"""

type Direction = tuple[int, int]
"""An axial coordinate direction `(dq, dr)` representing a relative move on the hex grid.

The first element `dq` represents the column offset and the second element `dr` represents
the row offset. A direction can be added to a coordinate to get the coordinate of a
neighboring hexagonal cell.
"""


HEX_DIRECTIONS: list[Direction] = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
"""Axial coordinate directions `(dq, dr)` to get the direct neighbors of a coordinate.

In the "pointy top" orientation, the first direction `(1, 0)` indicates the neighbor
directly to the right (east) of the reference coordinate. The directions then move
anti-clockwise around the reference coordinate. For example, the second direction
`(1, -1)` is the top-right neighbor and the third direction `(0, -1)` is the top-left
neighbor.
"""

HEX_DIRECTIONS_ANTI_CLOCKWISE: dict[Direction, Direction] = {
    direction: HEX_DIRECTIONS[(i + 1) % 6] for i, direction in enumerate(HEX_DIRECTIONS)
}
"""Mapping between axial coordinate directions and their anti-clockwise counterparts.

This dictionary maps each axial direction to the direction that points to the 
anti-clockwise neighbor. For example, the direction `(1, 0)` points to the right neighbor,
so the corresponding anti-clockwise direction `(1, -1)` points to the top-right neighbor.
Note that the values are essentially a right-shifted version of the keys.
"""

HEX_DIRECTIONS_CLOCKWISE: dict[Direction, Direction] = {
    direction: HEX_DIRECTIONS[(i - 1) % 6] for i, direction in enumerate(HEX_DIRECTIONS)
}
"""Mapping between axial coordinate directions and their clockwise counterparts.

This dictionary maps each axial direction to the direction that points to the clockwise
neighbor. For example, the direction `(1, 0)` points to the right neighbor, so the
corresponding clockwise direction `(0, 1)` points to the bottom-right neighbor. Note that
the values are essentially a left-shifted version of the keys.
"""


def add(coord: Coordinate, direction: Direction) -> Coordinate:
    """Add a hex grid direction to a coordinate to get a new coordinate.

    Args:
        coord: The axial coordinate `(q, r)` to add the direction to.
        direction: The direction `(dq, dr)` to add to the coordinate.

    Returns:
        The new axial coordinate `(q + dq, r + dr)`.
    """
    return (coord[0] + direction[0], coord[1] + direction[1])


@cache
def get_neighbors(coord: Coordinate) -> list[Coordinate]:
    """Get the six coordinates that directly neighbor the reference coordinate.

    The result is cached indefinitely — neighbor sets depend only on the coordinate and
    are the same for every board position, so the cache never needs to be invalidated. The
    returned list must not be modified by callers.

    Args:
        coord: The axial coordinate `(q, r)` to get the neighbors for.

    Returns:
        The six axial coordinates `(q', r')` that directly neighbor `(q, r)`.
    """
    return [add(coord=coord, direction=direction) for direction in HEX_DIRECTIONS]


def get_anti_clockwise_direction(direction: Direction) -> Direction:
    """Get the anti-clockwise direction for a given direction.

    Args:
        direction: The axial coordinate direction `(dq, dr)` to rotate.

    Returns:
        The axial coordinate direction `(dq', dr')` that points to the neighbor directly
        anti-clockwise from neighbor `(q + dq, r + dr)`.
    """
    return HEX_DIRECTIONS_ANTI_CLOCKWISE[direction]


def get_clockwise_direction(direction: Direction) -> Direction:
    """Get the clockwise direction for a given direction.

    Args:
        direction: The axial coordinate direction `(dq, dr)` to rotate.

    Returns:
        The axial coordinate direction `(dq', dr')` that points to the neighbor directly
        clockwise from neighbor `(q + dq, r + dr)`.
    """
    return HEX_DIRECTIONS_CLOCKWISE[direction]


def get_direction(source_coord: Coordinate, target_coord: Coordinate) -> Direction:
    """Get the axial coordinate direction to move from one coordinate to another.

    Args:
        source_coord: The axial coordinate `(q, r)` from which the pieces moves.
        target_coord: The axial coordinate `(q', r')` that the piece moves into.

    Returns:
        The axial coordinate direction `(dq, dr)` to move from `(q, r)` to `(q', r')`.
    """
    return (target_coord[0] - source_coord[0], target_coord[1] - source_coord[1])


def get_flanking_coords(
    source_coord: Coordinate, target_coord: Coordinate
) -> tuple[Coordinate, Coordinate]:
    """Get the two coordinates that neighbor both a coordinate and its neighbor.

    A piece sliding from the source to the target passes between these coordinates.

    Args:
        source_coord: The axial coordinate `(q, r)` from which the piece moves.
        target_coord: The neighboring axial coordinate `(q', r')` the piece moves to.

    Returns:
        The anti-clockwise and the clockwise flanking coordinate, seen from the source.
    """
    direction = get_direction(source_coord=source_coord, target_coord=target_coord)
    return (
        add(coord=source_coord, direction=get_anti_clockwise_direction(direction)),
        add(coord=source_coord, direction=get_clockwise_direction(direction)),
    )
