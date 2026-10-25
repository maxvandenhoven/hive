"""Request and response models of the API, separate from the database models."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hive.agents.factory import AgentRegistration, AgentSpec, AgentSpecDocument
from hive.api.db.models import GameResult, GameRow, GameStatus, MoveRow, MoveSource
from hive.engine.errors import InvalidBoardError
from hive.engine.serialization import (
    INITIAL_SETUP,
    JsonValue,
    deserialize_rules,
    deserialize_setup,
    serialize_rules,
    serialize_setup,
)

GAME_NAME_MAX_LENGTH = 100
"""The longest game name in characters."""

GAME_PAGE_MAX_LIMIT = 100
"""The most games one page of the game list may hold."""


class HumanPlayer(BaseModel):
    """A side played by a person at the table."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["human"] = "human"


class AgentPlayer(BaseModel):
    """A side played by an agent, whose moves a person executes on the board.

    Attributes:
        spec: The agent, as a serialized `AgentSpec`.
        budget_s: The time budget of every decision in seconds.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["agent"] = "agent"
    spec: AgentSpecDocument
    budget_s: float = Field(default=5.0, gt=0.0)

    def agent_spec(self) -> AgentSpec:
        """Validate the spec against the registered agent kinds.

        Returns:
            The spec.

        Raises:
            InvalidAgentSpecError: If the kind is unknown or the params are invalid.
        """
        return AgentSpec.from_dict(self.spec.model_dump(exclude_none=True))


type PlayerConfig = Annotated[HumanPlayer | AgentPlayer, Field(discriminator="type")]
"""A human or an agent side, told apart by its `type`."""


class GameCreate(BaseModel):
    """The request body that creates a game.

    Attributes:
        name: The display name.
        white: The white side.
        black: The black side. At least one side must be an agent.
        rules: The serialized rules, where missing fields take their default, or `None`
            for the default rules.
        setup: `"initial"`, or a serialized board from the board editor.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=GAME_NAME_MAX_LENGTH)
    white: PlayerConfig
    black: PlayerConfig
    rules: dict[str, Any] | None = None
    setup: Any = INITIAL_SETUP

    @model_validator(mode="after")
    def validate_game(self) -> Self:
        """Check the players, agent specs, rules and setup.

        Returns:
            The request, with the rules and setup normalized to their serialized form
            with every field.

        Raises:
            ValueError: If both sides are human, an agent spec is invalid, or the rules
                or setup are invalid.
        """
        if isinstance(self.white, HumanPlayer) and isinstance(self.black, HumanPlayer):
            msg = "At least one side must be an agent; human vs human is not supported."
            raise ValueError(msg)

        for player in (self.white, self.black):
            if isinstance(player, AgentPlayer):
                player.agent_spec()

        rules = deserialize_rules({} if self.rules is None else self.rules)
        setup = deserialize_setup(self.setup)

        if setup is not None:
            try:
                setup.state(rules)
            except InvalidBoardError as e:
                msg = f"Invalid setup: {e}"
                raise ValueError(msg) from e

        self.rules = serialize_rules(rules)
        self.setup = serialize_setup(setup)

        return self

    def to_row(self) -> GameRow:
        """Build the database row of the new game.

        Returns:
            An active game without moves.
        """
        return GameRow(
            name=self.name,
            status=GameStatus.ACTIVE,
            rules=self.rules,
            setup=self.setup,
            white_player=self.white.model_dump(),
            black_player=self.black.model_dump(),
        )


class GameUpdate(BaseModel):
    """The request body that changes a game; fields left out are unchanged.

    Attributes:
        name: The new display name.
        status: The new status.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=GAME_NAME_MAX_LENGTH)
    status: GameStatus | None = None

    def apply(self, row: GameRow) -> None:
        """Apply the changes to a game.

        Args:
            row: The game to change.
        """
        if self.name is not None:
            row.name = self.name

        if self.status is not None:
            row.status = self.status


class MoveRead(BaseModel):
    """A move of a game.

    Attributes:
        ply: The ply the move was played at.
        move: The serialized move, or `None` for a pass.
        source: How the move was entered.
        photo_id: The photo the move was read from, or `None`.
        decision: The serialized `DecisionRecord` of an agent move, or `None`.
        created_at: When the move was played.
    """

    model_config = ConfigDict(from_attributes=True)

    ply: int
    move: JsonValue
    source: MoveSource
    photo_id: uuid.UUID | None
    decision: dict[str, Any] | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: MoveRow) -> "MoveRead":
        """Build the response model of a move.

        Args:
            row: The move.

        Returns:
            The move.
        """
        return cls.model_validate(row)


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

    id: uuid.UUID
    name: str
    status: GameStatus
    white: PlayerConfig
    black: PlayerConfig
    result: GameResult | None
    ply_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: GameRow) -> Self:
        """Build the response model of a game.

        Args:
            row: The game, with its moves.

        Returns:
            The game.
        """
        return cls.model_validate(cls.row_fields(row))

    @classmethod
    def row_fields(cls, row: GameRow) -> dict[str, Any]:
        """Read the fields of the model from a game.

        Args:
            row: The game, with its moves.

        Returns:
            The field values by name.
        """
        return {
            "id": row.id,
            "name": row.name,
            "status": row.status,
            "white": row.white_player,
            "black": row.black_player,
            "result": row.result,
            "ply_count": len(row.moves),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }


class GameDetail(GameSummary):
    """A game with its rules, setup and moves.

    Attributes:
        rules: The serialized rules, with every field.
        setup: `"initial"`, or the serialized board from the board editor.
        moves: The moves, ordered by ply.
    """

    rules: dict[str, Any]
    setup: JsonValue
    moves: list[MoveRead]

    @classmethod
    def row_fields(cls, row: GameRow) -> dict[str, Any]:
        """Read the fields of the model from a game.

        Args:
            row: The game, with its moves.

        Returns:
            The summary fields, the rules, the setup and the moves by name.
        """
        return {
            **super().row_fields(row),
            "rules": row.rules,
            "setup": row.setup,
            "moves": [MoveRead.from_row(move) for move in row.moves],
        }


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


class AgentKindRead(BaseModel):
    """A registered agent kind, for the agent picker.

    Attributes:
        kind: The kind name used in agent specs.
        description: The summary line of the agent class docstring.
        params_schema: The JSON schema of the params.
    """

    kind: str
    description: str
    params_schema: dict[str, Any]

    @classmethod
    def from_registration(cls, registration: AgentRegistration) -> "AgentKindRead":
        """Build the response model of an agent kind.

        Args:
            registration: The registered kind.

        Returns:
            The kind.
        """
        return cls(
            kind=registration.kind,
            description=registration.description,
            params_schema=registration.params_schema,
        )
