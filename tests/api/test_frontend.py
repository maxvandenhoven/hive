from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest

from hive.api.app import create_app
from hive.api.settings import ApiSettings

pytestmark = pytest.mark.anyio

INDEX_HTML = "<!doctype html><title>Hive</title>"


@pytest.fixture(scope="function")
def frontend_dir(tmp_path: Path) -> Path:
    """Write a built frontend with an index page and one asset."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX_HTML)
    (tmp_path / "assets" / "app.js").write_text("console.log('hive');")

    return tmp_path


@asynccontextmanager
async def open_client(
    settings: ApiSettings, frontend_dir: Path | None
) -> AsyncGenerator[httpx2.AsyncClient]:
    """Yield a client of an app serving the frontend files, without running the lifespan.

    Static files and unknown routes need neither the database nor the pool.
    """
    app = create_app(settings=settings.model_copy(update={"frontend_dir": frontend_dir}))
    transport = httpx2.ASGITransport(app=app)

    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture(scope="function")
async def client(
    settings: ApiSettings, frontend_dir: Path
) -> AsyncGenerator[httpx2.AsyncClient]:
    """Yield a client of an app serving the test frontend."""
    async with open_client(settings=settings, frontend_dir=frontend_dir) as client:
        yield client


async def test_serves_index_at_root(client: httpx2.AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.text == INDEX_HTML


async def test_serves_assets(client: httpx2.AsyncClient) -> None:
    response = await client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "console.log('hive');"


@pytest.mark.parametrize("path", ["/games", "/games/0c4a3b5e/replay"])
async def test_falls_back_to_index_for_client_routes(
    client: httpx2.AsyncClient, path: str
) -> None:
    response = await client.get(path)

    assert response.status_code == 200
    assert response.text == INDEX_HTML


@pytest.mark.parametrize("path", ["/api", "/api/unknown", "/api/games/x/unknown"])
async def test_unknown_api_paths_stay_not_found(
    client: httpx2.AsyncClient, path: str
) -> None:
    response = await client.get(path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_routes_take_precedence(client: httpx2.AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("configured", [None, "missing"])
async def test_serves_only_the_api_without_a_build(
    settings: ApiSettings, tmp_path: Path, configured: str | None
) -> None:
    frontend_dir = None if configured is None else tmp_path / configured

    async with open_client(settings=settings, frontend_dir=frontend_dir) as client:
        response = await client.get("/")

    assert response.status_code == 404
