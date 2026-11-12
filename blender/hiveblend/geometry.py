"""Geometry and colour math of the renderer, without `bpy`, so tests can import it.

Lengths are in metres unless a name says otherwise. Hexagons are pointy-top, like the
engine grid: a corner points up (+y) and the flat sides face east and west.
"""

import colorsys
import math
from collections.abc import Sequence

type Point2 = tuple[float, float]
"""A point or vector in the plane."""

SQRT3 = math.sqrt(3.0)


def rounded_hexagon(
    apothem: float, corner_radius: float, corner_segments: int
) -> list[Point2]:
    """Get the outline of a pointy-top hexagon with rounded corners.

    The outline is the hexagon with the given apothem (half the across-flats width) whose
    corners are replaced by circular arcs tangent to both sides.

    Args:
        apothem: The distance from the centre to the middle of each side.
        corner_radius: The radius of the corner arcs, at most `apothem`.
        corner_segments: The number of straight segments per corner arc, at least 1.

    Returns:
        The outline points anti-clockwise, starting at the east side, without repeating
        the first point.
    """
    radius = min(max(corner_radius, 0.0), apothem)
    # The arc centres are the corners of the hexagon whose apothem is shrunk by the arc
    # radius, so each arc touches the two sides of its corner.
    centre_distance = (apothem - radius) / math.cos(math.pi / 6)
    points: list[Point2] = []

    for corner in range(6):
        corner_angle = math.pi / 6 + corner * math.pi / 3
        centre_x = centre_distance * math.cos(corner_angle)
        centre_y = centre_distance * math.sin(corner_angle)

        for step in range(corner_segments + 1):
            angle = corner_angle - math.pi / 6 + step * (math.pi / 3) / corner_segments
            points.append(
                (centre_x + radius * math.cos(angle), centre_y + radius * math.sin(angle))
            )

    return points


def polygon_area(points: Sequence[Point2]) -> float:
    """Get the area of a simple polygon with the shoelace formula.

    Args:
        points: The polygon corners in order, without repeating the first one.

    Returns:
        The area, positive for anti-clockwise and negative for clockwise polygons.
    """
    total = 0.0

    for index, (x, y) in enumerate(points):
        next_x, next_y = points[(index + 1) % len(points)]
        total += x * next_y - next_x * y

    return total / 2.0


def axial_to_plane(q: int, r: int, spacing: float) -> Point2:
    """Get the centre of a pointy-top hex cell in the plane.

    Axial direction `(1, 0)` points east and `(0, -1)` points to the top left, as in the
    engine grid.

    Args:
        q: The axial column.
        r: The axial row.
        spacing: The distance between the centres of two neighbouring cells.

    Returns:
        The centre `(x, y)`, with y pointing up.
    """
    return spacing * (q + r / 2.0), -spacing * SQRT3 / 2.0 * r


def kelvin_to_rgb(temperature_k: float) -> tuple[float, float, float]:
    """Approximate the colour of a black body, normalised so the brightest channel is 1.

    Uses the curve fit by Tanner Helland, which is accurate enough for light colours
    between 1000 K and 40000 K.

    Args:
        temperature_k: The colour temperature in kelvin.

    Returns:
        The linear-ish RGB colour with channels between 0 and 1.
    """
    t = min(max(temperature_k, 1000.0), 40000.0) / 100.0

    if t <= 66:
        red = 255.0
        green = 99.4708025861 * math.log(t) - 161.1195681661
        blue = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        red = 329.698727446 * (t - 60) ** -0.1332047592
        green = 288.1221695283 * (t - 60) ** -0.0755148492
        blue = 255.0

    channels = [min(max(value, 0.0), 255.0) / 255.0 for value in (red, green, blue)]
    peak = max(channels)

    return channels[0] / peak, channels[1] / peak, channels[2] / peak


def srgb_to_linear(value: float) -> float:
    """Convert an sRGB channel value to linear light.

    Args:
        value: The sRGB value between 0 and 1.

    Returns:
        The linear value between 0 and 1.
    """
    if value <= 0.04045:
        return value / 12.92

    return ((value + 0.055) / 1.055) ** 2.4


def hex_to_linear_rgb(color: str) -> tuple[float, float, float]:
    """Convert a `#rrggbb` colour to linear RGB.

    Args:
        color: The colour as six hex digits after a `#`.

    Returns:
        The linear RGB channels between 0 and 1.
    """
    digits = color.lstrip("#")

    return (
        srgb_to_linear(int(digits[0:2], 16) / 255),
        srgb_to_linear(int(digits[2:4], 16) / 255),
        srgb_to_linear(int(digits[4:6], 16) / 255),
    )


def shift_color(
    color: str, hue_shift: float, saturation_scale: float, value_scale: float
) -> tuple[float, float, float]:
    """Shift a `#rrggbb` colour in HSV space and convert it to linear RGB.

    Args:
        color: The sRGB colour as six hex digits after a `#`.
        hue_shift: The hue change as a fraction of the colour wheel.
        saturation_scale: The factor the saturation is multiplied by, clamped to 1.
        value_scale: The factor the value is multiplied by, clamped to 1.

    Returns:
        The linear RGB channels between 0 and 1.
    """
    digits = color.lstrip("#")
    red, green, blue = (int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    shifted = colorsys.hsv_to_rgb(
        (hue + hue_shift) % 1.0,
        min(saturation * saturation_scale, 1.0),
        min(value * value_scale, 1.0),
    )

    return (
        srgb_to_linear(shifted[0]),
        srgb_to_linear(shifted[1]),
        srgb_to_linear(shifted[2]),
    )


def offset_direction(
    offset: Point2, horizontal_fov: float, vertical_fov: float
) -> tuple[float, float, float]:
    """Get the view direction in camera space at which a point appears at an offset.

    Args:
        offset: The position in the frame, from -1 (left, bottom) to 1 (right, top).
        horizontal_fov: The horizontal field of view in radians.
        vertical_fov: The vertical field of view in radians.

    Returns:
        The unit direction in camera space, where the camera looks along -z with y up.
    """
    x = offset[0] * math.tan(horizontal_fov / 2)
    y = offset[1] * math.tan(vertical_fov / 2)
    length = math.sqrt(x * x + y * y + 1.0)

    return x / length, y / length, -1.0 / length
