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
    ///     stop_check_interval: The number of nodes between two calls of
    ///         `turn.should_stop`.
    ///     alpha_beta: Whether to prune with alpha-beta, which finds the same scores in
    ///         far fewer nodes but may choose another of several equally scored moves.
    ///     table_megabytes: The size of the transposition table in MB, zero for none.
    ///         Negamax with alpha-beta uses it and orders moves by killers and history.
    ///
    /// Raises:
    ///     ValueError: If `algorithm` is unknown or `depth` is less than one.
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
        stop_check_interval = 1024,
        alpha_beta = true,
        table_megabytes = 32
    ))]
    #[expect(clippy::too_many_arguments, reason = "the agent params, passed by keyword")]
    fn new(
        rules: PyRef<'_, PyRules>,
        algorithm: &str,
        depth: Option<u32>,
        queen_safety: f64,
        mobility: f64,
        positioning: f64,
        material_on_board: f64,
        material_in_hand: f64,
        stop_check_interval: u64,
        alpha_beta: bool,
        table_megabytes: usize,
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

        let weights = EvaluationWeights {
            queen_safety,
            mobility,
            positioning,
            material_on_board,
            material_in_hand,
        };
        let config = SearchConfig {
            algorithm,
            depth,
            weights,
            stop_check_interval,
            alpha_beta,
            table_megabytes,
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
