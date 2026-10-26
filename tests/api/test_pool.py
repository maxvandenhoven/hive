"""Tests of the agent worker pool, which start real worker processes."""

import uuid
from pathlib import Path

import anyio
import pytest
from pydantic import JsonValue

from hive.agents.factory import AgentSpec
from hive.api.app import create_app
from hive.api.errors import AgentUnavailableError, PoolBusyError
from hive.api.pool import AgentPool, agent_pool_key
from hive.api.settings import ApiSettings
from hive.api.storage import ObjectStore
from hive.engine.rules import Rules

GAME_ID = uuid.uuid4()

pytestmark = pytest.mark.anyio


def counting_spec(path: Path, **params: JsonValue) -> AgentSpec:
    """Build the spec of the test agent that counts its constructions and resets."""
    return AgentSpec(kind="test-counting", params={"path": str(path), **params})


def count_lines(path: Path) -> list[str]:
    """Read what a counting agent wrote: a process ID per construction, then resets."""
    return path.read_text().splitlines() if path.exists() else []


class TestBorrow:
    async def test_reuses_worker_across_borrows(
        self, pool: AgentPool, tmp_path: Path
    ) -> None:
        path = tmp_path / "agent.txt"

        for _ in range(3):
            async with pool.borrow(
                spec=counting_spec(path), rules=Rules(), game_id=GAME_ID
            ) as worker:
                assert worker.running

        assert len(count_lines(path)) == 1
        assert (pool.size, pool.busy) == (1, 0)

    async def test_lends_busy_agent_to_one_request(
        self, pool: AgentPool, tmp_path: Path
    ) -> None:
        spec = counting_spec(tmp_path / "agent.txt")

        async with (
            pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID) as first,
            pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID) as second,
        ):
            assert first is not second
            assert (pool.size, pool.busy) == (2, 2)

    async def test_resets_agent_between_games(
        self, pool: AgentPool, tmp_path: Path
    ) -> None:
        path = tmp_path / "agent.txt"
        spec = counting_spec(path)

        for game_id in (GAME_ID, GAME_ID, uuid.uuid4()):
            async with pool.borrow(spec=spec, rules=Rules(), game_id=game_id):
                pass

        assert count_lines(path)[1:] == ["reset"]

    async def test_keys_by_spec_and_rules(self) -> None:
        spec = AgentSpec(kind="negamax", params={"depth": 2, "mobility": 0.5})
        same = AgentSpec(kind="negamax", params={"mobility": 0.5, "depth": 2})

        assert agent_pool_key(spec=spec, rules=Rules()) == agent_pool_key(
            spec=same, rules=Rules()
        )
        assert agent_pool_key(spec=spec, rules=Rules()) != agent_pool_key(
            spec=spec, rules=Rules(max_turns=10)
        )
        assert agent_pool_key(spec=spec, rules=Rules()) != agent_pool_key(
            spec=AgentSpec(kind="negamax", params={"depth": 2}), rules=Rules()
        )


class TestCapacity:
    async def test_evicts_least_recently_used_idle_worker(
        self, pool: AgentPool, tmp_path: Path
    ) -> None:
        paths = [tmp_path / f"agent-{index}.txt" for index in range(3)]
        workers = []

        for path in [paths[0], paths[1], paths[0], paths[2]]:
            async with pool.borrow(
                spec=counting_spec(path), rules=Rules(), game_id=GAME_ID
            ) as worker:
                workers.append(worker)

        assert pool.size == 2
        assert not workers[1].running
        assert workers[0].running
        assert workers[3].running

        async with pool.borrow(
            spec=counting_spec(paths[0]), rules=Rules(), game_id=GAME_ID
        ) as worker:
            assert worker is workers[0]

    async def test_full_pool_fails_after_waiting(
        self, pool: AgentPool, tmp_path: Path
    ) -> None:
        spec = counting_spec(tmp_path / "agent.txt")

        async with (
            pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID),
            pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID),
        ):
            with anyio.fail_after(2.0), pytest.raises(PoolBusyError):
                async with pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID):
                    pass

    async def test_waiting_request_gets_returned_worker(
        self, pool: AgentPool, tmp_path: Path
    ) -> None:
        spec = counting_spec(tmp_path / "agent.txt")
        other = counting_spec(tmp_path / "other.txt")
        borrowed = []

        async def borrow_when_free() -> None:
            async with pool.borrow(spec=other, rules=Rules(), game_id=GAME_ID) as worker:
                borrowed.append(worker)

        async with anyio.create_task_group() as task_group:
            async with (
                pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID),
                pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID),
            ):
                task_group.start_soon(borrow_when_free)
                await anyio.sleep(0.05)
                assert not borrowed

        assert len(borrowed) == 1
        assert pool.size == 2
        assert len(count_lines(tmp_path / "other.txt")) == 1


class TestFailures:
    async def test_start_failure_is_unavailable(self, pool: AgentPool) -> None:
        spec = AgentSpec(kind="negamax", params={"depth": 0})

        with pytest.raises(AgentUnavailableError, match="params.depth"):
            async with pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID):
                pass

        assert pool.size == 0

    async def test_drops_dead_worker(self, pool: AgentPool, tmp_path: Path) -> None:
        spec = counting_spec(tmp_path / "agent.txt")

        async with pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID) as worker:
            worker.kill()

        assert pool.size == 0

        async with pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID) as worker:
            assert worker.running

    async def test_cancelled_borrow_returns_worker(
        self, pool: AgentPool, tmp_path: Path
    ) -> None:
        spec = counting_spec(tmp_path / "agent.txt")

        with anyio.move_on_after(0.01):
            async with pool.borrow(spec=spec, rules=Rules(), game_id=GAME_ID):
                await anyio.sleep(1.0)

        assert pool.busy == 0


class TestClose:
    async def test_closes_idle_and_returned_workers(self, tmp_path: Path) -> None:
        pool = AgentPool(capacity=2, wait_s=0.1, preload=["hive.match.testing"])
        idle_spec = counting_spec(tmp_path / "idle.txt")
        busy_spec = counting_spec(tmp_path / "busy.txt")

        async with pool.borrow(spec=idle_spec, rules=Rules(), game_id=GAME_ID) as idle:
            pass

        async with pool.borrow(spec=busy_spec, rules=Rules(), game_id=GAME_ID) as busy:
            await pool.close()
            assert not idle.running
            assert busy.running

        assert not busy.running
        assert pool.size == 0

        with pytest.raises(AgentUnavailableError, match="shut down"):
            async with pool.borrow(spec=idle_spec, rules=Rules(), game_id=GAME_ID):
                pass


async def test_app_creates_and_closes_its_pool(
    settings: ApiSettings, store: ObjectStore
) -> None:
    app = create_app(settings=settings.model_copy(update={"pool_size": 3}), store=store)

    async with app.router.lifespan_context(app):
        pool = app.state.pool
        assert (pool.capacity, pool.wait_s) == (3, settings.pool_wait_s)
        assert not pool.closed

    assert pool.closed
