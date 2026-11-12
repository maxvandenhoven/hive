//! The rules: configuration, legal moves, the end of the game and validated entry points.

use std::collections::{HashSet, VecDeque};

use crate::engine::board::MAX_STACK_HEIGHT;
use crate::engine::errors::EngineError;
use crate::engine::grid::{Cell, CellSet, Coord, DIRECTION_COUNT, MAX_PIECES};
use crate::engine::movement::{MoveTargets, add_piece_targets};
use crate::engine::moves::{CoordMove, Move};
use crate::engine::piece::{Piece, PieceType, Player};
use crate::engine::state::{GameState, PieceCounts};

/// The most pieces one player may receive, so a game never exceeds [`MAX_PIECES`].
pub const MAX_PIECES_PER_PLAYER: i32 = 14;

/// The configuration of [`Rules`] before it is validated.
///
/// The default is the base game with the defaults of the Python package.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RulesConfig {
    /// The number of copies of each piece type a player receives.
    pub piece_counts: PieceCounts,
    /// The player who takes the first turn.
    pub starting_player: Player,
    /// The turn (one-indexed, per player) by which the queen must be placed, or `None`.
    pub queen_by_turn: Option<i64>,
    /// Whether the queen may be placed on a player's first turn.
    pub allow_queen_first_turn: bool,
    /// Whether pieces may move before their owner's queen is placed.
    pub move_before_queen: bool,
    /// The turns per player after which the game is a draw, or `None` for no limit.
    pub max_turns: Option<i64>,
}

impl Default for RulesConfig {
    fn default() -> Self {
        RulesConfig {
            piece_counts: PieceCounts::base(),
            starting_player: Player::White,
            queen_by_turn: Some(4),
            allow_queen_first_turn: true,
            move_before_queen: false,
            max_turns: None,
        }
    }
}

/// The players who won a finished game.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Winners {
    /// One player surrounded the opponent's queen.
    Player(Player),
    /// Both queens are surrounded, a draw.
    BothQueensSurrounded,
    /// The turn limit was exceeded, a draw.
    TurnLimit,
}

impl Winners {
    /// Get the winners as the Python package lists them: the winner, or both players for
    /// a draw (black first when both queens are surrounded).
    pub fn players(self) -> Vec<Player> {
        match self {
            Winners::Player(player) => vec![player],
            Winners::BothQueensSurrounded => vec![Player::Black, Player::White],
            Winners::TurnLimit => vec![Player::White, Player::Black],
        }
    }

    /// Get the winning player, or `None` for a draw.
    pub fn winner(self) -> Option<Player> {
        match self {
            Winners::Player(player) => Some(player),
            Winners::BothQueensSurrounded | Winners::TurnLimit => None,
        }
    }
}

/// A set of piece types.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct PieceTypeSet(u8);

impl PieceTypeSet {
    /// Check whether the set holds a piece type.
    pub fn contains(self, piece_type: PieceType) -> bool {
        self.0 & (1 << piece_type.index()) != 0
    }

    /// Add a piece type.
    pub fn insert(&mut self, piece_type: PieceType) {
        self.0 |= 1 << piece_type.index();
    }

    /// Iterate the piece types of the set, ordered by piece type.
    pub fn iter(self) -> impl Iterator<Item = PieceType> {
        PieceType::ALL.into_iter().filter(move |&piece_type| self.contains(piece_type))
    }
}

/// The rules of a game, holding both the configuration and the rule behaviour.
///
/// `Rules` is a validated, immutable value; [`Rules::new`] checks the configuration.
/// Every method reads a [`GameState`] and leaves it as it was, apart from the methods
/// that apply moves.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct Rules {
    /// The validated configuration.
    config: RulesConfig,
}

impl Rules {
    /// Validate a configuration.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError::InvalidRules`] if the queen count is not exactly one, a
    /// count is negative, a player would receive more than [`MAX_PIECES_PER_PLAYER`]
    /// pieces, or the queen must be placed on the first turn while that is not allowed.
    pub fn new(config: RulesConfig) -> Result<Self, EngineError> {
        let counts = &config.piece_counts;
        let queens = counts.count(PieceType::Queen);

        if queens != 1 {
            let message = format!(
                "Each player must receive exactly one queen piece, but got count \
                 `{queens}`."
            );
            return Err(EngineError::InvalidRules(message));
        }

        if let Some((piece_type, count)) = counts.iter().find(|&(_, count)| count < 0) {
            let message = format!(
                "The count of piece type `{}` must not be negative, but got `{count}`.",
                piece_type.name()
            );
            return Err(EngineError::InvalidRules(message));
        }

        if counts.total() > MAX_PIECES_PER_PLAYER {
            let message = format!(
                "Each player may receive at most `{MAX_PIECES_PER_PLAYER}` pieces, so a \
                 game fits the board grid of the engine, but got `{}`.",
                counts.total()
            );
            return Err(EngineError::InvalidRules(message));
        }

        if config.queen_by_turn == Some(1) && !config.allow_queen_first_turn {
            let message = "The queen cannot be required on the first turn when \
                           `allow_queen_first_turn` is `False`.";
            return Err(EngineError::InvalidRules(message.to_owned()));
        }

        Ok(Rules { config })
    }

    /// Get the configuration.
    pub fn config(&self) -> &RulesConfig {
        &self.config
    }

    /// Create the initial state: an empty board and full hands.
    pub fn create_initial_state(&self) -> GameState {
        GameState::new(self.config.piece_counts, self.config.starting_player)
    }

    /// Generate the legal moves of the player to move into `moves`, replacing its
    /// contents: placements, then movements. An empty list means the player must pass.
    ///
    /// The order follows the board, not the documented order of the Python package;
    /// [`Rules::legal_coord_moves`] sorts.
    pub fn legal_moves(&self, state: &mut GameState, moves: &mut Vec<Move>) {
        moves.clear();
        self.placement_moves(state, moves);
        self.movement_moves(state, moves);
    }

    /// Count the legal moves of the player to move, zero when the player must pass.
    ///
    /// `buffer` is scratch space whose contents are replaced.
    pub fn count_legal_moves(
        &self,
        state: &mut GameState,
        buffer: &mut Vec<Move>,
    ) -> usize {
        self.legal_moves(state, buffer);
        buffer.len()
    }

    /// Append the legal placements of the player to move to `moves`.
    pub fn placement_moves(&self, state: &GameState, moves: &mut Vec<Move>) {
        let types = self.placeable_piece_types(state);
        let mut types = types.iter();
        let Some(first) = types.next() else { return };
        let start = moves.len();
        Self::for_each_placeable_cell(state, |cell| {
            moves.push(Move::placement(first, cell));
        });
        let end = moves.len();

        for piece_type in types {
            for index in start..end {
                let target = moves[index].target();
                moves.push(Move::placement(piece_type, target));
            }
        }
    }

    /// Append the legal movements of the player to move to `moves`.
    pub fn movement_moves(&self, state: &mut GameState, moves: &mut Vec<Move>) {
        let player = state.current_player();

        if !self.config.move_before_queen && state.queen_coord(player).is_none() {
            return;
        }

        let articulation = state.board().articulation_slots();

        for slot in 0..state.board().occupied_count() {
            let cell = state.board().occupied()[slot];
            let piece = state.board().top(cell);

            if piece.owner() != player || articulation & (1 << slot) != 0 {
                continue;
            }

            let piece_type = piece.piece_type();
            let mut targets = MoveTargets { moves, piece_type, source: cell };
            add_piece_targets(state.board_mut(), cell, piece_type, &mut targets);
        }
    }

    /// Get the piece types the player to move may place.
    ///
    /// Only the queen once the queen deadline is reached without it, and never the queen
    /// on the player's first turn when `allow_queen_first_turn` is off.
    pub fn placeable_piece_types(&self, state: &GameState) -> PieceTypeSet {
        let player = state.current_player();
        let player_turn = state.current_ply().div_euclid(2) + 1;
        let mut types = PieceTypeSet::default();

        if let Some(queen_by_turn) = self.config.queen_by_turn
            && player_turn >= queen_by_turn
            && state.queen_coord(player).is_none()
        {
            types.insert(PieceType::Queen);
            return types;
        }

        for (piece_type, count) in state.hand(player).iter() {
            let queen_forbidden = piece_type == PieceType::Queen
                && player_turn == 1
                && !self.config.allow_queen_first_turn;

            if count > 0 && !queen_forbidden {
                types.insert(piece_type);
            }
        }

        types
    }

    /// Call `visit` with every cell the player to move may place a piece on.
    ///
    /// The first piece goes on the origin and the second next to it. Later pieces go on a
    /// free cell next to a stack topped by the player and not next to one topped by the
    /// opponent.
    fn for_each_placeable_cell(state: &GameState, mut visit: impl FnMut(Cell)) {
        let origin = Coord::ORIGIN.cell();

        match state.current_ply() {
            0 => visit(origin),
            1 => (0..DIRECTION_COUNT)
                .for_each(|direction| visit(origin.neighbor(direction))),
            _ => {
                let board = state.board();
                let player = state.current_player();
                let mut checked = CellSet::new();

                for &cell in board.occupied() {
                    if board.top(cell).owner() != player {
                        continue;
                    }

                    for direction in 0..DIRECTION_COUNT {
                        let candidate = cell.neighbor(direction);

                        if board.is_occupied(candidate) || !checked.insert(candidate) {
                            continue;
                        }

                        let placeable = (0..DIRECTION_COUNT).all(|side| {
                            let neighbor = candidate.neighbor(side);
                            !board.is_occupied(neighbor)
                                || board.top(neighbor).owner() == player
                        });

                        if placeable {
                            visit(candidate);
                        }
                    }
                }
            }
        }
    }

    /// Get the occupied cells whose top piece the player to move may move, with the type
    /// of that piece: the player's pieces that are not articulation points, once the
    /// player's queen is placed (or always with `move_before_queen`).
    pub fn movable_pieces(&self, state: &GameState) -> Vec<(Cell, PieceType)> {
        let player = state.current_player();

        if !self.config.move_before_queen && state.queen_coord(player).is_none() {
            return Vec::new();
        }

        let board = state.board();
        let articulation = board.articulation_slots();
        board
            .occupied()
            .iter()
            .enumerate()
            .filter(|&(slot, &cell)| {
                board.top(cell).owner() == player && articulation & (1 << slot) == 0
            })
            .map(|(_, &cell)| (cell, board.top(cell).piece_type()))
            .collect()
    }

    /// Get the players who won the game, or `None` while it is in progress.
    ///
    /// A player wins when the opponent's queen is surrounded. Both queens surrounded, or
    /// more than `max_turns` turns per player, is a draw.
    pub fn winners(&self, state: &GameState) -> Option<Winners> {
        if let Some(max_turns) = self.config.max_turns
            && state.current_ply() > max_turns.saturating_mul(2)
        {
            return Some(Winners::TurnLimit);
        }

        let surrounded = |player: Player| {
            state
                .queen_coord(player)
                .is_some_and(|coord| state.board().is_surrounded(coord.cell()))
        };

        match (surrounded(Player::White), surrounded(Player::Black)) {
            (true, true) => Some(Winners::BothQueensSurrounded),
            (true, false) => Some(Winners::Player(Player::Black)),
            (false, true) => Some(Winners::Player(Player::White)),
            (false, false) => None,
        }
    }

    /// Check whether the game has ended.
    #[inline]
    pub fn is_finished(&self, state: &GameState) -> bool {
        self.winners(state).is_some()
    }

    /// Get the legal moves with coordinates in the documented order: placements first,
    /// then by piece type, source and target. `[None]` means the player must pass.
    pub fn legal_coord_moves(&self, state: &mut GameState) -> Vec<Option<CoordMove>> {
        let mut moves = Vec::new();
        self.legal_moves(state, &mut moves);

        if moves.is_empty() {
            return vec![None];
        }

        let mut coord_moves: Vec<_> =
            moves.into_iter().map(|mv| state.decode(mv)).collect();
        coord_moves.sort_unstable();
        coord_moves.into_iter().map(Some).collect()
    }

    /// Get the legal placements with coordinates, ordered by piece type and target.
    pub fn placement_coord_moves(&self, state: &GameState) -> Vec<CoordMove> {
        let mut moves = Vec::new();
        self.placement_moves(state, &mut moves);
        Self::decode_sorted(state, &moves)
    }

    /// Get the legal movements with coordinates, ordered by piece type, source and
    /// target.
    pub fn movement_coord_moves(&self, state: &mut GameState) -> Vec<CoordMove> {
        let mut moves = Vec::new();
        self.movement_moves(state, &mut moves);
        Self::decode_sorted(state, &moves)
    }

    /// Convert moves to coordinates and sort them.
    fn decode_sorted(state: &GameState, moves: &[Move]) -> Vec<CoordMove> {
        let mut coord_moves: Vec<_> = moves.iter().map(|&mv| state.decode(mv)).collect();
        coord_moves.sort_unstable();
        coord_moves
    }

    /// Get the coordinates the player to move may place a piece on, sorted.
    pub fn placeable_coords(&self, state: &GameState) -> Vec<Coord> {
        let mut coords = Vec::new();
        Self::for_each_placeable_cell(state, |cell| {
            coords.push(state.board().locate(cell));
        });
        coords.sort_unstable();
        coords
    }

    /// Get the movable pieces with their coordinates, sorted by coordinate.
    pub fn movable_coords(&self, state: &GameState) -> Vec<(Coord, PieceType)> {
        let mut pieces: Vec<_> = self
            .movable_pieces(state)
            .into_iter()
            .map(|(cell, piece_type)| (state.board().coord(cell), piece_type))
            .collect();
        pieces.sort_unstable();
        pieces
    }

    /// Get the sorted coordinates the top piece at `coord` may move to, empty if it is
    /// not one of the movable pieces.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError::InvalidArgument`] if `coord` is not occupied.
    pub fn target_coords(
        &self,
        state: &mut GameState,
        coord: Coord,
    ) -> Result<Vec<Coord>, EngineError> {
        let Some(cell) = state.occupied_cell(coord) else {
            let message = format!(
                "Cannot get target coordinates for unoccupied coordinate `{coord}`."
            );
            return Err(EngineError::InvalidArgument(message));
        };
        let Some((_, piece_type)) =
            self.movable_pieces(state).into_iter().find(|&(movable, _)| movable == cell)
        else {
            return Ok(Vec::new());
        };
        let mut targets = Vec::new();
        add_piece_targets(state.board_mut(), cell, piece_type, &mut targets);
        let mut coords: Vec<_> =
            targets.into_iter().map(|target| state.board().locate(target)).collect();
        coords.sort_unstable();
        Ok(coords)
    }

    /// Apply a move from outside the engine after checking that it is legal.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError::IllegalMove`] with the reason from
    /// [`Rules::illegal_move_reason`] if the move is not one of the legal moves.
    pub fn apply_checked_move(
        &self,
        state: &mut GameState,
        mv: Option<CoordMove>,
    ) -> Result<(), EngineError> {
        if !self.legal_coord_moves(state).contains(&mv) {
            let described = mv.map_or_else(|| "pass".to_owned(), |mv| mv.to_string());
            let message = format!(
                "Move `{described}` is not legal for player `{}` at ply `{}`: {}.",
                state.current_player().name(),
                state.current_ply(),
                self.illegal_move_reason(state, mv)
            );
            return Err(EngineError::IllegalMove(message));
        }

        state.apply_coord_move(mv)
    }

    /// Explain why a move is not legal, for messages to the player.
    ///
    /// The checks go from the most basic (is there a piece to move) to the most specific
    /// (can the piece reach the target), and the first that fails is the reason. The
    /// reason starts in lower case, has no final period, and does not repeat the
    /// coordinates, which the move already names.
    pub fn illegal_move_reason(
        &self,
        state: &mut GameState,
        mv: Option<CoordMove>,
    ) -> String {
        let Some(mv) = mv else {
            return "passing is only allowed when there is no legal move".to_owned();
        };
        let name = mv.piece_type.lower_name();

        let Some(source) = mv.source else {
            if !self.placeable_piece_types(state).contains(mv.piece_type) {
                if state.hand(state.current_player()).count(mv.piece_type) == 0 {
                    return format!("there is no {name} left in hand");
                }

                if mv.piece_type != PieceType::Queen {
                    let deadline = self
                        .config
                        .queen_by_turn
                        .map_or_else(|| "None".to_owned(), |turn| turn.to_string());
                    return format!("the queen must be placed by turn `{deadline}`");
                }

                return "the queen may not be placed on the first turn".to_owned();
            }

            if !self.placeable_coords(state).contains(&mv.target) {
                return match state.current_ply() {
                    0 => "the first piece must be placed at `(0, 0)`",
                    1 => "the second piece must be placed next to `(0, 0)`",
                    _ if state.occupied_cell(mv.target).is_some() => {
                        "the target is occupied"
                    }
                    _ => {
                        "a piece must be placed next to a piece of its owner and not \
                         next to a piece of the opponent"
                    }
                }
                .to_owned();
            }

            return "the placement is not legal".to_owned();
        };

        if let Some(reason) = self.immobility_reason(state, source) {
            return reason;
        }

        let Some(cell) = state.occupied_cell(source) else {
            return "there is no piece to move".to_owned();
        };
        let top_type = state.board().top(cell).piece_type();

        if top_type != mv.piece_type {
            return format!(
                "the piece is of type `{}`, not `{name}`",
                top_type.lower_name()
            );
        }

        format!("the {name} cannot reach the target")
    }

    /// Explain why the top piece at a coordinate cannot move, for messages, or get `None`
    /// if it has at least one legal target.
    pub fn immobility_reason(
        &self,
        state: &mut GameState,
        coord: Coord,
    ) -> Option<String> {
        let Some(cell) = state.occupied_cell(coord) else {
            return Some("there is no piece to move".to_owned());
        };
        let player = state.current_player();
        let top = state.board().top(cell);

        if top.owner() != player {
            return Some(format!("the piece belongs to `{}`", top.owner().name()));
        }

        if !self.config.move_before_queen && state.queen_coord(player).is_none() {
            return Some(
                "pieces may only move once their owner's queen is placed".to_owned(),
            );
        }

        let articulation = state.board().articulation_slots();

        if articulation & (1 << state.board().slot(cell)) != 0 {
            return Some("moving the piece would split the hive".to_owned());
        }

        let mut targets = Vec::new();
        add_piece_targets(state.board_mut(), cell, top.piece_type(), &mut targets);

        if targets.is_empty() {
            return Some(format!(
                "the {} has no legal target",
                top.piece_type().lower_name()
            ));
        }

        None
    }

    /// Create a validated state from the stacks of a board.
    ///
    /// The hands and queens follow from the pieces on the board. If `current_ply` is
    /// `None`, the lowest ply consistent with the board is used.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError::InvalidBoard`] if a stack is empty or too high, a player
    /// has more pieces of a type than `piece_counts` allows, the pieces are not
    /// connected, or the ply is inconsistent with the board (see
    /// [`Rules::validate_ply`]).
    pub fn from_board(
        &self,
        stacks: &[(Coord, Vec<Piece>)],
        current_player: Player,
        current_ply: Option<i64>,
    ) -> Result<GameState, EngineError> {
        let mut hands = [self.config.piece_counts; 2];
        let mut queens = [None; 2];

        for (coord, stack) in stacks {
            if stack.is_empty() {
                let message = format!("The stack at coordinate `{coord}` is empty.");
                return Err(EngineError::InvalidBoard(message));
            }

            for piece in stack {
                hands[piece.owner().index()].add(piece.piece_type(), -1);

                if piece.piece_type() == PieceType::Queen {
                    queens[piece.owner().index()] = Some(*coord);
                }
            }
        }

        for player in Player::ALL {
            for (piece_type, count) in hands[player.index()].iter() {
                if count < 0 {
                    let allowed = self.config.piece_counts.count(piece_type);
                    let message = format!(
                        "Player `{}` has `{}` pieces of type `{}` on the board, but at \
                         most `{allowed}` are allowed.",
                        player.name(),
                        allowed - count,
                        piece_type.name()
                    );
                    return Err(EngineError::InvalidBoard(message));
                }
            }
        }

        if !coords_are_connected(stacks) {
            let message = "The pieces on the board do not form one connected hive.";
            return Err(EngineError::InvalidBoard(message.to_owned()));
        }

        if let Some((coord, stack)) =
            stacks.iter().find(|(_, stack)| stack.len() > MAX_STACK_HEIGHT)
        {
            let message = format!(
                "The stack at coordinate `{coord}` has `{}` pieces, but a stack holds at \
                 most `{MAX_STACK_HEIGHT}`.",
                stack.len()
            );
            return Err(EngineError::InvalidBoard(message));
        }

        debug_assert!(
            stacks.iter().map(|(_, stack)| stack.len()).sum::<usize>() <= MAX_PIECES
        );
        let mut state = self.create_initial_state();

        for (coord, stack) in stacks {
            for &piece in stack {
                state.place_unchecked(*coord, piece);
            }
        }

        state.restore_hands_and_queens(hands, queens);
        state.set_current_player(current_player);
        let ply = self.validate_ply(&state, current_ply)?;
        state.set_current_ply(ply);
        Ok(state)
    }

    /// Validate the ply of a state built from a board, or derive the lowest valid one.
    ///
    /// The player to move alternates every ply starting with `starting_player`, and a
    /// player cannot have more pieces on the board than turns taken.
    ///
    /// # Errors
    ///
    /// Returns [`EngineError::InvalidBoard`] if `current_ply` is negative, does not match
    /// the player to move, or leaves a player with more pieces than turns taken.
    pub fn validate_ply(
        &self,
        state: &GameState,
        current_ply: Option<i64>,
    ) -> Result<i64, EngineError> {
        let mut piece_count = [0_i64; 2];

        for &cell in state.board().occupied() {
            for piece in state.board().stack(cell) {
                piece_count[piece.owner().index()] += 1;
            }
        }

        let starting = self.config.starting_player;
        let second = starting.opponent();
        let expect_even = state.current_player() == starting;

        let Some(ply) = current_ply else {
            let mut ply = (2 * piece_count[starting.index()] - 1)
                .max(2 * piece_count[second.index()])
                .max(0);

            if (ply % 2 == 0) != expect_even {
                ply += 1;
            }

            return Ok(ply);
        };

        if ply < 0 {
            let message = format!("The ply must not be negative, but got `{ply}`.");
            return Err(EngineError::InvalidBoard(message));
        }

        if (ply % 2 == 0) != expect_even {
            let message = format!(
                "Player `{}` cannot be to move at ply `{ply}` when `{}` starts the game.",
                state.current_player().name(),
                starting.name()
            );
            return Err(EngineError::InvalidBoard(message));
        }

        let mut turns_taken = [0_i64; 2];
        turns_taken[starting.index()] = (ply + 1) / 2;
        turns_taken[second.index()] = ply / 2;

        for player in Player::ALL {
            if piece_count[player.index()] > turns_taken[player.index()] {
                let message = format!(
                    "Player `{}` has `{}` pieces on the board, but has only taken `{}` \
                     turns at ply `{ply}`.",
                    player.name(),
                    piece_count[player.index()],
                    turns_taken[player.index()]
                );
                return Err(EngineError::InvalidBoard(message));
            }
        }

        Ok(ply)
    }
}

/// Check whether the coordinates of the stacks form one connected group, by real
/// coordinate rather than grid cell (true when there are none).
fn coords_are_connected(stacks: &[(Coord, Vec<Piece>)]) -> bool {
    let coords: HashSet<Coord> = stacks.iter().map(|(coord, _)| *coord).collect();
    let Some(&start) = coords.iter().next() else { return true };
    let mut seen = HashSet::from([start]);
    let mut queue = VecDeque::from([start]);

    while let Some(coord) = queue.pop_front() {
        for neighbor in coord.neighbors() {
            if coords.contains(&neighbor) && seen.insert(neighbor) {
                queue.push_back(neighbor);
            }
        }
    }

    seen.len() == coords.len()
}
