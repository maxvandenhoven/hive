//! Where the pieces can move: the targets of each piece type.
//!
//! Every function treats the moving piece as lifted from its cell while it looks for
//! targets, so a piece never slides along itself, and puts it back before returning. The
//! rules match the Python package exactly; perft and the differential tests check that.

use crate::engine::board::Board;
use crate::engine::grid::{Cell, CellSet, DIRECTION_COUNT, anti_clockwise, clockwise};
use crate::engine::moves::Move;
use crate::engine::piece::PieceType;

/// Where move generation writes the targets of a piece.
///
/// The ant's flood fill reads its targets back as the queue of cells to expand, so it
/// needs no list of its own.
pub(crate) trait Targets {
    /// Add a target.
    fn add(&mut self, target: Cell);

    /// Get the target at a position, counting every target ever added.
    fn get(&self, index: usize) -> Cell;

    /// Get the number of targets added so far.
    fn count(&self) -> usize;
}

/// Targets written as movements of one piece into a move list.
pub(crate) struct MoveTargets<'a> {
    /// The list the movements are appended to.
    pub moves: &'a mut Vec<Move>,
    /// The type of the moving piece.
    pub piece_type: PieceType,
    /// The cell the piece moves from.
    pub source: Cell,
}

impl Targets for MoveTargets<'_> {
    #[inline]
    fn add(&mut self, target: Cell) {
        self.moves.push(Move::movement(self.piece_type, self.source, target));
    }

    #[inline]
    fn get(&self, index: usize) -> Cell {
        self.moves[index].target()
    }

    #[inline]
    fn count(&self) -> usize {
        self.moves.len()
    }
}

impl Targets for Vec<Cell> {
    fn add(&mut self, target: Cell) {
        self.push(target);
    }

    fn get(&self, index: usize) -> Cell {
        self[index]
    }

    fn count(&self) -> usize {
        self.len()
    }
}

/// Check the gate and contact rules of a slide from a cell in a direction: exactly one of
/// the two cells flanking the step is occupied. Two form a gate the piece cannot pass,
/// and none would leave it without contact to the hive.
#[inline]
pub(crate) fn can_slide(board: &Board, cell: Cell, direction: usize) -> bool {
    board.is_occupied(cell.neighbor(anti_clockwise(direction)))
        != board.is_occupied(cell.neighbor(clockwise(direction)))
}

/// Add the free neighbours a piece on `cell` can slide into (see [`can_slide`]).
#[inline]
fn add_slides(board: &Board, cell: Cell, targets: &mut impl Targets) {
    for direction in 0..DIRECTION_COUNT {
        let neighbor = cell.neighbor(direction);

        if !board.is_occupied(neighbor) && can_slide(board, cell, direction) {
            targets.add(neighbor);
        }
    }
}

/// Add the targets of the top piece of a cell, which is of `piece_type`.
pub(crate) fn add_piece_targets(
    board: &mut Board,
    cell: Cell,
    piece_type: PieceType,
    targets: &mut impl Targets,
) {
    match piece_type {
        PieceType::Queen => add_queen_targets(board, cell, targets),
        PieceType::Beetle => add_beetle_targets(board, cell, targets),
        PieceType::Grasshopper => add_grasshopper_targets(board, cell, targets),
        PieceType::Spider => add_spider_targets(board, cell, targets),
        PieceType::Ant => add_ant_targets(board, cell, targets),
    }
}

/// Add the targets of a queen, which slides exactly one space.
fn add_queen_targets(board: &mut Board, cell: Cell, targets: &mut impl Targets) {
    board.lift(cell);
    add_slides(board, cell, targets);
    board.put_back(cell);
}

/// Add the targets of a beetle, which moves one space and may climb the hive.
///
/// On the ground it slides like the queen. A step where the beetle is on the hive before
/// or after, at the higher of the source height (without the beetle) and the target
/// height, is blocked only by a gate of two flanking stacks that are both higher.
fn add_beetle_targets(board: &mut Board, cell: Cell, targets: &mut impl Targets) {
    board.lift(cell);
    let source_height = board.height(cell);

    if source_height == 0 {
        add_slides(board, cell, targets);
    }

    for direction in 0..DIRECTION_COUNT {
        let neighbor = cell.neighbor(direction);
        let height = source_height.max(board.height(neighbor));

        if height == 0 {
            continue;
        }

        if board.height(cell.neighbor(anti_clockwise(direction))) > height
            && board.height(cell.neighbor(clockwise(direction))) > height
        {
            continue;
        }

        targets.add(neighbor);
    }

    board.put_back(cell);
}

/// Add the targets of a grasshopper, which jumps in a straight line over at least one
/// piece onto the first free cell.
fn add_grasshopper_targets(board: &Board, cell: Cell, targets: &mut impl Targets) {
    for direction in 0..DIRECTION_COUNT {
        let mut current = cell.neighbor(direction);

        if !board.is_occupied(current) {
            continue;
        }

        while board.is_occupied(current) {
            current = current.neighbor(direction);
        }

        targets.add(current);
    }
}

/// Add the targets of a spider, which slides exactly three spaces without revisiting a
/// cell. Each target is added once, and never the starting cell.
fn add_spider_targets(board: &mut Board, cell: Cell, targets: &mut impl Targets) {
    board.lift(cell);
    let mut found = CellSet::new();
    found.insert(cell);
    let mut path = [cell; 4];
    walk_spider(board, &mut path, 0, &mut found, targets);
    board.put_back(cell);
}

/// Extend a spider path by one slide in every way, adding the ends of complete paths.
///
/// `path[..=depth]` holds the cells of the path so far, which it may not revisit.
fn walk_spider(
    board: &Board,
    path: &mut [Cell; 4],
    depth: usize,
    found: &mut CellSet,
    targets: &mut impl Targets,
) {
    let current = path[depth];

    if depth == 3 {
        if found.insert(current) {
            targets.add(current);
        }

        return;
    }

    for direction in 0..DIRECTION_COUNT {
        let neighbor = current.neighbor(direction);

        if board.is_occupied(neighbor)
            || !can_slide(board, current, direction)
            || path[..=depth].contains(&neighbor)
        {
            continue;
        }

        path[depth + 1] = neighbor;
        walk_spider(board, path, depth + 1, found, targets);
    }
}

/// Add the targets of an ant, which slides any number of spaces: every free cell
/// connected to its cell by a chain of slides.
fn add_ant_targets(board: &mut Board, cell: Cell, targets: &mut impl Targets) {
    board.lift(cell);
    let mut visited = CellSet::new();
    visited.insert(cell);
    let mut next = targets.count();
    let mut current = cell;

    loop {
        for direction in 0..DIRECTION_COUNT {
            let neighbor = current.neighbor(direction);

            if !board.is_occupied(neighbor)
                && can_slide(board, current, direction)
                && visited.insert(neighbor)
            {
                targets.add(neighbor);
            }
        }

        if next == targets.count() {
            break;
        }

        current = targets.get(next);
        next += 1;
    }

    board.put_back(cell);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::grid::Coord;
    use crate::engine::piece::{Piece, Player};

    /// Build a board with one piece per `(q, r, piece type)`, all white.
    fn board_of(pieces: &[(i32, i32, PieceType)]) -> Board {
        let mut board = Board::new();

        for &(q, r, piece_type) in pieces {
            let coord = Coord::new(q, r);
            board.push(coord.cell(), Piece::new(Player::White, piece_type), coord);
        }

        board
    }

    /// Get the targets of the top piece at `(q, r)` as sorted coordinates.
    fn targets_of(
        board: &mut Board,
        q: i32,
        r: i32,
        piece_type: PieceType,
    ) -> Vec<Coord> {
        let cell = Coord::new(q, r).cell();
        let mut targets = Vec::new();
        add_piece_targets(board, cell, piece_type, &mut targets);
        let mut coords: Vec<_> =
            targets.into_iter().map(|target| board.locate(target)).collect();
        coords.sort_unstable();
        coords
    }

    #[test]
    fn a_gate_of_two_flanks_blocks_a_slide() {
        // From (0, 0) east to (1, 0), the flanks are (1, -1) and (0, 1).
        let gate = board_of(&[
            (0, 0, PieceType::Ant),
            (1, -1, PieceType::Ant),
            (0, 1, PieceType::Ant),
        ]);
        assert!(!can_slide(&gate, Coord::ORIGIN.cell(), 0));

        let one_flank = board_of(&[(0, 0, PieceType::Ant), (1, -1, PieceType::Ant)]);
        assert!(can_slide(&one_flank, Coord::ORIGIN.cell(), 0));

        let no_flank = board_of(&[(0, 0, PieceType::Ant), (-1, 0, PieceType::Ant)]);
        assert!(!can_slide(&no_flank, Coord::ORIGIN.cell(), 0), "a slide keeps contact");
    }

    #[test]
    fn a_queen_slides_along_its_neighbour() {
        let mut board = board_of(&[(0, 0, PieceType::Queen), (1, 0, PieceType::Ant)]);
        assert_eq!(
            targets_of(&mut board, 0, 0, PieceType::Queen),
            [Coord::new(0, 1), Coord::new(1, -1)]
        );
        assert_eq!(board.height(Coord::ORIGIN.cell()), 1, "the queen is put back");
    }

    #[test]
    fn a_grasshopper_jumps_over_a_line() {
        let mut board = board_of(&[
            (0, 0, PieceType::Grasshopper),
            (1, 0, PieceType::Ant),
            (2, 0, PieceType::Ant),
        ]);
        assert_eq!(
            targets_of(&mut board, 0, 0, PieceType::Grasshopper),
            [Coord::new(3, 0)]
        );
    }

    #[test]
    fn a_beetle_climbs_and_slides() {
        let mut board = board_of(&[(0, 0, PieceType::Beetle), (1, 0, PieceType::Ant)]);
        assert_eq!(
            targets_of(&mut board, 0, 0, PieceType::Beetle),
            [Coord::new(0, 1), Coord::new(1, -1), Coord::new(1, 0)]
        );
    }

    #[test]
    fn an_ant_circles_a_line_but_not_into_a_gated_hole() {
        // A ring of five around the hole (1, 0), closed by the ant at (0, 0): the ant
        // cannot slide into the hole, which a gate guards.
        let mut ring = board_of(&[
            (0, 0, PieceType::Ant),
            (1, -1, PieceType::Ant),
            (2, -1, PieceType::Ant),
            (2, 0, PieceType::Ant),
            (1, 1, PieceType::Ant),
            (0, 1, PieceType::Ant),
        ]);
        let targets = targets_of(&mut ring, 0, 0, PieceType::Ant);
        assert!(!targets.contains(&Coord::new(1, 0)));
        assert!(!targets.contains(&Coord::ORIGIN));

        // Next to a single piece, the ant reaches the five other cells around it.
        let mut pair = board_of(&[(0, 0, PieceType::Ant), (1, 0, PieceType::Ant)]);
        assert_eq!(targets_of(&mut pair, 0, 0, PieceType::Ant).len(), 5);
    }

    #[test]
    fn a_spider_walks_exactly_three_slides() {
        // Around a single piece both directions of three slides end opposite the spider.
        let mut board = board_of(&[(0, 0, PieceType::Spider), (1, 0, PieceType::Ant)]);
        assert_eq!(targets_of(&mut board, 0, 0, PieceType::Spider), [Coord::new(2, 0)]);
    }
}
