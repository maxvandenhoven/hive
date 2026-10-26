"""Routes that create, list, change, delete and export games."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from hive.api.db.models import GameStatus
from hive.api.dependencies import GameServiceDependency
from hive.api.errors import GAME_NOT_FOUND_RESPONSES
from hive.api.routes import API_PREFIX
from hive.api.schemas import (
    GAME_PAGE_MAX_LIMIT,
    GameCreate,
    GameDetail,
    GamePage,
    GameSummary,
    GameUpdate,
)
from hive.engine.record import GameRecord

router = APIRouter(prefix=f"{API_PREFIX}/games", tags=["games"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    description="Create a game. At least one side must be an agent.",
)
async def create_game(body: GameCreate, games: GameServiceDependency) -> GameDetail:
    """Create a game. At least one side must be an agent.

    Args:
        body: The name, players, rules and setup of the game, already validated.
        games: The game service.

    Returns:
        The new game, active and without moves.
    """
    return GameDetail.model_validate(await games.create_game(body))


@router.get("", description="List games, newest first.")
async def list_games(
    games: GameServiceDependency,
    game_status: Annotated[
        GameStatus | None,
        Query(alias="status", description="Only games with this status."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=GAME_PAGE_MAX_LIMIT)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> GamePage:
    """List games, newest first.

    Args:
        games: The game service.
        game_status: Only list games with this status, or `None` for every game.
        limit: The most games on the page.
        offset: The number of games to skip before the page.

    Returns:
        The page of games and the number of matching games on all pages.
    """
    rows, total = await games.list_games(status=game_status, limit=limit, offset=offset)

    return GamePage(
        items=[GameSummary.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{game_id}",
    description="Get a game with its rules, setup and moves.",
    responses=GAME_NOT_FOUND_RESPONSES,
)
async def read_game(game_id: uuid.UUID, games: GameServiceDependency) -> GameDetail:
    """Get a game with its rules, setup and moves.

    Args:
        game_id: The game ID.
        games: The game service.

    Returns:
        The game.

    Raises:
        GameNotFoundError: If there is no game with the ID.
    """
    return GameDetail.model_validate(await games.get_game(game_id))


@router.patch(
    "/{game_id}",
    description="Rename a game or change its status.",
    responses=GAME_NOT_FOUND_RESPONSES,
)
async def update_game(
    game_id: uuid.UUID, body: GameUpdate, games: GameServiceDependency
) -> GameDetail:
    """Rename a game or change its status.

    Args:
        game_id: The game ID.
        body: The changes; fields left out are unchanged.
        games: The game service.

    Returns:
        The changed game.

    Raises:
        GameNotFoundError: If there is no game with the ID.
    """
    return GameDetail.model_validate(await games.update_game(game_id=game_id, body=body))


@router.delete(
    "/{game_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description="Delete a game with its moves, its photos and their stored images.",
    responses=GAME_NOT_FOUND_RESPONSES,
)
async def delete_game(game_id: uuid.UUID, games: GameServiceDependency) -> None:
    """Delete a game with its moves, its photos and their stored images.

    Args:
        game_id: The game ID.
        games: The game service.

    Raises:
        GameNotFoundError: If there is no game with the ID.
    """
    await games.delete_game(game_id)


@router.get(
    "/{game_id}/export",
    description="Download the game as a serialized `GameRecord` with its rules, setup "
    "and moves.",
    responses=GAME_NOT_FOUND_RESPONSES,
)
async def export_game(
    game_id: uuid.UUID, games: GameServiceDependency, response: Response
) -> GameRecord:
    """Download the game as a serialized `GameRecord` with its rules, setup and moves.

    Args:
        game_id: The game ID.
        games: The game service.
        response: The response, which gets a `Content-Disposition` header.

    Returns:
        The serialized game record, as an attachment named `game-<id>.json`.

    Raises:
        GameNotFoundError: If there is no game with the ID.
    """
    record = (await games.get_game(game_id)).to_record()
    response.headers["Content-Disposition"] = (
        f'attachment; filename="game-{game_id}.json"'
    )

    return record
