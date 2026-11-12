//! Python bindings of the Hive engine and search, built into the extension `hive._core`.
//!
//! The classes are the public classes of the Python package: `hive.engine.state`
//! re-exports `GameState` and `Move`, `hive.engine.rules` re-exports `Rules`, and
//! `hive.agents.search` re-exports `Searcher`. Their doc comments are Python docstrings
//! in Google style, repeated in `src/hive/_core.pyi` for type checkers and editors, and a
//! test keeps the two in sync.

#![allow(
    clippy::doc_markdown,
    reason = "doc comments here are Python docstrings in Google style, not Markdown"
)]
#![allow(
    clippy::needless_pass_by_value,
    reason = "PyO3 extracts `PyRef` and `PyRefMut` arguments by value"
)]

mod json;
mod moves;
mod rules;
mod search;
mod state;
mod values;

use pyo3::prelude::*;

/// The Rust core of the Hive engine and the agents' search.
#[pymodule]
fn _core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<moves::PyMove>()?;
    module.add_class::<state::PyGameState>()?;
    module.add_class::<rules::PyRules>()?;
    module.add_class::<search::PySearcher>()?;
    Ok(())
}
