//! Perft: counting the leaf positions of the game tree to a fixed depth.
//!
//! The counts depend only on the rules, so they prove move generation correct against
//! reference engines, and the time taken measures the speed of the engine.

use crate::engine::moves::Move;
use crate::engine::rules::Rules;
use crate::engine::state::GameState;

impl Rules {
    /// Count the positions reached after exactly `depth` plies.
    ///
    /// Every leaf is applied and undone, as in the Python harness, so the time measures
    /// move generation, apply and undo together. A finished game counts as a leaf at
    /// depth zero and has no children; a forced pass counts as one move.
    pub fn perft(&self, state: &mut GameState, depth: u32) -> u64 {
        let mut buffers = move_buffers(depth);
        self.perft_with(state, depth, &mut buffers, false)
    }

    /// Count like [`Rules::perft`], but count the moves of the last ply instead of
    /// applying them (bulk counting), which gives the same count faster.
    pub fn perft_bulk(&self, state: &mut GameState, depth: u32) -> u64 {
        let mut buffers = move_buffers(depth);
        self.perft_with(state, depth, &mut buffers, true)
    }

    /// Count the positions below each legal move: the move (`None` for a pass) and the
    /// perft count after it at `depth - 1`. Empty if the game is finished.
    pub fn divide(&self, state: &mut GameState, depth: u32) -> Vec<(Option<Move>, u64)> {
        if depth == 0 || self.is_finished(state) {
            return Vec::new();
        }

        let mut moves = Vec::new();
        self.legal_moves(state, &mut moves);
        let moves: Vec<Option<Move>> = if moves.is_empty() {
            vec![None]
        } else {
            moves.into_iter().map(Some).collect()
        };
        let mut buffers = move_buffers(depth);

        moves
            .into_iter()
            .map(|mv| {
                state.apply_move(mv);
                let count = self.perft_with(state, depth - 1, &mut buffers, false);
                state.undo_move(mv);
                (mv, count)
            })
            .collect()
    }

    /// Count recursively, with one move buffer per remaining ply.
    fn perft_with(
        &self,
        state: &mut GameState,
        depth: u32,
        buffers: &mut [Vec<Move>],
        bulk: bool,
    ) -> u64 {
        if depth == 0 {
            return 1;
        }

        if self.is_finished(state) {
            return 0;
        }

        let (moves, rest) = buffers.split_first_mut().expect("one buffer per ply");
        self.legal_moves(state, moves);

        if moves.is_empty() {
            state.apply_move(None);
            let count = self.perft_with(state, depth - 1, rest, bulk);
            state.undo_move(None);
            return count;
        }

        if bulk && depth == 1 {
            return moves.len() as u64;
        }

        let mut count = 0;

        for &mv in moves.iter() {
            state.apply_move(Some(mv));
            count += self.perft_with(state, depth - 1, rest, bulk);
            state.undo_move(Some(mv));
        }

        count
    }
}

/// Create one empty move buffer per ply of a walk.
fn move_buffers(depth: u32) -> Vec<Vec<Move>> {
    (0..depth).map(|_| Vec::with_capacity(256)).collect()
}
