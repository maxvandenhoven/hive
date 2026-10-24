import math
from enum import IntEnum

from hive.engine.state import Coordinate


class HexOrientation(IntEnum):
    """The visual orientation of hexagons on the board."""

    POINTY_TOP = 0
    FLAT_TOP = 1


def axial_to_pixel(
    q: int, r: int, orientation: HexOrientation, size: float = 1.0
) -> tuple[float, float]:
    """Convert axial hex coordinates to pixel `(x, y)` positions.

    Args:
        q: The column coordinate in the axial system.
        r: The row coordinate in the axial system.
        orientation: Whether hexagons are pointy-top or flat-top.
        size: The radius of each hexagon (center to vertex), by default 1.0.

    Returns:
        The `(x, y)` pixel position of the hex center.
    """
    if orientation is HexOrientation.POINTY_TOP:
        x = size * (math.sqrt(3) * q + math.sqrt(3) / 2 * r)
        y = size * (3 / 2 * r)
    else:
        x = size * (3 / 2 * q)
        y = size * (math.sqrt(3) / 2 * q + math.sqrt(3) * r)

    return x, y


def get_hex_points(
    cx: float, cy: float, orientation: HexOrientation, size: float = 1.0
) -> list[float]:
    """Compute the flat list of hex corner coordinates for drawsvg.

    Args:
        cx: The x-coordinate of the hex center.
        cy: The y-coordinate of the hex center.
        orientation: Whether hexagons are pointy-top or flat-top.
        size: The radius of the hexagon (center to vertex), by default 1.0.

    Returns:
        A flat list `[x0, y0, x1, y1, ..., x5, y5]` of the six corner coordinates.
    """
    angle_offset = 30.0 if orientation is HexOrientation.POINTY_TOP else 0.0

    points: list[float] = []
    for i in range(6):
        angle_rad = math.radians(60.0 * i + angle_offset)
        points.append(cx + size * math.cos(angle_rad))
        points.append(cy + size * math.sin(angle_rad))

    return points


def get_grid_coords(radius: int) -> list[Coordinate]:
    """Generate all axial coordinates within a given hex radius of the origin.

    Args:
        radius: The maximum hex distance from `(0, 0)` to include.

    Returns:
        All axial coordinates `(q, r)` within the specified radius.
    """
    coords: list[Coordinate] = []
    for q in range(-radius, radius + 1):
        r_min = max(-radius, -q - radius)
        r_max = min(radius, -q + radius)
        for r in range(r_min, r_max + 1):
            coords.append((q, r))

    return coords


def get_distance(source_coord: Coordinate, target_coord: Coordinate) -> int:
    """Compute the hex distance between two axial coordinates.

    Args:
        source_coord: The first axial coordinate `(q, r)`.
        target_coord: The second axial coordinate `(q', r')`.

    Returns:
        The number of hex steps between `source_coord` and `target_coord`.
    """
    dq = source_coord[0] - target_coord[0]
    dr = source_coord[1] - target_coord[1]

    return (abs(dq) + abs(dq + dr) + abs(dr)) // 2
