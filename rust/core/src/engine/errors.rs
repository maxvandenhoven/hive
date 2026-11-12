//! Errors of the engine, with the messages of the Python package.

use std::fmt;

use crate::engine::grid::Coord;

/// An error of the engine. The bindings raise each kind as its Python exception.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EngineError {
    /// The rules are not valid (`ValueError` in Python).
    InvalidRules(String),
    /// A board does not describe a valid game state (`InvalidBoardError`).
    InvalidBoard(String),
    /// A move is not legal in the state it is played in (`IllegalMoveError`).
    IllegalMove(String),
    /// An argument is not valid for the call (`ValueError`).
    InvalidArgument(String),
    /// There is no piece at a coordinate that needs one (`KeyError`, like a dict).
    MissingPiece(Coord),
}

impl fmt::Display for EngineError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            EngineError::InvalidRules(message)
            | EngineError::InvalidBoard(message)
            | EngineError::IllegalMove(message)
            | EngineError::InvalidArgument(message) => formatter.write_str(message),
            EngineError::MissingPiece(coord) => write!(formatter, "{coord}"),
        }
    }
}

impl std::error::Error for EngineError {}
