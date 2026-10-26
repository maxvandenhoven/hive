import json
import uuid

import pytest
from fastapi import Request, status

from hive.api.errors import GameNotFoundError, handle_api_error

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
