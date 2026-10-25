"""ORM models of the database tables: games, their moves and their photos.

Engine values are stored in their serialized JSON form (see `hive.engine.serialization`).
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from hive.engine.serialization import (
    GameRecord,
    deserialize_move,
    deserialize_rules,
    deserialize_setup,
)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
"""Constraint names, so migrations can refer to constraints by a predictable name."""


class GameStatus(StrEnum):
    """Whether a game is still being played."""

    ACTIVE = "active"
    FINISHED = "finished"
    ABANDONED = "abandoned"


class GameResult(StrEnum):
    """The result of a finished game."""

    WHITE = "white"
    BLACK = "black"
    DRAW = "draw"


class MoveSource(StrEnum):
    """How a move was entered."""

    MANUAL = "manual"
    PHOTO = "photo"
    AGENT = "agent"


def utc_now() -> datetime:
    """Get the current time, for timestamp column defaults.

    Returns:
        The current time in UTC.
    """
    return datetime.now(UTC)


def text_enum(enum: type[StrEnum], name: str) -> Enum:
    """Build a column type that stores a string enum as its values in a text column.

    Args:
        enum: The enum class.
        name: The name of the check constraint that limits the column to the values.

    Returns:
        A non-native enum type with a check constraint.
    """
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda members: [member.value for member in members],
    )


JSON_VALUE = JSONB(none_as_null=False)
"""A JSON column type where Python `None` is stored as JSON `null`."""

NULLABLE_JSON_VALUE = JSONB(none_as_null=True)
"""A JSON column type where Python `None` is stored as SQL `NULL`."""


class Base(DeclarativeBase):
    """The base class of the ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class GameRow(Base):
    """A game tracked by the app.

    Attributes:
        id: The game ID.
        name: The display name.
        status: Whether the game is still being played.
        rules: The serialized rules.
        setup: The serialized setup: `"initial"`, or a board from the board editor.
        white_player: The white player: `{"type": "human"}`, or `{"type": "agent",
            "spec": ..., "budget_s": ...}` with a serialized `AgentSpec`.
        black_player: The black player, in the same form as `white_player`.
        result: The result, or `None` while there is none.
        created_at: When the game was created.
        updated_at: When the game was last changed.
        moves: The moves of the game, ordered by ply.
        photos: The photos taken during the game.
    """

    __tablename__ = "game"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[GameStatus] = mapped_column(
        text_enum(enum=GameStatus, name="status"), default=GameStatus.ACTIVE
    )
    rules: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)
    setup: Mapped[Any] = mapped_column(JSON_VALUE)
    white_player: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)
    black_player: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)
    result: Mapped[GameResult | None] = mapped_column(
        text_enum(enum=GameResult, name="result")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    moves: Mapped[list["MoveRow"]] = relationship(
        back_populates="game",
        order_by="MoveRow.ply",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    photos: Mapped[list["PhotoRow"]] = relationship(
        back_populates="game",
        order_by="PhotoRow.created_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def photo_prefix(self) -> str:
        """The object key prefix of the photos of the game."""
        return f"photos/{self.id}/"

    def to_record(self) -> GameRecord:
        """Build the game record of the game.

        Returns:
            The rules, setup and moves of the game. The moves are not replayed.

        Raises:
            ValueError: If a stored value is not a valid serialized engine value.
        """
        return GameRecord(
            rules=deserialize_rules(self.rules),
            setup=deserialize_setup(self.setup),
            moves=[deserialize_move(move.move) for move in self.moves],
        )


class PhotoRow(Base):
    """A photo of the board, taken to enter a move.

    Attributes:
        id: The photo ID.
        game_id: The ID of the game.
        ply: The ply the photo was taken for.
        object_key: The key of the image in the object store.
        width: The image width in pixels.
        height: The image height in pixels.
        reader: The board reader that read the photo, or `None` if it was not read.
        model_version: The version of the reader model, or `None` if it has none.
        detections: The raw tile observations of the reader, or `None`.
        match: The top move candidates with their scores, or `None`.
        confirmed: Whether the move the photo proposed was committed.
        created_at: When the photo was taken.
        game: The game.
    """

    __tablename__ = "photo"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), index=True
    )
    ply: Mapped[int]
    object_key: Mapped[str] = mapped_column(String)
    width: Mapped[int]
    height: Mapped[int]
    reader: Mapped[str | None] = mapped_column(String)
    model_version: Mapped[str | None] = mapped_column(String)
    detections: Mapped[Any] = mapped_column(NULLABLE_JSON_VALUE, nullable=True)
    match: Mapped[Any] = mapped_column(NULLABLE_JSON_VALUE, nullable=True)
    confirmed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    game: Mapped[GameRow] = relationship(back_populates="photos")


class MoveRow(Base):
    """A move played in a game.

    Attributes:
        game_id: The ID of the game.
        ply: The ply the move was played at, counted from the start of the game record.
        move: The serialized move, or `None` for a pass.
        source: How the move was entered.
        photo_id: The photo the move was read from, or `None`.
        decision: The serialized `DecisionRecord` of an agent move, or `None`.
        created_at: When the move was played.
        game: The game.
    """

    __tablename__ = "move"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    ply: Mapped[int] = mapped_column(primary_key=True)
    move: Mapped[Any] = mapped_column(JSON_VALUE)
    source: Mapped[MoveSource] = mapped_column(text_enum(enum=MoveSource, name="source"))
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("photo.id", ondelete="SET NULL")
    )
    decision: Mapped[Any] = mapped_column(NULLABLE_JSON_VALUE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    game: Mapped[GameRow] = relationship(back_populates="moves")
