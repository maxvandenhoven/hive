"""The game service: creating, finding, changing, playing and deleting stored games.

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

from hive.api.db.models import (
    GameResult,
    GameRow,
    GameStatus,
    MoveRow,
    MoveSource,
    PhotoRow,
    utc_now,
)
from hive.api.errors import (
    AgentTurnError,
    CoordinateEmptyError,
    GameNotActiveError,
    GameNotFoundError,
    MoveNotLegalError,
    MovePendingError,
    NoMoveToUndoError,
    NoPendingMoveError,
    PhotoNotFoundError,
    PieceNotMovableError,
    PlyConflictError,
    PlyOutOfRangeError,
    SetupNotSupportedError,
)
from hive.api.players import AgentPlayer, BoardLocation
from hive.api.schemas import (
    GameCreate,
    GamePosition,
    GameUpdate,
    MoveConfirm,
    MoveCreate,
    PieceTargets,
)
from hive.api.storage import ObjectStore
from hive.engine.errors import IllegalMoveError
from hive.engine.grid import Coordinate
from hive.engine.state import GameState, Move
from hive.match.records import DecisionRecord

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
            board_location=body.location,
            moves=[],
            photos=[],
        )
        self.session.add(game)
        await self.commit(game)
        logger.info("Created game `%s`.", game.id, extra={"game_id": str(game.id)})

        return game

    async def commit(self, game: GameRow) -> None:
        """Commit the changes of the session and reload what SQL derives from the moves.

        Args:
            game: The changed game.
        """
        await self.session.commit()
        # Writes expire the column properties, which async sessions cannot load lazily.
        await self.session.refresh(game, attribute_names=["ply_count", "pending_move"])

    async def get_game(self, game_id: uuid.UUID, *, lock: bool = False) -> GameRow:
        """Load a game with its moves.

        Args:
            game_id: The game ID.
            lock: Whether to lock the game row until the next commit or rollback, so
                writes to the game, such as playing and undoing moves, run one at a time.

        Returns:
            The game.

        Raises:
            GameNotFoundError: If there is no game with the ID.
        """
        game = await self.session.get(
            GameRow, game_id, options=[selectinload(GameRow.moves)], with_for_update=lock
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
        """Rename a game, change its status or move it between the screen and the table.

        A pending move is confirmed when the game moves to the screen, where agent moves
        apply at once.

        Args:
            game_id: The game ID.
            body: The changes; fields left out are unchanged.

        Returns:
            The changed game with its moves.

        Raises:
            GameNotFoundError: If there is no game with the ID.
            SetupNotSupportedError: If the players cannot play at the new board location.
        """
        game = await self.get_game(game_id, lock=True)

        if body.board_location is not None:
            error = body.board_location.setup_error(
                white=game.white_player, black=game.black_player
            )

            if error is not None:
                raise SetupNotSupportedError(error)

            if body.board_location is BoardLocation.SCREEN and game.moves:
                game.moves[-1].pending = False

        for name, value in body.model_dump(exclude_none=True).items():
            setattr(game, name, value)

        await self.commit(game)

        return game

    async def get_position(self, game_id: uuid.UUID, ply: int | None) -> GamePosition:
        """Replay a game to one of its positions.

        Args:
            game_id: The game ID.
            ply: The number of moves to replay, or `None` for the latest position.

        Returns:
            The position after the moves.

        Raises:
            GameNotFoundError: If there is no game with the ID.
            PlyOutOfRangeError: If the ply is past the last move.
        """
        game = await self.get_game(game_id)
        ply_count = len(game.moves)

        if ply is None:
            ply = ply_count
        elif ply > ply_count:
            raise PlyOutOfRangeError(ply=ply, ply_count=ply_count)

        return GamePosition.from_state(game=game, state=game.replay(ply), ply=ply)

    async def get_targets(self, game_id: uuid.UUID, coord: Coordinate) -> PieceTargets:
        """Get the legal targets of a piece in the latest position of a game.

        Args:
            game_id: The game ID.
            coord: The coordinate of the piece, which is the top piece of its stack.

        Returns:
            The piece with the coordinates it may move to.

        Raises:
            GameNotFoundError: If there is no game with the ID.
            CoordinateEmptyError: If there is no piece at the coordinate.
            PieceNotMovableError: If the piece cannot move, for example because it belongs
                to the other side or the game is over.
        """
        game = await self.get_game(game_id)
        state = game.replay()

        if not state.is_occupied(coord):
            raise CoordinateEmptyError(coord)

        if game.rules.is_finished(state):
            reason = "the game is over"
        else:
            reason = game.rules.immobility_reason(state=state, coord=coord)

        if reason is not None:
            raise PieceNotMovableError(coord=coord, reason=reason)

        return PieceTargets(
            coord=coord,
            piece=state.get_top_piece(coord).type,
            targets=sorted(game.rules.target_coords(state=state, coord=coord)),
        )

    async def play_move(self, game_id: uuid.UUID, body: MoveCreate) -> GamePosition:
        """Play a move entered by hand or read from a photo.

        Args:
            game_id: The game ID.
            body: The move, how it was entered and the ply the client expects.

        Returns:
            The position after the move.

        Raises:
            GameNotFoundError: If there is no game with the ID.
            PlyConflictError: If the game is not at the expected ply.
            GameNotActiveError: If the game is finished or abandoned.
            MovePendingError: If the last move waits to be made on the board.
            AgentTurnError: If an agent plays the side to move and the request does not
                allow entering its move.
            PhotoNotFoundError: If the photo is not a photo of the game.
            MoveNotLegalError: If the move is not legal.
        """
        game = await self.get_game(game_id, lock=True)
        state = game.replay()

        if body.expected_ply != len(game.moves):
            raise PlyConflictError(
                expected_ply=body.expected_ply, ply_count=len(game.moves)
            )

        self.check_active(game=game, state=state)
        self.check_no_pending_move(game)
        side = state.current_player

        if isinstance(game.player(side), AgentPlayer) and not body.allow_agent_side:
            raise AgentTurnError(side)

        if body.photo_id is not None:
            photo = await self.session.get(PhotoRow, body.photo_id)

            if photo is None or photo.game_id != game.id:
                raise PhotoNotFoundError(body.photo_id)

            photo.confirmed = True

        return await self.append_move(
            game=game,
            state=state,
            move=body.move,
            source=body.source,
            photo_id=body.photo_id,
        )

    def check_no_pending_move(self, game: GameRow) -> None:
        """Check that the last move of a game does not wait to be made on the board.

        Args:
            game: The game, with its moves loaded.

        Raises:
            MovePendingError: If the last move is pending.
        """
        if game.moves and game.moves[-1].pending:
            raise MovePendingError(game_id=game.id, ply=game.moves[-1].ply)

    def check_active(self, game: GameRow, state: GameState) -> None:
        """Check that moves can be played in a game.

        Args:
            game: The game.
            state: The latest state of the game.

        Raises:
            GameNotActiveError: If the game is finished or abandoned, by its status or
                by its latest state.
        """
        if game.status is not GameStatus.ACTIVE:
            raise GameNotActiveError(game_id=game.id, status=game.status)

        if game.rules.is_finished(state):
            raise GameNotActiveError(game_id=game.id, status=GameStatus.FINISHED)

    async def append_move(
        self,
        game: GameRow,
        state: GameState,
        move: Move | None,
        source: MoveSource,
        photo_id: uuid.UUID | None = None,
        decision: DecisionRecord | None = None,
        pending: bool = False,
    ) -> GamePosition:
        """Check, store and commit a move, finishing the game if the move ends it.

        This is where every way of entering a move ends, including agent decisions.

        Args:
            game: The game, loaded with `lock` and its moves.
            state: The latest state of the game, which the move is applied to.
            move: The move, or `None` for a pass.
            source: How the move was entered.
            photo_id: The photo the move was read from, or `None`.
            decision: The decision behind an agent move, or `None`.
            pending: Whether the move waits for a person to make it on the board.

        Returns:
            The position after the move.

        Raises:
            GameNotActiveError: If the game is finished or abandoned.
            MovePendingError: If the last move waits to be made on the board.
            MoveNotLegalError: If the move is not legal.
        """
        self.check_active(game=game, state=state)
        self.check_no_pending_move(game)

        try:
            game.rules.apply_checked_move(state=state, move=move)
        except IllegalMoveError as e:
            raise MoveNotLegalError(str(e)) from e

        game.moves.append(
            MoveRow(
                ply=len(game.moves),
                move=move,
                source=source,
                photo_id=photo_id,
                decision=decision,
                pending=pending,
            )
        )
        result = GameResult.from_winners(game.rules.winners(state))

        if result is not None:
            game.status = GameStatus.FINISHED
            game.result = result

        game.updated_at = utc_now()
        await self.commit(game)
        logger.info(
            "Played `%s` in game `%s` at ply %d.",
            "pass" if move is None else move,
            game.id,
            len(game.moves) - 1,
            extra={"game_id": str(game.id)},
        )

        return GamePosition.from_state(game=game, state=state, ply=len(game.moves))

    async def commit_decision(
        self, game_id: uuid.UUID, ply: int, decision: DecisionRecord
    ) -> GamePosition:
        """Play the move an agent decided, storing its decision with it.

        In a `table` game the move is pending until a person confirms making it on the
        board.

        Args:
            game_id: The game ID.
            ply: The ply the agent decided at, which the game must still be at.
            decision: The decision of the agent playing the side to move.

        Returns:
            The position after the move.

        Raises:
            GameNotFoundError: If there is no game with the ID.
            PlyConflictError: If another move was played or undone meanwhile.
            GameNotActiveError: If the game was finished or abandoned meanwhile.
            MovePendingError: If the last move waits to be made on the board.
            MoveNotLegalError: If the move is not legal, which a decision never is.
        """
        game = await self.get_game(game_id, lock=True)

        if ply != len(game.moves):
            raise PlyConflictError(expected_ply=ply, ply_count=len(game.moves))

        return await self.append_move(
            game=game,
            state=game.replay(),
            move=decision.move,
            source=MoveSource.AGENT,
            decision=decision,
            pending=game.board_location is BoardLocation.TABLE,
        )

    async def confirm_move(self, game_id: uuid.UUID, body: MoveConfirm) -> GamePosition:
        """Confirm that the pending last move of a game was made on the physical board.

        Args:
            game_id: The game ID.
            body: The ply the client expects the game at.

        Returns:
            The latest position, without a pending move.

        Raises:
            GameNotFoundError: If there is no game with the ID.
            PlyConflictError: If the game is not at the expected ply.
            NoPendingMoveError: If the last move is not pending.
        """
        game = await self.get_game(game_id, lock=True)

        if body.expected_ply != len(game.moves):
            raise PlyConflictError(
                expected_ply=body.expected_ply, ply_count=len(game.moves)
            )

        if not game.moves or not game.moves[-1].pending:
            raise NoPendingMoveError(game_id)

        game.moves[-1].pending = False
        game.updated_at = utc_now()
        await self.commit(game)
        logger.info(
            "Confirmed ply %d of game `%s` on the board.",
            len(game.moves) - 1,
            game.id,
            extra={"game_id": str(game.id)},
        )

        return GamePosition.from_state(
            game=game, state=game.replay(), ply=len(game.moves)
        )

    async def undo_move(
        self, game_id: uuid.UUID, expected_ply: int | None
    ) -> GamePosition:
        """Undo the last move of a game, reopening it if the move finished it.

        Args:
            game_id: The game ID.
            expected_ply: The ply the client expects the game at, or `None` to undo
                whatever move is last.

        Returns:
            The position after undoing the move.

        Raises:
            GameNotFoundError: If there is no game with the ID.
            PlyConflictError: If the game is not at the expected ply.
            NoMoveToUndoError: If the game has no moves.
        """
        game = await self.get_game(game_id, lock=True)

        if expected_ply is not None and expected_ply != len(game.moves):
            raise PlyConflictError(expected_ply=expected_ply, ply_count=len(game.moves))

        if not game.moves:
            raise NoMoveToUndoError(game_id)

        move = game.moves.pop()

        # The photo of the move no longer proposed a committed move.
        if move.photo_id is not None:
            photo = await self.session.get(PhotoRow, move.photo_id)

            if photo is not None:
                photo.confirmed = False

        if game.status is GameStatus.FINISHED:
            game.status = GameStatus.ACTIVE
            game.result = None

        game.updated_at = utc_now()
        await self.commit(game)
        logger.info(
            "Undid ply %d of game `%s`.",
            move.ply,
            game.id,
            extra={"game_id": str(game.id)},
        )

        return GamePosition.from_state(
            game=game, state=game.replay(), ply=len(game.moves)
        )

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
