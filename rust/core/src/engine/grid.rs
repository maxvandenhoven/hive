//! Hex grid geometry: axial coordinates, directions and the cells of the board grid.
//!
//! Coordinates are axial `(q, r)` pairs in the "pointy top" orientation, the same as in
//! the Python package. The board keeps its pieces in a grid of [`CELL_COUNT`] cells, a
//! 32 × 32 twisted torus: the cell of `(q, r)` is `(q + 32 r) mod 1024`, so the six
//! neighbours of every cell are at constant index offsets and a neighbour is one add and
//! one mask.
//!
//! Two coordinates share a cell only if their `q` or their `r` differ by 32 or more. The
//! engine reads cells at most two steps from the hive, which spans at most `n + 3` in
//! `q` and in `r` for `n` connected pieces, so with at most [`MAX_PIECES`] pieces no two
//! cells the engine reads share an index.

use std::fmt;

/// The width of the board grid in cells.
pub const GRID_WIDTH: i32 = 32;

/// The number of cells of the board grid.
pub const CELL_COUNT: usize = 1024;

/// The most pieces a game may have in total, so that cells never alias.
pub const MAX_PIECES: usize = 28;

/// The mask that wraps a cell index into the grid.
const CELL_MASK: u16 = 1023;

/// The number of hex directions.
pub const DIRECTION_COUNT: usize = 6;

/// An axial hex coordinate `(q, r)`.
///
/// The ordering is lexicographic, the order of Python tuples, so sorted coordinates match
/// the sorted order of the Python package.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Coord {
    /// The column of the coordinate.
    pub q: i32,
    /// The row of the coordinate.
    pub r: i32,
}

/// The six directions `(dq, dr)` to the neighbours of a coordinate.
///
/// The first direction points east, and the others follow anti-clockwise, the order of
/// `HEX_DIRECTIONS` in the Python package.
pub const DIRECTIONS: [Coord; DIRECTION_COUNT] = [
    Coord::new(1, 0),
    Coord::new(1, -1),
    Coord::new(0, -1),
    Coord::new(-1, 0),
    Coord::new(-1, 1),
    Coord::new(0, 1),
];

/// The cell index offset of each direction, modulo [`CELL_COUNT`].
const NEIGHBOR_OFFSETS: [u16; DIRECTION_COUNT] = [1, 993, 992, 1023, 31, 32];

/// Get the direction next to `direction` in the anti-clockwise order.
///
/// A piece sliding from a cell in `direction` passes between the neighbours in the
/// anti-clockwise and the clockwise direction next to it.
pub const fn anti_clockwise(direction: usize) -> usize {
    (direction + 1) % DIRECTION_COUNT
}

/// Get the direction next to `direction` in the clockwise order.
pub const fn clockwise(direction: usize) -> usize {
    (direction + DIRECTION_COUNT - 1) % DIRECTION_COUNT
}

/// Get the direction that points back to where `direction` came from.
pub const fn opposite(direction: usize) -> usize {
    (direction + 3) % DIRECTION_COUNT
}

impl Coord {
    /// The origin `(0, 0)`, where the first piece of a game is placed.
    pub const ORIGIN: Coord = Coord::new(0, 0);

    /// Create a coordinate from its column and row.
    pub const fn new(q: i32, r: i32) -> Self {
        Coord { q, r }
    }

    /// Get the neighbouring coordinate in a direction (an index into [`DIRECTIONS`]).
    pub const fn neighbor(self, direction: usize) -> Self {
        let step = DIRECTIONS[direction];
        Coord::new(self.q.wrapping_add(step.q), self.r.wrapping_add(step.r))
    }

    /// Get the six neighbouring coordinates, in the order of [`DIRECTIONS`].
    pub fn neighbors(self) -> [Coord; DIRECTION_COUNT] {
        std::array::from_fn(|direction| self.neighbor(direction))
    }

    /// Get the cell of the board grid that holds the coordinate.
    #[expect(
        clippy::cast_sign_loss,
        reason = "the index is masked to 0..1024 before the cast"
    )]
    pub const fn cell(self) -> Cell {
        let index = self.q.wrapping_add(self.r.wrapping_mul(GRID_WIDTH)) & 1023;
        Cell(index as u16)
    }
}

/// Coordinates are written like Python tuples, `(q, r)`, as in the messages of the
/// Python package.
impl fmt::Display for Coord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "({}, {})", self.q, self.r)
    }
}

/// A cell of the board grid, which holds the coordinates congruent modulo the grid.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Cell(u16);

impl Cell {
    /// Create a cell from its index.
    ///
    /// # Panics
    ///
    /// Panics if `index` is not below [`CELL_COUNT`].
    pub fn from_index(index: usize) -> Self {
        assert!(index < CELL_COUNT, "the cell index `{index}` is outside the grid");
        Cell(u16::try_from(index).expect("a cell index fits in 16 bits"))
    }

    /// Get the index of the cell, below [`CELL_COUNT`].
    pub const fn index(self) -> usize {
        self.0 as usize
    }

    /// Get the index of the cell as the 16 bits it is stored in.
    pub const fn bits(self) -> u16 {
        self.0
    }

    /// Get the neighbouring cell in a direction (an index into [`DIRECTIONS`]).
    #[inline]
    pub const fn neighbor(self, direction: usize) -> Self {
        Cell((self.0 + NEIGHBOR_OFFSETS[direction]) & CELL_MASK)
    }

    /// Get the coordinate of the cell nearest to the origin, with `q` and `r` in
    /// `-16..16`.
    ///
    /// This is the coordinate of the cell on an empty board, where a placement can only
    /// be at the origin or next to it.
    pub const fn coord_near_origin(self) -> Coord {
        let index = self.0 as i32;
        let q = ((index + 16) & 31) - 16;
        let r = ((((index - q) >> 5) + 16) & 31) - 16;
        Coord::new(q, r)
    }
}

/// A set of cells as a 1024-bit set, cheap to create on the stack for one search.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CellSet {
    /// One bit per cell, 64 cells per word.
    words: [u64; CELL_COUNT / 64],
}

impl Default for CellSet {
    fn default() -> Self {
        Self::new()
    }
}

impl CellSet {
    /// Create an empty set.
    pub const fn new() -> Self {
        CellSet { words: [0; CELL_COUNT / 64] }
    }

    /// Check whether the set holds a cell.
    #[inline]
    pub const fn contains(&self, cell: Cell) -> bool {
        self.words[cell.index() / 64] & (1 << (cell.index() % 64)) != 0
    }

    /// Add a cell, and report whether it was new to the set.
    #[inline]
    pub fn insert(&mut self, cell: Cell) -> bool {
        let word = &mut self.words[cell.index() / 64];
        let bit = 1 << (cell.index() % 64);
        let new = *word & bit == 0;
        *word |= bit;
        new
    }

    /// Remove a cell from the set.
    #[inline]
    pub fn remove(&mut self, cell: Cell) {
        self.words[cell.index() / 64] &= !(1 << (cell.index() % 64));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn neighbor_cells_match_neighbor_coordinates() {
        for q in -40..40 {
            for r in -40..40 {
                let coord = Coord::new(q, r);

                for direction in 0..DIRECTION_COUNT {
                    assert_eq!(
                        coord.neighbor(direction).cell(),
                        coord.cell().neighbor(direction)
                    );
                }
            }
        }
    }

    #[test]
    fn cells_near_the_origin_decode_to_their_coordinates() {
        for q in -16..16 {
            for r in -16..16 {
                let coord = Coord::new(q, r);
                assert_eq!(coord.cell().coord_near_origin(), coord);
            }
        }
    }

    #[test]
    fn coordinates_less_than_a_grid_width_apart_never_share_a_cell() {
        let origin = Coord::ORIGIN.cell();

        for q in -31..32 {
            for r in -31..32 {
                if (q, r) != (0, 0) {
                    assert_ne!(Coord::new(q, r).cell(), origin, "({q}, {r})");
                }
            }
        }
    }

    #[test]
    fn opposite_directions_cancel() {
        for direction in 0..DIRECTION_COUNT {
            let coord = Coord::new(3, -2);
            assert_eq!(coord.neighbor(direction).neighbor(opposite(direction)), coord);
            assert_eq!(clockwise(anti_clockwise(direction)), direction);
        }
    }

    #[test]
    fn cell_sets_track_membership() {
        let mut set = CellSet::new();
        let cell = Coord::new(-5, 7).cell();

        assert!(set.insert(cell));
        assert!(!set.insert(cell));
        assert!(set.contains(cell));
        set.remove(cell);
        assert!(!set.contains(cell));
    }

    #[test]
    fn coordinates_display_like_python_tuples() {
        assert_eq!(Coord::new(1, -2).to_string(), "(1, -2)");
    }
}
