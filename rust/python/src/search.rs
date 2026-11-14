//! The Python `Searcher` class, the search of the search agents.

use hive_core::agents::{
    DepthReport, EvaluationWeights, SearchAlgorithm, SearchConfig, SearchObserver,
    Searcher,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use crate::moves::PyMove;
use crate::rules::PyRules;
use crate::state::PyGameState;
use crate::values::extract_player;

/// The tree search of the search agents, which runs in the Rust core.
///
/// A search agent builds one searcher from its params and hands it every decision with
/// `think`. The search deepens iteratively: after each completed depth it reports
/// `depth`, `nodes`, `score`, `pv` and `nps` to `turn.info` and submits the first move of
/// the principal variation, final once the depth limit is reached, the whole game tree
/// was searched or the result is decided. It asks `turn.should_stop` before each depth
/// and every `stop_check_interval` nodes, and discards a depth that is interrupted. The
/// search runs without the GIL and holds it only for these calls.
///
/// Attributes:
///     nodes: The number of nodes the last decision visited.
#[pyclass(name = "Searcher", module = "hive.agents.search")]
pub(crate) struct PySearcher {
    /// The search in the Rust core.
    inner: Searcher,
}

/// A search observer that talks to a Python turn context.
struct TurnObserver {
    /// The turn context of the decision.
    turn: Py<PyAny>,
    /// The first error a call into Python raised, which stops the search.
    error: Option<PyErr>,
}

impl TurnObserver {
    /// Report a completed depth to the turn: `info`, then `submit` of the best move.
    fn send_report(&self, py: Python<'_>, report: &DepthReport) -> PyResult<()> {
        let turn = self.turn.bind(py);
        let line = report
            .principal_variation
            .iter()
            .map(|&mv| match mv {
                None => Ok(py.None().into_bound(py)),
                Some(_) => PyMove::to_object(py, mv)?.call_method0("to_json"),
            })
            .collect::<PyResult<Vec<_>>>()?;
        let info = PyDict::new(py);
        info.set_item("depth", report.depth)?;
        info.set_item("nodes", report.nodes)?;
        info.set_item("score", report.score)?;
        info.set_item("pv", PyList::new(py, line)?)?;
        info.set_item("nps", nodes_per_second(report))?;
        turn.call_method("info", (), Some(&info))?;

        let best = report.principal_variation.first().copied().flatten();
        let submission = PyDict::new(py);
        submission.set_item("move", PyMove::to_object(py, best)?)?;
        submission.set_item("final", report.is_final)?;
        turn.call_method("submit", (), Some(&submission))?;
        Ok(())
    }
}

/// Get the nodes per second of a report, rounded like Python's `round`, or `None` if no
/// time was measured.
fn nodes_per_second(report: &DepthReport) -> Option<i64> {
    if report.elapsed_seconds <= 0.0 {
        return None;
    }

    #[expect(
        clippy::cast_precision_loss,
        clippy::cast_possible_truncation,
        reason = "node counts and speeds are far below 2^52"
    )]
    let rounded = (report.nodes as f64 / report.elapsed_seconds).round_ties_even() as i64;
    Some(rounded)
}

impl SearchObserver for TurnObserver {
    fn should_stop(&mut self) -> bool {
        if self.error.is_some() {
            return true;
        }

        Python::attach(|py| {
            let answer = self
                .turn
                .bind(py)
                .call_method0("should_stop")
                .and_then(|stop| stop.is_truthy());
            answer.unwrap_or_else(|error| {
                self.error = Some(error);
                true
            })
        })
    }

    fn report(&mut self, report: &DepthReport) {
        if self.error.is_none() {
            self.error = Python::attach(|py| self.send_report(py, report).err());
        }
    }
}

#[pymethods]
impl PySearcher {
    /// Create a searcher.
    ///
    /// Args:
    ///     rules: The rules governing the game.
    ///     algorithm: The tree search, `"minimax"` or `"negamax"`.
    ///     depth: The maximum search depth in plies, or `None` to search until stopped.
    ///     queen_safety: The weight of the occupied neighbours of the opponent's queen
    ///         minus those of the player's own queen.
    ///     mobility: The weight of the player's legal moves minus the opponent's.
    ///     positioning: The weight of the player's pieces next to the opponent's queen
    ///         minus the opponent's pieces next to the player's queen.
    ///     material_on_board: The weight of the value of the player's pieces on the
    ///         board minus the opponent's.
    ///     material_in_hand: The weight of the value of the player's pieces in hand
    ///         minus the opponent's.
    ///     queen_danger: Nonlinear queen crowding: squared occupied-neighbour counts.
    ///     queen_escape: Legal queen escapes, excluding covered or pinned queens.
    ///     pinned_material: Opponent minus own covered or articulation-pinned material.
    ///     free_ants: Own minus opponent uncovered, unpinned ants after queen placement.
    ///     beetle_control: Elevated beetle balance, doubled over an enemy queen.
    ///     tempo: A bonus for the player to move.
    ///     mobile_queen: Own minus opponent queens that can take a first step.
    ///     mobile_beetle: Own minus opponent beetles that can move.
    ///     mobile_grasshopper: Own minus opponent grasshoppers that can move.
    ///     mobile_spider: Own minus opponent spiders that can take a first step.
    ///     mobile_ant: Own minus opponent ants that can take a first step.
    ///     placement_cells: Own minus opponent free cells to place a piece on.
    ///     queen_locked_neighbors: Queen neighbours its owner cannot move away.
    ///     stop_check_interval: The number of nodes between two calls of
    ///         `turn.should_stop`.
    ///     alpha_beta: Whether to prune with alpha-beta, which finds the same scores in
    ///         far fewer nodes but may choose another of several equally scored moves.
    ///     table_megabytes: The size of the transposition table in MB, zero for none.
    ///         Negamax with alpha-beta uses it and orders moves by killers and history.
    ///     aspiration_window: Initial score half-window, zero to disable aspiration.
    ///     threads: Total negamax search threads sharing one table, at least one.
    ///     principal_variation_search: Scout later moves before a full-window search.
    ///     table_deeper_hits: Reuse table entries searched deeper than needed.
    ///     late_move_reductions: Moves searched at full depth before later ones are
    ///         scouted a ply shallower, zero for none. Needs principal variation search.
    ///     null_move_reduction: Extra depth reduction of a null move at scout nodes,
    ///         zero for none.
    ///     queen_attack_ordering: Order moves next to the enemy queen after killers.
    ///     queen_threat_extension: Search a ply deeper once a queen has five neighbours.
    ///     repetition_draws: Score a repeat of an earlier position as a draw.
    ///     forced_move_extension: Search a forced move without using up depth.
    ///
    /// Raises:
    ///     ValueError: If the algorithm, depth, window or thread count is invalid.
    #[new]
    #[pyo3(signature = (
        rules,
        *,
        algorithm,
        depth = None,
        queen_safety = 1.0,
        mobility = 0.0,
        positioning = 0.0,
        material_on_board = 0.0,
        material_in_hand = 0.0,
        queen_danger = 0.0,
        queen_escape = 0.0,
        pinned_material = 0.0,
        free_ants = 0.0,
        beetle_control = 0.0,
        tempo = 0.0,
        mobile_queen = 0.0,
        mobile_beetle = 0.0,
        mobile_grasshopper = 0.0,
        mobile_spider = 0.0,
        mobile_ant = 0.0,
        placement_cells = 0.0,
        queen_locked_neighbors = 0.0,
        stop_check_interval = 1024,
        alpha_beta = true,
        table_megabytes = 32,
        aspiration_window = 0.0,
        threads = 1,
        principal_variation_search = false,
        table_deeper_hits = false,
        late_move_reductions = 0,
        null_move_reduction = 0,
        queen_attack_ordering = false,
        queen_threat_extension = false,
        repetition_draws = false,
        forced_move_extension = false
    ))]
    #[expect(
        clippy::too_many_arguments,
        clippy::fn_params_excessive_bools,
        reason = "the agent params, passed by keyword"
    )]
    fn new(
        rules: PyRef<'_, PyRules>,
        algorithm: &str,
        depth: Option<u32>,
        queen_safety: f64,
        mobility: f64,
        positioning: f64,
        material_on_board: f64,
        material_in_hand: f64,
        queen_danger: f64,
        queen_escape: f64,
        pinned_material: f64,
        free_ants: f64,
        beetle_control: f64,
        tempo: f64,
        mobile_queen: f64,
        mobile_beetle: f64,
        mobile_grasshopper: f64,
        mobile_spider: f64,
        mobile_ant: f64,
        placement_cells: f64,
        queen_locked_neighbors: f64,
        stop_check_interval: u64,
        alpha_beta: bool,
        table_megabytes: usize,
        aspiration_window: f64,
        threads: usize,
        principal_variation_search: bool,
        table_deeper_hits: bool,
        late_move_reductions: u32,
        null_move_reduction: u32,
        queen_attack_ordering: bool,
        queen_threat_extension: bool,
        repetition_draws: bool,
        forced_move_extension: bool,
    ) -> PyResult<Self> {
        let algorithm = match algorithm {
            "minimax" => SearchAlgorithm::Minimax,
            "negamax" => SearchAlgorithm::Negamax,
            _ => {
                let message = format!("Unknown search algorithm `{algorithm}`.");
                return Err(PyValueError::new_err(message));
            }
        };

        if depth == Some(0) {
            return Err(PyValueError::new_err("The search depth must be at least `1`."));
        }

        if !(1..=256).contains(&threads)
            || !aspiration_window.is_finite()
            || aspiration_window < 0.0
        {
            return Err(PyValueError::new_err(
                "Use 1..256 threads and a finite, nonnegative aspiration_window.",
            ));
        }

        if [
            queen_safety,
            mobility,
            positioning,
            material_on_board,
            material_in_hand,
            queen_danger,
            queen_escape,
            pinned_material,
            free_ants,
            beetle_control,
            tempo,
            mobile_queen,
            mobile_beetle,
            mobile_grasshopper,
            mobile_spider,
            mobile_ant,
            placement_cells,
            queen_locked_neighbors,
        ]
        .iter()
        .any(|weight| !weight.is_finite())
        {
            return Err(PyValueError::new_err("Evaluation weights must be finite."));
        }

        let weights = EvaluationWeights {
            queen_safety,
            mobility,
            positioning,
            material_on_board,
            material_in_hand,
            queen_danger,
            queen_escape,
            pinned_material,
            free_ants,
            beetle_control,
            tempo,
            mobile_queen,
            mobile_beetle,
            mobile_grasshopper,
            mobile_spider,
            mobile_ant,
            placement_cells,
            queen_locked_neighbors,
        };
        let config = SearchConfig {
            algorithm,
            depth,
            weights,
            stop_check_interval,
            alpha_beta,
            table_megabytes,
            aspiration_window,
            threads,
            principal_variation_search,
            table_deeper_hits,
            late_move_reductions,
            null_move_reduction,
            queen_attack_ordering,
            queen_threat_extension,
            repetition_draws,
            forced_move_extension,
        };
        Ok(PySearcher { inner: Searcher::new(rules.inner, config) })
    }

    /// Forget the transposition table, killer moves and history, before a new game.
    fn clear(&mut self) {
        self.inner.clear();
    }

    /// The number of nodes the last decision visited.
    #[getter]
    fn nodes(&self) -> u64 {
        self.inner.nodes()
    }

    /// Search a decision with iterative deepening, reporting to the turn.
    ///
    /// Args:
    ///     state: The state to decide a move in, searched in place and restored before
    ///         returning, also when the turn stops the search.
    ///     turn: The turn context: `should_stop`, `info` and `submit` are called on it.
    ///
    /// Returns:
    ///     The number of nodes visited.
    ///
    /// Raises:
    ///     Exception: Whatever a call on `turn` raised, which stops the search.
    fn think(
        &mut self,
        py: Python<'_>,
        mut state: PyRefMut<'_, PyGameState>,
        turn: &Bound<'_, PyAny>,
    ) -> PyResult<u64> {
        let mut observer = TurnObserver { turn: turn.clone().unbind(), error: None };
        let searcher = &mut self.inner;
        let inner = &mut state.inner;
        py.detach(|| searcher.think(inner, &mut observer));

        match observer.error {
            Some(error) => Err(error),
            None => Ok(self.inner.nodes()),
        }
    }

    /// Evaluate a position as the weighted sum of the evaluation terms.
    ///
    /// Args:
    ///     state: The game state to evaluate.
    ///     player: The player from whose perspective the position is evaluated.
    ///
    /// Returns:
    ///     A score where positive values favour `player`.
    fn evaluate(
        &mut self,
        mut state: PyRefMut<'_, PyGameState>,
        player: &Bound<'_, PyAny>,
    ) -> PyResult<f64> {
        let player = extract_player(player)?;
        Ok(self.inner.evaluate(&mut state.inner, player))
    }
}
