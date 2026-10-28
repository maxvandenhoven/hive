"""Routes that create, list, change, delete, export and play games."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from fastapi.sse import EventSourceResponse

from hive.api.db.models import GameStatus
from hive.api.dependencies import (
    GameServiceDependency,
    SessionFactoryDependency,
    StoreDependency,
    ThinkingDependency,
)
from hive.api.errors import (
    GAME_NOT_FOUND_RESPONSES,
    AgentRequiredError,
    AgentTurnError,
    AgentUnavailableError,
    CommitNotAllowedError,
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
    PoolBusyError,
    SetupNotSupportedError,
    error_responses,
)
from hive.api.routes import API_PREFIX
from hive.api.schemas import (
    GAME_PAGE_MAX_LIMIT,
    GameCreate,
    GameDetail,
    GamePage,
    GamePosition,
    GameSummary,
    GameUpdate,
    MoveConfirm,
    MoveCreate,
    PieceTargets,
    ThinkEvent,
)
from hive.engine.record import GameRecord

router = APIRouter(prefix=f"{API_PREFIX}/games", tags=["games"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    description="Create a game: human vs agent on the screen or at the table, human vs "
    "human with a hint agent on at least one side at the table, or agent vs agent on the "
    "screen.",
)
async def create_game(body: GameCreate, games: GameServiceDependency) -> GameDetail:
    """Create a game in one of the supported setups.

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
    description="Rename a game, change its status or move it between the screen and the "
    "table. Moving it to the screen confirms a pending move.",
    responses=error_responses(GameNotFoundError, SetupNotSupportedError),
)
async def update_game(
    game_id: uuid.UUID, body: GameUpdate, games: GameServiceDependency
) -> GameDetail:
    """Rename a game, change its status or move it between the screen and the table.

    Args:
        game_id: The game ID.
        body: The changes; fields left out are unchanged.
        games: The game service.

    Returns:
        The changed game.

    Raises:
        GameNotFoundError: If there is no game with the ID.
        SetupNotSupportedError: If the players cannot play at the new board location.
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


@router.get(
    "/{game_id}/state",
    description="Get the position of a game at a ply, with what the side to move may "
    "play. Without `ply`, the latest position.",
    responses=error_responses(GameNotFoundError, PlyOutOfRangeError),
)
async def read_game_state(
    game_id: uuid.UUID,
    games: GameServiceDependency,
    ply: Annotated[
        int | None,
        Query(ge=0, description="The number of moves to replay; the latest by default."),
    ] = None,
) -> GamePosition:
    """Get the position of a game at a ply, with what the side to move may play.

    Args:
        game_id: The game ID.
        games: The game service.
        ply: The number of moves to replay, or `None` for the latest position.

    Returns:
        The position.

    Raises:
        GameNotFoundError: If there is no game with the ID.
        PlyOutOfRangeError: If the ply is past the last move.
    """
    return await games.get_position(game_id=game_id, ply=ply)


@router.get(
    "/{game_id}/targets",
    description="Get the legal targets of the piece on top of the stack at `(q, r)` in "
    "the latest position.",
    responses=error_responses(
        GameNotFoundError, CoordinateEmptyError, PieceNotMovableError
    ),
)
async def read_piece_targets(
    game_id: uuid.UUID,
    games: GameServiceDependency,
    q: Annotated[int, Query(description="The column of the piece.")],
    r: Annotated[int, Query(description="The row of the piece.")],
) -> PieceTargets:
    """Get the legal targets of the piece on top of the stack at `(q, r)`.

    Args:
        game_id: The game ID.
        games: The game service.
        q: The axial column of the piece.
        r: The axial row of the piece.

    Returns:
        The piece with the coordinates it may move to.

    Raises:
        GameNotFoundError: If there is no game with the ID.
        CoordinateEmptyError: If there is no piece at the coordinate.
        PieceNotMovableError: If the piece cannot move.
    """
    return await games.get_targets(game_id=game_id, coord=(q, r))


@router.post(
    "/{game_id}/moves",
    status_code=status.HTTP_201_CREATED,
    description="Play a move entered by hand or read from a photo, at the expected ply. "
    "Moves for a side that an agent plays need `allow_agent_side`.",
    responses=error_responses(
        GameNotFoundError,
        PlyConflictError,
        GameNotActiveError,
        MovePendingError,
        AgentTurnError,
        PhotoNotFoundError,
        MoveNotLegalError,
    ),
)
async def play_move(
    game_id: uuid.UUID, body: MoveCreate, games: GameServiceDependency
) -> GamePosition:
    """Play a move entered by hand or read from a photo, at the expected ply.

    Args:
        game_id: The game ID.
        body: The move, how it was entered and the ply the client expects.
        games: The game service.

    Returns:
        The position after the move, whose `last_move` is the stored move.

    Raises:
        GameNotFoundError: If there is no game with the ID.
        PlyConflictError: If the game is not at the expected ply.
        GameNotActiveError: If the game is finished or abandoned.
        MovePendingError: If the last move waits to be made on the board.
        AgentTurnError: If an agent plays the side to move without `allow_agent_side`.
        PhotoNotFoundError: If the photo is not a photo of the game.
        MoveNotLegalError: If the move is not legal.
    """
    return await games.play_move(game_id=game_id, body=body)


@router.delete(
    "/{game_id}/moves/last",
    description="Undo the last move, reopening the game if the move finished it.",
    responses=error_responses(GameNotFoundError, PlyConflictError, NoMoveToUndoError),
)
async def undo_move(
    game_id: uuid.UUID,
    games: GameServiceDependency,
    expected_ply: Annotated[
        int | None,
        Query(
            ge=0,
            description="The ply the client expects the game at; the move is only "
            "undone if it is.",
        ),
    ] = None,
) -> GamePosition:
    """Undo the last move, reopening the game if the move finished it.

    Args:
        game_id: The game ID.
        games: The game service.
        expected_ply: The ply the client expects the game at, or `None` to undo
            whatever move is last.

    Returns:
        The position after undoing the move.

    Raises:
        GameNotFoundError: If there is no game with the ID.
        PlyConflictError: If the game is not at the expected ply.
        NoMoveToUndoError: If the game has no moves.
    """
    return await games.undo_move(game_id=game_id, expected_ply=expected_ply)


@router.post(
    "/{game_id}/moves/last/confirm",
    description="Confirm that the pending agent move, the last move of a game at the "
    "table, was made on the physical board, so the game can go on.",
    responses=error_responses(GameNotFoundError, PlyConflictError, NoPendingMoveError),
)
async def confirm_move(
    game_id: uuid.UUID, body: MoveConfirm, games: GameServiceDependency
) -> GamePosition:
    """Confirm that the pending last move of a game was made on the physical board.

    Args:
        game_id: The game ID.
        body: The ply the client expects the game at.
        games: The game service.

    Returns:
        The latest position, without a pending move.

    Raises:
        GameNotFoundError: If there is no game with the ID.
        PlyConflictError: If the game is not at the expected ply.
        NoPendingMoveError: If the last move is not pending.
    """
    return await games.confirm_move(game_id=game_id, body=body)


@router.post(
    "/{game_id}/think",
    response_class=EventSourceResponse,
    description="Let an agent think about the latest position within a time budget, "
    "streaming `info` and `candidate` events and ending with the `decision`. Without "
    "`agent`, the agent or hint agent of the side to move thinks. With `commit`, the "
    "agent playing the side to move plays its decision in the game, pending at the "
    "table until it is confirmed. "
    "Failures after the stream started end it with an `error` event. Closing the "
    "stream stops the agent.",
    responses=error_responses(
        GameNotFoundError,
        GameNotActiveError,
        CommitNotAllowedError,
        MovePendingError,
        AgentRequiredError,
        PoolBusyError,
        AgentUnavailableError,
    ),
)
async def think(
    game_id: uuid.UUID,
    thinking: ThinkingDependency,
    session_factory: SessionFactoryDependency,
    store: StoreDependency,
) -> AsyncIterator[ThinkEvent]:
    """Let an agent think about the latest position, streaming its search.

    The request body is read by the thinking dependency, which checks it and starts the
    decision before the stream starts.

    Args:
        game_id: The game ID, also read by the thinking dependency.
        thinking: The running decision.
        session_factory: Opens the session that commits the decision.
        store: The object store of the app.

    Yields:
        The events of the decision, as server-sent events.

    Raises:
        GameNotFoundError: If there is no game with the ID.
        GameNotActiveError: If the game is finished or abandoned.
        CommitNotAllowedError: If the request commits, but no agent plays the side to
            move or the request names another agent.
        MovePendingError: If the request commits while the last move waits to be made
            on the board.
        AgentRequiredError: If a person without a hint agent plays the side to move and
            no agent is named.
        PoolBusyError: If every agent worker stayed busy.
        AgentUnavailableError: If the worker of the agent failed to start.
    """
    async for event in thinking.events(session_factory=session_factory, store=store):
        yield event
