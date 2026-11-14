"""The Rust core of the Hive engine and the agents' search, built from `rust/python`.

`hive.engine.state` re-exports `GameState` and `Move`, `hive.engine.rules` re-exports
`Rules`, and `hive.agents.search` re-exports `Searcher`; import them from there. This stub
gives type checkers and editors their types and documentation. The docstrings repeat the
doc comments of the bindings, and `tests/test_core_stub.py` keeps the two in sync.
"""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Literal, Protocol, Self, final

from pydantic import GetCoreSchemaHandler, JsonValue
from pydantic_core import CoreSchema

from hive.engine.grid import Coordinate
from hive.engine.state import Piece, PieceType, Player

class _Turn(Protocol):
    """The calls a search makes on its turn context (`hive.agents.base.TurnContext`)."""

    def submit(self, move: Move | None, *, final: bool = False) -> None: ...
    def should_stop(self) -> bool: ...
    def info(self, **fields: JsonValue) -> None: ...

@final
class Move:
    """A game move that places or moves a piece on the board.

    A move with `source_coord` set to `None` represents a placement from the player's
    hand. A move with a `source_coord` represents a movement of an existing piece on the
    board. The JSON form is `{"piece": "ant", "from": [q, r] | null, "to": [q, r]}`, and a
    pass (`None` where a move is expected) is `null`.

    Attributes:
        piece_type: The type of piece being placed or moved.
        source_coord: The axial coordinate `(q, r)` the piece moves from, or `None` if the
            piece is being placed from the hand.
        target_coord: The axial coordinate `(q', r')` the piece moves or is placed to.
    """

    __match_args__: ClassVar[tuple[str, str, str]]

    def __init__(
        self,
        piece_type: PieceType,
        source_coord: Coordinate | None,
        target_coord: Coordinate,
    ) -> None:
        """Create a move.

        Args:
            piece_type: The type of piece being placed or moved.
            source_coord: The axial coordinate the piece moves from, or `None` for a
                placement from the hand.
            target_coord: The axial coordinate the piece moves or is placed to.
        """

    @property
    def piece_type(self) -> PieceType:
        """The type of piece being placed or moved."""

    @property
    def source_coord(self) -> Coordinate | None:
        """The axial coordinate the piece moves from, or `None` for a placement."""

    @property
    def target_coord(self) -> Coordinate:
        """The axial coordinate the piece moves or is placed to."""

    def __hash__(self) -> int: ...
    def __eq__(self, other: object) -> bool: ...
    def to_json(self) -> JsonValue:
        """Serialize the value.

        Returns:
            The JSON-compatible form, with field aliases and enums as names.
        """

    @classmethod
    def from_json(cls, data: object) -> Self:
        """Deserialize and validate a value.

        Args:
            data: The JSON-compatible form, for example from `json.loads`.

        Returns:
            The value.

        Raises:
            pydantic.ValidationError: If `data` does not describe a valid value. It is a
                `ValueError` that lists the location of every problem.
        """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        """Describe the value to pydantic through its JSON form in `hive.engine.forms`.

        Args:
            source: The annotated type, this class.
            handler: Builds the schemas of other types.

        Returns:
            The pydantic core schema of the value.
        """

@final
class GameState:
    """The complete state of a Hive game at a given point in time.

    Tracks the board layout, current player, ply count, queen positions and each player's
    hand, and provides methods for querying and manipulating the board. The state lives in
    the Rust core: `board`, `hand` and `queen_coord` build new dicts on every access, so
    changing them does not change the state, and code that reads the board in a loop uses
    the query methods instead. Two states are equal if they describe the same position.

    Attributes:
        board: The pieces on each occupied coordinate, ordered bottom to top.
        hand: The number of pieces of each type each player has in hand.
        queen_coord: The coordinate of each player's queen, or `None` if it is not placed.
        current_player: The player to move.
        current_ply: The number of plies played so far, including passes.
    """

    __hash__: ClassVar[None]

    def __init__(
        self,
        piece_type_count: Mapping[PieceType, int],
        starting_player: Player | None = None,
    ) -> None:
        """Initialize a new game state with an empty board.

        Args:
            piece_type_count: A mapping from each piece type to the number of copies each
                player receives at the start of the game.
            starting_player: The player who takes the first turn. Defaults to
                `Player.WHITE`.
        """

    @property
    def board(self) -> dict[Coordinate, list[Piece]]:
        """The pieces on each occupied coordinate, bottom to top, as a new dict."""

    @property
    def hand(self) -> dict[Player, dict[PieceType, int]]:
        """The number of pieces of each type each player has in hand, as a new dict."""

    @property
    def queen_coord(self) -> dict[Player, Coordinate | None]:
        """Each player's queen coordinate, or `None` if not placed, as a new dict."""

    @property
    def current_player(self) -> Player:
        """The player to move."""

    @current_player.setter
    def current_player(self, player: Player) -> None: ...
    @property
    def current_ply(self) -> int:
        """The number of plies played so far, including passes."""

    @current_ply.setter
    def current_ply(self, ply: int) -> None: ...
    def __eq__(self, other: object) -> bool: ...
    def copy(self) -> GameState:
        """Copy the state, so moves applied to the copy do not affect the original.

        Returns:
            A state with the same board, player, ply, hands and queen coordinates.
        """

    def is_surrounded(self, coord: Coordinate) -> bool:
        """Check whether a coordinate is surrounded by other pieces.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            True if the coordinate to check has six occupied neighbors, otherwise False.
        """

    def count_occupied_neighbors(self, coord: Coordinate) -> int:
        """Count the occupied coordinates that directly neighbor a coordinate.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            The number of occupied neighbors, from zero to six.
        """

    def is_occupied(self, coord: Coordinate) -> bool:
        """Check if a coordinate on the game board is occupied (has a piece) or not.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            True if there is a piece on the given coordinate, otherwise False.
        """

    def get_queen_coord(self, player: Player) -> Coordinate | None:
        """Get the coordinate of the player's queen piece.

        Args:
            player: The player to get the queen coordinate for.

        Returns:
            The axial coordinate `(q, r)` of the player's queen piece, or None if the
            queen has not been placed on the board yet.
        """

    def get_top_piece(self, coord: Coordinate) -> Piece:
        """Get the top piece that is on an occupied coordinate.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            The top-most piece that is occupying the given coordinate.

        Raises:
            KeyError: If the coordinate is not occupied.
        """

    def get_stack_height(self, coord: Coordinate) -> int:
        """Get the height of the stack on a coordinate.

        Args:
            coord: The axial coordinate `(q, r)` to check.

        Returns:
            The height of the stack, or zero if the coordinate is unoccupied.
        """

    def get_occupied_coords(self) -> set[Coordinate]:
        """Get all occupied coordinates on the board.

        Returns:
            The axial coordinates `(q, r)` that have at least one piece on the board.
        """

    def get_articulation_points(self) -> set[Coordinate]:
        """Find all coordinates whose removal would disconnect the board.

        Uses Tarjan's articulation point algorithm to identify articulation points in
        linear time. A coordinate is an articulation point if removing it would split the
        remaining occupied coordinates into two or more disconnected components.
        Coordinates with a stack height greater than one are excluded, as removing the top
        piece still leaves the coordinate occupied.

        Returns:
            The set of coordinates whose removal would disconnect the board.
        """

    def is_connected(self) -> bool:
        """Check if all occupied coordinates on the board form one connected group.

        Returns:
            True if every occupied coordinate can be reached from every other one by
            moving between direct neighbors, or if the board is empty.
        """

    def is_connected_after_removing(self, coord: Coordinate) -> bool:
        """Check if the game board remains connected after removing a piece.

        Args:
            coord: The axial coordinate `(q, r)` to remove the top piece from.

        Returns:
            True if the board remains connected after removing the top piece from the
            given coordinate.

        Raises:
            KeyError: If the coordinate is not occupied.
        """

    def apply_placement(self, move: Move) -> None:
        """Apply a placement move to the game state, without advancing the turn.

        Removes the piece from the current player's hand and places it on the board at the
        target coordinate. If the placed piece is a queen, the queen coordinate for the
        current player is updated.

        Args:
            move: The placement move to apply.
        """

    def undo_placement(self, move: Move) -> None:
        """Undo a previously applied placement move.

        Removes the piece from the board at the target coordinate and returns it to the
        current player's hand. If the piece is a queen, the queen coordinate for the
        current player is reset to `None`.

        Args:
            move: The placement move to undo.
        """

    def apply_movement(self, move: Move) -> None:
        """Apply a movement move to the game state, without advancing the turn.

        Moves the top piece from the source coordinate to the target coordinate. If the
        moved piece is a queen, the queen coordinate for the current player is updated.

        Args:
            move: The movement move to apply. The `source_coord` must not be `None`.

        Raises:
            ValueError: If `move.source_coord` is `None`.
            KeyError: If there is no piece at the source coordinate.
        """

    def undo_movement(self, move: Move) -> None:
        """Undo a previously applied movement move.

        Moves the top piece from the target coordinate back to the source coordinate. If
        the moved piece is a queen, the queen coordinate for the current player is
        restored.

        Args:
            move: The movement move to undo. The `source_coord` must not be `None`.

        Raises:
            ValueError: If `move.source_coord` is `None`.
            KeyError: If there is no piece at the target coordinate.
        """

    def apply_move(self, move: Move | None) -> None:
        """Apply a move to the game state and advance the turn.

        A `None` move represents a pass. After applying the move, the ply counter is
        incremented and the current player switches to the opponent.

        Args:
            move: The move to apply, or `None` to pass the turn.
        """

    def undo_move(self, move: Move | None) -> None:
        """Undo the most recently applied move and revert the turn.

        A `None` move represents an undone pass. After undoing the move, the ply counter
        is decremented and the current player switches back.

        Args:
            move: The move to undo, or `None` if the previous turn was a pass.
        """

@final
class Rules:
    """The rules of a Hive game, holding both the configuration and the rule behaviour.

    `Rules` is an immutable value: it is hashable, equal for equal fields, and cheap to
    pass to worker processes or to store. Every method reads the configuration and a
    `GameState`, and never modifies the state permanently. The JSON form is an object with
    every field and `piece_counts` keyed by piece type name; missing fields take their
    default when reading.

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

    def __init__(
        self,
        piece_counts: Mapping[PieceType, int] | None = None,
        starting_player: Player | None = None,
        queen_by_turn: int | None = 4,
        allow_queen_first_turn: bool = True,
        move_before_queen: bool = False,
        max_turns: int | None = None,
    ) -> None:
        """Create and validate the rules.

        Args:
            piece_counts: The number of copies of each piece type a player receives, or
                `None` for the base game.
            starting_player: The player who takes the first turn, or `None` for white.
            queen_by_turn: The turn by which the queen must be placed, or `None`.
            allow_queen_first_turn: Whether the queen may be placed on the first turn.
            move_before_queen: Whether pieces may move before their queen is placed.
            max_turns: The turns per player before the game is a draw, or `None`.

        Raises:
            ValueError: If the queen count is not exactly one, a count is negative, a
                player would receive more than 14 pieces, or the queen must be placed on
                the first turn while that is not allowed.
        """

    @property
    def piece_counts(self) -> Mapping[PieceType, int]:
        """The number of copies of each piece type a player receives, read-only."""

    @property
    def starting_player(self) -> Player:
        """The player who takes the first turn."""

    @property
    def queen_by_turn(self) -> int | None:
        """The turn by which the queen must be placed, or `None` for no deadline."""

    @property
    def allow_queen_first_turn(self) -> bool:
        """Whether the queen may be placed on a player's first turn."""

    @property
    def move_before_queen(self) -> bool:
        """Whether pieces may move before their owner's queen is placed."""

    @property
    def max_turns(self) -> int | None:
        """The maximum number of turns per player before the game is a draw, or `None`."""

    def __hash__(self) -> int: ...
    def __eq__(self, other: object) -> bool: ...
    def to_json(self) -> JsonValue:
        """Serialize the value.

        Returns:
            The JSON-compatible form, with field aliases and enums as names.
        """

    @classmethod
    def from_json(cls, data: object) -> Self:
        """Deserialize and validate a value.

        Args:
            data: The JSON-compatible form, for example from `json.loads`.

        Returns:
            The value.

        Raises:
            pydantic.ValidationError: If `data` does not describe a valid value. It is a
                `ValueError` that lists the location of every problem.
        """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        """Describe the value to pydantic through its JSON form in `hive.engine.forms`.

        Args:
            source: The annotated type, this class.
            handler: Builds the schemas of other types.

        Returns:
            The pydantic core schema of the value.
        """

    def create_initial_state(self) -> GameState:
        """Create the initial game state with an empty board and full hands.

        Returns:
            The initial game state ready for play.
        """

    def from_board(
        self,
        board: Mapping[Coordinate, Sequence[Piece]],
        current_player: Player,
        current_ply: int | None = None,
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

    def validate_ply(self, state: GameState, current_ply: int | None) -> int:
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

    def apply_checked_move(self, state: GameState, move: Move | None) -> None:
        """Apply a move to the state after checking that it is legal.

        Use this for moves from outside the engine, such as user input or game records.
        Search code that takes moves from `legal_moves` can call `state.apply_move`
        directly.

        Args:
            state: The current game state, which is modified in place.
            move: The move to apply, or `None` to pass.

        Raises:
            IllegalMoveError: If the move is not in `legal_moves(state)`. The message
                names the move and the reason from `illegal_move_reason`.
        """

    def illegal_move_reason(self, state: GameState, move: Move | None) -> str:
        """Explain why a move is not legal, for messages to the player.

        The checks follow the rules from the most basic (is there a piece to move) to the
        most specific (can the piece reach the target), and the first that fails is the
        reason. Reasons do not repeat the coordinates, which the move already names.

        Args:
            state: The current game state.
            move: A move that is not in `legal_moves(state)`, or `None` for a pass.

        Returns:
            The reason, starting in lower case and without a final period.
        """

    def immobility_reason(self, state: GameState, coord: Coordinate) -> str | None:
        """Explain why the top piece at a coordinate cannot move, for messages.

        Args:
            state: The current game state.
            coord: The axial coordinate `(q, r)` of the piece.

        Returns:
            The reason, starting in lower case and without a final period, or `None` if
            the piece has at least one legal target.
        """

    def legal_moves(self, state: GameState) -> list[Move | None]:
        """Get all legal moves for the current player.

        Combines the results of `placement_moves` and `movement_moves`. If there are no
        legal moves, the returned list contains only `None`, which represents a pass. The
        order depends only on the position: placements first, then movements, each sorted
        by piece type, source and target coordinate, so seeded agents that pick moves by
        index are reproducible.

        Args:
            state: The current game state.

        Returns:
            All legal placement and movement moves, or `[None]` if the current player
            must pass.
        """

    def placement_moves(self, state: GameState) -> list[Move]:
        """Get all legal placement moves for the current player.

        Combines each placeable coordinate with each placeable piece type.

        Args:
            state: The current game state.

        Returns:
            All legal placement moves, sorted by piece type and target coordinate. Each
            move has `source_coord` set to `None`.
        """

    def movement_moves(self, state: GameState) -> list[Move]:
        """Get all legal movement moves for the current player.

        Args:
            state: The current game state.

        Returns:
            All legal movement moves of the pieces returned by `movable_pieces`, sorted by
            piece type, source and target coordinate.
        """

    def movable_pieces(self, state: GameState) -> list[tuple[Coordinate, PieceType]]:
        """Get the pieces of the current player that are allowed to move.

        A piece may move if its owner's queen has been placed (unless `move_before_queen`
        is `True`), it is the top piece of its stack, and removing it does not split the
        hive into disconnected components (the one-hive rule).

        Args:
            state: The current game state.

        Returns:
            The axial coordinate `(q, r)` and piece type of each movable piece, sorted by
            coordinate.
        """

    def target_coords(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
        """Get the coordinates the top piece at `coord` may move to.

        Args:
            state: The current game state.
            coord: The axial coordinate `(q, r)` of the piece to move.

        Returns:
            All axial coordinates the piece may legally move to, sorted. Empty if the
            piece is not one of the `movable_pieces`.

        Raises:
            ValueError: If `coord` is not occupied.
        """

    def placeable_coords(self, state: GameState) -> list[Coordinate]:
        """Get all coordinates where the current player may place a piece from the hand.

        On the first ply the piece is placed at the origin `(0, 0)`, and on the second ply
        on any neighbor of the origin. Afterwards a piece may only be placed on an
        unoccupied coordinate that is adjacent to at least one of the current player's
        pieces and not adjacent to any of the opponent's pieces.

        Args:
            state: The current game state.

        Returns:
            All axial coordinates `(q, r)` where a piece may be placed, sorted.
        """

    def placeable_piece_types(self, state: GameState) -> list[PieceType]:
        """Get all piece types the current player may place.

        If the queen has not been placed by turn `queen_by_turn`, only the queen may be
        placed. If `allow_queen_first_turn` is `False`, the queen may not be placed on the
        player's first turn.

        Args:
            state: The current game state.

        Returns:
            All piece types the current player has in hand and is allowed to place,
            sorted.
        """

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

    def is_finished(self, state: GameState) -> bool:
        """Check whether the game has ended.

        Args:
            state: The current game state.

        Returns:
            `True` if `winners` returns a result, otherwise `False`.
        """

    def perft(self, state: GameState, depth: int) -> int:
        """Count the leaf positions of the game tree to a fixed depth, in Rust.

        Every leaf is applied and undone, like the Python perft of `hive.bench`. The
        count runs without the GIL.

        Args:
            state: The game state to start from, which is restored afterwards.
            depth: The number of plies to walk.

        Returns:
            The number of positions reached after exactly `depth` plies.
        """

    def perft_bulk(self, state: GameState, depth: int) -> int:
        """Count like `perft`, but count the last ply's moves instead of playing them.

        Args:
            state: The game state to start from, which is restored afterwards.
            depth: The number of plies to walk.

        Returns:
            The number of positions reached after exactly `depth` plies.
        """

@final
class Searcher:
    """The tree search of the search agents, which runs in the Rust core.

    A search agent builds one searcher from its params and hands it every decision with
    `think`. The search deepens iteratively: after each completed depth it reports
    `depth`, `nodes`, `score`, `pv` and `nps` to `turn.info` and submits the first move of
    the principal variation, final once the depth limit is reached, the whole game tree
    was searched or the result is decided. It asks `turn.should_stop` before each depth
    and every `stop_check_interval` nodes, and discards a depth that is interrupted. The
    search runs without the GIL and holds it only for these calls.

    Attributes:
        nodes: The number of nodes the last decision visited.
    """

    def __init__(
        self,
        rules: Rules,
        *,
        algorithm: Literal["minimax", "negamax"],
        depth: int | None = None,
        queen_safety: float = 1.0,
        mobility: float = 0.0,
        positioning: float = 0.0,
        material_on_board: float = 0.0,
        material_in_hand: float = 0.0,
        queen_danger: float = 0.0,
        queen_escape: float = 0.0,
        pinned_material: float = 0.0,
        free_ants: float = 0.0,
        beetle_control: float = 0.0,
        tempo: float = 0.0,
        mobile_queen: float = 0.0,
        mobile_beetle: float = 0.0,
        mobile_grasshopper: float = 0.0,
        mobile_spider: float = 0.0,
        mobile_ant: float = 0.0,
        placement_cells: float = 0.0,
        queen_locked_neighbors: float = 0.0,
        stop_check_interval: int = 1024,
        alpha_beta: bool = True,
        table_megabytes: int = 32,
        aspiration_window: float = 0.0,
        threads: int = 1,
        principal_variation_search: bool = False,
        table_deeper_hits: bool = False,
        late_move_reductions: int = 0,
        null_move_reduction: int = 0,
        queen_attack_ordering: bool = False,
        queen_threat_extension: bool = False,
        repetition_draws: bool = False,
        forced_move_extension: bool = False,
    ) -> None:
        """Create a searcher.

        Args:
            rules: The rules governing the game.
            algorithm: The tree search, `"minimax"` or `"negamax"`.
            depth: The maximum search depth in plies, or `None` to search until stopped.
            queen_safety: The weight of the occupied neighbours of the opponent's queen
                minus those of the player's own queen.
            mobility: The weight of the player's legal moves minus the opponent's.
            positioning: The weight of the player's pieces next to the opponent's queen
                minus the opponent's pieces next to the player's queen.
            material_on_board: The weight of the value of the player's pieces on the
                board minus the opponent's.
            material_in_hand: The weight of the value of the player's pieces in hand
                minus the opponent's.
            queen_danger: Nonlinear queen crowding: squared occupied-neighbour counts.
            queen_escape: Legal queen escapes, excluding covered or pinned queens.
            pinned_material: Opponent minus own covered or articulation-pinned material.
            free_ants: Own minus opponent uncovered, unpinned ants after queen placement.
            beetle_control: Elevated beetle balance, doubled over an enemy queen.
            tempo: A bonus for the player to move.
            mobile_queen: Own minus opponent queens that can take a first step.
            mobile_beetle: Own minus opponent beetles that can move.
            mobile_grasshopper: Own minus opponent grasshoppers that can move.
            mobile_spider: Own minus opponent spiders that can take a first step.
            mobile_ant: Own minus opponent ants that can take a first step.
            placement_cells: Own minus opponent free cells to place a piece on.
            queen_locked_neighbors: Queen neighbours its owner cannot move away.
            stop_check_interval: The number of nodes between two calls of
                `turn.should_stop`.
            alpha_beta: Whether to prune with alpha-beta, which finds the same scores in
                far fewer nodes but may choose another of several equally scored moves.
            table_megabytes: The size of the transposition table in MB, zero for none.
                Negamax with alpha-beta uses it and orders moves by killers and history.
            aspiration_window: Initial score half-window, zero to disable aspiration.
            threads: Total negamax search threads sharing one table, at least one.
            principal_variation_search: Scout later moves before a full-window search.
            table_deeper_hits: Reuse table entries searched deeper than needed.
            late_move_reductions: Moves searched at full depth before later ones are
                scouted a ply shallower, zero for none. Needs principal variation search.
            null_move_reduction: Extra depth reduction of a null move at scout nodes,
                zero for none.
            queen_attack_ordering: Order moves next to the enemy queen after killers.
            queen_threat_extension: Search a ply deeper once a queen has five neighbours.
            repetition_draws: Score a repeat of an earlier position as a draw.
            forced_move_extension: Search a forced move without using up depth.

        Raises:
            ValueError: If the algorithm, depth, window or thread count is invalid.
        """

    def clear(self) -> None:
        """Forget the transposition table, killer moves and history, before a new game."""

    @property
    def nodes(self) -> int:
        """The number of nodes the last decision visited."""

    def think(self, state: GameState, turn: _Turn) -> int:
        """Search a decision with iterative deepening, reporting to the turn.

        Args:
            state: The state to decide a move in, searched in place and restored before
                returning, also when the turn stops the search.
            turn: The turn context: `should_stop`, `info` and `submit` are called on it.

        Returns:
            The number of nodes visited.

        Raises:
            Exception: Whatever a call on `turn` raised, which stops the search.
        """

    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate a position as the weighted sum of the evaluation terms.

        Args:
            state: The game state to evaluate.
            player: The player from whose perspective the position is evaluated.

        Returns:
            A score where positive values favour `player`.
        """
