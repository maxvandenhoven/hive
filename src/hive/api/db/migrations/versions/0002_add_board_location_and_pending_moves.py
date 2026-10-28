"""Add the board location of games and the pending flag of moves.

Existing agent vs agent games are played on the `screen`, every other game at the
`table`. No existing move is pending.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.add_column(
        "game",
        sa.Column(
            "board_location",
            sa.Enum(
                "screen",
                "table",
                name=op.f("ck_game_board_location"),
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE game
        SET board_location = CASE
            WHEN white_player ->> 'type' = 'agent' AND black_player ->> 'type' = 'agent'
            THEN 'screen'
            ELSE 'table'
        END
        """
    )
    op.alter_column("game", "board_location", nullable=False)
    op.add_column(
        "move",
        sa.Column("pending", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.alter_column("move", "pending", server_default=None)


def downgrade() -> None:
    """Revert the migration, dropping the hint agents the earlier schema cannot read."""
    op.execute(
        "UPDATE game SET white_player = white_player - 'hint', "
        "black_player = black_player - 'hint'"
    )
    op.drop_column("move", "pending")
    op.drop_column("game", "board_location")
