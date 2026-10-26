import json
import uuid

import pytest
from fastapi import Request, status

from hive.api.errors import (
    ErrorResponse,
    GameNotFoundError,
    PlyConflictError,
    PlyOutOfRangeError,
    error_responses,
    handle_api_error,
)

pytestmark = pytest.mark.anyio


async def test_handler_builds_error_response() -> None:
    game_id = uuid.uuid4()
    response = await handle_api_error(
        request=Request({"type": "http"}), error=GameNotFoundError(game_id)
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert json.loads(bytes(response.body)) == {
        "code": "game_not_found",
        "detail": f"Game `{game_id}` not found.",
    }


async def test_handler_rejects_other_errors() -> None:
    with pytest.raises(TypeError):
        await handle_api_error(request=Request({"type": "http"}), error=ValueError())


def test_error_responses_share_status_codes() -> None:
    responses = error_responses(GameNotFoundError, PlyConflictError, PlyOutOfRangeError)

    assert responses[status.HTTP_404_NOT_FOUND] == {
        "model": ErrorResponse,
        "description": "Game not found.",
    }
    assert responses[status.HTTP_409_CONFLICT]["description"] == (
        "The game is not at the expected ply."
    )
    assert responses[status.HTTP_422_UNPROCESSABLE_CONTENT]["description"] == (
        "The ply is past the last move. Or the request is not valid."
    )
