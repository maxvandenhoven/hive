from hive_engine.grid import (
    HEX_DIRECTIONS,
    add,
    get_anti_clockwise_direction,
    get_clockwise_direction,
    get_direction,
    get_neighbors,
)


class TestAdd:
    """Test the `add` coordinate addition."""

    def test_coordinate_addition(self):
        """Test that adding two coordinates produces the correct result."""
        assert add((0, 0), (0, 0)) == (0, 0)
        assert add((0, 0), (1, 0)) == (1, 0)
        assert add((2, -1), (-1, 1)) == (1, 0)


class TestNeighbors:
    """Test the `get_neighbors` neighbor lookup."""

    def test_neighbor_count(self):
        """Test that exactly six neighbors are returned."""
        neighbors = get_neighbors((0, 0))
        assert len(neighbors) == 6

    def test_neighbor_positions(self):
        """Test that the correct six neighbors are returned for the origin."""
        neighbors = get_neighbors((0, 0))
        expected = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
        assert set(neighbors) == set(expected)

    def test_cached_identity(self):
        """Test that repeated calls with the same coordinate return the same object."""
        n1 = get_neighbors((0, 0))
        n2 = get_neighbors((0, 0))
        assert n1 is n2


class TestDirectionRotation:
    """Test the (anti-)clockwise rotation functions."""

    def test_anti_clockwise_rotation_cycle(self):
        """Test that six anti-clockwise rotations return to the original direction."""
        start_direction = (1, 0)
        current_direction = start_direction
        for _ in range(6):
            current_direction = get_anti_clockwise_direction(current_direction)
        assert current_direction == start_direction

    def test_clockwise_rotation_cycle(self):
        """Test that six clockwise rotations return to the original direction."""
        start_direction = (1, 0)
        current_direction = start_direction
        for _ in range(6):
            current_direction = get_clockwise_direction(current_direction)
        assert current_direction == start_direction

    def test_clockwise_then_anticlockwise(self):
        """Test that clockwise and anti-clockwise rotations are inverses."""
        for direction in HEX_DIRECTIONS:
            rotated = get_clockwise_direction(direction)
            restored = get_anti_clockwise_direction(rotated)
            assert restored == direction

    def test_anticlockwise_then_clockwise(self):
        """Test that anti-clockwise and clockwise rotations are inverses."""
        for direction in HEX_DIRECTIONS:
            rotated = get_anti_clockwise_direction(direction)
            restored = get_clockwise_direction(rotated)
            assert restored == direction


class TestGetDirection:
    """Test the `get_direction` direction calculation."""

    def test_basic_directions(self):
        """Test basic direction calculations."""
        assert get_direction((0, 0), (1, 0)) == (1, 0)
        assert get_direction((0, 0), (1, -1)) == (1, -1)
        assert get_direction((2, 3), (1, 3)) == (-1, 0)
        assert get_direction((2, 3), (2, 4)) == (0, 1)

    def test_inverse_of_add(self):
        """Test that `get_direction` is the inverse of `add`."""
        source_coord = (5, -2)
        for direction in HEX_DIRECTIONS:
            target_coord = add(source_coord, direction)
            computed_direction = get_direction(source_coord, target_coord)
            assert computed_direction == direction

    def test_non_neighboring_coordinates(self):
        """Test that `get_direction` works for non-neighboring coordinates."""
        assert get_direction((0, 0), (2, -2)) == (2, -2)
