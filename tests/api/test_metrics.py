import httpx2
import pytest
from prometheus_client.parser import text_string_to_metric_families

from hive.api.metrics import ApiMetrics
from hive.engine.state import Player
from hive.match.records import DecisionRecord, TurnCloseReason

pytestmark = pytest.mark.anyio


def scrape(text: str) -> dict[tuple[str, frozenset[tuple[str, str]]], float]:
    """Parse the Prometheus text format into values by sample name and labels."""
    return {
        (sample.name, frozenset(sample.labels.items())): sample.value
        for family in text_string_to_metric_families(text)
        for sample in family.samples
    }


def sample(name: str, **labels: str) -> tuple[str, frozenset[tuple[str, str]]]:
    """Build the key of a scraped sample."""
    return name, frozenset(labels.items())


def decision(
    illegal_submissions: int = 0, worker_restarted: bool = False
) -> DecisionRecord:
    """Build a decision record that took a second and closed at the deadline."""
    return DecisionRecord(
        ply=0,
        player=Player.WHITE,
        agent_label="nm",
        seed=0,
        budget_s=1.0,
        elapsed_s=1.0,
        overrun_s=0.01,
        close_reason=TurnCloseReason.DEADLINE,
        candidates=2,
        illegal_submissions=illegal_submissions,
        move=None,
        worker_restarted=worker_restarted,
    )


class TestEndpoint:
    async def test_exposes_documented_metrics(
        self, offline_client: httpx2.AsyncClient
    ) -> None:
        response = await offline_client.get("/metrics")
        names = {family.name for family in text_string_to_metric_families(response.text)}

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert {
            "hive_http_request_seconds",
            "hive_decision_seconds",
            "hive_decision_overrun_seconds",
            "hive_decision_close",
            "hive_worker_restarts",
            "hive_illegal_submissions",
            "hive_worker_pool_size",
            "hive_worker_pool_busy",
        } <= names

    async def test_labels_requests_by_route(
        self, offline_client: httpx2.AsyncClient
    ) -> None:
        await offline_client.get("/healthz")
        await offline_client.get("/healthz")
        await offline_client.get("/api/agents/unknown/path")
        values = scrape((await offline_client.get("/metrics")).text)

        assert (
            values[
                sample(
                    "hive_http_request_seconds_count",
                    method="GET",
                    route="/healthz",
                    status="200",
                )
            ]
            == 2
        )
        assert (
            values[
                sample(
                    "hive_http_request_seconds_count",
                    method="GET",
                    route="unmatched",
                    status="404",
                )
            ]
            == 1
        )

    async def test_counts_decisions_and_pool(self, client: httpx2.AsyncClient) -> None:
        response = await client.post(
            "/api/games",
            json={
                "name": "Game",
                "white": {"type": "agent", "spec": {"kind": "negamax"}, "budget_s": 0.1},
                "black": {"type": "human"},
            },
        )
        game_id = response.json()["id"]
        await client.post(f"/api/games/{game_id}/think", json={})
        values = scrape((await client.get("/metrics")).text)

        assert values[sample("hive_decision_seconds_count", kind="negamax")] == 1
        assert values[sample("hive_decision_close_total", reason="deadline")] == 1
        assert values[sample("hive_worker_pool_size")] == 1
        assert values[sample("hive_worker_pool_busy")] == 0
        assert (
            values[
                sample(
                    "hive_http_request_seconds_count",
                    method="POST",
                    route="/api/games/{game_id}/think",
                    status="200",
                )
            ]
            == 1
        )


class TestApiMetrics:
    def test_observes_decision(self) -> None:
        metrics = ApiMetrics()

        metrics.observe_decision(
            kind="negamax",
            decision=decision(illegal_submissions=2, worker_restarted=True),
        )
        values = scrape(metrics.render().decode())

        assert values[sample("hive_decision_seconds_sum", kind="negamax")] == 1.0
        assert values[sample("hive_decision_overrun_seconds_sum", kind="negamax")] == 0.01
        assert values[sample("hive_illegal_submissions_total")] == 2
        assert values[sample("hive_worker_restarts_total")] == 1

    def test_apps_do_not_share_metrics(self) -> None:
        first, second = ApiMetrics(), ApiMetrics()

        first.observe_decision(kind="random", decision=decision())

        assert sample("hive_decision_seconds_count", kind="random") not in scrape(
            second.render().decode()
        )
