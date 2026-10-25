"""Errors of the API that map to HTTP responses with a machine-readable code.

Services raise subclasses of `ApiError`; one exception handler turns them into an
`ErrorResponse` body with the status code of the error. Routes list the errors they may
return with `ApiError.openapi_responses`, so the generated client knows their shape.
"""

import uuid
from enum import StrEnum
from typing import Any, ClassVar

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ApiErrorCode(StrEnum):
    """The machine-readable code of an error response."""

    GAME_NOT_FOUND = "game_not_found"


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
        detail: A human-readable description, also the exception message.
    """

    status_code: ClassVar[int] = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: ClassVar[ApiErrorCode]

    def __init__(self, detail: str) -> None:
        """Create the error.

        Args:
            detail: A human-readable description.
        """
        super().__init__(detail)
        self.detail = detail

    def to_response(self) -> JSONResponse:
        """Build the HTTP response of the error.

        Returns:
            An `ErrorResponse` body with the status code of the error.
        """
        body = ErrorResponse(code=self.code, detail=self.detail)

        return JSONResponse(status_code=self.status_code, content=body.model_dump())

    @classmethod
    def openapi_responses(cls, *errors: type["ApiError"]) -> dict[int | str, Any]:
        """Describe the error responses of a route for its `responses` argument.

        Args:
            *errors: The errors the route may return.

        Returns:
            The `ErrorResponse` model under the status code of each error, with the
            possible error codes in the description.
        """
        responses: dict[int | str, Any] = {}

        for error in errors:
            response = responses.setdefault(
                error.status_code, {"model": ErrorResponse, "description": ""}
            )
            response["description"] += f"`{error.code}`: {error.__doc__}\n"

        return responses


class GameNotFoundError(ApiError):
    """There is no game with the ID.

    Attributes:
        game_id: The game ID that was not found.
    """

    status_code = status.HTTP_404_NOT_FOUND
    code = ApiErrorCode.GAME_NOT_FOUND

    def __init__(self, game_id: uuid.UUID) -> None:
        """Create the error.

        Args:
            game_id: The game ID that was not found.
        """
        super().__init__(f"Game `{game_id}` not found.")
        self.game_id = game_id


async def handle_api_error(request: Request, error: Exception) -> JSONResponse:
    """Turn an `ApiError` raised while handling a request into its response.

    Args:
        request: The request being handled.
        error: The error, always an `ApiError` since the handler is registered for it.

    Returns:
        The response of the error.

    Raises:
        TypeError: If the error is not an `ApiError`.
    """
    if not isinstance(error, ApiError):
        raise TypeError(error)

    return error.to_response()
