"""The game service: creating, finding, changing and deleting stored games.

Route handlers stay thin: they parse the request, call a `GameService` method and build
the response model. The service is also what background work such as committing an agent
move uses, so the same rules apply however a game is changed.
"""

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from hive.api.db.models import GameRow, GameStatus
from hive.api.errors import GameNotFoundError
from hive.api.schemas import GameCreate, GameUpdate
from hive.api.storage import ObjectStore

logger = logging.getLogger(__name__)


class GameService:
    """Reads and changes games in one database session.

    Every method that changes the database commits before it returns, so each call is
    one unit of work and holds no connection afterwards.

    Attributes:
        session: The database session.
        store: The object store holding the photo images.
    """

    def __init__(self, session: AsyncSession, store: ObjectStore) -> None:
        """Create the service.

        Args:
            session: The database session.
            store: The object store holding the photo images.
        """
        self.session = session
        self.store = store

    async def create_game(self, body: GameCreate) -> GameRow:
        """Create a game.

        Args:
            body: The validated name, players, rules and setup of the game.

        Returns:
            The new game, active and without moves.
        """
        game = GameRow(
            name=body.name,
            rules=body.rules,
            setup=body.setup,
            white_player=body.white,
            black_player=body.black,
            moves=[],
            photos=[],
        )
        self.session.add(game)
        await self.session.commit()
        # Writes expire the counted `ply_count`, which async sessions cannot load lazily.
        await self.session.refresh(game, attribute_names=["ply_count"])
        logger.info("Created game `%s`.", game.id, extra={"game_id": str(game.id)})

        return game

    async def get_game(self, game_id: uuid.UUID) -> GameRow:
        """Load a game with its moves.

        Args:
            game_id: The game ID.

        Returns:
            The game.

        Raises:
            GameNotFoundError: If there is no game with the ID.
        """
        game = await self.session.get(
            GameRow, game_id, options=[selectinload(GameRow.moves)]
        )

        if game is None:
            raise GameNotFoundError(game_id)

        return game

    async def list_games(
        self, status: GameStatus | None, limit: int, offset: int
    ) -> tuple[Sequence[GameRow], int]:
        """List games, newest first, without loading their moves.

        Args:
            status: Only list games with this status, or `None` for every game.
            limit: The most games to return.
            offset: The number of games to skip.

        Returns:
            The games, and the number of games matching the filter without the limit and
            offset.
        """
        query = select(GameRow)

        if status is not None:
            query = query.where(GameRow.status == status)

        total = await self.session.scalar(
            select(func.count()).select_from(query.subquery())
        )
        games = await self.session.scalars(
            query.order_by(GameRow.created_at.desc(), GameRow.id)
            .limit(limit)
            .offset(offset)
        )

        return games.all(), total or 0

    async def update_game(self, game_id: uuid.UUID, body: GameUpdate) -> GameRow:
        """Rename a game or change its status.

        Args:
            game_id: The game ID.
            body: The changes; fields left out are unchanged.

        Returns:
            The changed game with its moves.

        Raises:
            GameNotFoundError: If there is no game with the ID.
        """
        game = await self.get_game(game_id)

        for name, value in body.model_dump(exclude_none=True).items():
            setattr(game, name, value)

        await self.session.commit()
        await self.session.refresh(game, attribute_names=["ply_count"])

        return game

    async def delete_game(self, game_id: uuid.UUID) -> None:
        """Delete a game with its moves, its photos and their stored images.

        The images are deleted after the rows are committed. If that fails, the failure
        is logged and the game stays deleted.

        Args:
            game_id: The game ID.

        Raises:
            GameNotFoundError: If there is no game with the ID.
        """
        game = await self.session.get(GameRow, game_id)

        if game is None:
            raise GameNotFoundError(game_id)

        prefix = game.photo_prefix
        await self.session.delete(game)
        await self.session.commit()

        # The rows go first: images left behind by a failure here are harmless, while rows
        # pointing at deleted images are not.
        try:
            deleted = await self.store.delete_prefix(prefix)
        except Exception:
            logger.exception(
                "Deleted game `%s`, but not its photo objects.",
                game_id,
                extra={"game_id": str(game_id)},
            )
        else:
            logger.info(
                "Deleted game `%s` and %d photo objects.",
                game_id,
                deleted,
                extra={"game_id": str(game_id)},
            )
