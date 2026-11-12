//! The game engine: the board, game states, moves and the rules.

pub mod board;
pub mod errors;
pub mod grid;
mod movement;
pub mod moves;
mod perft;
pub mod piece;
pub mod rules;
pub mod state;
pub mod zobrist;

pub use board::Board;
pub use errors::EngineError;
pub use grid::{Cell, Coord};
pub use moves::{CoordMove, Move};
pub use piece::{Piece, PieceType, Player};
pub use rules::{Rules, RulesConfig, Winners};
pub use state::{GameState, PieceCounts};
