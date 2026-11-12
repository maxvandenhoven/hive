import math

import pytest
from hiveblend.geometry import (
    axial_to_plane,
    hex_to_linear_rgb,
    kelvin_to_rgb,
    offset_direction,
    polygon_area,
    rounded_hexagon,
)


def test_rounded_hexagon_without_rounding_is_the_hexagon() -> None:
    points = rounded_hexagon(apothem=1.0, corner_radius=0.0, corner_segments=1)
    corners = {(round(x, 9), round(y, 9)) for x, y in points}
    circumradius = 2 / math.sqrt(3)

    assert len(corners) == 6
    assert (0.0, round(circumradius, 9)) in corners
    assert polygon_area(points) == pytest.approx(2 * math.sqrt(3))


def test_rounded_hexagon_touches_its_sides() -> None:
    points = rounded_hexagon(apothem=1.0, corner_radius=0.2, corner_segments=8)

    assert len(points) == 6 * 9
    assert max(x for x, _ in points) == pytest.approx(1.0)
    assert max(math.hypot(x, y) for x, y in points) < 2 / math.sqrt(3)
    assert polygon_area(points) > 0
    assert polygon_area(list(reversed(points))) < 0


def test_neighbours_are_one_spacing_apart() -> None:
    spacing = 1.04

    for q, r in [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]:
        x, y = axial_to_plane(q=q, r=r, spacing=spacing)

        assert math.hypot(x, y) == pytest.approx(spacing)

    assert axial_to_plane(q=1, r=0, spacing=1.0) == pytest.approx((1.0, 0.0))
    assert axial_to_plane(q=0, r=-1, spacing=1.0)[0] < 0
    assert axial_to_plane(q=0, r=-1, spacing=1.0)[1] > 0


def test_kelvin_colours_go_from_warm_to_cool() -> None:
    warm = kelvin_to_rgb(2700)
    neutral = kelvin_to_rgb(6600)
    cool = kelvin_to_rgb(12000)

    assert max(warm) == pytest.approx(1.0)
    assert warm[0] > warm[2]
    assert neutral == pytest.approx((1.0, 1.0, 1.0), abs=0.03)
    assert cool[2] > cool[0]


def test_hex_to_linear_rgb() -> None:
    assert hex_to_linear_rgb("#FFFFFF") == pytest.approx((1.0, 1.0, 1.0))
    assert hex_to_linear_rgb("#000000") == pytest.approx((0.0, 0.0, 0.0))
    assert hex_to_linear_rgb("#808080")[0] == pytest.approx(0.2158, abs=1e-3)


def test_offset_direction() -> None:
    assert offset_direction(offset=(0.0, 0.0), horizontal_fov=1.0, vertical_fov=0.8) == (
        pytest.approx((0.0, 0.0, -1.0))
    )

    x, y, z = offset_direction(
        offset=(1.0, -1.0), horizontal_fov=math.pi / 2, vertical_fov=1.0
    )

    assert x / -z == pytest.approx(1.0)
    assert y / -z == pytest.approx(-math.tan(0.5))
    assert math.hypot(x, y, z) == pytest.approx(1.0)
