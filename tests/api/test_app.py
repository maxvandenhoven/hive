import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx2
import pytest
from fastapi import FastAPI

from hive.api.app import create_app
from hive.api.db.session import Database
from hive.api.settings import ApiSettings
from hive.api.storage import ObjectStore


def test_operation_ids_are_handler_names(settings: ApiSettings) -> None:
    operation_ids = [
        operation["operationId"]
        for path in create_app(settings).openapi()["paths"].values()
        for operation in path.values()
    ]

    assert sorted(operation_ids) == [
        "create_game",
        "delete_game",
        "export_game",
        "list_agent_kinds",
        "list_games",
        "read_game",
        "read_liveness",
        "read_readiness",
        "update_game",
    ]


def test_resources_are_under_api(settings: ApiSettings) -> None:
    paths = set(create_app(settings).openapi()["paths"])

    assert {"/healthz", "/readyz", "/api/agents", "/api/games"} <= paths
    assert all(path.startswith("/api/") for path in paths - {"/healthz", "/readyz"})


def test_error_responses_are_documented(settings: ApiSettings) -> None:
    schema = create_app(settings).openapi()
    read_game = schema["paths"]["/api/games/{game_id}"]["get"]
    readiness = schema["paths"]["/readyz"]["get"]

    assert read_game["responses"]["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert "503" in readiness["responses"]


@pytest.mark.anyio
async def test_serves_with_its_own_database(
    settings: ApiSettings,
    database: Database,
    store: ObjectStore,
    app_server: Callable[[FastAPI], AbstractAsyncContextManager[httpx2.AsyncClient]],
) -> None:
    own_settings = settings.model_copy(
        update={"database_url": database.engine.url.render_as_string(hide_password=False)}
    )
    app = create_app(own_settings, store=store)

    async with app_server(app) as client:
        response = await client.get(f"/api/games/{uuid.uuid4()}")
        own_database = app.state.database

    assert response.status_code == 404
    assert own_database is not database
