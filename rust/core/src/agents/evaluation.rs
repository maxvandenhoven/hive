//! The evaluation of search agents: a weighted sum of heuristic terms.
//!
//! Each term scores a position from the perspective of a player, and the opponent's
//! score is the negation. Terms with weight zero are skipped, and the weighted terms are
//! summed in a fixed order, so the floating point result matches the Python agents.

use crate::engine::{GameState, Move, PieceType, Player, Rules};

/// The heuristic value of each piece type for the material terms, by piece type value.
pub const PIECE_VALUES: [f64; PieceType::COUNT] = [10.0, 4.0, 4.0, 3.0, 7.0];

/// The weights of the evaluation terms, the agent params of the search agents.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct EvaluationWeights {
    /// The weight of the occupied neighbours of the opponent's queen minus those of the
    /// player's own queen.
    pub queen_safety: f64,
    /// The weight of the player's legal moves minus the opponent's, which generates
    /// moves at every leaf.
    pub mobility: f64,
    /// The weight of the player's top pieces next to the opponent's queen minus the
    /// opponent's next to the player's queen.
    pub positioning: f64,
    /// The weight of the value of the player's pieces on the board minus the opponent's.
    pub material_on_board: f64,
    /// The weight of the value of the player's pieces in hand minus the opponent's.
    pub material_in_hand: f64,
}

impl Default for EvaluationWeights {
    fn default() -> Self {
        EvaluationWeights {
            queen_safety: 1.0,
            mobility: 0.0,
            positioning: 0.0,
            material_on_board: 0.0,
            material_in_hand: 0.0,
        }
    }
}

/// Evaluates positions with a set of weights, keeping a move buffer for mobility.
#[derive(Clone, Debug)]
pub struct Evaluator {
    /// The rules, which generate the moves of the mobility term.
    rules: Rules,
    /// The weights of the terms.
    weights: EvaluationWeights,
    /// Scratch space for counting moves.
    buffer: Vec<Move>,
}

impl Evaluator {
    /// Create an evaluator.
    pub fn new(rules: Rules, weights: EvaluationWeights) -> Self {
        Evaluator { rules, weights, buffer: Vec::with_capacity(256) }
    }

    /// Get the weights.
    pub fn weights(&self) -> &EvaluationWeights {
        &self.weights
    }

    /// Score a position from the perspective of `player`: the weighted sum of every term
    /// with a nonzero weight. Positive values favour `player`.
    ///
    /// The mobility term generates the moves of both players, so it switches the player
    /// to move and back; the state is unchanged afterwards.
    pub fn evaluate(&mut self, state: &mut GameState, player: Player) -> f64 {
        let weights = self.weights;
        let mut score = 0.0;

        if weights.queen_safety != 0.0 {
            score += weights.queen_safety * queen_safety(state, player);
        }

        if weights.mobility != 0.0 {
            score += weights.mobility * self.mobility(state, player);
        }

        if weights.positioning != 0.0 {
            score += weights.positioning * positioning(state, player);
        }

        if weights.material_on_board != 0.0 {
            score += weights.material_on_board * material_on_board(state, player);
        }

        if weights.material_in_hand != 0.0 {
            score += weights.material_in_hand * material_in_hand(state, player);
        }

        score
    }

    /// Compare the number of legal moves of the player and of the opponent, where a
    /// forced pass counts as zero moves.
    fn mobility(&mut self, state: &mut GameState, player: Player) -> f64 {
        let own = self.count_moves(state, player);
        let opponent = self.count_moves(state, player.opponent());
        count_to_float(own) - count_to_float(opponent)
    }

    /// Count the legal moves of a player by making them the player to move for a moment.
    fn count_moves(&mut self, state: &mut GameState, player: Player) -> usize {
        let original = state.current_player();
        state.set_current_player(player);
        let count = self.rules.count_legal_moves(state, &mut self.buffer);
        state.set_current_player(original);
        count
    }
}

/// Convert a small count to a float exactly.
fn count_to_float(count: usize) -> f64 {
    f64::from(u32::try_from(count).unwrap_or(u32::MAX))
}

/// Count the occupied neighbours of a player's queen, zero if it is not placed.
fn occupied_queen_neighbors(state: &GameState, owner: Player) -> f64 {
    state.queen_coord(owner).map_or(0.0, |queen| {
        count_to_float(state.board().count_occupied_neighbors(queen.cell()))
    })
}

/// Compare how surrounded the opponent's queen is to the player's own queen.
fn queen_safety(state: &GameState, player: Player) -> f64 {
    occupied_queen_neighbors(state, player.opponent())
        - occupied_queen_neighbors(state, player)
}

/// Count the stacks next to the defender's queen that the attacker tops, zero if the
/// defender's queen is not placed.
fn queen_pressure(state: &GameState, attacker: Player) -> f64 {
    let Some(queen) = state.queen_coord(attacker.opponent()) else { return 0.0 };
    let board = state.board();
    let cell = queen.cell();
    let count = (0..6)
        .map(|direction| cell.neighbor(direction))
        .filter(|&neighbor| {
            board.is_occupied(neighbor) && board.top(neighbor).owner() == attacker
        })
        .count();
    count_to_float(count)
}

/// Compare the pressure each player puts on the opponent's queen.
fn positioning(state: &GameState, player: Player) -> f64 {
    queen_pressure(state, player) - queen_pressure(state, player.opponent())
}

/// Compare the value of the pieces each player has on the board.
fn material_on_board(state: &GameState, player: Player) -> f64 {
    let board = state.board();
    let mut scores = [0.0; 2];

    for &cell in board.occupied() {
        for piece in board.stack(cell) {
            scores[piece.owner().index()] += PIECE_VALUES[piece.piece_type().index()];
        }
    }

    scores[player.index()] - scores[player.opponent().index()]
}

/// Compare the value of the pieces each player still has in hand.
fn material_in_hand(state: &GameState, player: Player) -> f64 {
    let mut scores = [0.0; 2];

    for owner in Player::ALL {
        for (piece_type, count) in state.hand(owner).iter() {
            scores[owner.index()] += f64::from(count) * PIECE_VALUES[piece_type.index()];
        }
    }

    scores[player.index()] - scores[player.opponent().index()]
}
