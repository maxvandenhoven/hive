//! The game state: the board, the hands, the queens and whose turn it is.

use crate::engine::board::{Board, MAX_OCCUPIED_CELLS, MAX_STACK_HEIGHT};
use crate::engine::errors::EngineError;
use crate::engine::grid::{Cell, Coord};
use crate::engine::moves::{CoordMove, Move};
use crate::engine::piece::{Piece, PieceType, Player};
use crate::engine::zobrist::SIDE_KEY;

/// A count per piece type, such as the pieces each player receives or has in hand.
///
/// Only listed piece types have a count, like the keys of the Python dict it mirrors, so
/// a hand of `{}` and a hand of zeros stay different. Counts may be negative while a
/// board is validated.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct PieceCounts {
    /// The count of each piece type, zero when not listed.
    counts: [i32; PieceType::COUNT],
    /// The listed piece types, one bit per type.
    listed: u8,
}

impl PieceCounts {
    /// Create counts that list no piece type.
    pub const fn new() -> Self {
        PieceCounts { counts: [0; PieceType::COUNT], listed: 0 }
    }

    /// Get the pieces each player receives in the base game.
    pub fn base() -> Self {
        let mut counts = PieceCounts::new();

        for (piece_type, count) in PieceType::ALL.into_iter().zip([1, 2, 3, 2, 3]) {
            counts.set(piece_type, count);
        }

        counts
    }

    /// Set the count of a piece type, listing it.
    pub fn set(&mut self, piece_type: PieceType, count: i32) {
        self.counts[piece_type.index()] = count;
        self.listed |= 1 << piece_type.index();
    }

    /// Add to the count of a piece type, listing it.
    #[inline]
    pub fn add(&mut self, piece_type: PieceType, amount: i32) {
        self.counts[piece_type.index()] += amount;
        self.listed |= 1 << piece_type.index();
    }

    /// Get the count of a piece type, or `None` if it is not listed.
    pub fn get(&self, piece_type: PieceType) -> Option<i32> {
        self.is_listed(piece_type).then_some(self.counts[piece_type.index()])
    }

    /// Get the count of a piece type, zero if it is not listed.
    #[inline]
    pub fn count(&self, piece_type: PieceType) -> i32 {
        self.counts[piece_type.index()]
    }

    /// Check whether a piece type is listed.
    pub fn is_listed(&self, piece_type: PieceType) -> bool {
        self.listed & (1 << piece_type.index()) != 0
    }

    /// Iterate the listed piece types with their counts, ordered by piece type.
    pub fn iter(&self) -> impl Iterator<Item = (PieceType, i32)> + '_ {
        PieceType::ALL
            .into_iter()
            .filter(|&piece_type| self.is_listed(piece_type))
            .map(|piece_type| (piece_type, self.count(piece_type)))
    }

    /// Get the sum of all counts.
    pub fn total(&self) -> i32 {
        self.counts.iter().sum()
    }
}

/// The complete state of a game: the board, each player's hand, the queens, the player
/// to move and the number of plies played.
///
/// [`GameState::apply_move`] and [`GameState::undo_move`] take moves from move
/// generation and trust them. The methods that take coordinates are for moves from
/// outside the engine and check the coordinates against the board.
#[derive(Clone)]
pub struct GameState {
    /// The pieces on the board.
    board: Board,
    /// The pieces each player has in hand, indexed by player.
    hands: [PieceCounts; 2],
    /// The coordinate of each player's queen, if placed.
    queens: [Option<Coord>; 2],
    /// The player to move.
    current_player: Player,
    /// The number of plies played, including passes.
    current_ply: i64,
}

impl GameState {
    /// Create a state with an empty board and the given pieces in each player's hand.
    pub fn new(piece_counts: PieceCounts, starting_player: Player) -> Self {
        GameState {
            board: Board::new(),
            hands: [piece_counts; 2],
            queens: [None; 2],
            current_player: starting_player,
            current_ply: 0,
        }
    }

    /// Get the board.
    #[inline]
    pub fn board(&self) -> &Board {
        &self.board
    }

    /// Get the board for move generation, which lifts pieces temporarily.
    #[inline]
    pub(crate) fn board_mut(&mut self) -> &mut Board {
        &mut self.board
    }

    /// Get the player to move.
    #[inline]
    pub fn current_player(&self) -> Player {
        self.current_player
    }

    /// Set the player to move, without any check.
    pub fn set_current_player(&mut self, player: Player) {
        self.current_player = player;
    }

    /// Get the number of plies played.
    #[inline]
    pub fn current_ply(&self) -> i64 {
        self.current_ply
    }

    /// Set the number of plies played, without any check.
    pub fn set_current_ply(&mut self, ply: i64) {
        self.current_ply = ply;
    }

    /// Get the pieces a player has in hand.
    #[inline]
    pub fn hand(&self, player: Player) -> &PieceCounts {
        &self.hands[player.index()]
    }

    /// Get the coordinate of a player's queen, or `None` if it is not placed.
    #[inline]
    pub fn queen_coord(&self, player: Player) -> Option<Coord> {
        self.queens[player.index()]
    }

    /// Get the Zobrist hash of the position: the pieces and the player to move.
    pub fn hash(&self) -> u64 {
        match self.current_player {
            Player::White => self.board.hash(),
            Player::Black => self.board.hash() ^ SIDE_KEY,
        }
    }

    /// Get the occupied cell of a coordinate, if any (see [`Board::occupied_cell`]).
    pub fn occupied_cell(&self, coord: Coord) -> Option<Cell> {
        self.board.occupied_cell(coord)
    }

    /// Convert a generated move to coordinates.
    pub fn decode(&self, mv: Move) -> CoordMove {
        CoordMove {
            piece_type: mv.piece_type(),
            source: mv.source().map(|source| self.board.coord(source)),
            target: self.board.locate(mv.target()),
        }
    }

    /// Apply a move from move generation and pass the turn; `None` is a pass.
    #[inline]
    pub fn apply_move(&mut self, mv: Option<Move>) {
        if let Some(mv) = mv {
            let piece_type = mv.piece_type();
            let target = mv.target();
            let player = self.current_player;

            let piece = match mv.source() {
                None => {
                    self.hands[player.index()].add(piece_type, -1);
                    Piece::new(player, piece_type)
                }
                Some(source) => self.board.pop(source),
            };

            let coord = self.board.locate(target);
            self.board.push(target, piece, coord);

            if piece_type == PieceType::Queen {
                self.queens[player.index()] = Some(coord);
            }
        }

        self.current_ply += 1;
        self.current_player = self.current_player.opponent();
    }

    /// Undo the last move applied with [`GameState::apply_move`]; `None` is a pass.
    #[inline]
    pub fn undo_move(&mut self, mv: Option<Move>) {
        self.current_ply -= 1;
        self.current_player = self.current_player.opponent();

        if let Some(mv) = mv {
            let piece_type = mv.piece_type();
            let player = self.current_player;
            let piece = self.board.pop(mv.target());

            match mv.source() {
                None => {
                    self.hands[player.index()].add(piece_type, 1);

                    if piece_type == PieceType::Queen {
                        self.queens[player.index()] = None;
                    }
                }
                Some(source) => {
                    let coord = self.board.locate(source);
                    self.board.push(source, piece, coord);

                    if piece_type == PieceType::Queen {
                        self.queens[player.index()] = Some(coord);
                    }
                }
            }
        }
    }

    /// Apply a move with coordinates and pass the turn; `None` is a pass.
    ///
    /// # Errors
    ///
    /// Returns an error if the source is empty or a stack or the board would be full; see
    /// [`GameState::apply_placement`] and [`GameState::apply_movement`].
    pub fn apply_coord_move(&mut self, mv: Option<CoordMove>) -> Result<(), EngineError> {
        if let Some(mv) = mv {
            match mv.source {
                None => self.apply_placement(mv.piece_type, mv.target)?,
                Some(source) => self.apply_movement(mv.piece_type, source, mv.target)?,
            }
        }

        self.current_ply += 1;
        self.current_player = self.current_player.opponent();
        Ok(())
    }

    /// Undo a move with coordinates and take the turn back; `None` is a pass.
    ///
    /// # Errors
    ///
    /// Returns an error if the target is empty; see [`GameState::undo_placement`] and
    /// [`GameState::undo_movement`].
    pub fn undo_coord_move(&mut self, mv: Option<CoordMove>) -> Result<(), EngineError> {
        self.current_ply -= 1;
        self.current_player = self.current_player.opponent();

        if let Some(mv) = mv {
            match mv.source {
                None => self.undo_placement(mv.piece_type, mv.target)?,
                Some(source) => self.undo_movement(mv.piece_type, source, mv.target)?,
            }
        }

        Ok(())
    }

    /// Place a piece of the player to move from the hand, without passing the turn.
    ///
    /// # Errors
    ///
    /// Returns an error if the target stack or the board is full, or the target's cell
    /// holds pieces at another coordinate (a board wider than the grid).
    pub fn apply_placement(
        &mut self,
        piece_type: PieceType,
        target: Coord,
    ) -> Result<(), EngineError> {
        let player = self.current_player;
        self.push_checked(target, Piece::new(player, piece_type))?;
        self.hands[player.index()].add(piece_type, -1);

        if piece_type == PieceType::Queen {
            self.queens[player.index()] = Some(target);
        }

        Ok(())
    }

    /// Undo [`GameState::apply_placement`]: take the top piece of the target back into
    /// the hand of the player to move.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError::MissingPiece`] if the target is empty.
    pub fn undo_placement(
        &mut self,
        piece_type: PieceType,
        target: Coord,
    ) -> Result<(), EngineError> {
        let player = self.current_player;
        self.pop_checked(target)?;
        self.hands[player.index()].add(piece_type, 1);

        if piece_type == PieceType::Queen {
            self.queens[player.index()] = None;
        }

        Ok(())
    }

    /// Move the top piece of the source onto the target, without passing the turn.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError::MissingPiece`] if the source is empty, and an error if the
    /// target is full or holds pieces at another coordinate.
    pub fn apply_movement(
        &mut self,
        piece_type: PieceType,
        source: Coord,
        target: Coord,
    ) -> Result<(), EngineError> {
        self.check_room(target)?;
        let piece = self.pop_checked(source)?;
        self.push_checked(target, piece)?;

        if piece_type == PieceType::Queen {
            self.queens[self.current_player.index()] = Some(target);
        }

        Ok(())
    }

    /// Undo [`GameState::apply_movement`]: move the top piece of the target back.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError::MissingPiece`] if the target is empty, and an error if the
    /// source is full or holds pieces at another coordinate.
    pub fn undo_movement(
        &mut self,
        piece_type: PieceType,
        source: Coord,
        target: Coord,
    ) -> Result<(), EngineError> {
        self.check_room(source)?;
        let piece = self.pop_checked(target)?;
        self.push_checked(source, piece)?;

        if piece_type == PieceType::Queen {
            self.queens[self.current_player.index()] = Some(source);
        }

        Ok(())
    }

    /// Check that a piece can be put on a coordinate.
    fn check_room(&self, coord: Coord) -> Result<(), EngineError> {
        let cell = coord.cell();
        let height = self.board.height(cell);

        if height == 0 {
            if self.board.occupied_count() >= MAX_OCCUPIED_CELLS {
                let message =
                    format!("A board holds at most `{MAX_OCCUPIED_CELLS}` stacks.");
                return Err(EngineError::InvalidArgument(message));
            }

            return Ok(());
        }

        if self.board.coord(cell) != coord {
            let message = format!(
                "Coordinate `{coord}` is 32 or more cells away from `{}`, which the \
                 board grid cannot hold at once.",
                self.board.coord(cell)
            );
            return Err(EngineError::InvalidArgument(message));
        }

        if height >= MAX_STACK_HEIGHT {
            let message = format!("A stack holds at most `{MAX_STACK_HEIGHT}` pieces.");
            return Err(EngineError::InvalidArgument(message));
        }

        Ok(())
    }

    /// Put a piece on a coordinate after [`GameState::check_room`].
    fn push_checked(&mut self, coord: Coord, piece: Piece) -> Result<(), EngineError> {
        self.check_room(coord)?;
        self.board.push(coord.cell(), piece, coord);
        Ok(())
    }

    /// Take the top piece off a coordinate, which must be occupied.
    fn pop_checked(&mut self, coord: Coord) -> Result<Piece, EngineError> {
        let cell =
            self.board.occupied_cell(coord).ok_or(EngineError::MissingPiece(coord))?;
        Ok(self.board.pop(cell))
    }

    /// Put a piece on the board while a validated board is built.
    pub(crate) fn place_unchecked(&mut self, coord: Coord, piece: Piece) {
        self.board.push(coord.cell(), piece, coord);
    }

    /// Replace the hands and queens without any check, for example when a validated
    /// board is built or a pickled state is restored.
    pub fn restore_hands_and_queens(
        &mut self,
        hands: [PieceCounts; 2],
        queens: [Option<Coord>; 2],
    ) {
        self.hands = hands;
        self.queens = queens;
    }
}

/// Two states are equal if they describe the same position: the same stacks at the same
/// coordinates, hands, queens, player to move and ply.
impl PartialEq for GameState {
    fn eq(&self, other: &Self) -> bool {
        self.current_player == other.current_player
            && self.current_ply == other.current_ply
            && self.hands == other.hands
            && self.queens == other.queens
            && self.board.occupied_count() == other.board.occupied_count()
            && self.board.occupied().iter().all(|&cell| {
                let coord = self.board.coord(cell);
                other.board.occupied_cell(coord).is_some_and(|other_cell| {
                    self.board.stack(cell) == other.board.stack(other_cell)
                })
            })
    }
}

impl Eq for GameState {}

impl std::fmt::Debug for GameState {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let mut stacks: Vec<_> = self
            .board
            .occupied()
            .iter()
            .map(|&cell| (self.board.coord(cell), self.board.stack(cell)))
            .collect();
        stacks.sort_by_key(|(coord, _)| *coord);
        formatter
            .debug_struct("GameState")
            .field("current_player", &self.current_player)
            .field("current_ply", &self.current_ply)
            .field("stacks", &stacks)
            .field("hands", &self.hands)
            .field("queens", &self.queens)
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn coordinate_moves_apply_and_undo() {
        let mut state = GameState::new(PieceCounts::base(), Player::White);
        let initial = state.clone();
        let placement = CoordMove {
            piece_type: PieceType::Queen,
            source: None,
            target: Coord::ORIGIN,
        };

        state.apply_coord_move(Some(placement)).expect("the placement fits");
        assert_eq!(state.queen_coord(Player::White), Some(Coord::ORIGIN));
        assert_eq!(state.hand(Player::White).count(PieceType::Queen), 0);
        assert_eq!(state.current_player(), Player::Black);
        assert_ne!(state, initial);

        state.undo_coord_move(Some(placement)).expect("the target is occupied");
        assert_eq!(state, initial);
        assert_eq!(state.hash(), initial.hash());
    }

    #[test]
    fn moving_from_an_empty_coordinate_fails() {
        let mut state = GameState::new(PieceCounts::base(), Player::White);
        let result =
            state.apply_movement(PieceType::Ant, Coord::ORIGIN, Coord::new(1, 0));
        assert_eq!(result, Err(EngineError::MissingPiece(Coord::ORIGIN)));
    }

    #[test]
    fn a_board_wider_than_the_grid_is_rejected() {
        let mut state = GameState::new(PieceCounts::base(), Player::White);
        state.apply_placement(PieceType::Ant, Coord::ORIGIN).expect("the board is empty");
        let result = state.apply_placement(PieceType::Ant, Coord::new(32, -1));
        assert!(matches!(result, Err(EngineError::InvalidArgument(_))));
    }

    #[test]
    fn unlisted_piece_types_stay_unlisted() {
        let mut counts = PieceCounts::new();
        counts.set(PieceType::Queen, 1);
        assert_eq!(counts.get(PieceType::Ant), None);
        assert_eq!(counts.iter().collect::<Vec<_>>(), [(PieceType::Queen, 1)]);
    }
}
