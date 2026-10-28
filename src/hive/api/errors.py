"""Errors of the API that map to HTTP responses with a machine-readable code.

Services raise subclasses of `ApiError`; one exception handler turns them into an
`ErrorResponse` body with the status code of the error. Routes list the errors they may
return in their `responses`, so the generated client knows their shape.
"""

import uuid
from enum import StrEnum
from typing import Any, ClassVar

from fastapi import Request, status
from fastapi.openapi.constants import REF_PREFIX
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from hive.api.db.models import GameStatus
from hive.engine.grid import Coordinate
from hive.engine.state import Player


class ApiErrorCode(StrEnum):
    """The machine-readable code of an error response."""

    GAME_NOT_FOUND = "game_not_found"
    GAME_NOT_ACTIVE = "game_not_active"
    PLY_OUT_OF_RANGE = "ply_out_of_range"
    PLY_CONFLICT = "ply_conflict"
    MOVE_NOT_LEGAL = "move_not_legal"
    AGENT_TURN = "agent_turn"
    PHOTO_NOT_FOUND = "photo_not_found"
    COORDINATE_EMPTY = "coordinate_empty"
    PIECE_NOT_MOVABLE = "piece_not_movable"
    NO_MOVE_TO_UNDO = "no_move_to_undo"
    AGENT_REQUIRED = "agent_required"
    COMMIT_NOT_ALLOWED = "commit_not_allowed"
    POOL_BUSY = "pool_busy"
    AGENT_UNAVAILABLE = "agent_unavailable"
    MOVE_PENDING = "move_pending"
    NO_PENDING_MOVE = "no_pending_move"
    SETUP_NOT_SUPPORTED = "setup_not_supported"


class ErrorResponse(BaseModel):
    """The body of an error response.

    Attributes:
        code: What went wrong, for clients to branch on.
        detail: A human-readable description.
    """

    code: ApiErrorCode
    detail: str


class ApiError(Exception):
    """An error that is returned to the client with a status code and an error code.

    Attributes:
        status_code: The HTTP status code of the response.
        code: The error code in the response body.
        description: When the error is returned, for the OpenAPI schema.
        detail: A human-readable description, also the exception message.
    """

    status_code: ClassVar[int] = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: ClassVar[ApiErrorCode]
    description: ClassVar[str]

    def __init__(self, detail: str) -> None:
        """Create the error.

        Args:
            detail: A human-readable description.
        """
        super().__init__(detail)
        self.detail = detail


class GameNotFoundError(ApiError):
    """There is no game with the ID.

    Attributes:
        game_id: The game ID that was not found.
    """

    status_code = status.HTTP_404_NOT_FOUND
    code = ApiErrorCode.GAME_NOT_FOUND
    description = "Game not found."

    def __init__(self, game_id: uuid.UUID) -> None:
        """Create the error.

        Args:
            game_id: The game ID that was not found.
        """
        super().__init__(f"Game `{game_id}` not found.")
        self.game_id = game_id


class GameNotActiveError(ApiError):
    """The game is finished or abandoned, so no more moves can be played.

    Attributes:
        game_id: The game ID.
        status: The status of the game.
    """

    status_code = status.HTTP_409_CONFLICT
    code = ApiErrorCode.GAME_NOT_ACTIVE
    description = "The game is finished or abandoned."

    def __init__(self, game_id: uuid.UUID, status: GameStatus) -> None:
        """Create the error.

        Args:
            game_id: The game ID.
            status: The status of the game.
        """
        super().__init__(f"Game `{game_id}` is {status}; no more moves can be played.")
        self.game_id = game_id
        self.status = status


class PlyOutOfRangeError(ApiError):
    """The requested ply is past the last move of the game.

    Attributes:
        ply: The requested ply.
        ply_count: The number of moves played.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = ApiErrorCode.PLY_OUT_OF_RANGE
    description = "The ply is past the last move."

    def __init__(self, ply: int, ply_count: int) -> None:
        """Create the error.

        Args:
            ply: The requested ply.
            ply_count: The number of moves played.
        """
        super().__init__(f"Ply `{ply}` is past the last move; the game has {ply_count}.")
        self.ply = ply
        self.ply_count = ply_count


class PlyConflictError(ApiError):
    """The game is not at the ply the client expected, so another move came first.

    Attributes:
        expected_ply: The ply the client expected.
        ply_count: The number of moves played, the actual ply.
    """

    status_code = status.HTTP_409_CONFLICT
    code = ApiErrorCode.PLY_CONFLICT
    description = "The game is not at the expected ply."

    def __init__(self, expected_ply: int, ply_count: int) -> None:
        """Create the error.

        Args:
            expected_ply: The ply the client expected.
            ply_count: The number of moves played, the actual ply.
        """
        super().__init__(
            f"Expected the game at ply `{expected_ply}`, but it is at ply `{ply_count}`."
        )
        self.expected_ply = expected_ply
        self.ply_count = ply_count


class MoveNotLegalError(ApiError):
    """The move is not legal in the current position."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = ApiErrorCode.MOVE_NOT_LEGAL
    description = "The move is not legal."


class AgentTurnError(ApiError):
    """A move was entered by hand for a side that an agent plays.

    Attributes:
        side: The side to move.
    """

    status_code = status.HTTP_409_CONFLICT
    code = ApiErrorCode.AGENT_TURN
    description = "An agent plays the side to move."

    def __init__(self, side: Player) -> None:
        """Create the error.

        Args:
            side: The side to move.
        """
        super().__init__(
            f"An agent plays `{side.name.lower()}`; its moves are committed by the "
            "agent unless `allow_agent_side` is set."
        )
        self.side = side


class PhotoNotFoundError(ApiError):
    """The photo of a move does not exist or belongs to another game.

    Attributes:
        photo_id: The photo ID.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = ApiErrorCode.PHOTO_NOT_FOUND
    description = "The photo is not a photo of the game."

    def __init__(self, photo_id: uuid.UUID) -> None:
        """Create the error.

        Args:
            photo_id: The photo ID.
        """
        super().__init__(f"Photo `{photo_id}` is not a photo of the game.")
        self.photo_id = photo_id


class CoordinateEmptyError(ApiError):
    """There is no piece at the coordinate.

    Attributes:
        coord: The coordinate.
    """

    status_code = status.HTTP_404_NOT_FOUND
    code = ApiErrorCode.COORDINATE_EMPTY
    description = "There is no piece at the coordinate."

    def __init__(self, coord: Coordinate) -> None:
        """Create the error.

        Args:
            coord: The coordinate.
        """
        super().__init__(f"There is no piece at `{coord}`.")
        self.coord = coord


class PieceNotMovableError(ApiError):
    """The piece at the coordinate cannot move now.

    Attributes:
        coord: The coordinate of the piece.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = ApiErrorCode.PIECE_NOT_MOVABLE
    description = "The piece cannot move."

    def __init__(self, coord: Coordinate, reason: str) -> None:
        """Create the error.

        Args:
            coord: The coordinate of the piece.
            reason: Why the piece cannot move, starting in lower case.
        """
        super().__init__(f"The piece at `{coord}` cannot move: {reason}.")
        self.coord = coord


class NoMoveToUndoError(ApiError):
    """The game has no moves, so there is nothing to undo.

    Attributes:
        game_id: The game ID.
    """

    status_code = status.HTTP_409_CONFLICT
    code = ApiErrorCode.NO_MOVE_TO_UNDO
    description = "The game has no moves to undo."

    def __init__(self, game_id: uuid.UUID) -> None:
        """Create the error.

        Args:
            game_id: The game ID.
        """
        super().__init__(f"Game `{game_id}` has no moves to undo.")
        self.game_id = game_id


class AgentRequiredError(ApiError):
    """A person plays the side to move, so the request has to name an agent to think.

    Attributes:
        side: The side to move.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = ApiErrorCode.AGENT_REQUIRED
    description = "A person plays the side to move and no agent was given."

    def __init__(self, side: Player) -> None:
        """Create the error.

        Args:
            side: The side to move.
        """
        super().__init__(
            f"A person plays `{side.name.lower()}`; name the `agent` that should think."
        )
        self.side = side


class CommitNotAllowedError(ApiError):
    """A decision may only be committed by the agent that plays the side to move."""

    status_code = status.HTTP_409_CONFLICT
    code = ApiErrorCode.COMMIT_NOT_ALLOWED
    description = "Only the agent of the side to move may commit its decision."


class PoolBusyError(ApiError):
    """Every agent worker stayed busy for as long as a request may wait for one.

    Attributes:
        wait_s: The seconds the request waited.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = ApiErrorCode.POOL_BUSY
    description = "Every agent worker is busy."

    def __init__(self, wait_s: float) -> None:
        """Create the error.

        Args:
            wait_s: The seconds the request waited.
        """
        super().__init__(f"Every agent worker stayed busy for {wait_s} s; try again.")
        self.wait_s = wait_s


class AgentUnavailableError(ApiError):
    """The worker process of an agent failed to start."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = ApiErrorCode.AGENT_UNAVAILABLE
    description = "The agent failed to start."


class MovePendingError(ApiError):
    """The last move waits for a person to make it on the physical board.

    Attributes:
        game_id: The game ID.
        ply: The ply of the pending move.
    """

    status_code = status.HTTP_409_CONFLICT
    code = ApiErrorCode.MOVE_PENDING
    description = "The last move waits to be confirmed on the board."

    def __init__(self, game_id: uuid.UUID, ply: int) -> None:
        """Create the error.

        Args:
            game_id: The game ID.
            ply: The ply of the pending move.
        """
        super().__init__(
            f"The agent move at ply `{ply}` of game `{game_id}` waits to be made on the "
            "board; confirm or undo it first."
        )
        self.game_id = game_id
        self.ply = ply


class NoPendingMoveError(ApiError):
    """The last move of the game does not wait for confirmation.

    Attributes:
        game_id: The game ID.
    """

    status_code = status.HTTP_409_CONFLICT
    code = ApiErrorCode.NO_PENDING_MOVE
    description = "The last move does not wait to be confirmed."

    def __init__(self, game_id: uuid.UUID) -> None:
        """Create the error.

        Args:
            game_id: The game ID.
        """
        super().__init__(f"The last move of game `{game_id}` is not pending.")
        self.game_id = game_id


class SetupNotSupportedError(ApiError):
    """The players and the board location of a game are not a supported setup."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = ApiErrorCode.SETUP_NOT_SUPPORTED
    description = "The players and the board location are not a supported setup."


def error_responses(*error_types: type[ApiError]) -> dict[int | str, dict[str, Any]]:
    """Describe the error responses of a route, for its `responses`.

    Errors with the same status code share one response. A 422 response is also what
    FastAPI returns for an invalid request, so its schema allows both bodies.

    Args:
        error_types: The errors the route may return.

    Returns:
        One response per status code, with the descriptions of its errors.
    """
    descriptions: dict[int, list[str]] = {}

    for error_type in error_types:
        descriptions.setdefault(error_type.status_code, []).append(error_type.description)

    responses: dict[int | str, dict[str, Any]] = {}

    for status_code, texts in descriptions.items():
        if status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
            schemas = [
                {"$ref": f"{REF_PREFIX}{ErrorResponse.__name__}"},
                {"$ref": f"{REF_PREFIX}HTTPValidationError"},
            ]
            responses[status_code] = {
                "description": " ".join([*texts, "Or the request is not valid."]),
                "content": {"application/json": {"schema": {"anyOf": schemas}}},
            }
        else:
            responses[status_code] = {
                "model": ErrorResponse,
                "description": " ".join(texts),
            }

    return responses


GAME_NOT_FOUND_RESPONSES = error_responses(GameNotFoundError)
"""The error responses of every route on one game, for its `responses`."""


async def handle_api_error(request: Request, error: Exception) -> JSONResponse:
    """Turn an `ApiError` raised while handling a request into its response.

    Args:
        request: The request being handled.
        error: The error, always an `ApiError` since the handler is registered for it.

    Returns:
        An `ErrorResponse` body with the status code of the error.

    Raises:
        TypeError: If the error is not an `ApiError`.
    """
    if not isinstance(error, ApiError):
        raise TypeError(error)

    body = ErrorResponse(code=error.code, detail=error.detail)

    return JSONResponse(status_code=error.status_code, content=body.model_dump())
