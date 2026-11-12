//! The board: stacks of pieces on the cells of the grid.

use crate::engine::grid::{CELL_COUNT, Cell, Coord, DIRECTION_COUNT, opposite};
use crate::engine::piece::Piece;
use crate::engine::zobrist::piece_key;

/// The most pieces a stack holds: a piece with all four beetles on top in the base game,
/// with room for the climbing pieces of the expansions.
pub const MAX_STACK_HEIGHT: usize = 8;

/// The most occupied cells a board holds, the width of the masks over them.
pub const MAX_OCCUPIED_CELLS: usize = 64;

/// The stacks of pieces on the grid, with the real coordinate of every occupied cell.
///
/// The occupied cells are also kept in a list, and each has a slot (its position in the
/// list), so connectivity and articulation points work on 64-bit masks over slots. The
/// Zobrist hash of the pieces is updated by every push and pop.
#[derive(Clone)]
pub struct Board {
    /// The number of pieces on each cell.
    heights: [u8; CELL_COUNT],
    /// The pieces on each cell, bottom to top; only the first `heights` entries count.
    stacks: [[Piece; MAX_STACK_HEIGHT]; CELL_COUNT],
    /// The real coordinate of each occupied cell.
    coords: [Coord; CELL_COUNT],
    /// The occupied cells, in no particular order.
    occupied: Vec<Cell>,
    /// The position of each occupied cell in `occupied`.
    slots: [u8; CELL_COUNT],
    /// The XOR of the Zobrist keys of all pieces.
    hash: u64,
}

impl Default for Board {
    fn default() -> Self {
        Self::new()
    }
}

impl Board {
    /// Create an empty board.
    pub fn new() -> Self {
        Board {
            heights: [0; CELL_COUNT],
            stacks: [[Piece::default(); MAX_STACK_HEIGHT]; CELL_COUNT],
            coords: [Coord::ORIGIN; CELL_COUNT],
            occupied: Vec::with_capacity(32),
            slots: [0; CELL_COUNT],
            hash: 0,
        }
    }

    /// Get the number of pieces on a cell.
    #[inline]
    pub fn height(&self, cell: Cell) -> usize {
        usize::from(self.heights[cell.index()])
    }

    /// Check whether a cell holds at least one piece.
    #[inline]
    pub fn is_occupied(&self, cell: Cell) -> bool {
        self.heights[cell.index()] != 0
    }

    /// Get the top piece of an occupied cell.
    ///
    /// The cell must be occupied; an empty cell returns an arbitrary piece in release
    /// builds.
    #[inline]
    pub fn top(&self, cell: Cell) -> Piece {
        debug_assert!(self.is_occupied(cell), "no piece on {cell:?}");
        let height = self.height(cell);
        self.stacks[cell.index()][height.saturating_sub(1)]
    }

    /// Get the pieces on a cell, bottom to top.
    pub fn stack(&self, cell: Cell) -> &[Piece] {
        &self.stacks[cell.index()][..self.height(cell)]
    }

    /// Get the real coordinate of an occupied cell.
    #[inline]
    pub fn coord(&self, cell: Cell) -> Coord {
        debug_assert!(self.is_occupied(cell), "no piece on {cell:?}");
        self.coords[cell.index()]
    }

    /// Get the cell of a coordinate if it is occupied.
    ///
    /// Unlike `coord.cell()`, this checks the real coordinate, so a coordinate far from
    /// the hive never matches a piece whose cell it shares.
    pub fn occupied_cell(&self, coord: Coord) -> Option<Cell> {
        let cell = coord.cell();
        (self.is_occupied(cell) && self.coords[cell.index()] == coord).then_some(cell)
    }

    /// Get the occupied cells, in no particular order.
    #[inline]
    pub fn occupied(&self) -> &[Cell] {
        &self.occupied
    }

    /// Get the number of occupied cells.
    pub fn occupied_count(&self) -> usize {
        self.occupied.len()
    }

    /// Check whether the board holds no piece.
    pub fn is_empty(&self) -> bool {
        self.occupied.is_empty()
    }

    /// Get the slot of an occupied cell: its position in [`Board::occupied`].
    #[inline]
    pub fn slot(&self, cell: Cell) -> usize {
        usize::from(self.slots[cell.index()])
    }

    /// Get the Zobrist hash of the pieces on the board.
    pub fn hash(&self) -> u64 {
        self.hash
    }

    /// Put a piece on top of a cell.
    ///
    /// `coord` is the real coordinate of the cell, which the board remembers when the
    /// cell becomes occupied.
    ///
    /// # Panics
    ///
    /// Panics if the stack already holds [`MAX_STACK_HEIGHT`] pieces, or the board
    /// already has [`MAX_OCCUPIED_CELLS`] occupied cells and `cell` is empty.
    #[inline]
    pub fn push(&mut self, cell: Cell, piece: Piece, coord: Coord) {
        let index = cell.index();
        let height = self.height(cell);
        assert!(
            height < MAX_STACK_HEIGHT,
            "a stack holds at most {MAX_STACK_HEIGHT} pieces"
        );

        if height == 0 {
            assert!(
                self.occupied.len() < MAX_OCCUPIED_CELLS,
                "a board holds at most {MAX_OCCUPIED_CELLS} occupied cells"
            );
            self.coords[index] = coord;
            self.slots[index] = u8::try_from(self.occupied.len()).unwrap_or(u8::MAX);
            self.occupied.push(cell);
        } else {
            debug_assert_eq!(
                self.coords[index], coord,
                "{cell:?} holds another coordinate"
            );
        }

        self.stacks[index][height] = piece;
        self.heights[index] += 1;
        self.hash ^= piece_key(cell, height, piece);
    }

    /// Take the top piece off a cell.
    ///
    /// # Panics
    ///
    /// Panics if the cell is empty.
    #[inline]
    pub fn pop(&mut self, cell: Cell) -> Piece {
        let index = cell.index();
        assert!(self.heights[index] > 0, "no piece to take from {cell:?}");
        self.heights[index] -= 1;
        let height = self.height(cell);
        let piece = self.stacks[index][height];
        self.hash ^= piece_key(cell, height, piece);

        if height == 0 {
            let slot = self.slot(cell);
            let last = self.occupied.pop().expect("an occupied cell is in the list");

            if last != cell {
                self.occupied[slot] = last;
                self.slots[last.index()] = self.slots[index];
            }
        }

        piece
    }

    /// Lower the stack of a cell by one for move generation, which treats the moving
    /// piece as lifted. Only [`Board::is_occupied`] and [`Board::height`] see the change,
    /// and [`Board::put_back`] must follow before anything else reads the board.
    #[inline]
    pub(crate) fn lift(&mut self, cell: Cell) {
        self.heights[cell.index()] -= 1;
    }

    /// Undo [`Board::lift`].
    #[inline]
    pub(crate) fn put_back(&mut self, cell: Cell) {
        self.heights[cell.index()] += 1;
    }

    /// Get the real coordinate of a cell that is occupied or next to an occupied cell.
    ///
    /// The coordinate of an empty cell comes from an occupied neighbour, which is exact
    /// because the engine never reads two cells of one index (see the `grid` module). A
    /// cell without occupied neighbours, which only happens on an empty board, is taken
    /// as the coordinate nearest to the origin.
    pub fn locate(&self, cell: Cell) -> Coord {
        if self.is_occupied(cell) {
            return self.coords[cell.index()];
        }

        for direction in 0..DIRECTION_COUNT {
            let neighbor = cell.neighbor(direction);

            if self.is_occupied(neighbor) {
                return self.coords[neighbor.index()].neighbor(opposite(direction));
            }
        }

        cell.coord_near_origin()
    }

    /// Count the occupied neighbours of a cell, from zero to six.
    #[inline]
    pub fn count_occupied_neighbors(&self, cell: Cell) -> usize {
        (0..DIRECTION_COUNT)
            .filter(|&direction| self.is_occupied(cell.neighbor(direction)))
            .count()
    }

    /// Check whether all six neighbours of a cell are occupied.
    #[inline]
    pub fn is_surrounded(&self, cell: Cell) -> bool {
        (0..DIRECTION_COUNT).all(|direction| self.is_occupied(cell.neighbor(direction)))
    }

    /// Get the slots of the occupied neighbours of an occupied cell, as a mask.
    #[inline]
    fn neighbor_slots(&self, cell: Cell) -> u64 {
        let mut mask = 0;

        for direction in 0..DIRECTION_COUNT {
            let neighbor = cell.neighbor(direction);

            if self.is_occupied(neighbor) {
                mask |= 1 << self.slot(neighbor);
            }
        }

        mask
    }

    /// Get the slots reachable from a slot through occupied neighbours, avoiding the
    /// slots in `blocked`.
    fn reachable_slots(&self, start: usize, blocked: u64) -> u64 {
        let mut reached: u64 = 1 << start;
        let mut frontier = reached;

        while frontier != 0 {
            let slot = frontier.trailing_zeros() as usize;
            frontier &= frontier - 1;
            let new = self.neighbor_slots(self.occupied[slot]) & !reached & !blocked;
            reached |= new;
            frontier |= new;
        }

        reached
    }

    /// Check whether the occupied cells form one connected group (true when empty).
    pub fn is_connected(&self) -> bool {
        let count = self.occupied.len();
        count == 0 || self.reachable_slots(0, 0).count_ones() as usize == count
    }

    /// Check whether the board stays connected without the top piece of a cell.
    ///
    /// The cell must be occupied. A stack higher than one stays occupied, so removing its
    /// top piece never disconnects the board.
    pub fn is_connected_without(&self, cell: Cell) -> bool {
        if self.height(cell) > 1 {
            return true;
        }

        let count = self.occupied.len();

        if count <= 2 {
            return true;
        }

        let removed = self.slot(cell);
        let start = usize::from(removed == 0);
        self.reachable_slots(start, 1 << removed).count_ones() as usize == count - 1
    }

    /// Get the slots of the articulation points: the single pieces whose removal would
    /// split the occupied cells into more groups.
    ///
    /// Uses Tarjan's algorithm over every group of occupied cells. A board of two or
    /// fewer occupied cells has none, and stacks higher than one are never articulation
    /// points, since their cell stays occupied.
    pub fn articulation_slots(&self) -> u64 {
        let count = self.occupied.len();

        if count <= 2 {
            return 0;
        }

        let mut search = ArticulationSearch {
            board: self,
            discovery: [0; MAX_OCCUPIED_CELLS],
            low: [0; MAX_OCCUPIED_CELLS],
            time: 0,
            articulation: 0,
        };

        for root in 0..count {
            if search.discovery[root] == 0 {
                search.visit(root, None);
            }
        }

        let mut articulation = search.articulation;
        let mut remaining = articulation;

        while remaining != 0 {
            let slot = remaining.trailing_zeros() as usize;
            remaining &= remaining - 1;

            if self.heights[self.occupied[slot].index()] > 1 {
                articulation &= !(1 << slot);
            }
        }

        articulation
    }

    /// Compute the Zobrist hash from scratch, to check the incremental one.
    pub fn recompute_hash(&self) -> u64 {
        let mut hash = 0;

        for &cell in &self.occupied {
            for (height, &piece) in self.stack(cell).iter().enumerate() {
                hash ^= piece_key(cell, height, piece);
            }
        }

        hash
    }

    /// Get the articulation points as cells (see [`Board::articulation_slots`]).
    pub fn articulation_cells(&self) -> Vec<Cell> {
        let mut slots = self.articulation_slots();
        let mut cells = Vec::with_capacity(slots.count_ones() as usize);

        while slots != 0 {
            cells.push(self.occupied[slots.trailing_zeros() as usize]);
            slots &= slots - 1;
        }

        cells
    }
}

/// The state of one run of Tarjan's articulation point algorithm over slots.
struct ArticulationSearch<'a> {
    /// The board searched.
    board: &'a Board,
    /// The discovery time of each slot, from one; zero means not yet discovered.
    discovery: [u8; MAX_OCCUPIED_CELLS],
    /// The earliest discovery time reachable from the subtree of each slot.
    low: [u8; MAX_OCCUPIED_CELLS],
    /// The last discovery time given out.
    time: u8,
    /// The articulation points found so far, as a mask over slots.
    articulation: u64,
}

impl ArticulationSearch<'_> {
    /// Discover a slot and its subtree, and mark articulation points in it.
    ///
    /// A non-root is an articulation point if some child subtree cannot reach above it,
    /// and a root if it has two or more children in the search tree. The recursion is at
    /// most as deep as the number of occupied cells.
    fn visit(&mut self, slot: usize, parent: Option<usize>) {
        self.time += 1;
        self.discovery[slot] = self.time;
        self.low[slot] = self.time;
        let mut children = 0;
        let mut neighbors = self.board.neighbor_slots(self.board.occupied[slot]);

        while neighbors != 0 {
            let neighbor = neighbors.trailing_zeros() as usize;
            neighbors &= neighbors - 1;

            if self.discovery[neighbor] == 0 {
                children += 1;
                self.visit(neighbor, Some(slot));
                self.low[slot] = self.low[slot].min(self.low[neighbor]);

                if parent.is_some() && self.low[neighbor] >= self.discovery[slot] {
                    self.articulation |= 1 << slot;
                }
            } else if Some(neighbor) != parent {
                self.low[slot] = self.low[slot].min(self.discovery[neighbor]);
            }
        }

        if parent.is_none() && children >= 2 {
            self.articulation |= 1 << slot;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::piece::{PieceType, Player};

    /// Build a board with one white ant on each coordinate.
    fn board_of(coords: &[(i32, i32)]) -> Board {
        let mut board = Board::new();

        for &(q, r) in coords {
            let coord = Coord::new(q, r);
            board.push(coord.cell(), Piece::new(Player::White, PieceType::Ant), coord);
        }

        board
    }

    /// Get the articulation points of a board as sorted coordinates.
    fn articulation_coords(board: &Board) -> Vec<(i32, i32)> {
        let mut coords: Vec<_> = board
            .articulation_cells()
            .into_iter()
            .map(|cell| {
                let coord = board.coord(cell);
                (coord.q, coord.r)
            })
            .collect();
        coords.sort_unstable();
        coords
    }

    #[test]
    fn line_has_its_middle_as_articulation_point() {
        let board = board_of(&[(-1, 0), (0, 0), (1, 0)]);
        assert_eq!(articulation_coords(&board), [(0, 0)]);
    }

    #[test]
    fn ring_has_no_articulation_points() {
        let board = board_of(&[(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]);
        assert_eq!(articulation_coords(&board), []);
    }

    #[test]
    fn long_chain_has_every_inner_piece_as_articulation_point() {
        let board = board_of(&[(-2, 0), (-1, 0), (0, 0), (1, 0), (2, 0)]);
        assert_eq!(articulation_coords(&board), [(-1, 0), (0, 0), (1, 0)]);
    }

    #[test]
    fn stacks_are_never_articulation_points() {
        let mut board = board_of(&[(-1, 0), (0, 0), (1, 0)]);
        let beetle = Piece::new(Player::Black, PieceType::Beetle);
        board.push(Coord::ORIGIN.cell(), beetle, Coord::ORIGIN);
        assert_eq!(articulation_coords(&board), []);
    }

    #[test]
    fn push_and_pop_restore_the_hash_and_the_occupied_cells() {
        let mut board = board_of(&[(0, 0), (1, 0), (2, 0)]);
        let hash = board.hash();
        let cell = Coord::new(1, 0).cell();
        let piece = board.pop(cell);

        assert!(!board.is_occupied(cell));
        assert_eq!(board.occupied_count(), 2);
        assert!(!board.is_connected());
        board.push(cell, piece, Coord::new(1, 0));
        assert_eq!(board.hash(), hash);
        assert!(board.is_connected());

        for &occupied in board.occupied() {
            assert_eq!(board.occupied[board.slot(occupied)], occupied);
        }
    }

    #[test]
    fn connectivity_without_a_piece() {
        let board = board_of(&[(-1, 0), (0, 0), (1, 0)]);
        assert!(!board.is_connected_without(Coord::ORIGIN.cell()));
        assert!(board.is_connected_without(Coord::new(1, 0).cell()));
    }

    #[test]
    fn empty_cells_are_located_through_their_neighbours() {
        let board = board_of(&[(40, -7)]);
        assert_eq!(board.locate(Coord::new(41, -7).cell()), Coord::new(41, -7));
        assert_eq!(board.locate(Coord::new(40, -8).cell()), Coord::new(40, -8));
        assert_eq!(Board::new().locate(Coord::new(0, -1).cell()), Coord::new(0, -1));
    }
}
