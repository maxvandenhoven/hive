"""Create the game, move and photo tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def text_enum(name: str, values: Sequence[str]) -> sa.Enum:
    """Build a text column type limited to some values by a check constraint.

    Args:
        name: The full name of the check constraint, used as is.
        values: The allowed values.

    Returns:
        The non-native enum type.
    """
    return sa.Enum(
        *values, name=op.f(name), native_enum=False, create_constraint=True, length=16
    )


def upgrade() -> None:
    """Apply the migration."""
    op.create_table(
        "game",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "status",
            text_enum(name="ck_game_status", values=("active", "finished", "abandoned")),
            nullable=False,
        ),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("setup", postgresql.JSONB(), nullable=False),
        sa.Column("white_player", postgresql.JSONB(), nullable=False),
        sa.Column("black_player", postgresql.JSONB(), nullable=False),
        sa.Column(
            "result",
            text_enum(name="ck_game_result", values=("white", "black", "draw")),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_game")),
    )
    op.create_table(
        "photo",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("ply", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("reader", sa.String(), nullable=True),
        sa.Column("model_version", sa.String(), nullable=True),
        sa.Column("detections", postgresql.JSONB(), nullable=True),
        sa.Column("match", postgresql.JSONB(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["game.id"],
            name=op.f("fk_photo_game_id_game"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_photo")),
    )
    op.create_index(op.f("ix_photo_game_id"), "photo", ["game_id"])
    op.create_table(
        "move",
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("ply", sa.Integer(), nullable=False),
        sa.Column("move", postgresql.JSONB(), nullable=False),
        sa.Column(
            "source",
            text_enum(name="ck_move_source", values=("manual", "photo", "agent")),
            nullable=False,
        ),
        sa.Column("photo_id", sa.Uuid(), nullable=True),
        sa.Column("decision", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["game.id"],
            name=op.f("fk_move_game_id_game"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["photo_id"],
            ["photo.id"],
            name=op.f("fk_move_photo_id_photo"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("game_id", "ply", name=op.f("pk_move")),
    )


def downgrade() -> None:
    """Revert the migration."""
    op.drop_table("move")
    op.drop_index(op.f("ix_photo_game_id"), table_name="photo")
    op.drop_table("photo")
    op.drop_table("game")
