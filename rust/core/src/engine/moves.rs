//! Moves: the packed form the engine generates and searches, and the coordinate form of
//! the Python package.

use std::fmt;
use std::num::NonZeroU32;

use crate::engine::grid::{Cell, Coord};
use crate::engine::piece::PieceType;

/// A move packed into 32 bits: a placement from the hand or a movement on the board.
///
/// A move names cells, not coordinates, so it is only meaningful in the position it was
/// generated in. `None` in an `Option<Move>` is a pass, which costs no space because the
/// top bit of a move is always set.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct Move(NonZeroU32);

/// The bit that is always set, so a move is never zero.
const PRESENT_BIT: u32 = 1 << 31;

/// The bit that marks a movement rather than a placement.
const MOVEMENT_BIT: u32 = 1 << 3;

/// The shift of the source cell.
const SOURCE_SHIFT: u32 = 4;

/// The shift of the target cell.
const TARGET_SHIFT: u32 = 14;

/// The mask of a cell index after shifting.
const CELL_BITS: u32 = 0x3ff;

impl Move {
    /// Create a placement of a piece type from the hand onto a cell.
    #[inline]
    pub fn placement(piece_type: PieceType, target: Cell) -> Self {
        Move::from_bits(
            PRESENT_BIT | piece_type as u32 | (u32::from(target.bits()) << TARGET_SHIFT),
        )
    }

    /// Create a movement of the top piece of `source` onto `target`.
    #[inline]
    pub fn movement(piece_type: PieceType, source: Cell, target: Cell) -> Self {
        Move::from_bits(
            PRESENT_BIT
                | MOVEMENT_BIT
                | piece_type as u32
                | (u32::from(source.bits()) << SOURCE_SHIFT)
                | (u32::from(target.bits()) << TARGET_SHIFT),
        )
    }

    /// Wrap bits that have the top bit set.
    #[inline]
    fn from_bits(bits: u32) -> Self {
        Move(NonZeroU32::new(bits).unwrap_or(NonZeroU32::MIN))
    }

    /// Get the type of the placed or moved piece.
    #[inline]
    pub fn piece_type(self) -> PieceType {
        PieceType::ALL[(self.0.get() & 7) as usize]
    }

    /// Check whether the move places a piece from the hand.
    #[inline]
    pub fn is_placement(self) -> bool {
        self.0.get() & MOVEMENT_BIT == 0
    }

    /// Get the cell the piece moves from, or `None` for a placement.
    #[inline]
    pub fn source(self) -> Option<Cell> {
        if self.is_placement() {
            None
        } else {
            Some(Cell::from_index(((self.0.get() >> SOURCE_SHIFT) & CELL_BITS) as usize))
        }
    }

    /// Get the cell the piece is placed or moved onto.
    #[inline]
    pub fn target(self) -> Cell {
        Cell::from_index(((self.0.get() >> TARGET_SHIFT) & CELL_BITS) as usize)
    }

    /// Get the 32 bits of the move, for example to store it in a table.
    pub const fn bits(self) -> u32 {
        self.0.get()
    }
}

impl fmt::Debug for Move {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.source() {
            None => {
                write!(formatter, "place {:?} at {:?}", self.piece_type(), self.target())
            }
            Some(source) => write!(
                formatter,
                "move {:?} from {:?} to {:?}",
                self.piece_type(),
                source,
                self.target()
            ),
        }
    }
}

/// A move with real coordinates, the form of the Python package and of game records.
///
/// A placement has no source. The ordering is the documented order of legal moves:
/// placements before movements, then by piece type, source and target.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct CoordMove {
    /// The type of the placed or moved piece.
    pub piece_type: PieceType,
    /// The coordinate the piece moves from, or `None` for a placement.
    pub source: Option<Coord>,
    /// The coordinate the piece is placed or moved onto.
    pub target: Coord,
}

impl CoordMove {
    /// Get the key that sorts moves in the documented order of legal moves.
    fn sort_key(&self) -> (bool, PieceType, Option<Coord>, Coord) {
        (self.source.is_some(), self.piece_type, self.source, self.target)
    }
}

impl PartialOrd for CoordMove {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for CoordMove {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.sort_key().cmp(&other.sort_key())
    }
}

/// Moves describe themselves like `Move.__str__` in Python, for example
/// `move ant from (0, 0) to (1, 0)`.
impl fmt::Display for CoordMove {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let name = self.piece_type.lower_name();

        match self.source {
            None => write!(formatter, "place {name} at {}", self.target),
            Some(source) => {
                write!(formatter, "move {name} from {source} to {}", self.target)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn packed_moves_round_trip() {
        let source = Coord::new(-3, 7).cell();
        let target = Coord::new(12, -9).cell();

        for piece_type in PieceType::ALL {
            let placement = Move::placement(piece_type, target);
            assert_eq!(
                (placement.piece_type(), placement.source(), placement.target()),
                (piece_type, None, target)
            );

            let movement = Move::movement(piece_type, source, target);
            assert_eq!(
                (movement.piece_type(), movement.source(), movement.target()),
                (piece_type, Some(source), target)
            );
        }
    }

    #[test]
    fn a_pass_costs_no_space() {
        assert_eq!(size_of::<Option<Move>>(), size_of::<u32>());
    }

    #[test]
    fn coordinate_moves_sort_placements_first() {
        let placement = CoordMove {
            piece_type: PieceType::Ant,
            source: None,
            target: Coord::new(5, 5),
        };
        let movement = CoordMove {
            piece_type: PieceType::Queen,
            source: Some(Coord::new(0, 0)),
            target: Coord::new(1, 0),
        };

        assert!(placement < movement);
        assert_eq!(movement.to_string(), "move queen from (0, 0) to (1, 0)");
        assert_eq!(placement.to_string(), "place ant at (5, 5)");
    }
}
