//! The Python `Move` class.

use hive_core::engine::CoordMove;
use pyo3::prelude::*;
use pyo3::types::{PyTuple, PyType};

use crate::json;
use crate::values::{
    PythonValues, coord_tuple, extract_coord, extract_piece_type, optional_coord,
};

/// The class and constructor arguments `__reduce__` pickles a move as.
type Reduced<'py> =
    (Bound<'py, PyType>, (Bound<'py, PyAny>, Bound<'py, PyAny>, Bound<'py, PyAny>));

/// A game move that places or moves a piece on the board.
///
/// A move with `source_coord` set to `None` represents a placement from the player's
/// hand. A move with a `source_coord` represents a movement of an existing piece on the
/// board. The JSON form is `{"piece": "ant", "from": [q, r] | null, "to": [q, r]}`, and a
/// pass (`None` where a move is expected) is `null`.
///
/// Attributes:
///     piece_type: The type of piece being placed or moved.
///     source_coord: The axial coordinate `(q, r)` the piece moves from, or `None` if the
///         piece is being placed from the hand.
///     target_coord: The axial coordinate `(q', r')` the piece moves or is placed to.
#[pyclass(name = "Move", module = "hive.engine.state", frozen, eq, hash)]
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub(crate) struct PyMove {
    /// The move with coordinates.
    pub(crate) inner: CoordMove,
}

impl PyMove {
    /// Get the Python value of an optional move, `None` for a pass.
    pub(crate) fn to_object(
        py: Python<'_>,
        mv: Option<CoordMove>,
    ) -> PyResult<Bound<'_, PyAny>> {
        match mv {
            None => Ok(py.None().into_bound(py)),
            Some(inner) => Ok(Bound::new(py, PyMove { inner })?.into_any()),
        }
    }

    /// Read an optional move from a `Move` or `None`.
    pub(crate) fn extract_optional(
        value: &Bound<'_, PyAny>,
    ) -> PyResult<Option<CoordMove>> {
        if value.is_none() {
            return Ok(None);
        }

        Ok(Some(value.cast::<PyMove>()?.get().inner))
    }
}

#[pymethods]
impl PyMove {
    /// Create a move.
    ///
    /// Args:
    ///     piece_type: The type of piece being placed or moved.
    ///     source_coord: The axial coordinate the piece moves from, or `None` for a
    ///         placement from the hand.
    ///     target_coord: The axial coordinate the piece moves or is placed to.
    #[new]
    #[pyo3(signature = (piece_type, source_coord, target_coord))]
    fn new(
        piece_type: &Bound<'_, PyAny>,
        source_coord: Option<&Bound<'_, PyAny>>,
        target_coord: &Bound<'_, PyAny>,
    ) -> PyResult<Self> {
        Ok(PyMove {
            inner: CoordMove {
                piece_type: extract_piece_type(piece_type)?,
                source: source_coord.map(extract_coord).transpose()?,
                target: extract_coord(target_coord)?,
            },
        })
    }

    /// The type of piece being placed or moved.
    #[getter]
    fn piece_type<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        Ok(PythonValues::get(py)?.piece_type(py, self.inner.piece_type))
    }

    /// The axial coordinate the piece moves from, or `None` for a placement.
    #[getter]
    fn source_coord<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        optional_coord(py, self.inner.source)
    }

    /// The axial coordinate the piece moves or is placed to.
    #[getter]
    fn target_coord<'py>(&self, py: Python<'py>) -> Bound<'py, PyTuple> {
        coord_tuple(py, self.inner.target)
    }

    /// The field names for positional patterns in `match` statements.
    #[classattr]
    fn __match_args__() -> (&'static str, &'static str, &'static str) {
        ("piece_type", "source_coord", "target_coord")
    }

    /// Describe the move like a dataclass, with every field.
    ///
    /// Returns:
    ///     The representation, for example `Move(piece_type=<PieceType.ANT: 4>, ...)`.
    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        Ok(format!(
            "Move(piece_type={}, source_coord={}, target_coord={})",
            self.piece_type(py)?.repr()?,
            self.source_coord(py).repr()?,
            self.target_coord(py).repr()?
        ))
    }

    /// Describe the move for messages, for example `move ant from (0, 0) to (1, 0)`.
    ///
    /// Returns:
    ///     The description of the placement or movement.
    fn __str__(&self) -> String {
        self.inner.to_string()
    }

    /// Pickle the move by its fields.
    ///
    /// Returns:
    ///     The class and the constructor arguments that recreate the move.
    fn __reduce__<'py>(slf: &Bound<'py, Self>) -> PyResult<Reduced<'py>> {
        let py = slf.py();
        let mv = slf.get();
        Ok((
            slf.get_type(),
            (mv.piece_type(py)?, mv.source_coord(py), mv.target_coord(py).into_any()),
        ))
    }

    /// Reject assignments, since moves are immutable.
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
}
