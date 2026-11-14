//! The Hive engine and the search of the agents, without Python.
//!
//! [`engine`] holds the board, game states, moves and rules; it imports nothing from
//! [`agents`], which holds the search. The `hive-python` crate exposes both to Python as
//! `hive._core`.

pub mod agents;
pub mod engine;
