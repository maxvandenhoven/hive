//! Perft parity with the reference counts of the perft suite of the Python tests, and
//! invariants checked over random games.

mod common;

use common::load_suite;
use hive_core::engine::{GameState, Move, PieceType, Player, Rules};

/// The counts above this many nodes run only in the slow test.
const FAST_NODE_LIMIT: u64 = 20_000_000;

/// Check every count of the suite up to `limit` nodes, or above it.
fn check_counts(slow: bool) {
    let (rules, positions) = load_suite();

    for mut position in positions {
        for &(depth, expected) in &position.counts {
            if (expected > FAST_NODE_LIMIT) != slow || expected > 1_000_000_000 {
                continue;
            }

            let before = position.state.clone();
            let count = rules.perft(&mut position.state, depth);
            assert_eq!(count, expected, "perft {} depth {depth}", position.name);
            assert_eq!(
                position.state, before,
                "perft {} restores the state",
                position.name
            );

            let bulk = rules.perft_bulk(&mut position.state, depth);
            assert_eq!(bulk, expected, "bulk perft {} depth {depth}", position.name);
        }
    }
}

#[test]
fn perft_matches_the_reference_counts() {
    check_counts(false);
}

#[test]
#[ignore = "slow: runs the large reference counts, `make test-slow`"]
fn perft_matches_the_large_reference_counts() {
    check_counts(true);
}

#[test]
fn legal_moves_match_the_reference_moves() {
    let (rules, positions) = load_suite();

    for mut position in positions {
        let Some(mut expected) = position.legal_moves else { continue };
        let mut moves = rules.legal_coord_moves(&mut position.state);
        expected.sort_unstable();
        moves.sort_unstable();
        assert_eq!(moves, expected, "legal moves of {}", position.name);
    }
}

/// A small xorshift generator, so random games need no dependency.
struct XorShift(u64);

impl XorShift {
    /// Get the next number below `bound`.
    fn below(&mut self, bound: usize) -> usize {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        usize::try_from(self.0 % bound as u64).expect("below the bound")
    }
}

/// Check the invariants of a state that do not depend on the moves played.
fn assert_invariants(state: &GameState) {
    let board = state.board();
    assert_eq!(board.hash(), board.recompute_hash(), "the incremental hash");
    assert!(board.is_connected(), "the hive is connected");

    for &cell in board.occupied() {
        assert_eq!(board.coord(cell).cell(), cell, "coordinates match their cells");
        assert_eq!(board.occupied()[board.slot(cell)], cell, "slots match the list");
    }

    for player in Player::ALL {
        if let Some(queen) = state.queen_coord(player) {
            let cell = board.occupied_cell(queen).expect("the queen is on the board");
            assert!(
                board
                    .stack(cell)
                    .iter()
                    .any(|piece| piece.piece_type() == PieceType::Queen)
            );
        }
    }
}

#[test]
fn random_games_keep_the_invariants() {
    let rules = Rules::default();
    let mut random = XorShift(0x9e37_79b9_7f4a_7c15);
    let mut moves = Vec::new();

    for _ in 0..200 {
        let mut state = rules.create_initial_state();
        let mut played: Vec<(Option<Move>, GameState)> = Vec::new();

        for _ in 0..150 {
            if rules.is_finished(&state) {
                break;
            }

            rules.legal_moves(&mut state, &mut moves);
            let mv = if moves.is_empty() {
                None
            } else {
                Some(moves[random.below(moves.len())])
            };
            let coord_move = mv.map(|mv| state.decode(mv));
            let mut by_coords = state.clone();
            by_coords.apply_coord_move(coord_move).expect("a decoded move applies");

            played.push((mv, state.clone()));
            state.apply_move(mv);
            assert_invariants(&state);
            assert_eq!(state, by_coords, "packed and coordinate moves agree");
        }

        while let Some((mv, before)) = played.pop() {
            state.undo_move(mv);
            assert_eq!(state, before, "undo restores the state");
            assert_eq!(state.hash(), before.hash(), "undo restores the hash");
        }
    }
}
