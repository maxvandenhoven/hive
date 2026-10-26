"""Request and response models of the API.

Engine, agent and match values (`Rules`, `BoardSetup`, `Move`, `DecisionRecord`,
`AgentSpec`) are used as they are, so their JSON form and schema have one definition.
Responses are read from the ORM rows with `from_attributes`.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hive.agents.base import SearchInfoValue
from hive.agents.factory import AgentSpec
from hive.api.db.models import GameResult, GameRow, GameStatus, MoveSource
from hive.api.errors import ApiErrorCode
from hive.api.players import AgentPlayer, HumanPlayer, PlayerConfig
from hive.engine.errors import InvalidBoardError
from hive.engine.grid import Coordinate
from hive.engine.record import BoardSetup
from hive.engine.rules import Rules
from hive.engine.state import BoardCell, GameState, Move, PieceType, Player
from hive.match.records import DecisionRecord

GAME_NAME_MAX_LENGTH = 100
"""The longest game name in characters."""

GAME_PAGE_MAX_LIMIT = 100
"""The most games one page of the game list may hold."""


class GameCreate(BaseModel):
    """The request body that creates a game.

    Attributes:
        name: The display name.
        white: The white side.
        black: The black side. At least one side must be an agent.
        rules: The rules; missing fields take their default.
        setup: A starting position from the board editor, or `None` for the initial
            state.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=GAME_NAME_MAX_LENGTH)
    white: PlayerConfig
    black: PlayerConfig
    rules: Rules = Field(default_factory=Rules)
    setup: BoardSetup | None = None

    @model_validator(mode="after")
    def validate_game(self) -> Self:
        """Check the players, the agent params and the setup.

        Returns:
            The request.

        Raises:
            ValueError: If both sides are human, an agent spec is invalid, or the setup
                is not valid under the rules.
        """
        if isinstance(self.white, HumanPlayer) and isinstance(self.black, HumanPlayer):
            msg = "At least one side must be an agent; human vs human is not supported."
            raise ValueError(msg)

        for player in (self.white, self.black):
            if isinstance(player, AgentPlayer):
                player.spec.validate_params()

        if self.setup is not None:
            try:
                self.setup.create_state(self.rules)
            except InvalidBoardError as e:
                msg = f"Invalid setup: {e}"
                raise ValueError(msg) from e

        return self


class GameUpdate(BaseModel):
    """The request body that changes a game; fields left out are unchanged.

    Attributes:
        name: The new display name.
        status: The new status.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=GAME_NAME_MAX_LENGTH)
    status: GameStatus | None = None


class MoveRead(BaseModel):
    """A move of a game.

    Attributes:
        ply: The ply the move was played at.
        move: The move, or `None` for a pass.
        source: How the move was entered.
        photo_id: The photo the move was read from, or `None`.
        decision: The decision behind an agent move, or `None`.
        created_at: When the move was played.
    """

    model_config = ConfigDict(from_attributes=True)

    ply: int
    move: Move | None
    source: MoveSource
    photo_id: uuid.UUID | None
    decision: DecisionRecord | None
    created_at: datetime


class MoveCreate(BaseModel):
    """The request body that plays a move.

    Attributes:
        move: The move, or `None` to pass, which is only legal without another move.
        source: How the move was entered. Agent moves are committed by the agent.
        photo_id: The photo the move was read from, required with source `photo` and
            only allowed with it.
        expected_ply: The ply the move is played at, which is the `ply_count` of the game
            the client saw. If another move came first, the move is rejected.
        allow_agent_side: Whether the move may be entered for a side that an agent plays,
            for example when the move made at the table differs from the agent's.
    """

    model_config = ConfigDict(extra="forbid")

    move: Move | None
    source: Literal[MoveSource.MANUAL, MoveSource.PHOTO] = MoveSource.MANUAL
    photo_id: uuid.UUID | None = None
    expected_ply: int = Field(ge=0)
    allow_agent_side: bool = False

    @model_validator(mode="after")
    def validate_photo(self) -> Self:
        """Check that a photo is given exactly for moves read from a photo.

        Returns:
            The request.

        Raises:
            ValueError: If the source is `photo` without a photo, or another source has
                one.
        """
        if (self.source == MoveSource.PHOTO) != (self.photo_id is not None):
            msg = "`photo_id` is required with source `photo` and only allowed with it."
            raise ValueError(msg)

        return self


class MovablePiece(BaseModel):
    """A piece of the side to move that has at least one legal target.

    Attributes:
        coord: The coordinate of the piece, on top of its stack.
        piece: The type of the piece.
    """

    coord: Coordinate
    piece: PieceType


class PieceTargets(BaseModel):
    """The legal targets of a piece of the side to move.

    Attributes:
        coord: The coordinate of the piece, on top of its stack.
        piece: The type of the piece.
        targets: The coordinates the piece may move to, sorted.
    """

    coord: Coordinate
    piece: PieceType
    targets: list[Coordinate]


class GamePosition(BaseModel):
    """The position of a game at one ply, with what the side to move may play.

    Attributes:
        ply: The number of moves played from the starting position, which is the setup
            for games from the board editor.
        ply_count: The number of moves of the game, so `ply == ply_count` is the latest
            position.
        board: The stacks on the board, ordered by coordinate.
        hands: The pieces each side has left to place, by piece type.
        current_player: The side to move.
        result: The result if the game ended in the position, otherwise `None`.
        last_move: The move that led to the position, or `None` at the start.
        movable_pieces: The pieces of the side to move with a legal target, sorted by
            coordinate. Empty once the game ended.
        placeable_coords: Where the side to move may place a piece, sorted. Empty once
            the game ended or without a piece that may be placed.
        placeable_piece_types: The piece types the side to move may place. Empty once
            the game ended or without a coordinate to place on.
        must_pass: Whether the side to move has no legal move and must pass, by playing
            the move `None`.
    """

    ply: int
    ply_count: int
    board: list[BoardCell]
    hands: dict[Player, dict[PieceType, int]]
    current_player: Player
    result: GameResult | None
    last_move: MoveRead | None
    movable_pieces: list[MovablePiece]
    placeable_coords: list[Coordinate]
    placeable_piece_types: list[PieceType]
    must_pass: bool

    @classmethod
    def from_state(cls, game: GameRow, state: GameState, ply: int) -> Self:
        """Describe the position of a game.

        Args:
            game: The game, with its moves loaded.
            state: The state of the game after its first `ply` moves.
            ply: The number of moves played to reach the state.

        Returns:
            The position, with the legal moves of the side to move.
        """
        result = GameResult.from_winners(game.rules.winners(state))
        legal_moves = [] if result is not None else game.rules.legal_moves(state)
        placements = [
            move for move in legal_moves if move is not None and move.source_coord is None
        ]
        movable_pieces = {
            move.source_coord: move.piece_type
            for move in legal_moves
            if move is not None and move.source_coord is not None
        }

        return cls(
            ply=ply,
            ply_count=len(game.moves),
            board=BoardCell.split_board(state.board),
            hands=state.hand,
            current_player=state.current_player,
            result=result,
            last_move=MoveRead.model_validate(game.moves[ply - 1]) if ply > 0 else None,
            movable_pieces=[
                MovablePiece(coord=coord, piece=piece_type)
                for coord, piece_type in sorted(movable_pieces.items())
            ],
            placeable_coords=sorted({move.target_coord for move in placements}),
            placeable_piece_types=sorted({move.piece_type for move in placements}),
            must_pass=legal_moves == [None],
        )


class GameSummary(BaseModel):
    """A game in the game list.

    Attributes:
        id: The game ID.
        name: The display name.
        status: Whether the game is still being played.
        white: The white side.
        black: The black side.
        result: The result, or `None` while there is none.
        ply_count: The number of moves played.
        created_at: When the game was created.
        updated_at: When the game was last changed.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: GameStatus
    white: PlayerConfig = Field(validation_alias="white_player")
    black: PlayerConfig = Field(validation_alias="black_player")
    result: GameResult | None
    ply_count: int
    created_at: datetime
    updated_at: datetime


class GameDetail(GameSummary):
    """A game with its rules, setup and moves.

    Attributes:
        rules: The rules.
        setup: The starting position from the board editor, or `None` for the initial
            state.
        moves: The moves, ordered by ply.
    """

    rules: Rules
    setup: BoardSetup | None
    moves: list[MoveRead]


class GamePage(BaseModel):
    """One page of the game list, newest first.

    Attributes:
        items: The games on the page.
        total: The number of games matching the filter, on all pages.
        limit: The most games a page holds.
        offset: The number of games before this page.
    """

    items: list[GameSummary]
    total: int
    limit: int
    offset: int


class ThinkRequest(BaseModel):
    """The request body that lets an agent think about the latest position of a game.

    Attributes:
        agent: The agent that thinks, or `None` for the agent playing the side to move.
        budget_s: The time budget in seconds, or `None` for the budget of the side to
            move. Budgets above the maximum of the service are shortened to it.
        commit: Whether to play the decided move in the game. Only the agent playing the
            side to move may commit, so `agent` must be `None` or its spec.
    """

    model_config = ConfigDict(extra="forbid")

    agent: AgentSpec | None = None
    budget_s: float | None = Field(default=None, gt=0.0, allow_inf_nan=False)
    commit: bool = False

    @model_validator(mode="after")
    def validate_agent(self) -> Self:
        """Check the params of the agent against its kind.

        Returns:
            The request.

        Raises:
            ValueError: If the kind is not registered or the params are invalid.
        """
        if self.agent is not None:
            self.agent.validate_params()

        return self


class ThinkInfoEvent(BaseModel):
    """A progress report of the thinking agent, such as a completed search depth.

    Attributes:
        type: Always `info`, which tells the events apart.
        info: The progress values, such as `depth`, `nodes`, `score` and `pv`.
    """

    type: Literal["info"] = "info"
    info: dict[str, SearchInfoValue]


class ThinkCandidateEvent(BaseModel):
    """A legal move the agent proposed as its current answer.

    Attributes:
        type: Always `candidate`, which tells the events apart.
        move: The proposed move, or `None` to pass.
        final: Whether the agent is done, which ends its thinking.
    """

    type: Literal["candidate"] = "candidate"
    move: Move | None
    final: bool


class ThinkDecisionEvent(BaseModel):
    """The decision of the agent, sent once its turn closed.

    Attributes:
        type: Always `decision`, which tells the events apart.
        decision: The record of the decision, with the decided move.
        position: The position after the move if it was committed, otherwise `None`.
    """

    type: Literal["decision"] = "decision"
    decision: DecisionRecord
    position: GamePosition | None


class ThinkErrorEvent(BaseModel):
    """A failure after the stream started, which ends the stream.

    Sent after the decision when committing it failed, for example because another move
    was played meanwhile, or instead of the decision when the worker failed.

    Attributes:
        type: Always `error`, which tells the events apart.
        code: What went wrong, as in error responses.
        detail: A human-readable description.
    """

    type: Literal["error"] = "error"
    code: ApiErrorCode
    detail: str


type ThinkEvent = Annotated[
    ThinkInfoEvent | ThinkCandidateEvent | ThinkDecisionEvent | ThinkErrorEvent,
    Field(discriminator="type"),
]
"""An event of a thinking stream, told apart by its `type`."""


type HealthCheckResult = Literal["ok", "failed"]
"""The result of one readiness check."""


class LivenessReport(BaseModel):
    """The answer of the liveness probe.

    Attributes:
        status: Always `ok`; any answer at all means the process is serving.
    """

    status: Literal["ok"] = "ok"


class ReadinessReport(BaseModel):
    """The answer of the readiness probe.

    Attributes:
        status: `ready` if every check passed.
        checks: The result of each check by name: `database` and `storage`.
    """

    status: Literal["ready", "not ready"]
    checks: dict[str, HealthCheckResult]

    @classmethod
    def from_checks(cls, checks: dict[str, HealthCheckResult]) -> "ReadinessReport":
        """Summarize the results of the readiness checks.

        Args:
            checks: The result of each check by name.

        Returns:
            The report, `ready` if every check passed.
        """
        ready = all(result == "ok" for result in checks.values())

        return cls(status="ready" if ready else "not ready", checks=checks)
