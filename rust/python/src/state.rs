//! The Python `GameState` class.

use hive_core::engine::{
    Cell, Coord, CoordMove, EngineError, GameState, Piece, PieceCounts, PieceType, Player,
};
use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PySet, PyTuple, PyType};

use crate::moves::PyMove;
use crate::values::{
    PythonValues, coord_tuple, extract_coord, extract_piece_type, extract_player,
    optional_coord, to_py_err,
};

/// The complete state of a Hive game at a given point in time.
///
/// Tracks the board layout, current player, ply count, queen positions and each player's
/// hand, and provides methods for querying and manipulating the board. The state lives in
/// the Rust core: `board`, `hand` and `queen_coord` build new dicts on every access, so
/// changing them does not change the state, and code that reads the board in a loop uses
/// the query methods instead. Two states are equal if they describe the same position.
///
/// Attributes:
///     board: The pieces on each occupied coordinate, ordered bottom to top.
///     hand: The number of pieces of each type each player has in hand.
///     queen_coord: The coordinate of each player's queen, or `None` if it is not placed.
///     current_player: The player to move.
///     current_ply: The number of plies played so far, including passes.
#[pyclass(name = "GameState", module = "hive.engine.state", eq)]
#[derive(Clone, PartialEq)]
pub(crate) struct PyGameState {
    /// The state in the Rust core.
    pub(crate) inner: GameState,
}

/// A pickled stack: its coordinate and the owner and type value of each piece.
type PickledStack = ((i32, i32), Vec<(usize, usize)>);

/// A pickled position: the stacks, the hands as type and count values per player, the
/// queen coordinates, and the values of the player to move and the ply.
type PickledPosition =
    (Vec<PickledStack>, Vec<Vec<(usize, i32)>>, Vec<Option<(i32, i32)>>, usize, i64);

/// Read piece counts from a mapping of piece types to counts.
pub(crate) fn extract_piece_counts(mapping: &Bound<'_, PyAny>) -> PyResult<PieceCounts> {
    let mut counts = PieceCounts::new();

    for item in mapping.call_method0("items")?.try_iter()? {
        let (piece_type, count): (Bound<'_, PyAny>, i32) = item?.extract()?;
        counts.set(extract_piece_type(&piece_type)?, count);
    }

    Ok(counts)
}

/// Get the coordinate a move ends on, which `apply_placement` and friends need.
fn source_of(mv: &CoordMove) -> PyResult<Coord> {
    mv.source.ok_or_else(|| {
        PyValueError::new_err("Source coordinate for a movement move cannot be None.")
    })
}

impl PyGameState {
    /// Convert a result of the core to a Python result.
    fn check(py: Python<'_>, result: Result<(), EngineError>) -> PyResult<()> {
        result.map_err(|error| to_py_err(py, error))
    }

    /// Get the occupied cell of a coordinate, or raise `KeyError` like the board dict.
    fn occupied(&self, coord: Coord) -> PyResult<Cell> {
        self.inner
            .occupied_cell(coord)
            .ok_or_else(|| PyKeyError::new_err((coord.q, coord.r)))
    }

    /// Count the occupied coordinates next to a coordinate, checking real coordinates.
    fn occupied_neighbors(&self, coord: Coord) -> usize {
        coord
            .neighbors()
            .into_iter()
            .filter(|&n| self.inner.occupied_cell(n).is_some())
            .count()
    }
}

#[pymethods]
impl PyGameState {
    /// Initialize a new game state with an empty board.
    ///
    /// Args:
    ///     piece_type_count: A mapping from each piece type to the number of copies each
    ///         player receives at the start of the game.
    ///     starting_player: The player who takes the first turn. Defaults to
    ///         `Player.WHITE`.
    #[new]
    #[pyo3(signature = (piece_type_count, starting_player = None))]
    fn new(
        piece_type_count: &Bound<'_, PyAny>,
        starting_player: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let player =
            starting_player.map(extract_player).transpose()?.unwrap_or(Player::White);
        Ok(PyGameState {
            inner: GameState::new(extract_piece_counts(piece_type_count)?, player),
        })
    }

    /// The pieces on each occupied coordinate, bottom to top, as a new dict.
    #[getter]
    fn board<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let values = PythonValues::get(py)?;
        let board = self.inner.board();
        let dict = PyDict::new(py);

        for &cell in board.occupied() {
            let stack = board.stack(cell).iter().map(|&piece| values.piece(py, piece));
            dict.set_item(coord_tuple(py, board.coord(cell)), PyList::new(py, stack)?)?;
        }

        Ok(dict)
    }

    /// The number of pieces of each type each player has in hand, as a new dict.
    #[getter]
    fn hand<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let values = PythonValues::get(py)?;
        let hands = PyDict::new(py);

        for player in Player::ALL {
            let hand = PyDict::new(py);

            for (piece_type, count) in self.inner.hand(player).iter() {
                hand.set_item(values.piece_type(py, piece_type), count)?;
            }

            hands.set_item(values.player(py, player), hand)?;
        }

        Ok(hands)
    }

    /// Each player's queen coordinate, or `None` if not placed, as a new dict.
    #[getter(queen_coord)]
    fn queen_coords<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let values = PythonValues::get(py)?;
        let queens = PyDict::new(py);

        for player in Player::ALL {
            queens.set_item(
                values.player(py, player),
                self.get_queen_coord_of(py, player),
            )?;
        }

        Ok(queens)
    }

    /// The player to move.
    #[getter]
    fn current_player<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        Ok(PythonValues::get(py)?.player(py, self.inner.current_player()))
    }

    /// Set the player to move, without any check.
    ///
    /// Args:
    ///     player: The player to move.
    #[setter]
    fn set_current_player(&mut self, player: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner.set_current_player(extract_player(player)?);
        Ok(())
    }

    /// The number of plies played so far, including passes.
    #[getter]
    fn current_ply(&self) -> i64 {
        self.inner.current_ply()
    }

    /// Set the number of plies played, without any check.
    ///
    /// Args:
    ///     ply: The number of plies.
    #[setter]
    fn set_current_ply(&mut self, ply: i64) {
        self.inner.set_current_ply(ply);
    }

    /// Copy the state, so moves applied to the copy do not affect the original.
    ///
    /// Returns:
    ///     A state with the same board, player, ply, hands and queen coordinates.
    fn copy(&self) -> Self {
        self.clone()
    }

    /// Check whether a coordinate is surrounded by other pieces.
    ///
    /// Args:
    ///     coord: The axial coordinate `(q, r)` to check.
    ///
    /// Returns:
    ///     True if the coordinate to check has six occupied neighbors, otherwise False.
    fn is_surrounded(&self, coord: &Bound<'_, PyAny>) -> PyResult<bool> {
        Ok(self.occupied_neighbors(extract_coord(coord)?) == 6)
    }

    /// Count the occupied coordinates that directly neighbor a coordinate.
    ///
    /// Args:
    ///     coord: The axial coordinate `(q, r)` to check.
    ///
    /// Returns:
    ///     The number of occupied neighbors, from zero to six.
    fn count_occupied_neighbors(&self, coord: &Bound<'_, PyAny>) -> PyResult<usize> {
        Ok(self.occupied_neighbors(extract_coord(coord)?))
    }

    /// Check if a coordinate on the game board is occupied (has a piece) or not.
    ///
    /// Args:
    ///     coord: The axial coordinate `(q, r)` to check.
    ///
    /// Returns:
    ///     True if there is a piece on the given coordinate, otherwise False.
    fn is_occupied(&self, coord: &Bound<'_, PyAny>) -> PyResult<bool> {
        Ok(self.inner.occupied_cell(extract_coord(coord)?).is_some())
    }

    /// Get the coordinate of the player's queen piece.
    ///
    /// Args:
    ///     player: The player to get the queen coordinate for.
    ///
    /// Returns:
    ///     The axial coordinate `(q, r)` of the player's queen piece, or None if the
    ///     queen has not been placed on the board yet.
    fn get_queen_coord<'py>(
        &self,
        py: Python<'py>,
        player: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        Ok(self.get_queen_coord_of(py, extract_player(player)?))
    }

    /// Get the top piece that is on an occupied coordinate.
    ///
    /// Args:
    ///     coord: The axial coordinate `(q, r)` to check.
    ///
    /// Returns:
    ///     The top-most piece that is occupying the given coordinate.
    ///
    /// Raises:
    ///     KeyError: If the coordinate is not occupied.
    fn get_top_piece<'py>(
        &self,
        py: Python<'py>,
        coord: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let cell = self.occupied(extract_coord(coord)?)?;
        Ok(PythonValues::get(py)?.piece(py, self.inner.board().top(cell)))
    }

    /// Get the height of the stack on a coordinate.
    ///
    /// Args:
    ///     coord: The axial coordinate `(q, r)` to check.
    ///
    /// Returns:
    ///     The height of the stack, or zero if the coordinate is unoccupied.
    fn get_stack_height(&self, coord: &Bound<'_, PyAny>) -> PyResult<usize> {
        let cell = self.inner.occupied_cell(extract_coord(coord)?);
        Ok(cell.map_or(0, |cell| self.inner.board().height(cell)))
    }

    /// Get all occupied coordinates on the board.
    ///
    /// Returns:
    ///     The axial coordinates `(q, r)` that have at least one piece on the board.
    fn get_occupied_coords<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PySet>> {
        let board = self.inner.board();
        PySet::new(
            py,
            board.occupied().iter().map(|&cell| coord_tuple(py, board.coord(cell))),
        )
    }

    /// Find all coordinates whose removal would disconnect the board.
    ///
    /// Uses Tarjan's articulation point algorithm to identify articulation points in
    /// linear time. A coordinate is an articulation point if removing it would split the
    /// remaining occupied coordinates into two or more disconnected components.
    /// Coordinates with a stack height greater than one are excluded, as removing the top
    /// piece still leaves the coordinate occupied.
    ///
    /// Returns:
    ///     The set of coordinates whose removal would disconnect the board.
    fn get_articulation_points<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PySet>> {
        let board = self.inner.board();
        let cells = board.articulation_cells();
        PySet::new(py, cells.into_iter().map(|cell| coord_tuple(py, board.coord(cell))))
    }

    /// Check if all occupied coordinates on the board form one connected group.
    ///
    /// Returns:
    ///     True if every occupied coordinate can be reached from every other one by
    ///     moving between direct neighbors, or if the board is empty.
    fn is_connected(&self) -> bool {
        self.inner.board().is_connected()
    }

    /// Check if the game board remains connected after removing a piece.
    ///
    /// Args:
    ///     coord: The axial coordinate `(q, r)` to remove the top piece from.
    ///
    /// Returns:
    ///     True if the board remains connected after removing the top piece from the
    ///     given coordinate.
    ///
    /// Raises:
    ///     KeyError: If the coordinate is not occupied.
    fn is_connected_after_removing(&self, coord: &Bound<'_, PyAny>) -> PyResult<bool> {
        let cell = self.occupied(extract_coord(coord)?)?;
        Ok(self.inner.board().is_connected_without(cell))
    }

    /// Apply a placement move to the game state, without advancing the turn.
    ///
    /// Removes the piece from the current player's hand and places it on the board at the
    /// target coordinate. If the placed piece is a queen, the queen coordinate for the
    /// current player is updated.
    ///
    /// Args:
    ///     move: The placement move to apply.
    fn apply_placement(
        &mut self,
        py: Python<'_>,
        r#move: PyRef<'_, PyMove>,
    ) -> PyResult<()> {
        let mv = r#move.inner;
        Self::check(py, self.inner.apply_placement(mv.piece_type, mv.target))
    }

    /// Undo a previously applied placement move.
    ///
    /// Removes the piece from the board at the target coordinate and returns it to the
    /// current player's hand. If the piece is a queen, the queen coordinate for the
    /// current player is reset to `None`.
    ///
    /// Args:
    ///     move: The placement move to undo.
    fn undo_placement(
        &mut self,
        py: Python<'_>,
        r#move: PyRef<'_, PyMove>,
    ) -> PyResult<()> {
        let mv = r#move.inner;
        Self::check(py, self.inner.undo_placement(mv.piece_type, mv.target))
    }

    /// Apply a movement move to the game state, without advancing the turn.
    ///
    /// Moves the top piece from the source coordinate to the target coordinate. If the
    /// moved piece is a queen, the queen coordinate for the current player is updated.
    ///
    /// Args:
    ///     move: The movement move to apply. The `source_coord` must not be `None`.
    ///
    /// Raises:
    ///     ValueError: If `move.source_coord` is `None`.
    ///     KeyError: If there is no piece at the source coordinate.
    fn apply_movement(
        &mut self,
        py: Python<'_>,
        r#move: PyRef<'_, PyMove>,
    ) -> PyResult<()> {
        let mv = r#move.inner;
        let source = source_of(&mv)?;
        Self::check(py, self.inner.apply_movement(mv.piece_type, source, mv.target))
    }

    /// Undo a previously applied movement move.
    ///
    /// Moves the top piece from the target coordinate back to the source coordinate. If
    /// the moved piece is a queen, the queen coordinate for the current player is
    /// restored.
    ///
    /// Args:
    ///     move: The movement move to undo. The `source_coord` must not be `None`.
    ///
    /// Raises:
    ///     ValueError: If `move.source_coord` is `None`.
    ///     KeyError: If there is no piece at the target coordinate.
    fn undo_movement(
        &mut self,
        py: Python<'_>,
        r#move: PyRef<'_, PyMove>,
    ) -> PyResult<()> {
        let mv = r#move.inner;
        let source = source_of(&mv)?;
        Self::check(py, self.inner.undo_movement(mv.piece_type, source, mv.target))
    }

    /// Apply a move to the game state and advance the turn.
    ///
    /// A `None` move represents a pass. After applying the move, the ply counter is
    /// incremented and the current player switches to the opponent.
    ///
    /// Args:
    ///     move: The move to apply, or `None` to pass the turn.
    fn apply_move(&mut self, py: Python<'_>, r#move: &Bound<'_, PyAny>) -> PyResult<()> {
        let mv = PyMove::extract_optional(r#move)?;
        Self::check(py, self.inner.apply_coord_move(mv))
    }

    /// Undo the most recently applied move and revert the turn.
    ///
    /// A `None` move represents an undone pass. After undoing the move, the ply counter
    /// is decremented and the current player switches back.
    ///
    /// Args:
    ///     move: The move to undo, or `None` if the previous turn was a pass.
    fn undo_move(&mut self, py: Python<'_>, r#move: &Bound<'_, PyAny>) -> PyResult<()> {
        let mv = PyMove::extract_optional(r#move)?;
        Self::check(py, self.inner.undo_coord_move(mv))
    }

    /// Describe the state for debugging.
    ///
    /// Returns:
    ///     The player to move, the ply and the number of stacks.
    fn __repr__(&self) -> String {
        format!(
            "GameState(current_player={}, current_ply={}, stacks={})",
            self.inner.current_player().name(),
            self.inner.current_ply(),
            self.inner.board().occupied_count()
        )
    }

    /// Pickle the state by its position.
    ///
    /// Returns:
    ///     The class, the constructor arguments and the position for `__setstate__`.
    fn __reduce__<'py>(
        slf: &Bound<'py, Self>,
    ) -> PyResult<(Bound<'py, PyType>, Bound<'py, PyTuple>, Bound<'py, PyTuple>)> {
        let py = slf.py();
        let args = PyTuple::new(py, [PyDict::new(py).into_any()])?;
        Ok((slf.get_type(), args, slf.borrow().position(py)?))
    }

    /// Restore a pickled position (see `__reduce__`).
    ///
    /// Args:
    ///     position: The position as written by `__reduce__`.
    fn __setstate__(&mut self, position: &Bound<'_, PyTuple>) -> PyResult<()> {
        let (stacks, hands, queens, player, ply): PickledPosition = position.extract()?;
        let invalid = || PyValueError::new_err("The pickled game state is not valid.");
        let player = Player::from_index(player).ok_or_else(invalid)?;
        let mut state = GameState::new(PieceCounts::new(), player);

        for ((q, r), stack) in stacks {
            for (owner, piece_type) in stack {
                let owner = Player::from_index(owner).ok_or_else(invalid)?;
                let piece_type = PieceType::from_index(piece_type).ok_or_else(invalid)?;
                state.set_current_player(owner);
                state
                    .apply_placement(piece_type, Coord::new(q, r))
                    .map_err(|error| PyValueError::new_err(error.to_string()))?;
            }
        }

        let mut restored = [PieceCounts::new(); 2];

        for (hand, counts) in restored.iter_mut().zip(hands) {
            for (piece_type, count) in counts {
                hand.set(PieceType::from_index(piece_type).ok_or_else(invalid)?, count);
            }
        }

        let queens = [
            queens.first().copied().flatten().map(|(q, r)| Coord::new(q, r)),
            queens.get(1).copied().flatten().map(|(q, r)| Coord::new(q, r)),
        ];
        state.restore_hands_and_queens(restored, queens);
        state.set_current_player(player);
        state.set_current_ply(ply);
        self.inner = state;
        Ok(())
    }
}

impl PyGameState {
    /// Get the queen coordinate of a player as a tuple or `None`.
    fn get_queen_coord_of<'py>(
        &self,
        py: Python<'py>,
        player: Player,
    ) -> Bound<'py, PyAny> {
        optional_coord(py, self.inner.queen_coord(player))
    }

    /// Write the position as plain Python values for pickling.
    fn position<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        let board = self.inner.board();
        let stacks: Vec<PickledStack> = board
            .occupied()
            .iter()
            .map(|&cell| {
                let coord = board.coord(cell);
                let stack = board
                    .stack(cell)
                    .iter()
                    .map(|piece: &Piece| {
                        (piece.owner().index(), piece.piece_type().index())
                    })
                    .collect();
                ((coord.q, coord.r), stack)
            })
            .collect();
        let hands: Vec<Vec<(usize, i32)>> = Player::ALL
            .iter()
            .map(|&player| {
                self.inner
                    .hand(player)
                    .iter()
                    .map(|(piece_type, count)| (piece_type.index(), count))
                    .collect()
            })
            .collect();
        let queens: Vec<Option<(i32, i32)>> = Player::ALL
            .iter()
            .map(|&player| self.inner.queen_coord(player).map(|coord| (coord.q, coord.r)))
            .collect();
        (
            stacks,
            hands,
            queens,
            self.inner.current_player().index(),
            self.inner.current_ply(),
        )
            .into_pyobject(py)
    }
}
