import json
import uuid

import pytest
from fastapi import Request, status

from hive.api.errors import ApiError, ErrorResponse, GameNotFoundError, handle_api_error


def test_to_response() -> None:
    game_id = uuid.uuid4()
    response = GameNotFoundError(game_id).to_response()

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert json.loads(bytes(response.body)) == {
        "code": "game_not_found",
        "detail": f"Game `{game_id}` not found.",
    }


def test_openapi_responses() -> None:
    responses = ApiError.openapi_responses(GameNotFoundError)

    assert list(responses) == [404]
    assert responses[404]["model"] is ErrorResponse
    assert "`game_not_found`" in responses[404]["description"]


@pytest.mark.anyio
async def test_handler_rejects_other_errors() -> None:
    with pytest.raises(TypeError):
        await handle_api_error(request=Request({"type": "http"}), error=ValueError())
