//! The evaluation of search agents: a weighted sum of heuristic terms.
//!
//! Each term scores a position from the perspective of a player, and the opponent's
//! score is the negation. Terms with weight zero are skipped, and the weighted terms are
//! summed in a fixed order, so the floating point result matches the Python agents.

use crate::engine::grid::{CellSet, DIRECTION_COUNT};
use crate::engine::movement::can_slide;
use crate::engine::{Board, Cell, GameState, Move, PieceType, Player, Rules};

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
    /// Nonlinear queen crowding: squared occupied-neighbour counts.
    pub queen_danger: f64,
    /// Legal queen escapes, excluding covered or pinned queens.
    pub queen_escape: f64,
    /// Opponent minus own material immobilized by covering or articulation.
    pub pinned_material: f64,
    /// Own minus opponent uncovered, unpinned ants after queen placement.
    pub free_ants: f64,
    /// Own minus opponent elevated beetles, with extra credit over a queen.
    pub beetle_control: f64,
    /// A bonus for the player to move, against the odd-even effect of the search depth.
    pub tempo: f64,
    /// Own minus opponent queens that can take a first step, by
    /// [`EvaluationWeights::mobile`].
    pub mobile_queen: f64,
    /// Own minus opponent beetles that can move.
    pub mobile_beetle: f64,
    /// Own minus opponent grasshoppers that can move.
    pub mobile_grasshopper: f64,
    /// Own minus opponent spiders that can take a first step.
    pub mobile_spider: f64,
    /// Own minus opponent ants that can take a first step.
    pub mobile_ant: f64,
    /// Own minus opponent free cells to place a piece on, for players with a hand.
    pub placement_cells: f64,
    /// Occupied neighbours of the opponent's queen minus the player's own that the
    /// queen's owner cannot move away: opponent pieces and own pinned or stuck ones.
    pub queen_locked_neighbors: f64,
}

impl Default for EvaluationWeights {
    fn default() -> Self {
        EvaluationWeights {
            queen_safety: 1.0,
            mobility: 0.0,
            positioning: 0.0,
            material_on_board: 0.0,
            material_in_hand: 0.0,
            queen_danger: 0.0,
            queen_escape: 0.0,
            pinned_material: 0.0,
            free_ants: 0.0,
            beetle_control: 0.0,
            tempo: 0.0,
            mobile_queen: 0.0,
            mobile_beetle: 0.0,
            mobile_grasshopper: 0.0,
            mobile_spider: 0.0,
            mobile_ant: 0.0,
            placement_cells: 0.0,
            queen_locked_neighbors: 0.0,
        }
    }
}

impl EvaluationWeights {
    /// Get the weights of the mobile pieces by piece type.
    ///
    /// A piece is mobile when it tops its stack, does not hold the hive together, its
    /// owner's queen is placed, and a queen, spider or ant on the ground can slide one
    /// step. It approximates whether the piece has a legal move without generating any.
    pub fn mobile(&self) -> [f64; PieceType::COUNT] {
        [
            self.mobile_queen,
            self.mobile_beetle,
            self.mobile_grasshopper,
            self.mobile_spider,
            self.mobile_ant,
        ]
    }

    /// Check whether any term reads the structure of the hive (see
    /// [`StructureFeatures`]).
    fn uses_structure(&self) -> bool {
        self.pinned_material != 0.0
            || self.free_ants != 0.0
            || self.beetle_control != 0.0
            || self.queen_locked_neighbors != 0.0
            || self.mobile().iter().any(|&weight| weight != 0.0)
    }
}

/// The integer counts of one player's structural terms, from a single scan of the board.
/// Counting in integers keeps the score independent of the order of the scan, which
/// depends on the move history.
#[derive(Clone, Copy, Debug, Default)]
struct StructureFeatures {
    /// The value of the player's pieces that are covered or hold the hive together.
    pinned_value: i32,
    /// The player's uncovered, unpinned ants once the player's queen is placed.
    free_ants: i32,
    /// The player's elevated top beetles, counted twice over the opponent's queen.
    beetle_control: i32,
    /// The player's mobile pieces by piece type (see [`EvaluationWeights::mobile`]).
    mobile: [i32; PieceType::COUNT],
    /// The occupied neighbours of the player's queen that the player cannot move away.
    locked_queen_neighbors: i32,
}

impl StructureFeatures {
    /// Count the features of both players, indexed by player.
    fn of_board(state: &GameState, articulation: u64) -> [Self; 2] {
        let board = state.board();
        let mut features = [StructureFeatures::default(); 2];
        let mut movable = CellSet::new();

        for (slot, &cell) in board.occupied().iter().enumerate() {
            let stack = board.stack(cell);

            for (height, piece) in stack.iter().enumerate() {
                let covered = height + 1 < stack.len();
                let pinned = stack.len() == 1 && articulation & (1 << slot) != 0;
                let owner = piece.owner();
                let piece_type = piece.piece_type();
                let own = &mut features[owner.index()];

                if covered || pinned {
                    own.pinned_value += PIECE_VALUE_COUNTS[piece_type.index()];
                    continue;
                }

                let queen_placed = state.queen_coord(owner).is_some();

                if piece_type == PieceType::Ant && queen_placed {
                    own.free_ants += 1;
                }

                if height > 0 && piece_type == PieceType::Beetle {
                    let over_queen = stack.iter().any(|below| {
                        below.piece_type() == PieceType::Queen && below.owner() != owner
                    });
                    own.beetle_control += if over_queen { 2 } else { 1 };
                }

                if queen_placed && piece_can_step(board, cell, piece_type, height) {
                    own.mobile[piece_type.index()] += 1;
                    movable.insert(cell);
                }
            }
        }

        for owner in Player::ALL {
            let Some(queen) = state.queen_coord(owner) else { continue };
            let cell = queen.cell();
            let locked = (0..DIRECTION_COUNT)
                .map(|direction| cell.neighbor(direction))
                .filter(|&neighbor| {
                    board.is_occupied(neighbor)
                        && !(board.top(neighbor).owner() == owner
                            && movable.contains(neighbor))
                })
                .count();
            features[owner.index()].locked_queen_neighbors =
                i32::try_from(locked).unwrap_or(i32::MAX);
        }

        features
    }
}

/// The piece values as integers, for exact sums of [`PIECE_VALUES`].
const PIECE_VALUE_COUNTS: [i32; PieceType::COUNT] = [10, 4, 4, 3, 7];

/// Check whether an uncovered, unpinned piece can make a first step: beetles and
/// grasshoppers always can, and a sliding piece on the ground needs a free neighbour it
/// can slide into.
fn piece_can_step(board: &Board, cell: Cell, kind: PieceType, height: usize) -> bool {
    match kind {
        PieceType::Beetle | PieceType::Grasshopper => true,
        PieceType::Queen | PieceType::Spider | PieceType::Ant => {
            height == 0
                && (0..DIRECTION_COUNT).any(|direction| {
                    !board.is_occupied(cell.neighbor(direction))
                        && can_slide(board, cell, direction)
                })
        }
    }
}

/// Count the free cells a player could place a piece on: next to a stack the player
/// tops and not next to one the opponent tops. Zero without pieces in hand or before
/// the second ply, when the placement rules differ.
fn placement_cells(state: &GameState, player: Player) -> i32 {
    if state.hand(player).total() == 0 || state.current_ply() < 2 {
        return 0;
    }

    let board = state.board();
    let mut checked = CellSet::new();
    let mut count = 0;

    for &cell in board.occupied() {
        if board.top(cell).owner() != player {
            continue;
        }

        for direction in 0..DIRECTION_COUNT {
            let candidate = cell.neighbor(direction);

            if board.is_occupied(candidate) || !checked.insert(candidate) {
                continue;
            }

            let placeable = (0..DIRECTION_COUNT).all(|side| {
                let neighbor = candidate.neighbor(side);
                !board.is_occupied(neighbor) || board.top(neighbor).owner() == player
            });

            if placeable {
                count += 1;
            }
        }
    }

    count
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

        if weights.queen_danger != 0.0 {
            let own = occupied_queen_neighbors(state, player);
            let enemy = occupied_queen_neighbors(state, player.opponent());
            score += weights.queen_danger * (enemy * enemy - own * own);
        }

        if weights.queen_escape != 0.0 {
            score += weights.queen_escape
                * (self.queen_escapes(state, player)
                    - self.queen_escapes(state, player.opponent()));
        }

        if weights.uses_structure() {
            score += self.structure(state, player);
        }

        if weights.placement_cells != 0.0 {
            let own = placement_cells(state, player);
            let opponent = placement_cells(state, player.opponent());
            score += weights.placement_cells * f64::from(own - opponent);
        }

        if weights.tempo != 0.0 {
            let to_move = state.current_player() == player;
            score += if to_move { weights.tempo } else { -weights.tempo };
        }

        score
    }

    /// Count actual queen moves, restoring the side to move after generation.
    fn queen_escapes(&self, state: &mut GameState, player: Player) -> f64 {
        let Some(queen) = state.queen_coord(player) else { return 0.0 };
        if state.board().height(queen.cell()) != 1 {
            return 0.0;
        }
        let original = state.current_player();
        state.set_current_player(player);
        let count = self.rules.target_coords(state, queen).map_or(0, |moves| moves.len());
        state.set_current_player(original);
        count_to_float(count)
    }

    /// Score the structural terms from one articulation calculation and board scan.
    fn structure(&self, state: &GameState, player: Player) -> f64 {
        let weights = self.weights;
        let needs_articulation = weights.pinned_material != 0.0
            || weights.free_ants != 0.0
            || weights.queen_locked_neighbors != 0.0
            || weights.mobile().iter().any(|&weight| weight != 0.0);
        let articulation =
            if needs_articulation { state.board().articulation_slots() } else { 0 };
        let features = StructureFeatures::of_board(state, articulation);
        let own = features[player.index()];
        let opponent = features[player.opponent().index()];
        let mut score = weights.pinned_material
            * f64::from(opponent.pinned_value - own.pinned_value)
            + weights.free_ants * f64::from(own.free_ants - opponent.free_ants)
            + weights.beetle_control
                * f64::from(own.beetle_control - opponent.beetle_control)
            + weights.queen_locked_neighbors
                * f64::from(opponent.locked_queen_neighbors - own.locked_queen_neighbors);

        for (weight, (own, opponent)) in
            weights.mobile().iter().zip(own.mobile.iter().zip(opponent.mobile.iter()))
        {
            if *weight != 0.0 {
                score += weight * f64::from(own - opponent);
            }
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
