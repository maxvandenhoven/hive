//! The Python `Rules` class.

use hive_core::engine::{Coord, CoordMove, Piece, Player, Rules, RulesConfig};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple, PyType};

use crate::json;
use crate::moves::PyMove;
use crate::state::{PyGameState, extract_piece_counts};
use crate::values::{
    PythonValues, coord_tuple, extract_coord, extract_piece, extract_player, to_py_err,
};

/// The rules of a Hive game, holding both the configuration and the rule behaviour.
///
/// `Rules` is an immutable value: it is hashable, equal for equal fields, and cheap to
/// pass to worker processes or to store. Every method reads the configuration and a
/// `GameState`, and never modifies the state permanently. The JSON form is an object with
/// every field and `piece_counts` keyed by piece type name; missing fields take their
/// default when reading.
///
/// Attributes:
///     piece_counts: The number of copies of each piece type a player receives. Any
///         mapping is accepted and stored as a read-only mapping ordered by piece type.
///     starting_player: The player who takes the first turn.
///     queen_by_turn: The turn number (one-indexed, per player) by which the queen must
///         be placed, or `None` for no deadline.
///     allow_queen_first_turn: Whether the queen may be placed on a player's first turn.
///     move_before_queen: Whether pieces may move before their owner's queen is placed.
///     max_turns: The maximum number of turns per player before the game is a draw, or
///         `None` for no limit.
#[pyclass(name = "Rules", module = "hive.engine.rules", frozen, eq, hash)]
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub(crate) struct PyRules {
    /// The rules in the Rust core.
    pub(crate) inner: Rules,
}

/// Build a Python list of moves.
fn move_list(
    py: Python<'_>,
    moves: impl IntoIterator<Item = Option<CoordMove>>,
) -> PyResult<Bound<'_, PyList>> {
    let items = moves
        .into_iter()
        .map(|mv| PyMove::to_object(py, mv))
        .collect::<PyResult<Vec<_>>>()?;
    PyList::new(py, items)
}

#[pymethods]
impl PyRules {
    /// Create and validate the rules.
    ///
    /// Args:
    ///     piece_counts: The number of copies of each piece type a player receives, or
    ///         `None` for the base game.
    ///     starting_player: The player who takes the first turn, or `None` for white.
    ///     queen_by_turn: The turn by which the queen must be placed, or `None`.
    ///     allow_queen_first_turn: Whether the queen may be placed on the first turn.
    ///     move_before_queen: Whether pieces may move before their queen is placed.
    ///     max_turns: The turns per player before the game is a draw, or `None`.
    ///
    /// Raises:
    ///     ValueError: If the queen count is not exactly one, a count is negative, a
    ///         player would receive more than 14 pieces, or the queen must be placed on
    ///         the first turn while that is not allowed.
    #[new]
    #[pyo3(
        text_signature = "(piece_counts=None, starting_player=None, queen_by_turn=4, \
                          allow_queen_first_turn=True, move_before_queen=False, \
                          max_turns=None)",
        signature = (
        piece_counts = None,
        starting_player = None,
        queen_by_turn = Some(4),
        allow_queen_first_turn = true,
        move_before_queen = false,
        max_turns = None
        )
    )]
    fn new(
        py: Python<'_>,
        piece_counts: Option<&Bound<'_, PyAny>>,
        starting_player: Option<&Bound<'_, PyAny>>,
        queen_by_turn: Option<i64>,
        allow_queen_first_turn: bool,
        move_before_queen: bool,
        max_turns: Option<i64>,
    ) -> PyResult<Self> {
        let mut config = RulesConfig {
            queen_by_turn,
            allow_queen_first_turn,
            move_before_queen,
            max_turns,
            ..RulesConfig::default()
        };

        if let Some(piece_counts) = piece_counts {
            config.piece_counts = extract_piece_counts(piece_counts)?;
        }

        if let Some(starting_player) = starting_player {
            config.starting_player = extract_player(starting_player)?;
        }

        Ok(PyRules { inner: Rules::new(config).map_err(|error| to_py_err(py, error))? })
    }

    /// The number of copies of each piece type a player receives, read-only.
    #[getter]
    fn piece_counts<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let values = PythonValues::get(py)?;
        let counts = PyDict::new(py);

        for (piece_type, count) in self.inner.config().piece_counts.iter() {
            counts.set_item(values.piece_type(py, piece_type), count)?;
        }

        values.read_only(py, &counts)
    }

    /// The player who takes the first turn.
    #[getter]
    fn starting_player<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        Ok(PythonValues::get(py)?.player(py, self.inner.config().starting_player))
    }

    /// The turn by which the queen must be placed, or `None` for no deadline.
    #[getter]
    fn queen_by_turn(&self) -> Option<i64> {
        self.inner.config().queen_by_turn
    }

    /// Whether the queen may be placed on a player's first turn.
    #[getter]
    fn allow_queen_first_turn(&self) -> bool {
        self.inner.config().allow_queen_first_turn
    }

    /// Whether pieces may move before their owner's queen is placed.
    #[getter]
    fn move_before_queen(&self) -> bool {
        self.inner.config().move_before_queen
    }

    /// The maximum number of turns per player before the game is a draw, or `None`.
    #[getter]
    fn max_turns(&self) -> Option<i64> {
        self.inner.config().max_turns
    }

    /// Describe the rules like a dataclass, with every field.
    ///
    /// Returns:
    ///     The representation, for example `Rules(piece_counts=mappingproxy(...), ...)`.
    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        let none = || "None".to_owned();
        let python_bool = |value: bool| if value { "True" } else { "False" };
        let config = self.inner.config();
        Ok(format!(
            "Rules(piece_counts={}, starting_player={}, queen_by_turn={}, \
             allow_queen_first_turn={}, move_before_queen={}, max_turns={})",
            self.piece_counts(py)?.repr()?,
            self.starting_player(py)?.repr()?,
            config.queen_by_turn.map_or_else(none, |turn| turn.to_string()),
            python_bool(config.allow_queen_first_turn),
            python_bool(config.move_before_queen),
            config.max_turns.map_or_else(none, |turns| turns.to_string()),
        ))
    }

    /// Pickle the rules by their fields, so they can be sent to worker processes.
    ///
    /// Returns:
    ///     The class and the constructor arguments that recreate the rules.
    fn __reduce__<'py>(
        slf: &Bound<'py, Self>,
    ) -> PyResult<(Bound<'py, PyType>, Bound<'py, PyTuple>)> {
        let py = slf.py();
        let rules = slf.get();
        let config = rules.inner.config();
        let counts = PyDict::new(py);
        counts.update(rules.piece_counts(py)?.cast::<pyo3::types::PyMapping>()?)?;
        let args = (
            counts,
            rules.starting_player(py)?,
            config.queen_by_turn,
            config.allow_queen_first_turn,
            config.move_before_queen,
            config.max_turns,
        )
            .into_pyobject(py)?;
        Ok((slf.get_type(), args))
    }

    /// Reject assignments, since rules are immutable.
    ///
    /// Args:
    ///     name: The name of the attribute.
    ///     value: The value that was to be assigned.
    ///
    /// Raises:
    ///     dataclasses.FrozenInstanceError: Always.
    #[expect(clippy::unused_self, reason = "Python passes the instance")]
    fn __setattr__(
        &self,
        py: Python<'_>,
        name: &str,
        value: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let _ = value;
        Err(PythonValues::get(py)?.frozen_error(py, name))
    }

    /// Serialize the value.
    ///
    /// Returns:
    ///     The JSON-compatible form, with field aliases and enums as names.
    fn to_json<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyAny>> {
        json::to_json(slf.as_any())
    }

    /// Deserialize and validate a value.
    ///
    /// Args:
    ///     data: The JSON-compatible form, for example from `json.loads`.
    ///
    /// Returns:
    ///     The value.
    ///
    /// Raises:
    ///     pydantic.ValidationError: If `data` does not describe a valid value. It is a
    ///         `ValueError` that lists the location of every problem.
    #[classmethod]
    fn from_json<'py>(
        cls: &Bound<'py, PyType>,
        data: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        json::from_json(cls, data)
    }

    /// Describe the value to pydantic through its JSON form in `hive.engine.forms`.
    ///
    /// Args:
    ///     source: The annotated type, this class.
    ///     handler: Builds the schemas of other types.
    ///
    /// Returns:
    ///     The pydantic core schema of the value.
    #[classmethod]
    fn __get_pydantic_core_schema__<'py>(
        cls: &Bound<'py, PyType>,
        source: &Bound<'py, PyAny>,
        handler: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let _ = source;
        json::core_schema(cls, handler)
    }

    /// Create the initial game state with an empty board and full hands.
    ///
    /// Returns:
    ///     The initial game state ready for play.
    fn create_initial_state(&self) -> PyGameState {
        PyGameState { inner: self.inner.create_initial_state() }
    }

    /// Create a validated game state from a board.
    ///
    /// The board is copied, so later changes to `board` do not affect the state. The
    /// hands and queen coordinates are derived from the pieces on the board.
    ///
    /// The ply must be consistent with the board: the current player alternates every
    /// ply starting with `starting_player`, and a player cannot have more pieces on the
    /// board than turns taken. If `current_ply` is `None`, the lowest consistent ply is
    /// used. For a game with placements only, this is the number of pieces on the board.
    ///
    /// Args:
    ///     board: The pieces on each occupied coordinate, ordered bottom to top.
    ///     current_player: The player to move.
    ///     current_ply: The number of plies played so far, or `None` to derive it.
    ///
    /// Returns:
    ///     The game state with the given board, player and ply.
    ///
    /// Raises:
    ///     InvalidBoardError: If a stack is empty, a player has more pieces of a type
    ///         than `piece_counts` allows, the pieces are not connected, or the ply is
    ///         inconsistent with the board and current player.
    #[pyo3(name = "from_board", signature = (board, current_player, current_ply = None))]
    fn state_from_board(
        &self,
        py: Python<'_>,
        board: &Bound<'_, PyAny>,
        current_player: &Bound<'_, PyAny>,
        current_ply: Option<i64>,
    ) -> PyResult<PyGameState> {
        let mut stacks: Vec<(Coord, Vec<Piece>)> = Vec::new();

        for item in board.call_method0("items")?.try_iter()? {
            let (coord, stack): (Bound<'_, PyAny>, Bound<'_, PyAny>) = item?.extract()?;
            let pieces = stack
                .try_iter()?
                .map(|piece| extract_piece(&piece?))
                .collect::<PyResult<_>>()?;
            stacks.push((extract_coord(&coord)?, pieces));
        }

        let player = extract_player(current_player)?;
        let state = self
            .inner
            .from_board(&stacks, player, current_ply)
            .map_err(|error| to_py_err(py, error))?;
        Ok(PyGameState { inner: state })
    }

    /// Validate the ply of a state built from a board, or derive the lowest valid one.
    ///
    /// Args:
    ///     state: The state with its board and current player already set.
    ///     current_ply: The ply to validate, or `None` to derive it.
    ///
    /// Returns:
    ///     The validated or derived ply.
    ///
    /// Raises:
    ///     InvalidBoardError: If `current_ply` is negative, does not match the current
    ///         player, or leaves a player with more pieces on the board than turns taken.
    fn validate_ply(
        &self,
        py: Python<'_>,
        state: PyRef<'_, PyGameState>,
        current_ply: Option<i64>,
    ) -> PyResult<i64> {
        self.inner
            .validate_ply(&state.inner, current_ply)
            .map_err(|error| to_py_err(py, error))
    }

    /// Apply a move to the state after checking that it is legal.
    ///
    /// Use this for moves from outside the engine, such as user input or game records.
    /// Search code that takes moves from `legal_moves` can call `state.apply_move`
    /// directly.
    ///
    /// Args:
    ///     state: The current game state, which is modified in place.
    ///     move: The move to apply, or `None` to pass.
    ///
    /// Raises:
    ///     IllegalMoveError: If the move is not in `legal_moves(state)`. The message
    ///         names the move and the reason from `illegal_move_reason`.
    fn apply_checked_move(
        &self,
        py: Python<'_>,
        mut state: PyRefMut<'_, PyGameState>,
        r#move: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let mv = PyMove::extract_optional(r#move)?;
        self.inner
            .apply_checked_move(&mut state.inner, mv)
            .map_err(|error| to_py_err(py, error))
    }

    /// Explain why a move is not legal, for messages to the player.
    ///
    /// The checks follow the rules from the most basic (is there a piece to move) to the
    /// most specific (can the piece reach the target), and the first that fails is the
    /// reason. Reasons do not repeat the coordinates, which the move already names.
    ///
    /// Args:
    ///     state: The current game state.
    ///     move: A move that is not in `legal_moves(state)`, or `None` for a pass.
    ///
    /// Returns:
    ///     The reason, starting in lower case and without a final period.
    fn illegal_move_reason(
        &self,
        mut state: PyRefMut<'_, PyGameState>,
        r#move: &Bound<'_, PyAny>,
    ) -> PyResult<String> {
        let mv = PyMove::extract_optional(r#move)?;
        Ok(self.inner.illegal_move_reason(&mut state.inner, mv))
    }

    /// Explain why the top piece at a coordinate cannot move, for messages.
    ///
    /// Args:
    ///     state: The current game state.
    ///     coord: The axial coordinate `(q, r)` of the piece.
    ///
    /// Returns:
    ///     The reason, starting in lower case and without a final period, or `None` if
    ///     the piece has at least one legal target.
    fn immobility_reason(
        &self,
        mut state: PyRefMut<'_, PyGameState>,
        coord: &Bound<'_, PyAny>,
    ) -> PyResult<Option<String>> {
        Ok(self.inner.immobility_reason(&mut state.inner, extract_coord(coord)?))
    }

    /// Get all legal moves for the current player.
    ///
    /// Combines the results of `placement_moves` and `movement_moves`. If there are no
    /// legal moves, the returned list contains only `None`, which represents a pass. The
    /// order depends only on the position: placements first, then movements, each sorted
    /// by piece type, source and target coordinate, so seeded agents that pick moves by
    /// index are reproducible.
    ///
    /// Args:
    ///     state: The current game state.
    ///
    /// Returns:
    ///     All legal placement and movement moves, or `[None]` if the current player
    ///     must pass.
    fn legal_moves<'py>(
        &self,
        py: Python<'py>,
        mut state: PyRefMut<'py, PyGameState>,
    ) -> PyResult<Bound<'py, PyList>> {
        move_list(py, self.inner.legal_coord_moves(&mut state.inner))
    }

    /// Get all legal placement moves for the current player.
    ///
    /// Combines each placeable coordinate with each placeable piece type.
    ///
    /// Args:
    ///     state: The current game state.
    ///
    /// Returns:
    ///     All legal placement moves, sorted by piece type and target coordinate. Each
    ///     move has `source_coord` set to `None`.
    fn placement_moves<'py>(
        &self,
        py: Python<'py>,
        state: PyRef<'py, PyGameState>,
    ) -> PyResult<Bound<'py, PyList>> {
        move_list(
            py,
            self.inner.placement_coord_moves(&state.inner).into_iter().map(Some),
        )
    }

    /// Get all legal movement moves for the current player.
    ///
    /// Args:
    ///     state: The current game state.
    ///
    /// Returns:
    ///     All legal movement moves of the pieces returned by `movable_pieces`, sorted by
    ///     piece type, source and target coordinate.
    fn movement_moves<'py>(
        &self,
        py: Python<'py>,
        mut state: PyRefMut<'py, PyGameState>,
    ) -> PyResult<Bound<'py, PyList>> {
        move_list(
            py,
            self.inner.movement_coord_moves(&mut state.inner).into_iter().map(Some),
        )
    }

    /// Get the pieces of the current player that are allowed to move.
    ///
    /// A piece may move if its owner's queen has been placed (unless `move_before_queen`
    /// is `True`), it is the top piece of its stack, and removing it does not split the
    /// hive into disconnected components (the one-hive rule).
    ///
    /// Args:
    ///     state: The current game state.
    ///
    /// Returns:
    ///     The axial coordinate `(q, r)` and piece type of each movable piece, sorted by
    ///     coordinate.
    fn movable_pieces<'py>(
        &self,
        py: Python<'py>,
        state: PyRef<'py, PyGameState>,
    ) -> PyResult<Bound<'py, PyList>> {
        let values = PythonValues::get(py)?;
        let pieces = self.inner.movable_coords(&state.inner).into_iter().map(
            |(coord, piece_type)| {
                PyTuple::new(
                    py,
                    [
                        coord_tuple(py, coord).into_any(),
                        values.piece_type(py, piece_type),
                    ],
                )
            },
        );
        PyList::new(py, pieces.collect::<PyResult<Vec<_>>>()?)
    }

    /// Get the coordinates the top piece at `coord` may move to.
    ///
    /// Args:
    ///     state: The current game state.
    ///     coord: The axial coordinate `(q, r)` of the piece to move.
    ///
    /// Returns:
    ///     All axial coordinates the piece may legally move to, sorted. Empty if the
    ///     piece is not one of the `movable_pieces`.
    ///
    /// Raises:
    ///     ValueError: If `coord` is not occupied.
    fn target_coords<'py>(
        &self,
        py: Python<'py>,
        mut state: PyRefMut<'py, PyGameState>,
        coord: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyList>> {
        let targets = self
            .inner
            .target_coords(&mut state.inner, extract_coord(coord)?)
            .map_err(|error| to_py_err(py, error))?;
        PyList::new(py, targets.into_iter().map(|target| coord_tuple(py, target)))
    }

    /// Get all coordinates where the current player may place a piece from the hand.
    ///
    /// On the first ply the piece is placed at the origin `(0, 0)`, and on the second ply
    /// on any neighbor of the origin. Afterwards a piece may only be placed on an
    /// unoccupied coordinate that is adjacent to at least one of the current player's
    /// pieces and not adjacent to any of the opponent's pieces.
    ///
    /// Args:
    ///     state: The current game state.
    ///
    /// Returns:
    ///     All axial coordinates `(q, r)` where a piece may be placed, sorted.
    fn placeable_coords<'py>(
        &self,
        py: Python<'py>,
        state: PyRef<'py, PyGameState>,
    ) -> PyResult<Bound<'py, PyList>> {
        let coords = self.inner.placeable_coords(&state.inner);
        PyList::new(py, coords.into_iter().map(|coord| coord_tuple(py, coord)))
    }

    /// Get all piece types the current player may place.
    ///
    /// If the queen has not been placed by turn `queen_by_turn`, only the queen may be
    /// placed. If `allow_queen_first_turn` is `False`, the queen may not be placed on the
    /// player's first turn.
    ///
    /// Args:
    ///     state: The current game state.
    ///
    /// Returns:
    ///     All piece types the current player has in hand and is allowed to place,
    ///     sorted.
    fn placeable_piece_types<'py>(
        &self,
        py: Python<'py>,
        state: PyRef<'py, PyGameState>,
    ) -> PyResult<Bound<'py, PyList>> {
        let values = PythonValues::get(py)?;
        let types = self.inner.placeable_piece_types(&state.inner);
        PyList::new(py, types.iter().map(|piece_type| values.piece_type(py, piece_type)))
    }

    /// Determine which players have won the game, if any.
    ///
    /// A player wins when the opponent's queen is surrounded on all six sides. If both
    /// queens are surrounded, or the turn limit `max_turns` has been exceeded, both
    /// players are returned, which indicates a draw.
    ///
    /// Args:
    ///     state: The current game state.
    ///
    /// Returns:
    ///     The winning players if the game has ended, or `None` if the game is still in
    ///     progress. A list with both players indicates a draw.
    fn winners<'py>(
        &self,
        py: Python<'py>,
        state: PyRef<'py, PyGameState>,
    ) -> PyResult<Option<Bound<'py, PyList>>> {
        let Some(winners) = self.inner.winners(&state.inner) else { return Ok(None) };
        let values = PythonValues::get(py)?;
        let players =
            winners.players().into_iter().map(|player: Player| values.player(py, player));
        Ok(Some(PyList::new(py, players)?))
    }

    /// Check whether the game has ended.
    ///
    /// Args:
    ///     state: The current game state.
    ///
    /// Returns:
    ///     `True` if `winners` returns a result, otherwise `False`.
    fn is_finished(&self, state: PyRef<'_, PyGameState>) -> bool {
        self.inner.is_finished(&state.inner)
    }

    /// Count the leaf positions of the game tree to a fixed depth, in Rust.
    ///
    /// Every leaf is applied and undone, like the Python perft of `hive.bench`. The
    /// count runs without the GIL.
    ///
    /// Args:
    ///     state: The game state to start from, which is restored afterwards.
    ///     depth: The number of plies to walk.
    ///
    /// Returns:
    ///     The number of positions reached after exactly `depth` plies.
    fn perft(
        &self,
        py: Python<'_>,
        mut state: PyRefMut<'_, PyGameState>,
        depth: u32,
    ) -> u64 {
        let rules = self.inner;
        let inner = &mut state.inner;
        py.detach(|| rules.perft(inner, depth))
    }

    /// Count like `perft`, but count the last ply's moves instead of playing them.
    ///
    /// Args:
    ///     state: The game state to start from, which is restored afterwards.
    ///     depth: The number of plies to walk.
    ///
    /// Returns:
    ///     The number of positions reached after exactly `depth` plies.
    fn perft_bulk(
        &self,
        py: Python<'_>,
        mut state: PyRefMut<'_, PyGameState>,
        depth: u32,
    ) -> u64 {
        let rules = self.inner;
        let inner = &mut state.inner;
        py.detach(|| rules.perft_bulk(inner, depth))
    }
}
