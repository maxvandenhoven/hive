from typing import Any

import pytest
from fastapi.testclient import TestClient

from hive.agents.factory import list_agents
from hive.api.storage import InMemoryObjectStore


def test_liveness(offline_client: TestClient) -> None:
    response = offline_client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_failed_database(offline_client: TestClient) -> None:
    response = offline_client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not ready",
        "checks": {"database": "failed", "storage": "ok"},
    }


def test_readiness_reports_failed_storage(
    client: TestClient, store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail() -> None:
        raise ConnectionError

    monkeypatch.setattr(store, "check", fail)
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "storage": "failed"}


def test_readiness(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "storage": "ok"},
    }


def test_agent_kinds(offline_client: TestClient) -> None:
    response = offline_client.get("/api/agents")
    kinds: list[dict[str, Any]] = response.json()

    assert response.status_code == 200
    assert [kind["kind"] for kind in kinds] == [r.kind for r in list_agents()]

    negamax = next(kind for kind in kinds if kind["kind"] == "negamax")
    assert negamax["description"]
    assert "depth" in negamax["params_schema"]["properties"]


def test_request_id_is_returned(offline_client: TestClient) -> None:
    given = offline_client.get("/healthz", headers={"X-Request-ID": "abc"})
    generated = offline_client.get("/healthz")

    assert given.headers["X-Request-ID"] == "abc"
    assert len(generated.headers["X-Request-ID"]) == 32
