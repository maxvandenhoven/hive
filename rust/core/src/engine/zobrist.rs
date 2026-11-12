//! Zobrist keys: random 64-bit numbers whose XOR identifies a position.
//!
//! A position's hash is the XOR of one key per piece, chosen by its cell, its height in
//! the stack and the piece, and of [`SIDE_KEY`] when black is to move. The keys are
//! computed with splitmix64 instead of looked up in a table, which costs a few
//! multiplications but no cache lines.

use crate::engine::grid::Cell;
use crate::engine::piece::Piece;

/// The key XOR-ed into the hash when black is to move.
pub const SIDE_KEY: u64 = splitmix64(0x5eed_51de_0f00_0001);

/// The seed mixed into every piece key.
const PIECE_SEED: u64 = 0x2545_f491_4f6c_dd1d;

/// Get the key of a piece at a height (zero at the bottom) of the stack on a cell.
#[inline]
pub fn piece_key(cell: Cell, height: usize, piece: Piece) -> u64 {
    let index = (cell.index() << 7) | (height << 4) | piece.code();
    splitmix64(PIECE_SEED ^ index as u64)
}

/// Get the key of a ply count, which search tables add to the position hash because the
/// legal moves and the end of the game depend on the ply (the queen deadline, the turn
/// limit).
pub fn ply_key(ply: i64) -> u64 {
    splitmix64(PLY_SEED ^ ply.cast_unsigned())
}

/// The seed mixed into every ply key.
const PLY_SEED: u64 = 0x6a09_e667_f3bc_c909;

/// Mix 64 bits into 64 well-distributed bits (the splitmix64 finaliser).
const fn splitmix64(value: u64) -> u64 {
    let mut z = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    z ^ (z >> 31)
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use super::*;
    use crate::engine::grid::CELL_COUNT;
    use crate::engine::piece::{PieceType, Player};

    #[test]
    fn keys_are_distinct() {
        let mut keys = HashSet::new();

        for index in 0..CELL_COUNT {
            for height in 0..8 {
                for owner in Player::ALL {
                    for piece_type in PieceType::ALL {
                        let piece = Piece::new(owner, piece_type);
                        assert!(keys.insert(piece_key(
                            Cell::from_index(index),
                            height,
                            piece
                        )));
                    }
                }
            }
        }

        assert!(!keys.contains(&SIDE_KEY));
    }
}
