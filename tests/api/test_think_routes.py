import json
import logging
import time
import uuid
from typing import Any

import anyio
import httpx2
import pytest
from fastapi import FastAPI
from starlette.types import Message

from hive.agents.factory import AgentSpec
from hive.api.pool import AgentPool
from hive.engine.rules import Rules
from hive.match.records import DecisionRecord
from hive.match.worker import AgentWorker, AgentWorkerError

BUDGET_S = 0.5
OVERHEAD_S = 0.5
"""The most a decision may take past its budget, generous for slow CI machines."""

HUMAN = {"type": "human"}

pytestmark = pytest.mark.anyio


def agent(budget_s: float = BUDGET_S, **spec: Any) -> dict[str, Any]:
    """Build an agent player, by default negamax without a depth limit."""
    return {"type": "agent", "spec": {"kind": "negamax", **spec}, "budget_s": budget_s}


async def create_game(
    client: httpx2.AsyncClient, white: dict[str, Any], black: dict[str, Any]
) -> str:
    """Create a game with the given players and return its ID."""
    response = await client.post(
        "/api/games", json={"name": "Game", "white": white, "black": black}
    )
    assert response.status_code == 201, response.text

    return response.json()["id"]


def parse_events(body: bytes | str) -> list[dict[str, Any]]:
    """Parse the data of every server-sent event in a stream body."""
    text = body.decode() if isinstance(body, bytes) else body
    events = []

    for block in text.split("\n\n"):
        data = [
            line[len("data: ") :]
            for line in block.splitlines()
            if line.startswith("data: ")
        ]

        if data:
            events.append(json.loads("\n".join(data)))

    return events


async def think(client: httpx2.AsyncClient, game_id: str, **body: Any) -> httpx2.Response:
    """Post a thinking request."""
    return await client.post(f"/api/games/{game_id}/think", json=body)


def error_code(response: httpx2.Response) -> str:
    """Get the error code of an error response."""
    return response.json()["code"]


class TestStream:
    async def test_streams_deepening_search_and_decision(
        self, client: httpx2.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        game_id = await create_game(client=client, white=agent(), black=HUMAN)
        start = time.monotonic()

        with caplog.at_level(logging.INFO, logger="hive.api.thinking"):
            response = await think(client=client, game_id=game_id)

        elapsed_s = time.monotonic() - start
        events = parse_events(response.text)
        depths = [event["info"]["depth"] for event in events if event["type"] == "info"]
        decision = events[-1]

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert len(depths) >= 2
        assert depths == sorted(set(depths))
        assert any(event["type"] == "candidate" for event in events)
        assert [event["type"] for event in events].count("decision") == 1
        assert decision["type"] == "decision"
        assert decision["position"] is None
        assert decision["decision"]["budget_s"] == BUDGET_S
        assert decision["decision"]["close_reason"] == "deadline"
        assert decision["decision"]["last_info"]["depth"] == depths[-1]
        assert elapsed_s < BUDGET_S + OVERHEAD_S

        records = [r for r in caplog.records if r.name == "hive.api.thinking"]
        assert len(records) == 1
        assert records[0].__dict__["game_id"] == game_id
        assert records[0].__dict__["decision"] == decision["decision"]
        assert records[0].__dict__["cancelled"] is False

    async def test_last_candidate_is_the_decision(
        self, client: httpx2.AsyncClient
    ) -> None:
        game_id = await create_game(client=client, white=agent(), black=HUMAN)

        events = parse_events((await think(client=client, game_id=game_id)).text)
        candidates = [event for event in events if event["type"] == "candidate"]

        assert candidates[-1]["move"] == events[-1]["decision"]["move"]

    async def test_advises_a_human_side(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client, white=HUMAN, black=agent())

        response = await think(
            client=client, game_id=game_id, agent={"kind": "random", "label": "rnd"}
        )
        decision = parse_events(response.text)[-1]
        game = (await client.get(f"/api/games/{game_id}")).json()

        assert decision["decision"]["agent_label"] == "rnd"
        assert decision["decision"]["close_reason"] == "final"
        assert decision["decision"]["budget_s"] == 5.0
        assert game["ply_count"] == 0

    async def test_clamps_budget(self, app: FastAPI, client: httpx2.AsyncClient) -> None:
        app.state.settings = app.state.settings.model_copy(update={"max_budget_s": 0.2})
        game_id = await create_game(client=client, white=agent(), black=HUMAN)

        response = await think(client=client, game_id=game_id, budget_s=10.0)

        assert parse_events(response.text)[-1]["decision"]["budget_s"] == 0.2

    async def test_reuses_worker_across_requests(
        self, client: httpx2.AsyncClient, pool: AgentPool
    ) -> None:
        game_id = await create_game(client=client, white=agent(budget_s=0.1), black=HUMAN)
        await think(client=client, game_id=game_id)
        worker = pool.workers[0].worker
        assert worker.process is not None
        pid = worker.process.pid

        await think(client=client, game_id=game_id, budget_s=0.1)

        assert pool.size == 1
        assert pool.workers[0].worker is worker
        assert worker.process.pid == pid


class TestCommit:
    async def test_commits_agent_move_with_decision(
        self, client: httpx2.AsyncClient
    ) -> None:
        game_id = await create_game(client=client, white=agent(), black=HUMAN)

        response = await think(client=client, game_id=game_id, commit=True)
        event = parse_events(response.text)[-1]
        game = (await client.get(f"/api/games/{game_id}")).json()

        assert event["type"] == "decision"
        assert event["position"]["ply"] == 1
        assert event["position"]["last_move"]["move"] == event["decision"]["move"]
        assert game["ply_count"] == 1
        assert game["moves"][0]["source"] == "agent"
        assert game["moves"][0]["move"] == event["decision"]["move"]
        assert game["moves"][0]["decision"] == event["decision"]

    async def test_commit_accepts_the_side_spec(self, client: httpx2.AsyncClient) -> None:
        white = agent(budget_s=0.1, params={"depth": 1})
        game_id = await create_game(client=client, white=white, black=HUMAN)

        response = await think(
            client=client, game_id=game_id, agent=white["spec"], commit=True
        )

        assert parse_events(response.text)[-1]["position"]["ply"] == 1

    async def test_commit_conflicts_with_a_move_played_meanwhile(
        self, client: httpx2.AsyncClient
    ) -> None:
        game_id = await create_game(client=client, white=agent(), black=HUMAN)
        responses: list[httpx2.Response] = []

        async def think_and_commit() -> None:
            responses.append(await think(client=client, game_id=game_id, commit=True))

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(think_and_commit)
            await anyio.sleep(BUDGET_S / 2)
            move = Rules().legal_moves(Rules().create_initial_state())[0]
            assert move is not None
            played = await client.post(
                f"/api/games/{game_id}/moves",
                json={
                    "move": move.to_json(),
                    "expected_ply": 0,
                    "allow_agent_side": True,
                },
            )
            assert played.status_code == 201, played.text

        events = parse_events(responses[0].text)
        game = (await client.get(f"/api/games/{game_id}")).json()

        assert [event["type"] for event in events[-2:]] == ["decision", "error"]
        assert events[-2]["position"] is None
        assert events[-1]["code"] == "ply_conflict"
        assert [move["source"] for move in game["moves"]] == ["manual"]

    async def test_rejects_commit_on_human_side(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client, white=HUMAN, black=agent())

        response = await think(
            client=client, game_id=game_id, agent={"kind": "random"}, commit=True
        )

        assert response.status_code == 409
        assert error_code(response) == "commit_not_allowed"

    async def test_rejects_commit_by_another_agent(
        self, client: httpx2.AsyncClient
    ) -> None:
        game_id = await create_game(client=client, white=agent(), black=HUMAN)

        response = await think(
            client=client, game_id=game_id, agent={"kind": "random"}, commit=True
        )

        assert response.status_code == 409
        assert error_code(response) == "commit_not_allowed"


class TestRejected:
    async def test_human_side_needs_an_agent(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client, white=HUMAN, black=agent())

        response = await think(client=client, game_id=game_id)

        assert response.status_code == 422
        assert error_code(response) == "agent_required"

    async def test_invalid_agent_params(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client, white=agent(), black=HUMAN)

        response = await think(
            client=client,
            game_id=game_id,
            agent={"kind": "negamax", "params": {"depth": 0}},
        )

        assert response.status_code == 422
        assert "params.depth" in response.text

    async def test_inactive_game(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client, white=agent(), black=HUMAN)
        await client.patch(f"/api/games/{game_id}", json={"status": "abandoned"})

        response = await think(client=client, game_id=game_id)

        assert response.status_code == 409
        assert error_code(response) == "game_not_active"

    async def test_missing_game(self, client: httpx2.AsyncClient) -> None:
        response = await think(client=client, game_id=str(uuid.uuid4()))

        assert response.status_code == 404
        assert error_code(response) == "game_not_found"

    async def test_busy_pool(self, client: httpx2.AsyncClient, pool: AgentPool) -> None:
        game_id = await create_game(client=client, white=agent(), black=HUMAN)
        spec = AgentSpec("random")

        async with (
            pool.borrow(spec=spec, rules=Rules(), game_id=uuid.uuid4()),
            pool.borrow(spec=spec, rules=Rules(), game_id=uuid.uuid4()),
        ):
            response = await think(client=client, game_id=game_id)

        assert response.status_code == 503
        assert error_code(response) == "pool_busy"


class TestWorkerFailure:
    async def test_failed_worker_ends_stream_with_error(
        self, client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        game_id = await create_game(client=client, white=agent(), black=HUMAN)

        def fail(*args: object, **kwargs: object) -> DecisionRecord:
            msg = "The worker of `negamax` failed to start: boom"
            raise AgentWorkerError(msg)

        monkeypatch.setattr(AgentWorker, "decide", fail)

        response = await think(client=client, game_id=game_id, commit=True)
        events = parse_events(response.text)
        game = (await client.get(f"/api/games/{game_id}")).json()

        assert response.status_code == 200
        assert events == [
            {
                "type": "error",
                "code": "agent_unavailable",
                "detail": "The worker of `negamax` failed to start: boom",
            }
        ]
        assert game["ply_count"] == 0


class TestDisconnect:
    async def test_disconnect_stops_agent_without_commit(
        self, app: FastAPI, client: httpx2.AsyncClient, pool: AgentPool
    ) -> None:
        game_id = await create_game(
            client=client, white=agent(budget_s=10.0), black=HUMAN
        )
        path = f"/api/games/{game_id}/think"
        body = json.dumps({"commit": True}).encode()
        first_event = anyio.Event()
        received: list[Message] = []
        requested = False

        async def receive() -> Message:
            """Send the body, then disconnect once the first event arrived."""
            nonlocal requested

            if not requested:
                requested = True
                return {"type": "http.request", "body": body, "more_body": False}

            await first_event.wait()

            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            """Collect the response and note the first event."""
            received.append(message)

            if message["type"] == "http.response.body" and message.get("body"):
                first_event.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"test"), (b"content-type", b"application/json")],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "state": {},
        }
        start = time.monotonic()

        with anyio.fail_after(5.0):
            await app(scope, receive, send)

        elapsed_s = time.monotonic() - start
        events = parse_events(
            b"".join(
                m.get("body", b"") for m in received if m["type"] == "http.response.body"
            )
        )
        game = (await client.get(f"/api/games/{game_id}")).json()

        assert received[0]["status"] == 200
        assert events
        assert "decision" not in {event["type"] for event in events}
        assert elapsed_s < 2.0
        assert (pool.size, pool.busy) == (1, 0)
        assert pool.workers[0].worker.running
        assert game["ply_count"] == 0
