"""Agent thinking for the API: one timed decision of a pooled worker, streamed live.

A thinking request borrows a worker before its stream starts, so a busy pool or a game
that cannot be thought about is an error response rather than a broken stream. The
decision runs in a thread of the pool; the worker's messages cross into the event loop
through a memory object stream, which the route reads and sends as server-sent events.
The worker returns to the pool only after the decision returned, also when the client
disconnects, which stops the agent early.
"""

import logging
import math
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import Self

import anyio
import anyio.from_thread
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from sqlalchemy.ext.asyncio import AsyncSession

from hive.agents.factory import AgentSpec
from hive.api.errors import (
    AgentRequiredError,
    AgentUnavailableError,
    ApiError,
    CommitNotAllowedError,
)
from hive.api.games import GameService
from hive.api.metrics import ApiMetrics
from hive.api.players import DEFAULT_AGENT_BUDGET_S, AgentPlayer
from hive.api.pool import AgentPool
from hive.api.schemas import (
    GamePosition,
    ThinkCandidateEvent,
    ThinkDecisionEvent,
    ThinkErrorEvent,
    ThinkEvent,
    ThinkInfoEvent,
    ThinkRequest,
)
from hive.api.storage import ObjectStore
from hive.engine.rules import Rules
from hive.engine.state import GameState
from hive.match.records import DecisionRecord
from hive.match.turn import InfoMessage, SubmissionMessage, WorkerMessage
from hive.match.worker import AgentWorker, AgentWorkerError

logger = logging.getLogger(__name__)

type ThinkingItem = WorkerMessage | DecisionRecord | ApiError
"""What a decision streams: worker messages, then the decision or the error that ended
it."""


@dataclass(frozen=True, slots=True)
class ThinkingPlan:
    """What an agent thinks about, and how, checked before the stream starts.

    Attributes:
        game_id: The game.
        ply: The record ply of the position, which the game must still be at to commit.
        rules: The rules of the game.
        state: The latest state of the game.
        spec: The agent that thinks.
        budget_s: The time budget in seconds, at most the maximum of the service.
        commit: Whether to play the decided move in the game.
    """

    game_id: uuid.UUID
    ply: int
    rules: Rules
    state: GameState
    spec: AgentSpec
    budget_s: float
    commit: bool

    @classmethod
    async def load(
        cls,
        games: GameService,
        game_id: uuid.UUID,
        body: ThinkRequest,
        max_budget_s: float,
    ) -> Self:
        """Check a thinking request against the latest position of its game.

        Args:
            games: The game service.
            game_id: The game ID.
            body: The request.
            max_budget_s: The longest budget in seconds; longer ones are shortened.

        Returns:
            The plan.

        Raises:
            GameNotFoundError: If there is no game with the ID.
            GameNotActiveError: If the game is finished or abandoned.
            CommitNotAllowedError: If the request commits, but no agent plays the side to
                move or the request names another agent.
            MovePendingError: If the request commits while the last move waits to be
                made on the board.
            AgentRequiredError: If a person without a hint agent plays the side to move
                and the request names no agent.
        """
        game = await games.get_game(game_id)
        state = game.replay()
        games.check_active(game=game, state=state)
        side = state.current_player
        player = game.player(side)
        side_agent = player if isinstance(player, AgentPlayer) else None

        if body.commit and (
            side_agent is None or body.agent not in (None, side_agent.spec)
        ):
            msg = (
                f"Only the agent playing `{side.name.lower()}` may commit its decision; "
                "leave out `agent` to use it."
            )
            raise CommitNotAllowedError(msg)

        if body.commit:
            games.check_no_pending_move(game)

        default = player if isinstance(player, AgentPlayer) else player.hint
        spec = body.agent or (default.spec if default is not None else None)

        if spec is None:
            raise AgentRequiredError(side)

        budget_s = body.budget_s or (
            default.budget_s if default is not None else DEFAULT_AGENT_BUDGET_S
        )

        return cls(
            game_id=game_id,
            ply=len(game.moves),
            rules=game.rules,
            state=state,
            spec=spec,
            budget_s=min(budget_s, max_budget_s),
            commit=body.commit,
        )


class AgentThinking:
    """One decision of a borrowed worker, streaming its messages to a request.

    Start it with `start`, which runs the decision in the background, and read its
    events with `events`.

    Attributes:
        plan: What the agent thinks about.
        worker: The borrowed worker.
        pool: The pool that lent the worker and runs its blocking calls.
        metrics: The metrics that record the decision.
        send_stream: Where the decision puts worker messages, then the decision or the
            error that ended it.
        receive_stream: Where `events` reads them.
        finished: Whether the decision returned or failed.
        cancelled: Whether the request stopped the decision early.
    """

    def __init__(
        self,
        plan: ThinkingPlan,
        worker: AgentWorker,
        pool: AgentPool,
        metrics: ApiMetrics,
    ) -> None:
        """Prepare a decision; `start` creates and runs it.

        Args:
            plan: What the agent thinks about.
            worker: The borrowed worker.
            pool: The pool that lent the worker.
            metrics: The metrics that record the decision.
        """
        self.plan = plan
        self.worker = worker
        self.pool = pool
        self.metrics = metrics
        # Unbounded, so the worker thread never waits for the client to read.
        self.send_stream: MemoryObjectSendStream[ThinkingItem]
        self.receive_stream: MemoryObjectReceiveStream[ThinkingItem]
        self.send_stream, self.receive_stream = anyio.create_memory_object_stream[
            ThinkingItem
        ](max_buffer_size=math.inf)
        self.finished = False
        self.cancelled = False

    @classmethod
    @asynccontextmanager
    async def start(
        cls, plan: ThinkingPlan, pool: AgentPool, metrics: ApiMetrics
    ) -> AsyncGenerator[Self]:
        """Borrow a worker and run the decision in the background.

        Args:
            plan: What the agent thinks about.
            pool: The pool to borrow the worker from.
            metrics: The metrics that record the decision.

        Yields:
            The running decision. When the block exits before the decision returned, the
            agent is stopped; the block waits for it to return before the worker goes
            back to the pool.

        Raises:
            PoolBusyError: If no worker became free in time.
            AgentUnavailableError: If the worker failed to start.
        """
        async with pool.borrow(
            spec=plan.spec, rules=plan.rules, game_id=plan.game_id
        ) as worker:
            thinking = cls(plan=plan, worker=worker, pool=pool, metrics=metrics)

            # The receive end stays open until the decision returned, so the decision
            # can always send, even after the request stopped reading.
            with thinking.receive_stream:
                async with anyio.create_task_group() as task_group:
                    task_group.start_soon(thinking.run)

                    try:
                        yield thinking
                    finally:
                        thinking.cancel()

    async def run(self) -> None:
        """Run the decision in a thread of the pool and stream what happens."""
        with self.send_stream:
            try:
                decision = await self.pool.run_blocking(
                    partial(
                        self.worker.decide,
                        state=self.plan.state,
                        budget_s=self.plan.budget_s,
                        message_callback=self.forward,
                    )
                )
            except AgentWorkerError as e:
                self.finished = True
                logger.exception(
                    "The worker of `%s` failed in game `%s`.",
                    self.worker.label,
                    self.plan.game_id,
                    extra={"game_id": str(self.plan.game_id)},
                )
                self.send_stream.send_nowait(AgentUnavailableError(str(e)))
                return

            self.finished = True
            self.record(decision)
            self.send_stream.send_nowait(decision)

    def forward(self, message: WorkerMessage) -> None:
        """Pass a worker message from the decision thread to the event loop.

        Stops the agent again if the decision was cancelled, in case the cancellation
        came before the decision started, which clears the stop.

        Args:
            message: The message.
        """
        if self.cancelled:
            self.worker.cancel()

        anyio.from_thread.run_sync(self.send_stream.send_nowait, message)

    def cancel(self) -> None:
        """Stop the agent early, unless the decision already returned."""
        if not self.finished:
            self.cancelled = True
            self.worker.cancel()

    def record(self, decision: DecisionRecord) -> None:
        """Log a decision and record its metrics.

        A cancelled decision is logged, but only its worker restart counts in the
        metrics, since its times and close reason reflect the cancellation.

        Args:
            decision: The decision.
        """
        logger.info(
            "Agent `%s` decided `%s` at ply %d of game `%s`.",
            decision.agent_label,
            "pass" if decision.move is None else decision.move,
            self.plan.ply,
            self.plan.game_id,
            extra={
                "game_id": str(self.plan.game_id),
                "agent_kind": self.plan.spec.kind,
                "cancelled": self.cancelled,
                "decision": decision.to_json(),
            },
        )

        if self.cancelled:
            if decision.worker_restarted:
                self.metrics.worker_restarts.inc()
        else:
            self.metrics.observe_decision(kind=self.plan.spec.kind, decision=decision)

    async def events(
        self, session_factory: Callable[[], AsyncSession], store: ObjectStore
    ) -> AsyncIterator[ThinkEvent]:
        """Turn the streamed messages into events, committing the decision if planned.

        Args:
            session_factory: Opens the session that commits the decision.
            store: The object store of the game service.

        Yields:
            An `info` or `candidate` event per worker message, then the `decision`, and
            an `error` if committing failed or instead of the decision if the worker
            failed.
        """
        async for item in self.receive_stream:
            match item:
                case InfoMessage(fields=fields):
                    yield ThinkInfoEvent(info=fields)
                case SubmissionMessage(move=move, final=final):
                    yield ThinkCandidateEvent(move=move, final=final)
                case DecisionRecord():
                    position: GamePosition | None = None
                    error: ApiError | None = None

                    if self.plan.commit:
                        try:
                            async with session_factory() as session:
                                position = await GameService(
                                    session=session, store=store
                                ).commit_decision(
                                    game_id=self.plan.game_id,
                                    ply=self.plan.ply,
                                    decision=item,
                                )
                        except ApiError as e:
                            error = e

                    yield ThinkDecisionEvent(decision=item, position=position)

                    if error is not None:
                        yield ThinkErrorEvent(code=error.code, detail=error.detail)
                case ApiError():
                    yield ThinkErrorEvent(code=item.code, detail=item.detail)
