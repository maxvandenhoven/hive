from typing import Any

import httpx2
import pytest

from hive.agents.factory import list_agents, list_presets
from hive.api.storage import ObjectStore

pytestmark = pytest.mark.anyio


async def test_liveness(offline_client: httpx2.AsyncClient) -> None:
    response = await offline_client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_failed_database(
    offline_client: httpx2.AsyncClient,
) -> None:
    response = await offline_client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not ready",
        "checks": {"database": "failed", "storage": "ok"},
    }


async def test_readiness_reports_failed_storage(
    client: httpx2.AsyncClient, store: ObjectStore
) -> None:
    store.client.delete_bucket(Bucket=store.bucket)
    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "storage": "failed"}


async def test_readiness(client: httpx2.AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "storage": "ok"},
    }


async def test_agent_kinds(offline_client: httpx2.AsyncClient) -> None:
    response = await offline_client.get("/api/agents")
    kinds: list[dict[str, Any]] = response.json()

    assert response.status_code == 200
    assert [kind["kind"] for kind in kinds] == [r.kind for r in list_agents()]

    negamax = next(kind for kind in kinds if kind["kind"] == "negamax")
    assert negamax["description"]
    assert "depth" in negamax["params_schema"]["properties"]


async def test_agent_presets(offline_client: httpx2.AsyncClient) -> None:
    response = await offline_client.get("/api/agents/presets")
    presets: list[dict[str, Any]] = response.json()

    assert response.status_code == 200
    assert [preset["name"] for preset in presets] == list_presets()

    nm3 = next(preset for preset in presets if preset["name"] == "nm3")
    assert nm3["description"]
    assert nm3["spec"] == {"kind": "negamax", "params": {"depth": 3}, "label": "nm3"}
