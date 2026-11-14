//! The search of the search agents: iterative deepening with minimax or negamax.
//!
//! The search runs to depth 1, 2, 3 and so on, reporting the best line after each
//! completed depth, until the depth limit is reached, the game tree is exhausted, the
//! result is decided, or the observer asks to stop. A depth that is interrupted is
//! discarded. This is the behaviour of the Python `SearchAgent`, ported exactly: the same
//! nodes are visited, scores are equal, and the root keeps the first best move in the
//! documented order of legal moves.

use std::time::Instant;

use crate::agents::evaluation::{EvaluationWeights, Evaluator};
use crate::engine::{CoordMove, GameState, Move, Player, Rules};

/// The score of a won position, reduced by one per ply so faster wins score higher.
pub const SEARCH_WIN_SCORE: f64 = 1_000_000.0;

/// The tree search of an agent.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SearchAlgorithm {
    /// Scores from the perspective of the player to move at the root, maximizing where
    /// that player moves and minimizing where the opponent moves.
    Minimax,
    /// Scores from the perspective of the player to move at every node, negating child
    /// scores.
    Negamax,
}

/// The configuration of a search, from the agent params.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SearchConfig {
    /// The tree search.
    pub algorithm: SearchAlgorithm,
    /// The maximum depth in plies, or `None` to search until stopped.
    pub depth: Option<u32>,
    /// The weights of the evaluation terms.
    pub weights: EvaluationWeights,
    /// The number of nodes between two calls of [`SearchObserver::should_stop`].
    pub stop_check_interval: u64,
}

/// The result of one completed depth of iterative deepening.
#[derive(Clone, Debug, PartialEq)]
pub struct DepthReport {
    /// The depth searched.
    pub depth: u32,
    /// The nodes visited in the decision so far, over all depths.
    pub nodes: u64,
    /// The score of the root from the perspective of the player to move.
    pub score: f64,
    /// The principal variation, starting with the best move (`None` is a pass).
    pub principal_variation: Vec<Option<CoordMove>>,
    /// The seconds since the decision started.
    pub elapsed_seconds: f64,
    /// Whether the decision is final: the depth limit is reached, the tree was searched
    /// to its end, or the result is decided.
    pub is_final: bool,
}

/// The caller of a search: it is asked whether to stop and receives the result of each
/// completed depth.
pub trait SearchObserver {
    /// Check whether the search should stop. It is called before each depth and every
    /// [`SearchConfig::stop_check_interval`] nodes, so a fixed sequence of answers gives
    /// a fixed search.
    fn should_stop(&mut self) -> bool;

    /// Receive the result of a completed depth.
    fn report(&mut self, report: &DepthReport);
}

/// The signal that unwinds a search when the observer asks to stop.
struct Stopped;

/// The search of an agent, which keeps its buffers between decisions.
#[derive(Clone, Debug)]
pub struct Searcher {
    /// The rules that generate the moves.
    rules: Rules,
    /// The configuration of the search.
    config: SearchConfig,
    /// The evaluation of leaf positions.
    evaluator: Evaluator,
    /// The nodes visited in the decision in progress.
    nodes: u64,
    /// Whether the depth in progress stopped at the depth limit somewhere, so a deeper
    /// search could change the result.
    cutoff: bool,
    /// One move buffer per ply.
    buffers: Vec<Vec<Move>>,
    /// The principal variation below each ply, a triangular table.
    lines: Vec<Vec<Option<Move>>>,
}

impl Searcher {
    /// Create a searcher.
    pub fn new(rules: Rules, config: SearchConfig) -> Self {
        Searcher {
            rules,
            config,
            evaluator: Evaluator::new(rules, config.weights),
            nodes: 0,
            cutoff: false,
            buffers: Vec::new(),
            lines: Vec::new(),
        }
    }

    /// Get the configuration.
    pub fn config(&self) -> &SearchConfig {
        &self.config
    }

    /// Get the nodes visited in the last decision.
    pub fn nodes(&self) -> u64 {
        self.nodes
    }

    /// Evaluate a position from the perspective of a player with the agent's weights.
    pub fn evaluate(&mut self, state: &mut GameState, player: Player) -> f64 {
        self.evaluator.evaluate(state, player)
    }

    /// Search with iterative deepening, reporting each completed depth to the observer.
    ///
    /// The state is searched in place and restored before returning, also when the
    /// observer stops the search.
    pub fn think(&mut self, state: &mut GameState, observer: &mut impl SearchObserver) {
        self.nodes = 0;
        let start = Instant::now();
        let mut depth = 1;

        while !observer.should_stop() {
            self.cutoff = false;
            self.reserve(depth);
            let root_player = state.current_player();

            let result = match self.config.algorithm {
                SearchAlgorithm::Negamax => self.negamax(state, depth, 0, observer),
                SearchAlgorithm::Minimax => {
                    self.minimax(state, depth, 0, root_player, observer)
                }
            };
            let Ok(score) = result else { return };

            let report = DepthReport {
                depth,
                nodes: self.nodes,
                score,
                principal_variation: decode_line(state, &self.lines[0]),
                elapsed_seconds: start.elapsed().as_secs_f64(),
                is_final: self.config.depth == Some(depth)
                    || !self.cutoff
                    || score.abs() >= SEARCH_WIN_SCORE - f64::from(depth),
            };
            observer.report(&report);

            if report.is_final {
                return;
            }

            depth += 1;
        }
    }

    /// Make sure there is a move buffer and a line for every ply of a depth.
    fn reserve(&mut self, depth: u32) {
        let plies = depth as usize + 2;

        while self.buffers.len() < plies {
            self.buffers.push(Vec::with_capacity(256));
            self.lines.push(Vec::with_capacity(plies));
        }
    }

    /// Count a node and ask the observer whether to stop every few nodes.
    #[inline]
    fn visit(&mut self, observer: &mut impl SearchObserver) -> Result<(), Stopped> {
        self.nodes += 1;

        if self.nodes.is_multiple_of(self.config.stop_check_interval.max(1))
            && observer.should_stop()
        {
            return Err(Stopped);
        }

        Ok(())
    }

    /// Score a finished game from the perspective of `player`, or `None` if it goes on.
    fn terminal_score(&self, state: &GameState, player: Player, ply: u32) -> Option<f64> {
        let winners = self.rules.winners(state)?;
        let Some(winner) = winners.winner() else { return Some(0.0) };
        let score = SEARCH_WIN_SCORE - f64::from(ply);
        Some(if winner == player { score } else { -score })
    }

    /// Generate the moves of a node into `moves`. At the root they are sorted in the
    /// documented order, so ties go to the same move as in the Python agents.
    fn generate(&self, state: &mut GameState, ply: u32, moves: &mut Vec<Move>) {
        self.rules.legal_moves(state, moves);

        if ply == 0 {
            let mut decoded: Vec<(CoordMove, Move)> =
                moves.iter().map(|&mv| (state.decode(mv), mv)).collect();
            decoded.sort_unstable_by_key(|&(coord_move, _)| coord_move);
            moves.clear();
            moves.extend(decoded.into_iter().map(|(_, mv)| mv));
        }
    }

    /// Record a new best move at a ply: the move followed by the line below it.
    fn update_line(&mut self, ply: usize, mv: Option<Move>) {
        let (above, below) = self.lines.split_at_mut(ply + 1);
        let line = &mut above[ply];
        line.clear();
        line.push(mv);
        line.extend_from_slice(&below[0]);
    }

    /// Search a node with negamax: the score is from the perspective of the player to
    /// move, and child scores are negated.
    fn negamax(
        &mut self,
        state: &mut GameState,
        depth: u32,
        ply: u32,
        observer: &mut impl SearchObserver,
    ) -> Result<f64, Stopped> {
        self.visit(observer)?;
        let index = ply as usize;
        self.lines[index].clear();
        let player = state.current_player();

        if let Some(score) = self.terminal_score(state, player, ply) {
            return Ok(score);
        }

        if depth == 0 {
            self.cutoff = true;
            return Ok(self.evaluator.evaluate(state, player));
        }

        let mut moves = std::mem::take(&mut self.buffers[index]);
        self.generate(state, ply, &mut moves);
        let mut best = f64::NEG_INFINITY;

        for position in 0..moves.len().max(1) {
            let mv = moves.get(position).copied();
            state.apply_move(mv);
            let child = self.negamax(state, depth - 1, ply + 1, observer);
            state.undo_move(mv);

            let Ok(child) = child else {
                self.buffers[index] = moves;
                return Err(Stopped);
            };
            let score = -child;

            if score > best {
                best = score;
                self.update_line(index, mv);
            }
        }

        self.buffers[index] = moves;
        Ok(best)
    }

    /// Search a node with minimax: the score is from the perspective of `root_player`,
    /// maximized where that player moves and minimized elsewhere.
    fn minimax(
        &mut self,
        state: &mut GameState,
        depth: u32,
        ply: u32,
        root_player: Player,
        observer: &mut impl SearchObserver,
    ) -> Result<f64, Stopped> {
        self.visit(observer)?;
        let index = ply as usize;
        self.lines[index].clear();

        if let Some(score) = self.terminal_score(state, root_player, ply) {
            return Ok(score);
        }

        if depth == 0 {
            self.cutoff = true;
            return Ok(self.evaluator.evaluate(state, root_player));
        }

        let maximizing = state.current_player() == root_player;
        let mut moves = std::mem::take(&mut self.buffers[index]);
        self.generate(state, ply, &mut moves);
        let mut best = if maximizing { f64::NEG_INFINITY } else { f64::INFINITY };

        for position in 0..moves.len().max(1) {
            let mv = moves.get(position).copied();
            state.apply_move(mv);
            let child = self.minimax(state, depth - 1, ply + 1, root_player, observer);
            state.undo_move(mv);

            let Ok(score) = child else {
                self.buffers[index] = moves;
                return Err(Stopped);
            };

            if (maximizing && score > best) || (!maximizing && score < best) {
                best = score;
                self.update_line(index, mv);
            }
        }

        self.buffers[index] = moves;
        Ok(best)
    }
}

/// Convert a line of moves from a state to coordinates, playing it on a copy.
fn decode_line(state: &GameState, line: &[Option<Move>]) -> Vec<Option<CoordMove>> {
    let mut state = state.clone();
    let mut decoded = Vec::with_capacity(line.len());

    for &mv in line {
        decoded.push(mv.map(|mv| state.decode(mv)));
        state.apply_move(mv);
    }

    decoded
}
