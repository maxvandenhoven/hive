"""ORM models of the database tables: games, their moves and their photos.

Engine, agent and match values are stored as JSONB in their JSON form and read back as
typed values (see `TypedJsonb`). Relationships are never loaded lazily, since that would
do I/O on attribute access, which the asyncio extension does not allow; queries load them
explicitly with `selectinload`.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, override

from sqlalchemy import DateTime, Dialect, Enum, ForeignKey, MetaData, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    column_property,
    mapped_column,
    relationship,
)
from sqlalchemy.types import TypeDecorator

from hive.api.players import PlayerConfig
from hive.engine.codec import json_adapter
from hive.engine.record import BoardSetup, GameRecord
from hive.engine.rules import Rules
from hive.engine.state import Move
from hive.match.records import DecisionRecord

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


class TypedJsonb(TypeDecorator[Any]):
    """A JSONB column holding values of one type, converted with its pydantic adapter.

    Attributes:
        kind: The type of the values, for example `Rules` or `Move | None`.
    """

    impl = JSONB
    cache_ok = True

    def __init__(self, kind: Any, *, none_as_null: bool = False) -> None:
        """Create the column type.

        Args:
            kind: The type of the values.
            none_as_null: Whether `None` is stored as SQL `NULL` rather than JSON `null`.
        """
        super().__init__(none_as_null=none_as_null)
        self.kind = kind

    @override
    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        """Convert a value to its JSON form before it is written.

        Args:
            value: The value.
            dialect: The database dialect; unused.

        Returns:
            The JSON form of the value.
        """
        return json_adapter(self.kind).dump_python(value, mode="json", by_alias=True)

    @override
    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        """Read a value from its JSON form after it is loaded.

        Args:
            value: The JSON form, or `None` for SQL `NULL`.
            dialect: The database dialect; unused.

        Returns:
            The typed value.
        """
        return json_adapter(self.kind).validate_python(value)


class DatabaseBase(DeclarativeBase):
    """The base class of the ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class PhotoRow(DatabaseBase):
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
    detections: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
    match: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
    confirmed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    game: Mapped["GameRow"] = relationship(back_populates="photos", lazy="raise")


class MoveRow(DatabaseBase):
    """A move played in a game.

    Attributes:
        game_id: The ID of the game.
        ply: The ply the move was played at, counted from the start of the game record.
        move: The move, or `None` for a pass.
        source: How the move was entered.
        photo_id: The photo the move was read from, or `None`.
        decision: The decision behind an agent move, or `None`.
        created_at: When the move was played.
        game: The game.
    """

    __tablename__ = "move"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    ply: Mapped[int] = mapped_column(primary_key=True)
    move: Mapped[Move | None] = mapped_column(TypedJsonb(Move | None), nullable=False)
    source: Mapped[MoveSource] = mapped_column(text_enum(enum=MoveSource, name="source"))
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("photo.id", ondelete="SET NULL")
    )
    decision: Mapped[DecisionRecord | None] = mapped_column(
        TypedJsonb(DecisionRecord | None, none_as_null=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    game: Mapped["GameRow"] = relationship(back_populates="moves", lazy="raise")


class GameRow(DatabaseBase):
    """A game tracked by the app.

    Attributes:
        id: The game ID.
        name: The display name.
        status: Whether the game is still being played.
        rules: The rules.
        setup: The starting position from the board editor, or `None` for the initial
            state.
        white_player: The white player.
        black_player: The black player.
        result: The result, or `None` while there is none.
        created_at: When the game was created.
        updated_at: When the game was last changed.
        ply_count: The number of moves played, counted in SQL so listing games does not
            load the moves.
        moves: The moves of the game, ordered by ply.
        photos: The photos taken during the game.
    """

    __tablename__ = "game"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[GameStatus] = mapped_column(
        text_enum(enum=GameStatus, name="status"), default=GameStatus.ACTIVE
    )
    rules: Mapped[Rules] = mapped_column(TypedJsonb(Rules))
    setup: Mapped[BoardSetup | None] = mapped_column(
        TypedJsonb(BoardSetup | None, none_as_null=True)
    )
    white_player: Mapped[PlayerConfig] = mapped_column(TypedJsonb(PlayerConfig))
    black_player: Mapped[PlayerConfig] = mapped_column(TypedJsonb(PlayerConfig))
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
    ply_count: Mapped[int] = column_property(
        select(func.count())
        .where(MoveRow.game_id == id)
        .correlate_except(MoveRow)
        .scalar_subquery()
    )

    moves: Mapped[list[MoveRow]] = relationship(
        back_populates="game",
        order_by=MoveRow.ply,
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    photos: Mapped[list[PhotoRow]] = relationship(
        back_populates="game",
        order_by=PhotoRow.created_at,
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )

    @property
    def photo_prefix(self) -> str:
        """The object key prefix of the photos of the game."""
        return f"photos/{self.id}/"

    def to_record(self) -> GameRecord:
        """Build the game record of the game, which needs its moves loaded.

        Returns:
            The rules, setup and moves of the game. The moves are not replayed.
        """
        return GameRecord(
            rules=self.rules, setup=self.setup, moves=[row.move for row in self.moves]
        )
