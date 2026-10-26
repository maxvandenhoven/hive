"""The pool of persistent agent workers that thinking requests borrow.

Workers are keyed by their agent spec and rules, created when first needed and reused
across requests and games, so agents load their models and caches once. A full pool
evicts its least recently used idle worker; when every worker is busy, a request waits up
to `wait_s` seconds and then fails with 503.

Pool state is only changed on the event loop, so it needs `anyio` primitives and no
thread locks. Blocking worker calls (starting, resetting, deciding, closing) run in
threads limited to the pool capacity, apart from the default limiter that other blocking
calls share.
"""

import json
import logging
import secrets
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

import anyio
import anyio.to_thread

from hive.agents.factory import AgentSpec
from hive.api.errors import AgentUnavailableError, PoolBusyError
from hive.engine.rules import Rules
from hive.match.worker import DEFAULT_GRACE_S, AgentWorker, AgentWorkerError

logger = logging.getLogger(__name__)


def agent_pool_key(spec: AgentSpec, rules: Rules) -> str:
    """Build the key of the workers that run an agent under some rules.

    Args:
        spec: The agent.
        rules: The rules.

    Returns:
        The spec and the rules as canonical JSON, since the params of a spec are a
        mapping that cannot be hashed.
    """
    return json.dumps([spec.to_json(), rules.to_json()], sort_keys=True)


@dataclass(slots=True)
class PooledWorker:
    """A worker of the pool and how it was last used.

    Attributes:
        key: The key of the agent and rules the worker runs.
        worker: The worker, which is not started yet right after the pool created it.
        busy: Whether the worker is lent to a request.
        game_id: The game the worker last decided in, or `None` before its first
            decision. The agent is reset before it decides in another game.
        last_used_at: When the worker was last returned, on the `time.monotonic` clock.
    """

    key: str
    worker: AgentWorker
    busy: bool = True
    game_id: uuid.UUID | None = None
    last_used_at: float = 0.0


class AgentPool:
    """Persistent agent workers shared by the thinking requests of the app.

    Borrow a worker for one decision with `borrow`:

    ```python
    async with pool.borrow(spec=spec, rules=rules, game_id=game_id) as worker:
        decision = await pool.run_blocking(lambda: worker.decide(state, budget_s=1.0))
    ```

    Attributes:
        capacity: The most worker processes kept at once, idle or busy.
        wait_s: The seconds a request waits for a free worker before it fails.
        grace_s: The seconds an agent may take to return after it was stopped before
            its worker is restarted.
        preload: Modules imported in the workers before their agents are built, which
            register agent kinds that are not built in.
        workers: The workers, including the ones being started.
        closed: Whether the pool was closed, after which it lends no more workers.
        changed: Guards the workers and wakes waiting requests when a worker is
            returned.
        limiter: Limits the threads that run blocking worker calls to the capacity.
    """

    def __init__(
        self,
        capacity: int,
        wait_s: float,
        *,
        grace_s: float = DEFAULT_GRACE_S,
        preload: Sequence[str] = (),
    ) -> None:
        """Create an empty pool; workers start when first borrowed.

        Args:
            capacity: The most worker processes kept at once, idle or busy.
            wait_s: The seconds a request waits for a free worker before it fails.
            grace_s: The seconds an agent may take to return after it was stopped
                before its worker is restarted.
            preload: Modules imported in the workers before their agents are built.
        """
        self.capacity = capacity
        self.wait_s = wait_s
        self.grace_s = grace_s
        self.preload = tuple(preload)
        self.workers: list[PooledWorker] = []
        self.closed = False
        self.changed = anyio.Condition()
        self.limiter = anyio.CapacityLimiter(capacity)

    @property
    def size(self) -> int:
        """The number of workers, idle or busy."""
        return len(self.workers)

    @property
    def busy(self) -> int:
        """The number of workers lent to a request."""
        return sum(pooled.busy for pooled in self.workers)

    @asynccontextmanager
    async def borrow(
        self, spec: AgentSpec, rules: Rules, game_id: uuid.UUID
    ) -> AsyncGenerator[AgentWorker]:
        """Borrow a started worker for a decision in a game.

        Args:
            spec: The agent.
            rules: The rules of the game.
            game_id: The game, so the agent is reset when it played another game last.

        Yields:
            The worker, returned to the pool when the block exits. A worker that is no
            longer running is dropped instead.

        Raises:
            PoolBusyError: If no worker became free within `wait_s` seconds.
            AgentUnavailableError: If the worker failed to start, or the pool is closed.
        """
        pooled = await self.acquire(spec=spec, rules=rules, game_id=game_id)

        try:
            yield pooled.worker
        finally:
            await self.release(pooled)

    async def acquire(
        self, spec: AgentSpec, rules: Rules, game_id: uuid.UUID
    ) -> PooledWorker:
        """Take an idle worker of the agent, or start one, waiting while all are busy.

        Args:
            spec: The agent.
            rules: The rules of the game.
            game_id: The game the worker decides in.

        Returns:
            The worker, marked busy, started and reset for the game.

        Raises:
            PoolBusyError: If no worker became free within `wait_s` seconds.
            AgentUnavailableError: If the worker failed to start, or the pool is closed.
        """
        key = agent_pool_key(spec=spec, rules=rules)
        claimed: tuple[PooledWorker, PooledWorker | None] | None = None

        with anyio.move_on_after(self.wait_s):
            async with self.changed:
                while (claimed := self.claim(key=key, spec=spec, rules=rules)) is None:
                    await self.changed.wait()

        if claimed is None:
            raise PoolBusyError(self.wait_s)

        pooled, evicted = claimed

        try:
            if evicted is not None:
                logger.info("Evicting the idle worker of `%s`.", evicted.worker.label)
                await self.run_blocking(evicted.worker.close)

            if not pooled.worker.running:
                await self.run_blocking(pooled.worker.start)
            elif pooled.game_id not in (None, game_id):
                await self.run_blocking(pooled.worker.reset)
        except BaseException as e:
            await self.release(pooled)

            if isinstance(e, AgentWorkerError):
                raise AgentUnavailableError(str(e)) from e

            raise

        pooled.game_id = game_id

        return pooled

    def claim(
        self, key: str, spec: AgentSpec, rules: Rules
    ) -> tuple[PooledWorker, PooledWorker | None] | None:
        """Claim a worker for an agent, which must be called holding `changed`.

        Prefers an idle worker of the agent, then a new worker while the pool is not
        full, then a new worker in place of the least recently used idle one.

        Args:
            key: The key of the agent and rules.
            spec: The agent.
            rules: The rules.

        Returns:
            The claimed worker, marked busy and possibly not started yet, with the idle
            worker it replaces, which the caller closes; or `None` if every worker is
            busy.

        Raises:
            AgentUnavailableError: If the pool is closed.
        """
        if self.closed:
            msg = "The agent pool is shut down."
            raise AgentUnavailableError(msg)

        idle = [pooled for pooled in self.workers if not pooled.busy]

        for pooled in idle:
            if pooled.key == key:
                pooled.busy = True
                return pooled, None

        evicted = None

        if len(self.workers) >= self.capacity:
            if not idle:
                return None

            evicted = min(idle, key=lambda pooled: pooled.last_used_at)
            self.workers.remove(evicted)

        pooled = PooledWorker(
            key=key,
            worker=AgentWorker(
                spec=spec,
                rules=rules,
                seed=secrets.randbits(63),
                grace_s=self.grace_s,
                preload=self.preload,
            ),
        )
        self.workers.append(pooled)

        return pooled, evicted

    async def release(self, pooled: PooledWorker) -> None:
        """Return a borrowed worker, or drop it if it stopped running or the pool closed.

        Runs to the end even when the caller is cancelled, so no worker is lost.

        Args:
            pooled: The borrowed worker.
        """
        with anyio.CancelScope(shield=True):
            drop = self.closed or not pooled.worker.running

            async with self.changed:
                if drop:
                    self.workers.remove(pooled)
                else:
                    pooled.busy = False
                    pooled.last_used_at = time.monotonic()

                self.changed.notify_all()

            if drop:
                await self.run_blocking(pooled.worker.close)

    async def run_blocking[T](self, function: Callable[[], T]) -> T:
        """Run a blocking worker call in a thread of the pool.

        The call is not abandoned when the caller is cancelled: cancellation waits for
        it to return, so a worker is never used by two threads at once.

        Args:
            function: The call, without arguments.

        Returns:
            What the call returned.
        """
        return await anyio.to_thread.run_sync(function, limiter=self.limiter)

    async def close(self) -> None:
        """Close the idle workers and lend no more; busy ones close when returned."""
        async with self.changed:
            self.closed = True
            idle = [pooled for pooled in self.workers if not pooled.busy]
            self.workers = [pooled for pooled in self.workers if pooled.busy]
            self.changed.notify_all()

        for pooled in idle:
            await self.run_blocking(pooled.worker.close)
