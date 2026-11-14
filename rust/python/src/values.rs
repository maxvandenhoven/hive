//! The Python values the bindings share with the Python package, and conversions.
//!
//! `Player`, `PieceType` and `Piece` stay Python classes (`hive.engine.state`). The
//! bindings return their cached members and shared pieces, so identity checks such as
//! `move.piece_type is PieceType.ANT` hold. The errors come from `hive.engine.errors`.

use hive_core::engine::{Coord, EngineError, Piece, PieceType, Player};
use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyDict, PyTuple, PyType};

/// The Python objects the bindings return or raise, imported once.
pub(crate) struct PythonValues {
    /// The `PieceType` members, by value.
    piece_types: Vec<Py<PyAny>>,
    /// The `Player` members, by value.
    players: Vec<Py<PyAny>>,
    /// The shared `Piece` instances of `SHARED_PIECES`, by player and piece type.
    pieces: Vec<Vec<Py<PyAny>>>,
    /// `types.MappingProxyType`, for read-only views.
    mapping_proxy: Py<PyType>,
    /// `hive.engine.errors.InvalidBoardError`.
    invalid_board_error: Py<PyType>,
    /// `hive.engine.errors.IllegalMoveError`.
    illegal_move_error: Py<PyType>,
    /// `dataclasses.FrozenInstanceError`, raised when a field of a value is assigned.
    frozen_instance_error: Py<PyType>,
}

/// The values, imported on first use rather than when `hive._core` is imported, because
/// `hive.engine.state` itself imports `hive._core`.
static PYTHON_VALUES: PyOnceLock<PythonValues> = PyOnceLock::new();

impl PythonValues {
    /// Get the values, importing them on first use.
    pub(crate) fn get(py: Python<'_>) -> PyResult<&'static PythonValues> {
        PYTHON_VALUES.get_or_try_init(py, || {
            let state = py.import("hive.engine.state")?;
            let errors = py.import("hive.engine.errors")?;
            let piece_type = state.getattr("PieceType")?;
            let player = state.getattr("Player")?;
            let shared_pieces = state.getattr("SHARED_PIECES")?;
            let piece_types = PieceType::ALL
                .iter()
                .map(|piece_type_value| {
                    Ok(piece_type.call1((piece_type_value.index(),))?.unbind())
                })
                .collect::<PyResult<Vec<_>>>()?;
            let players = Player::ALL
                .iter()
                .map(|player_value| Ok(player.call1((player_value.index(),))?.unbind()))
                .collect::<PyResult<Vec<_>>>()?;
            let pieces = players
                .iter()
                .map(|owner| {
                    piece_types
                        .iter()
                        .map(|piece_type_member| {
                            let key = (owner.bind(py), piece_type_member.bind(py));
                            Ok(shared_pieces.get_item(key)?.unbind())
                        })
                        .collect::<PyResult<Vec<_>>>()
                })
                .collect::<PyResult<Vec<_>>>()?;

            Ok(PythonValues {
                piece_types,
                players,
                pieces,
                mapping_proxy: py
                    .import("types")?
                    .getattr("MappingProxyType")?
                    .cast_into()?
                    .unbind(),
                invalid_board_error: errors
                    .getattr("InvalidBoardError")?
                    .cast_into()?
                    .unbind(),
                illegal_move_error: errors
                    .getattr("IllegalMoveError")?
                    .cast_into()?
                    .unbind(),
                frozen_instance_error: py
                    .import("dataclasses")?
                    .getattr("FrozenInstanceError")?
                    .cast_into()?
                    .unbind(),
            })
        })
    }

    /// Get the `PieceType` member of a piece type.
    pub(crate) fn piece_type<'py>(
        &self,
        py: Python<'py>,
        piece_type: PieceType,
    ) -> Bound<'py, PyAny> {
        self.piece_types[piece_type.index()].bind(py).clone()
    }

    /// Get the `Player` member of a player.
    pub(crate) fn player<'py>(
        &self,
        py: Python<'py>,
        player: Player,
    ) -> Bound<'py, PyAny> {
        self.players[player.index()].bind(py).clone()
    }

    /// Get the shared `Piece` instance of a piece.
    pub(crate) fn piece<'py>(&self, py: Python<'py>, piece: Piece) -> Bound<'py, PyAny> {
        self.pieces[piece.owner().index()][piece.piece_type().index()].bind(py).clone()
    }

    /// Wrap a dict in a read-only `MappingProxyType`.
    pub(crate) fn read_only<'py>(
        &self,
        py: Python<'py>,
        dict: &Bound<'py, PyDict>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.mapping_proxy.bind(py).call1((dict,))
    }

    /// Get the error for assigning a field of an immutable value.
    pub(crate) fn frozen_error(&self, py: Python<'_>, name: &str) -> PyErr {
        let message = format!("cannot assign to field '{name}'");
        PyErr::from_type(self.frozen_instance_error.bind(py).clone(), message)
    }
}

/// Convert an engine error to its Python exception.
pub(crate) fn to_py_err(py: Python<'_>, error: EngineError) -> PyErr {
    let values = match PythonValues::get(py) {
        Ok(values) => values,
        Err(import_error) => return import_error,
    };

    match error {
        EngineError::InvalidRules(message) | EngineError::InvalidArgument(message) => {
            PyValueError::new_err(message)
        }
        EngineError::InvalidBoard(message) => {
            PyErr::from_type(values.invalid_board_error.bind(py).clone(), message)
        }
        EngineError::IllegalMove(message) => {
            PyErr::from_type(values.illegal_move_error.bind(py).clone(), message)
        }
        EngineError::MissingPiece(coord) => PyKeyError::new_err((coord.q, coord.r)),
    }
}

/// Read a coordinate from a `(q, r)` tuple.
pub(crate) fn extract_coord(value: &Bound<'_, PyAny>) -> PyResult<Coord> {
    let (q, r): (i32, i32) = value.extract()?;
    Ok(Coord::new(q, r))
}

/// Write a coordinate as a `(q, r)` tuple.
pub(crate) fn coord_tuple(py: Python<'_>, coord: Coord) -> Bound<'_, PyTuple> {
    PyTuple::new(py, [coord.q, coord.r]).expect("a tuple of two integers")
}

/// Write an optional coordinate as a `(q, r)` tuple or `None`.
pub(crate) fn optional_coord(py: Python<'_>, coord: Option<Coord>) -> Bound<'_, PyAny> {
    coord.map_or_else(
        || py.None().into_bound(py),
        |coord| coord_tuple(py, coord).into_any(),
    )
}

/// Read a piece type from a `PieceType` member or its integer value.
pub(crate) fn extract_piece_type(value: &Bound<'_, PyAny>) -> PyResult<PieceType> {
    let index: usize = value.extract()?;
    PieceType::from_index(index)
        .ok_or_else(|| PyValueError::new_err(format!("`{index}` is not a piece type.")))
}

/// Read a player from a `Player` member or its integer value.
pub(crate) fn extract_player(value: &Bound<'_, PyAny>) -> PyResult<Player> {
    let index: usize = value.extract()?;
    Player::from_index(index)
        .ok_or_else(|| PyValueError::new_err(format!("`{index}` is not a player.")))
}

/// Read a piece from a `Piece` (or any object with `type` and `owner`).
pub(crate) fn extract_piece(value: &Bound<'_, PyAny>) -> PyResult<Piece> {
    let piece_type = extract_piece_type(&value.getattr("type")?)?;
    let owner = extract_player(&value.getattr("owner")?)?;
    Ok(Piece::new(owner, piece_type))
}
