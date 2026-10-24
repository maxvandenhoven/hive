from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar

from hive.engine.errors import IllegalMoveError, InvalidBoardError
from hive.engine.grid import (
    HEX_DIRECTIONS,
    Coordinate,
    add,
    get_flanking_coords,
    get_neighbors,
)
from hive.engine.state import GameBoard, GameState, Move, PieceType, Player

BASE_PIECE_COUNTS: Mapping[PieceType, int] = MappingProxyType(
    {
        PieceType.QUEEN: 1,
        PieceType.BEETLE: 2,
        PieceType.GRASSHOPPER: 3,
        PieceType.SPIDER: 2,
        PieceType.ANT: 3,
    }
)
"""The number of copies of each piece type a player receives in the base game."""


@dataclass(frozen=True, slots=True)
class Rules:
    """The rules of a Hive game, holding both the configuration and the rule behaviour.

    `Rules` is an immutable value: it is hashable, equal for equal fields, and cheap to
    pass to worker processes or to store. Every method reads the configuration and a
    `GameState`, and never modifies the state permanently.

    Attributes:
        piece_counts: The number of copies of each piece type a player receives. Any
            mapping is accepted and stored as a read-only mapping ordered by piece type.
        starting_player: The player who takes the first turn.
        queen_by_turn: The turn number (one-indexed, per player) by which the queen must
            be placed, or `None` for no deadline.
        allow_queen_first_turn: Whether the queen may be placed on a player's first turn.
        move_before_queen: Whether pieces may move before their owner's queen is placed.
        max_turns: The maximum number of turns per player before the game is a draw, or
            `None` for no limit.
    """

    piece_counts: Mapping[PieceType, int] = field(
        default_factory=lambda: BASE_PIECE_COUNTS
    )
    starting_player: Player = Player.WHITE
    queen_by_turn: int | None = 4
    allow_queen_first_turn: bool = True
    move_before_queen: bool = False
    max_turns: int | None = None

    def __post_init__(self) -> None:
        """Freeze `piece_counts` and validate the configuration.

        Raises:
            ValueError: If the queen count is not exactly one, if a piece type with a
                positive count has no movement behaviour, or if the queen must be placed
                on the first turn while that is not allowed.
        """
        piece_counts = MappingProxyType(dict(sorted(self.piece_counts.items())))
        object.__setattr__(self, "piece_counts", piece_counts)

        # Validate that each player only gets one queen piece.
        if piece_counts.get(PieceType.QUEEN, 0) != 1:
            msg = (
                "Each player must receive exactly one queen piece, but got count "
                f"`{piece_counts.get(PieceType.QUEEN, 0)}`."
            )
            raise ValueError(msg)

        # Validate that every piece type in the config has movement behaviour.
        for piece_type, count in piece_counts.items():
            if count > 0 and piece_type not in self._TARGET_COORDS:
                msg = (
                    f"Missing movement behaviour for piece type `{piece_type.name}` with "
                    f"count `{count}`."
                )
                raise ValueError(msg)

        if self.queen_by_turn == 1 and not self.allow_queen_first_turn:
            msg = (
                "The queen cannot be required on the first turn when "
                "`allow_queen_first_turn` is `False`."
            )
            raise ValueError(msg)

    def __hash__(self) -> int:
        """Hash the rules by value.

        `piece_counts` is a read-only mapping, which is not hashable itself, so it is
        hashed as a tuple of its items. The items are ordered by piece type, so equal
        rules always have equal hashes.

        Returns:
            The hash of all fields.
        """
        return hash(
            (
                tuple(self.piece_counts.items()),
                self.starting_player,
                self.queen_by_turn,
                self.allow_queen_first_turn,
                self.move_before_queen,
                self.max_turns,
            )
        )

    def create_initial_state(self) -> GameState:
        """Create the initial game state with an empty board and full hands.

        Returns:
            The initial game state ready for play.
        """
        return GameState(
            piece_type_count=self.piece_counts, starting_player=self.starting_player
        )

    def from_board(
        self, board: GameBoard, current_player: Player, current_ply: int | None = None
    ) -> GameState:
        """Create a validated game state from a board.

        The board is copied, so later changes to `board` do not affect the state. The
        hands and queen coordinates are derived from the pieces on the board.

        The ply must be consistent with the board: the current player alternates every
        ply starting with `starting_player`, and a player cannot have more pieces on the
        board than turns taken. If `current_ply` is `None`, the lowest consistent ply is
        used. For a game with placements only, this is the number of pieces on the board.

        Args:
            board: The pieces on each occupied coordinate, ordered bottom to top.
            current_player: The player to move.
            current_ply: The number of plies played so far, or `None` to derive it.

        Returns:
            The game state with the given board, player and ply.

        Raises:
            InvalidBoardError: If a stack is empty, a player has more pieces of a type
                than `piece_counts` allows, the pieces are not connected, or the ply is
                inconsistent with the board and current player.
        """
        state = self.create_initial_state()

        for coord, stack in board.items():
            if not stack:
                msg = f"The stack at coordinate `{coord}` is empty."
                raise InvalidBoardError(msg)

            state.board[coord] = list(stack)
            for piece in stack:
                state.hand[piece.owner][piece.type] = (
                    state.hand[piece.owner].get(piece.type, 0) - 1
                )
                if piece.type is PieceType.QUEEN:
                    state.queen_coord[piece.owner] = coord

        # A negative count in hand means more pieces on the board than allowed. This also
        # limits each player to one queen, since `piece_counts` has exactly one.
        for player, hand in state.hand.items():
            for piece_type, count in hand.items():
                if count < 0:
                    allowed = self.piece_counts.get(piece_type, 0)
                    msg = (
                        f"Player `{player.name}` has `{allowed - count}` pieces of type "
                        f"`{piece_type.name}` on the board, but at most `{allowed}` are "
                        "allowed."
                    )
                    raise InvalidBoardError(msg)

        if not state.is_connected():
            msg = "The pieces on the board do not form one connected hive."
            raise InvalidBoardError(msg)

        state.current_player = current_player
        state.current_ply = self._validate_ply(state, current_ply)

        return state

    def _validate_ply(self, state: GameState, current_ply: int | None) -> int:
        """Validate the ply of a state built from a board, or derive the lowest valid one.

        Args:
            state: The state with its board and current player already set.
            current_ply: The ply to validate, or `None` to derive it.

        Returns:
            The validated or derived ply.

        Raises:
            InvalidBoardError: If `current_ply` is negative, does not match the current
                player, or leaves a player with more pieces on the board than turns taken.
        """
        piece_count = {player: 0 for player in Player}
        for stack in state.board.values():
            for piece in stack:
                piece_count[piece.owner] += 1

        # After `ply` plies, the starting player has taken `(ply + 1) // 2` turns and the
        # other player `ply // 2`. Each turn places at most one piece.
        starting_player = self.starting_player
        second_player = starting_player.opponent
        expect_even = state.current_player is starting_player

        if current_ply is None:
            current_ply = max(
                2 * piece_count[starting_player] - 1, 2 * piece_count[second_player], 0
            )
            if (current_ply % 2 == 0) != expect_even:
                current_ply += 1
            return current_ply

        if current_ply < 0:
            msg = f"The ply must not be negative, but got `{current_ply}`."
            raise InvalidBoardError(msg)

        if (current_ply % 2 == 0) != expect_even:
            msg = (
                f"Player `{state.current_player.name}` cannot be to move at ply "
                f"`{current_ply}` when `{starting_player.name}` starts the game."
            )
            raise InvalidBoardError(msg)

        turns_taken = {
            starting_player: (current_ply + 1) // 2,
            second_player: current_ply // 2,
        }
        for player in Player:
            if piece_count[player] > turns_taken[player]:
                msg = (
                    f"Player `{player.name}` has `{piece_count[player]}` pieces on the "
                    f"board, but has only taken `{turns_taken[player]}` turns at ply "
                    f"`{current_ply}`."
                )
                raise InvalidBoardError(msg)

        return current_ply

    def apply_checked_move(self, state: GameState, move: Move | None) -> None:
        """Apply a move to the state after checking that it is legal.

        Use this for moves from outside the engine, such as user input or game records.
        Search code that takes moves from `legal_moves` can call `state.apply_move`
        directly.

        Args:
            state: The current game state, which is modified in place.
            move: The move to apply, or `None` to pass.

        Raises:
            IllegalMoveError: If the move is not in `legal_moves(state)`.
        """
        if move not in self.legal_moves(state):
            msg = (
                f"Move `{move}` is not legal for player `{state.current_player.name}` at "
                f"ply `{state.current_ply}`."
            )
            raise IllegalMoveError(msg)

        state.apply_move(move)

    def legal_moves(self, state: GameState) -> list[Move | None]:
        """Get all legal moves for the current player.

        Combines the results of `placement_moves` and `movement_moves`. If there are no
        legal moves, the returned list contains only `None`, which represents a pass.

        Args:
            state: The current game state.

        Returns:
            All legal placement and movement moves, or `[None]` if the current player
            must pass.
        """
        moves: list[Move | None] = []
        moves += self.placement_moves(state)
        moves += self.movement_moves(state)

        if not moves:
            return [None]

        return moves

    def placement_moves(self, state: GameState) -> list[Move]:
        """Get all legal placement moves for the current player.

        Combines each placeable coordinate with each placeable piece type.

        Args:
            state: The current game state.

        Returns:
            All legal placement moves. Each move has `source_coord` set to `None`.
        """
        placeable_piece_types = self.placeable_piece_types(state)

        moves: list[Move] = []
        for coord in self.placeable_coords(state):
            for piece_type in placeable_piece_types:
                moves.append(
                    Move(piece_type=piece_type, source_coord=None, target_coord=coord)
                )
        return moves

    def movement_moves(self, state: GameState) -> list[Move]:
        """Get all legal movement moves for the current player.

        Args:
            state: The current game state.

        Returns:
            All legal movement moves of the pieces returned by `movable_pieces`.
        """
        moves: list[Move] = []
        for coord, piece_type in self.movable_pieces(state):
            for target_coord in self._TARGET_COORDS[piece_type](self, state, coord):
                moves.append(
                    Move(
                        piece_type=piece_type,
                        source_coord=coord,
                        target_coord=target_coord,
                    )
                )
        return moves

    def movable_pieces(self, state: GameState) -> list[tuple[Coordinate, PieceType]]:
        """Get the pieces of the current player that are allowed to move.

        A piece may move if its owner's queen has been placed (unless `move_before_queen`
        is `True`), it is the top piece of its stack, and removing it does not split the
        hive into disconnected components (the one-hive rule).

        Args:
            state: The current game state.

        Returns:
            The axial coordinate `(q, r)` and piece type of each movable piece.
        """
        if (
            not self.move_before_queen
            and state.get_queen_coord(state.current_player) is None
        ):
            return []

        articulation_points = state.get_articulation_points()

        movable_pieces: list[tuple[Coordinate, PieceType]] = []
        for coord in state.get_occupied_coords():
            top_piece = state.get_top_piece(coord)

            if top_piece.owner != state.current_player:
                continue

            if coord in articulation_points:
                continue

            movable_pieces.append((coord, top_piece.type))

        return movable_pieces

    def target_coords(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get the coordinates the top piece at `coord` may move to.

        Args:
            state: The current game state.
            coord: The axial coordinate `(q, r)` of the piece to move.

        Returns:
            All axial coordinates the piece may legally move to. Empty if the piece is not
            one of the `movable_pieces`.

        Raises:
            ValueError: If `coord` is not occupied.
        """
        if not state.is_occupied(coord):
            msg = f"Cannot get target coordinates for unoccupied coordinate `{coord}`."
            raise ValueError(msg)

        for movable_coord, piece_type in self.movable_pieces(state):
            if movable_coord == coord:
                return self._TARGET_COORDS[piece_type](self, state, coord)

        return []

    def placeable_coords(self, state: GameState) -> list[Coordinate]:
        """Get all coordinates where the current player may place a piece from the hand.

        On the first ply the piece is placed at the origin `(0, 0)`, and on the second ply
        on any neighbor of the origin. Afterwards a piece may only be placed on an
        unoccupied coordinate that is adjacent to at least one of the current player's
        pieces and not adjacent to any of the opponent's pieces.

        Args:
            state: The current game state.

        Returns:
            All axial coordinates `(q, r)` where a piece may be placed.
        """
        if state.current_ply == 0:
            return [(0, 0)]

        if state.current_ply == 1:
            return get_neighbors((0, 0))

        placeable_coords = set()
        for coord in state.get_occupied_coords():
            top_piece = state.get_top_piece(coord)
            if top_piece.owner != state.current_player:
                continue

            for neighbor in get_neighbors(coord):
                if state.is_occupied(neighbor):
                    continue

                if state.get_adjacent_players(neighbor) == {state.current_player}:
                    placeable_coords.add(neighbor)

        return list(placeable_coords)

    def placeable_piece_types(self, state: GameState) -> list[PieceType]:
        """Get all piece types the current player may place.

        If the queen has not been placed by turn `queen_by_turn`, only the queen may be
        placed. If `allow_queen_first_turn` is `False`, the queen may not be placed on the
        player's first turn.

        Args:
            state: The current game state.

        Returns:
            All piece types the current player has in hand and is allowed to place.
        """
        player_turn = state.current_ply // 2 + 1

        if self.queen_by_turn is not None:
            queen_placed = state.get_queen_coord(state.current_player) is not None
            if player_turn >= self.queen_by_turn and not queen_placed:
                return [PieceType.QUEEN]

        return [
            piece_type
            for piece_type, count in state.hand[state.current_player].items()
            if count > 0
            and not (
                piece_type is PieceType.QUEEN
                and player_turn == 1
                and not self.allow_queen_first_turn
            )
        ]

    def winners(self, state: GameState) -> list[Player] | None:
        """Determine which players have won the game, if any.

        A player wins when the opponent's queen is surrounded on all six sides. If both
        queens are surrounded, or the turn limit `max_turns` has been exceeded, both
        players are returned, which indicates a draw.

        Args:
            state: The current game state.

        Returns:
            The winning players if the game has ended, or `None` if the game is still in
            progress. A list with both players indicates a draw.
        """
        # The ply counts moves across all players, so the total number of allowed plies is
        # twice the max turns per player. A draw may be made in the final allowed turn, so
        # the game only ends in a draw if the ply count exceeds this total.
        if self.max_turns is not None and state.current_ply > 2 * self.max_turns:
            return [Player.WHITE, Player.BLACK]

        winners: list[Player] = []
        for player in Player:
            queen_coord = state.get_queen_coord(player)
            if queen_coord is not None and state.is_surrounded(queen_coord):
                winners.append(player.opponent)

        return winners if winners else None

    def is_finished(self, state: GameState) -> bool:
        """Check whether the game has ended.

        Args:
            state: The current game state.

        Returns:
            `True` if `winners` returns a result, otherwise `False`.
        """
        return self.winners(state) is not None

    def _slideable_neighbors(
        self, state: GameState, coord: Coordinate
    ) -> list[Coordinate]:
        """Get the neighboring coordinates that a piece can slide into.

        A neighbor is slideable if it is unoccupied, not blocked by the gate rule (both
        flanking coordinates occupied), and at least one flanking coordinate is occupied,
        so the piece keeps contact with the hive while it slides.

        Args:
            state: The current game state.
            coord: The axial coordinate `(q, r)` to slide from.

        Returns:
            The neighboring coordinates that satisfy all sliding constraints.
        """
        slideable_neighbors: list[Coordinate] = []
        for neighbor_coord in get_neighbors(coord):
            if state.is_occupied(neighbor_coord):
                continue

            if not state.can_slide(source_coord=coord, target_coord=neighbor_coord):
                continue

            if not any(
                state.is_occupied(flanking_coord)
                for flanking_coord in get_flanking_coords(coord, neighbor_coord)
            ):
                continue

            slideable_neighbors.append(neighbor_coord)

        return slideable_neighbors

    def _queen_targets(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get the targets of a queen, which slides exactly one space.

        Args:
            state: The current game state.
            coord: The axial coordinate `(q, r)` of the queen.

        Returns:
            The coordinates the queen can slide to.
        """
        with state.piece_lifted(coord):
            return self._slideable_neighbors(state, coord)

    def _beetle_targets(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get the targets of a beetle, which moves one space and may climb the hive.

        On the ground, the beetle slides like the queen. A move where the beetle is on
        the hive before or after, at the higher of the source height (without the beetle)
        and the target height, is blocked only by a gate of two flanking stacks that are
        both higher than that.

        Args:
            state: The current game state.
            coord: The axial coordinate `(q, r)` of the beetle.

        Returns:
            The coordinates the beetle can slide to on the ground, followed by the
            coordinates it can reach on the hive.
        """
        with state.piece_lifted(coord):
            source_height = state.get_stack_height(coord)
            destinations = (
                [] if source_height else self._slideable_neighbors(state, coord)
            )

            for neighbor_coord in get_neighbors(coord):
                height = max(source_height, state.get_stack_height(neighbor_coord))
                if height == 0:
                    continue

                if all(
                    state.get_stack_height(flanking_coord) > height
                    for flanking_coord in get_flanking_coords(coord, neighbor_coord)
                ):
                    continue

                destinations.append(neighbor_coord)

        return destinations

    def _grasshopper_targets(
        self, state: GameState, coord: Coordinate
    ) -> list[Coordinate]:
        """Get the targets of a grasshopper, which jumps in a straight line.

        The grasshopper must jump over at least one piece and lands on the first
        unoccupied coordinate in that direction.

        Args:
            state: The current game state.
            coord: The axial coordinate `(q, r)` of the grasshopper.

        Returns:
            The coordinates the grasshopper can jump to.
        """
        destinations = []

        for direction in HEX_DIRECTIONS:
            current_coord = add(coord, direction)
            if not state.is_occupied(current_coord):
                continue

            while state.is_occupied(current_coord):
                current_coord = add(current_coord, direction)

            destinations.append(current_coord)

        return destinations

    def _spider_targets(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get the targets of a spider, which slides exactly three spaces.

        Each step must be a valid slide and the path cannot revisit a coordinate. A
        depth-first search explores all paths of length three.

        Args:
            state: The current game state.
            coord: The axial coordinate `(q, r)` of the spider.

        Returns:
            The coordinates the spider can reach in exactly three slides.
        """
        destinations = set()

        def _dfs(
            current_coord: Coordinate, visited_coords: set[Coordinate], depth: int
        ) -> None:
            if depth == 3:
                destinations.add(current_coord)
                return

            for neighbor_coord in self._slideable_neighbors(state, current_coord):
                if neighbor_coord in visited_coords:
                    continue

                visited_coords.add(neighbor_coord)
                _dfs(
                    current_coord=neighbor_coord,
                    visited_coords=visited_coords,
                    depth=depth + 1,
                )
                visited_coords.remove(neighbor_coord)

        with state.piece_lifted(coord):
            _dfs(current_coord=coord, visited_coords={coord}, depth=0)

        destinations.discard(coord)

        return list(destinations)

    def _ant_targets(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get the targets of an ant, which slides any number of spaces.

        A search explores all unoccupied coordinates connected to the start through a
        chain of valid slides.

        Args:
            state: The current game state.
            coord: The axial coordinate `(q, r)` of the ant.

        Returns:
            The coordinates the ant can reach.
        """
        destinations = set()

        visited_coords = {coord}
        frontier = [coord]

        with state.piece_lifted(coord):
            while frontier:
                current_coord = frontier.pop()
                for neighbor_coord in self._slideable_neighbors(state, current_coord):
                    if neighbor_coord in visited_coords:
                        continue

                    destinations.add(neighbor_coord)
                    visited_coords.add(neighbor_coord)
                    frontier.append(neighbor_coord)

        destinations.discard(coord)

        return list(destinations)

    # Movement behaviour per piece type. Piece types missing here cannot be used in
    # `piece_counts`, which `__post_init__` validates.
    _TARGET_COORDS: ClassVar[
        Mapping[PieceType, Callable[["Rules", GameState, Coordinate], list[Coordinate]]]
    ] = MappingProxyType(
        {
            PieceType.QUEEN: _queen_targets,
            PieceType.BEETLE: _beetle_targets,
            PieceType.GRASSHOPPER: _grasshopper_targets,
            PieceType.SPIDER: _spider_targets,
            PieceType.ANT: _ant_targets,
        }
    )
