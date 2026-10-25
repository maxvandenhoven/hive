"""Routes that create, list, change, delete and export games."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from hive.api.db.models import GameRow, GameStatus
from hive.api.dependencies import SessionDependency, StoreDependency
from hive.api.schemas import (
    GAME_PAGE_MAX_LIMIT,
    GameCreate,
    GameDetail,
    GamePage,
    GameSummary,
    GameUpdate,
)
from hive.engine.serialization import serialize_record

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/games", tags=["games"])


def get_game(session: Session, game_id: uuid.UUID) -> GameRow:
    """Load a game with its moves.

    Args:
        session: The database session.
        game_id: The game ID.

    Returns:
        The game.

    Raises:
        HTTPException: With status 404 if there is no game with the ID.
    """
    game = session.get(GameRow, game_id, options=[selectinload(GameRow.moves)])

    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Game `{game_id}` not found."
        )

    return game


@router.post("", status_code=status.HTTP_201_CREATED)
def create_game(body: GameCreate, session: SessionDependency) -> GameDetail:
    """Create a game. At least one side must be an agent."""
    game = body.to_row()
    session.add(game)
    session.commit()
    logger.info("Created game `%s`.", game.id, extra={"game_id": str(game.id)})

    return GameDetail.from_row(get_game(session=session, game_id=game.id))


@router.get("")
def list_games(
    session: SessionDependency,
    game_status: Annotated[
        GameStatus | None,
        Query(alias="status", description="Only games with this status."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=GAME_PAGE_MAX_LIMIT)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> GamePage:
    """List games, newest first."""
    query = select(GameRow)

    if game_status is not None:
        query = query.where(GameRow.status == game_status)

    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    games = session.scalars(
        query.options(selectinload(GameRow.moves))
        .order_by(GameRow.created_at.desc(), GameRow.id)
        .limit(limit)
        .offset(offset)
    )

    return GamePage(
        items=[GameSummary.from_row(game) for game in games],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{game_id}")
def read_game(game_id: uuid.UUID, session: SessionDependency) -> GameDetail:
    """Get a game with its rules, setup and moves."""
    return GameDetail.from_row(get_game(session=session, game_id=game_id))


@router.patch("/{game_id}")
def update_game(
    game_id: uuid.UUID, body: GameUpdate, session: SessionDependency
) -> GameDetail:
    """Rename a game or change its status."""
    game = get_game(session=session, game_id=game_id)
    body.apply(game)
    session.commit()

    return GameDetail.from_row(game)


@router.delete("/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_game(
    game_id: uuid.UUID, session: SessionDependency, store: StoreDependency
) -> Response:
    """Delete a game with its moves, its photos and their stored images."""
    game = get_game(session=session, game_id=game_id)
    prefix = game.photo_prefix
    session.delete(game)
    session.commit()

    # The rows go first: images left behind by a failure here are harmless, while rows
    # pointing at deleted images are not.
    try:
        deleted = store.delete_prefix(prefix)
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

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{game_id}/export")
def export_game(game_id: uuid.UUID, session: SessionDependency) -> JSONResponse:
    """Download the game as a serialized `GameRecord` with its rules, setup and moves."""
    game = get_game(session=session, game_id=game_id)

    return JSONResponse(
        content=serialize_record(game.to_record()),
        headers={"Content-Disposition": f'attachment; filename="game-{game_id}.json"'},
    )
