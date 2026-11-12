//! The search of the search agents: iterative deepening with minimax or negamax.
//!
//! The search runs to depth 1, 2, 3 and so on, reporting the best line after each
//! completed depth, until the depth limit is reached, the game tree is exhausted, the
//! result is decided, or the observer asks to stop. A depth that is interrupted is
//! discarded. This is the behaviour of the Python `SearchAgent`, ported exactly: the same
//! nodes are visited, scores are equal, and the root keeps the first best move in the
//! documented order of legal moves.

use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Instant;

use crate::agents::evaluation::{EvaluationWeights, Evaluator};
use crate::agents::table::{
    TableBound, TableEntry, TranspositionTable, from_table_score, to_table_score,
};
use crate::engine::grid::DIRECTION_COUNT;
use crate::engine::zobrist::ply_key;
use crate::engine::{Cell, Coord, CoordMove, GameState, Move, PieceType, Player, Rules};

/// The number of cells, the stride of the history table per piece type.
const HISTORY_CELLS: usize = 1024;

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
#[expect(
    clippy::struct_excessive_bools,
    reason = "independent on/off agent params, set by keyword"
)]
pub struct SearchConfig {
    /// The tree search.
    pub algorithm: SearchAlgorithm,
    /// The maximum depth in plies, or `None` to search until stopped.
    pub depth: Option<u32>,
    /// The weights of the evaluation terms.
    pub weights: EvaluationWeights,
    /// The number of nodes between two calls of [`SearchObserver::should_stop`].
    pub stop_check_interval: u64,
    /// Whether to prune with alpha-beta, searching the principal variation of the
    /// previous depth first. The root score is the same as without pruning; among moves
    /// with an equal score, another may be chosen.
    pub alpha_beta: bool,
    /// The size of the transposition table in MB, zero for none. Negamax with alpha-beta
    /// uses it, and orders moves by killer moves and a history table too.
    pub table_megabytes: usize,
    /// Initial half-width around the previous score, zero for full windows.
    pub aspiration_window: f64,
    /// Total search threads, including the reporting thread. Negamax only.
    pub threads: usize,
    /// Scout later moves with a minimal window, re-searching improvements exactly.
    pub principal_variation_search: bool,
    /// Reuse transposition table entries searched deeper than needed, not only those of
    /// the same remaining depth.
    pub table_deeper_hits: bool,
    /// The number of moves searched at full depth before later moves of an inner node
    /// at least three plies deep are scouted one ply shallower, zero for none. A reduced
    /// move that improves the score is searched again at full depth. Needs principal
    /// variation search.
    pub late_move_reductions: u32,
    /// The extra depth reduction of a null move (a pass) at scout nodes, zero for none.
    /// When the side to move still scores at least `beta` after passing, the node is cut
    /// off without searching its moves.
    pub null_move_reduction: u32,
    /// Order the moves onto or next to the opponent's queen right after the killer moves.
    pub queen_attack_ordering: bool,
    /// Search a move one ply deeper when it brings a queen to five or more occupied
    /// neighbours, so threats to win are resolved, up to twice the iteration's depth.
    pub queen_threat_extension: bool,
}

impl SearchConfig {
    /// Create a configuration with the given algorithm, depth and weights, and every
    /// refinement of the search off: alpha-beta and a 32 MB table, one thread.
    pub fn new(
        algorithm: SearchAlgorithm,
        depth: Option<u32>,
        weights: EvaluationWeights,
    ) -> Self {
        SearchConfig {
            algorithm,
            depth,
            weights,
            stop_check_interval: 1024,
            alpha_beta: true,
            table_megabytes: 32,
            aspiration_window: 0.0,
            threads: 1,
            principal_variation_search: false,
            table_deeper_hits: false,
            late_move_reductions: 0,
            null_move_reduction: 0,
            queen_attack_ordering: false,
            queen_threat_extension: false,
        }
    }
}

/// The place of a node in the search: its remaining depth, its ply from the root, its
/// alpha-beta window and whether it lies on the principal variation of the previous
/// depth.
#[derive(Clone, Copy, Debug)]
struct Node {
    /// The remaining depth in plies.
    depth: u32,
    /// The number of plies from the root.
    ply: u32,
    /// The score the side to move (negamax) or the root player (minimax) is assured of.
    alpha: f64,
    /// The score the opponent is assured of, as a bound on the side's score.
    beta: f64,
    /// Whether every move from the root to the node follows the previous principal
    /// variation, so its next move is searched first.
    on_principal_variation: bool,
    /// Whether the node may try a null move: not right after another one.
    allow_null: bool,
}

impl Node {
    /// Get the root node of a search to a depth, with an infinite window.
    fn root(depth: u32) -> Self {
        Node {
            depth,
            ply: 0,
            alpha: f64::NEG_INFINITY,
            beta: f64::INFINITY,
            on_principal_variation: true,
            allow_null: true,
        }
    }

    /// Check whether the node has a minimal window, as scouted by principal variation
    /// search, so its exact score is never needed.
    fn is_scout(self) -> bool {
        self.beta.is_finite() && self.alpha >= self.beta.next_down()
    }
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
    /// The principal variation of the previous depth, searched first with alpha-beta.
    previous_line: Vec<Option<Move>>,
    /// The transposition table, kept between decisions.
    table: TranspositionTable,
    /// Two moves per ply that recently caused a cutoff, tried early in sibling nodes.
    killers: Vec<[Option<Move>; 2]>,
    /// How often a move of a piece type onto a cell caused a cutoff, weighted by depth.
    history: Vec<u32>,
    /// Scratch space for ordering moves: the sort key and the move.
    ordering: Vec<(u64, Move)>,
    /// Root move rotation that diversifies helper searches.
    worker_index: usize,
    /// The depth of the iteration in progress, which limits extensions.
    root_depth: u32,
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
            previous_line: Vec::new(),
            table: TranspositionTable::new(config.table_megabytes),
            killers: Vec::new(),
            history: vec![0; PieceType::COUNT * HISTORY_CELLS],
            ordering: Vec::new(),
            worker_index: 0,
            root_depth: 0,
        }
    }

    /// Get the configuration.
    pub fn config(&self) -> &SearchConfig {
        &self.config
    }

    /// Forget everything learned in earlier decisions: the transposition table, the
    /// killer moves and the history, for example before a new game.
    pub fn clear(&mut self) {
        self.table.clear();
        self.killers.clear();
        self.history.fill(0);
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
        if self.config.threads <= 1 || self.config.algorithm != SearchAlgorithm::Negamax {
            self.think_serial(state, observer);
            return;
        }

        self.table.share();
        let stop = AtomicBool::new(false);
        std::thread::scope(|scope| {
            let _cancel_helpers = SearchCancellation { stop: &stop };
            for index in 1..self.config.threads {
                let mut helper = self.clone();
                helper.worker_index = index;
                let mut position = state.clone();
                let stop = &stop;
                scope.spawn(move || {
                    helper.think_serial(&mut position, &mut HelperObserver { stop });
                });
            }

            self.think_serial(state, observer);
        });
    }

    /// Run iterative deepening on one thread; only the main thread calls the client.
    fn think_serial(
        &mut self,
        state: &mut GameState,
        observer: &mut impl SearchObserver,
    ) {
        self.nodes = 0;
        self.previous_line.clear();
        let start = Instant::now();
        let mut depth = 1;
        let mut previous_score = 0.0;

        while !observer.should_stop() {
            self.cutoff = false;
            self.reserve(depth);
            let root_player = state.current_player();

            self.root_depth = depth;
            let mut root = Node::root(depth);
            let mut width = self.config.aspiration_window;

            if depth > 1 && self.config.alpha_beta && width > 0.0 {
                root.alpha = previous_score - width;
                root.beta = previous_score + width;
            }

            let score = loop {
                self.cutoff = false;
                let result = match self.config.algorithm {
                    SearchAlgorithm::Negamax => self.negamax(state, root, observer),
                    SearchAlgorithm::Minimax => {
                        self.minimax(state, root, root_player, observer)
                    }
                };
                let Ok(score) = result else { return };

                if score > root.alpha && score < root.beta {
                    break score;
                }

                // A failed window is only a bound. Widen before publishing a result.
                if observer.should_stop() {
                    return;
                }

                width *= 4.0;
                if width >= SEARCH_WIN_SCORE || !width.is_finite() {
                    root = Node::root(depth);
                } else {
                    root.alpha = score - width;
                    root.beta = score + width;
                }
            };
            previous_score = score;

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

            self.previous_line.clone_from(&self.lines[0]);
            depth += 1;
        }
    }

    /// Make sure there is a move buffer and a line for every ply of a depth.
    fn reserve(&mut self, depth: u32) {
        let extended = if self.config.queen_threat_extension { 2 * depth } else { depth };
        let plies = extended as usize + 2;

        while self.buffers.len() < plies {
            self.buffers.push(Vec::with_capacity(256));
            self.lines.push(Vec::with_capacity(plies));
        }

        while self.killers.len() < plies {
            self.killers.push([None; 2]);
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

            if !moves.is_empty() {
                let rotation = self.worker_index % moves.len();
                moves.rotate_left(rotation);
            }
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

    /// Move the move of the previous principal variation at a node to the front of its
    /// moves, keeping the order of the others. Returns whether the node follows that
    /// variation, so its children may too.
    fn order_principal_variation(&self, node: Node, moves: &mut [Move]) -> bool {
        if !self.config.alpha_beta || !node.on_principal_variation {
            return false;
        }

        let Some(&expected) = self.previous_line.get(node.ply as usize) else {
            return false;
        };

        if let Some(mv) = expected
            && let Some(position) = moves.iter().position(|&candidate| candidate == mv)
        {
            moves[..=position].rotate_right(1);
        }

        true
    }

    /// Check whether a child of a node that follows the previous principal variation
    /// follows it too: its move is the variation's move at the node.
    fn follows_principal_variation(
        &self,
        follows: bool,
        ply: u32,
        mv: Option<Move>,
    ) -> bool {
        follows && self.previous_line.get(ply as usize) == Some(&mv)
    }

    /// Order the moves of an inner node: the moves in `first` in their order (the move of
    /// the previous principal variation, the table move and the killer moves), then the
    /// moves onto or next to `enemy_queen` if given, then the rest by their history,
    /// keeping the generation order between equals.
    fn order_moves(
        &mut self,
        first: [Option<Move>; 4],
        enemy_queen: Option<Cell>,
        moves: &mut [Move],
    ) {
        let ordering = &mut self.ordering;
        ordering.clear();

        for (position, &mv) in moves.iter().enumerate() {
            let attacks = enemy_queen.is_some_and(|queen| {
                let target = mv.target();
                target == queen
                    || (0..DIRECTION_COUNT).any(|side| queen.neighbor(side) == target)
            });
            let rank =
                first.iter().position(|&candidate| candidate == Some(mv)).map_or_else(
                    || {
                        if attacks {
                            u64::from(u32::MAX) - 8
                        } else {
                            u64::from(self.history[history_index(mv)])
                        }
                    },
                    |priority| u64::from(u32::MAX) - priority as u64,
                );
            let key = (rank << 16) | (0xffff - (position as u64).min(0xffff));
            ordering.push((key, mv));
        }

        ordering.sort_unstable_by_key(|&(key, _)| std::cmp::Reverse(key));

        for (slot, &(_, mv)) in moves.iter_mut().zip(ordering.iter()) {
            *slot = mv;
        }
    }

    /// Order the moves of an inner node at a ply with [`Searcher::order_moves`]: first
    /// the previous principal variation's move if the node follows it, the table move and
    /// the killers of the ply.
    fn order_inner_moves(
        &mut self,
        state: &GameState,
        index: usize,
        follows: bool,
        table_move: Option<Move>,
        moves: &mut [Move],
    ) {
        let expected = if follows { self.previous_line[index] } else { None };
        let killers = self.killers[index];
        let enemy_queen = if self.config.queen_attack_ordering {
            state.queen_coord(state.current_player().opponent()).map(Coord::cell)
        } else {
            None
        };
        self.order_moves(
            [expected, table_move, killers[0], killers[1]],
            enemy_queen,
            moves,
        );
    }

    /// Remember a move that caused a cutoff at a ply, as a killer and in the history.
    fn record_cutoff(&mut self, index: usize, depth: u32, mv: Move) {
        let killers = &mut self.killers[index];

        if killers[0] != Some(mv) {
            killers[1] = killers[0];
            killers[0] = Some(mv);
        }

        let entry = &mut self.history[history_index(mv)];
        *entry = entry.saturating_add(depth * depth);
    }

    /// Search a node with negamax: the score is from the perspective of the player to
    /// move, and child scores are negated. With alpha-beta, the search of a node stops as
    /// soon as a move scores at least `beta`, which the opponent will not allow. Results
    /// are stored in the transposition table and reused when a position recurs at the
    /// same remaining depth; moves are ordered by the table, killers and
    /// history.
    fn negamax(
        &mut self,
        state: &mut GameState,
        node: Node,
        observer: &mut impl SearchObserver,
    ) -> Result<f64, Stopped> {
        self.visit(observer)?;
        let index = node.ply as usize;
        self.lines[index].clear();
        let player = state.current_player();

        if let Some(score) = self.terminal_score(state, player, node.ply) {
            return Ok(score);
        }

        if node.depth == 0 {
            self.cutoff = true;
            return Ok(self.evaluator.evaluate(state, player));
        }

        let use_table = self.config.alpha_beta && self.config.table_megabytes > 0;
        let key = state.hash() ^ ply_key(state.current_ply());
        let mut table_move = None;

        if use_table && let Some(entry) = self.table.probe(key) {
            table_move = entry.best_move();
            let score = from_table_score(entry.score, node.ply);
            let depth_matches = if self.config.table_deeper_hits {
                u32::from(entry.depth) >= node.depth
            } else {
                u32::from(entry.depth) == node.depth
            };
            let usable = index > 0
                && depth_matches
                && match entry.bound {
                    TableBound::Exact => true,
                    TableBound::Lower => score >= node.beta,
                    TableBound::Upper => score <= node.alpha,
                };

            if usable {
                self.cutoff |= entry.cutoff;
                self.lines[index].push(table_move);
                return Ok(score);
            }
        }

        if self.null_move_cuts_off(state, node, player, observer)? {
            return Ok(node.beta);
        }

        let mut moves = std::mem::take(&mut self.buffers[index]);
        self.generate(state, node.ply, &mut moves);
        let follows = self.order_principal_variation(node, &mut moves);

        if use_table && index > 0 && moves.len() > 1 {
            self.order_inner_moves(state, index, follows, table_move, &mut moves);
        }

        let outer_cutoff = std::mem::replace(&mut self.cutoff, false);
        let mut alpha = node.alpha;
        let mut best = f64::NEG_INFINITY;
        let crowding = queen_crowding(state);

        for position in 0..moves.len().max(1) {
            let mv = moves.get(position).copied();
            state.apply_move(mv);
            let extend = self.extends(state, node, crowding);
            let mut child = Node {
                depth: node.depth - 1 + u32::from(extend),
                ply: node.ply + 1,
                alpha: -node.beta,
                beta: -alpha,
                on_principal_variation: self
                    .follows_principal_variation(follows, node.ply, mv),
                allow_null: true,
            };
            let late = self.config.late_move_reductions;
            let reduce = late > 0
                && index > 0
                && node.depth >= 3
                && mv.is_some()
                && !extend
                && position >= late as usize;
            child.allow_null = !extend;
            let result = self.search_child(state, child, position > 0, reduce, observer);
            state.undo_move(mv);

            let Ok(child_score) = result else {
                self.buffers[index] = moves;
                return Err(Stopped);
            };
            let score = -child_score;

            if score > best {
                best = score;
                self.update_line(index, mv);
            }

            if self.config.alpha_beta {
                alpha = alpha.max(best);

                if alpha >= node.beta {
                    if let Some(mv) = mv
                        && use_table
                    {
                        self.record_cutoff(index, node.depth, mv);
                    }

                    break;
                }
            }
        }

        self.buffers[index] = moves;
        let subtree_cutoff = self.cutoff;
        self.cutoff |= outer_cutoff;

        if use_table {
            self.store_node(key, node, best, subtree_cutoff);
        }

        Ok(best)
    }

    /// Store the result of a searched node in the transposition table, with its bound
    /// relative to the node's window and the first move of its line.
    fn store_node(&mut self, key: u64, node: Node, best: f64, subtree_cutoff: bool) {
        let bound = if best <= node.alpha {
            TableBound::Upper
        } else if best >= node.beta {
            TableBound::Lower
        } else {
            TableBound::Exact
        };
        let best_move = self.lines[node.ply as usize].first().copied().flatten();
        self.table.store(TableEntry {
            key,
            score: to_table_score(best, node.ply),
            best: best_move.map_or(0, Move::bits),
            depth: u8::try_from(node.depth).unwrap_or(u8::MAX),
            bound,
            cutoff: subtree_cutoff,
        });
    }

    /// Scout a later child, then search its full window if it improves the best score.
    /// A reduced child is scouted one ply shallower first, and searched as usual when
    /// that scout does not fail low for the parent.
    fn search_child(
        &mut self,
        state: &mut GameState,
        child: Node,
        scout: bool,
        reduce: bool,
        observer: &mut impl SearchObserver,
    ) -> Result<f64, Stopped> {
        if !scout
            || !self.config.alpha_beta
            || !self.config.principal_variation_search
            || !child.beta.is_finite()
        {
            return self.negamax(state, child, observer);
        }

        let narrow = Node { alpha: child.beta.next_down(), ..child };

        if reduce {
            let reduced = Node { depth: child.depth - 1, ..narrow };
            let score = self.negamax(state, reduced, observer)?;

            if score >= child.beta {
                return Ok(score);
            }
        }

        let score = self.negamax(state, narrow, observer)?;

        if score > child.alpha && score < child.beta {
            self.negamax(state, child, observer)
        } else {
            Ok(score)
        }
    }

    /// Check whether the move just applied at a node is extended: the option is on, the
    /// extended line stays within twice the iteration's depth, and a queen's occupied
    /// neighbours grew to five or more from `before`, its count at the node.
    fn extends(&self, state: &GameState, node: Node, before: [usize; 2]) -> bool {
        if !self.config.queen_threat_extension
            || node.ply + node.depth >= 2 * self.root_depth
        {
            return false;
        }

        let after = queen_crowding(state);
        (0..2).any(|index| after[index] >= 5 && after[index] > before[index])
    }

    /// Try a null move at a node if [`Searcher::null_move_applies`]: pass, and search the
    /// opponent's reply shallower with a minimal window at `beta`. Returns whether the
    /// player still reaches `beta`, so the node can be cut off.
    fn null_move_cuts_off(
        &mut self,
        state: &mut GameState,
        node: Node,
        player: Player,
        observer: &mut impl SearchObserver,
    ) -> Result<bool, Stopped> {
        if !self.null_move_applies(state, node, player) {
            return Ok(false);
        }

        let child = Node {
            depth: node.depth - 1 - self.config.null_move_reduction,
            ply: node.ply + 1,
            alpha: -node.beta,
            beta: (-node.beta).next_up(),
            on_principal_variation: false,
            allow_null: false,
        };
        state.apply_move(None);
        let result = self.negamax(state, child, observer);
        state.undo_move(None);
        let score = -result?;
        self.lines[node.ply as usize].clear();
        let cuts_off = score >= node.beta;
        self.cutoff |= cuts_off;
        Ok(cuts_off)
    }

    /// Check whether a node tries a null move: the option is on, the node is an inner
    /// scout node deep enough for the reduction, not right after another null move, the
    /// player's queen is placed with at most three neighbours, and the static evaluation
    /// already reaches `beta`.
    fn null_move_applies(
        &mut self,
        state: &mut GameState,
        node: Node,
        player: Player,
    ) -> bool {
        let reduction = self.config.null_move_reduction;

        if reduction == 0
            || !self.config.alpha_beta
            || node.ply == 0
            || !node.allow_null
            || !node.is_scout()
            || node.depth < reduction + 2
        {
            return false;
        }

        let Some(queen) = state.queen_coord(player) else { return false };

        if state.board().count_occupied_neighbors(queen.cell()) > 3 {
            return false;
        }

        self.evaluator.evaluate(state, player) >= node.beta
    }

    /// Search a node with minimax: the score is from the perspective of `root_player`,
    /// maximized where that player moves and minimized elsewhere. With alpha-beta, the
    /// search of a node stops once its score leaves the window `alpha..beta`.
    fn minimax(
        &mut self,
        state: &mut GameState,
        node: Node,
        root_player: Player,
        observer: &mut impl SearchObserver,
    ) -> Result<f64, Stopped> {
        self.visit(observer)?;
        let index = node.ply as usize;
        self.lines[index].clear();

        if let Some(score) = self.terminal_score(state, root_player, node.ply) {
            return Ok(score);
        }

        if node.depth == 0 {
            self.cutoff = true;
            return Ok(self.evaluator.evaluate(state, root_player));
        }

        let maximizing = state.current_player() == root_player;
        let mut moves = std::mem::take(&mut self.buffers[index]);
        self.generate(state, node.ply, &mut moves);
        let follows = self.order_principal_variation(node, &mut moves);
        let (mut alpha, mut beta) = (node.alpha, node.beta);
        let mut best = if maximizing { f64::NEG_INFINITY } else { f64::INFINITY };

        for position in 0..moves.len().max(1) {
            let mv = moves.get(position).copied();
            let child = Node {
                depth: node.depth - 1,
                ply: node.ply + 1,
                alpha,
                beta,
                on_principal_variation: self
                    .follows_principal_variation(follows, node.ply, mv),
                allow_null: true,
            };
            state.apply_move(mv);
            let result = self.minimax(state, child, root_player, observer);
            state.undo_move(mv);

            let Ok(score) = result else {
                self.buffers[index] = moves;
                return Err(Stopped);
            };

            if (maximizing && score > best) || (!maximizing && score < best) {
                best = score;
                self.update_line(index, mv);
            }

            if self.config.alpha_beta {
                if maximizing {
                    alpha = alpha.max(best);
                } else {
                    beta = beta.min(best);
                }

                if alpha >= beta {
                    break;
                }
            }
        }

        self.buffers[index] = moves;
        Ok(best)
    }
}

/// Count the occupied neighbours of both queens, by player index, zero if unplaced.
fn queen_crowding(state: &GameState) -> [usize; 2] {
    Player::ALL.map(|player| {
        state
            .queen_coord(player)
            .map_or(0, |queen| state.board().count_occupied_neighbors(queen.cell()))
    })
}

/// Get the slot of a move in the history table: its piece type and target cell.
fn history_index(mv: Move) -> usize {
    mv.piece_type().index() * HISTORY_CELLS + mv.target().index()
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

/// A helper only polls the shared cancellation flag; its table entries help the main
/// search, but incomplete or speculative helper results are never submitted.
struct HelperObserver<'a> {
    /// Set when the reporting thread finishes or is stopped by its observer.
    stop: &'a AtomicBool,
}

impl SearchObserver for HelperObserver<'_> {
    fn should_stop(&mut self) -> bool {
        self.stop.load(Ordering::Relaxed)
    }

    fn report(&mut self, _report: &DepthReport) {}
}

/// Cancels helpers on normal return and when a client observer unwinds with a panic.
struct SearchCancellation<'a> {
    /// The flag polled by every helper.
    stop: &'a AtomicBool,
}

impl Drop for SearchCancellation<'_> {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
    }
}
