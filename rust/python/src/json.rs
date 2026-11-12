//! JSON conversion of the Rust values through pydantic, like the Python `JsonCodec`.
//!
//! Each value has a JSON form in `hive.engine.forms`, a plain dataclass with the same
//! name, fields and docstring, which pydantic validates, serializes and describes.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyType};

/// Get the cached pydantic `TypeAdapter` of a type, from `hive.engine.codec`.
fn json_adapter<'py>(kind: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    kind.py().import("hive.engine.codec")?.getattr("json_adapter")?.call1((kind,))
}

/// Serialize a value to its JSON-compatible form.
pub(crate) fn to_json<'py>(value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    let py = value.py();
    let kwargs = PyDict::new(py);
    kwargs.set_item("mode", "json")?;
    kwargs.set_item("by_alias", true)?;
    json_adapter(&value.get_type().into_any())?.call_method(
        "dump_python",
        (value,),
        Some(&kwargs),
    )
}

/// Deserialize and validate a value of a class.
pub(crate) fn from_json<'py>(
    cls: &Bound<'py, PyType>,
    data: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    json_adapter(cls.as_any())?.call_method1("validate_python", (data,))
}

/// Build the pydantic core schema of a class from its JSON form.
pub(crate) fn core_schema<'py>(
    cls: &Bound<'py, PyType>,
    handler: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    cls.py().import("hive.engine.forms")?.getattr("core_schema_of")?.call1((cls, handler))
}
