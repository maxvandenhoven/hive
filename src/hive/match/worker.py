"""Persistent worker processes that run one agent each under a time budget.

A worker builds its agent once and then decides moves turn after turn, so models and
caches load once per match. At the deadline the runner stops the agent cooperatively
through a shared event and takes the latest legal candidate. The worker is only killed
and restarted when the agent does not return within a grace period.
"""

import importlib
import logging
import multiprocessing
import random
import signal
import time
from collections.abc import Callable, Sequence
from multiprocessing.connection import Connection
from multiprocessing.context import ForkServerContext, SpawnContext
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event
from types import TracebackType
from typing import Self

from hive.agents.factory import AgentSpec, build_agent
from hive.engine.rules import Rules
from hive.engine.state import GameState
from hive.match.records import DecisionRecord
from hive.match.turn import (
    STARTUP_TURN_ID,
    CandidateSelection,
    FailedMessage,
    IdleMessage,
    PipeTurnContext,
    ThinkMessage,
    WorkerMessage,
)

logger = logging.getLogger(__name__)

DEFAULT_GRACE_S = 1.0
"""The default number of seconds an agent may take to return after it was stopped."""

DEFAULT_STARTUP_TIMEOUT_S = 60.0
"""The default number of seconds a worker may take to build its agent."""

MAX_FAILURE_LENGTH = 500
"""The maximum number of characters of a recorded failure description."""


class AgentWorkerError(RuntimeError):
    """Raised when a worker cannot start, for example because its agent fails to build."""


class AgentWorker:
    """A handle to a persistent worker process that decides moves for one agent.

    Use it as a context manager, or call `start` and `close`:

    ```python
    with AgentWorker(AgentSpec("negamax"), rules, seed=0) as worker:
        decision = worker.decide(state, budget_s=1.0)
    ```

    Attributes:
        spec: The agent the worker runs.
        rules: The rules the agent is built with.
        seed: The seed the agent is built with, also used for fallback moves.
        grace_s: The number of seconds the agent may take to return after it was stopped
            before the worker is killed and restarted.
        startup_timeout_s: The number of seconds the worker may take to build its agent.
        preload: Modules imported in the worker before the agent is built, which register
            agent kinds that are not built in.
        restarts: The number of times the worker was killed and restarted.
        fallback_rng: The random number generator that picks a move when the agent
            submitted no legal one.
        turn_id: The id of the latest turn, or `STARTUP_TURN_ID` before the first one.
        process: The worker process, or `None` when the worker is not started.
        conn: The runner end of the pipe to the worker, or `None` when not started.
        stop_event: The event that stops the agent, or `None` when not started.
    """

    def __init__(
        self,
        spec: AgentSpec,
        rules: Rules,
        *,
        seed: int,
        grace_s: float = DEFAULT_GRACE_S,
        startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
        preload: Sequence[str] = (),
    ) -> None:
        """Initialize the handle without starting the worker.

        Args:
            spec: The agent the worker runs.
            rules: The rules the agent is built with.
            seed: The seed the agent is built with, also used for fallback moves.
            grace_s: The number of seconds the agent may take to return after it was
                stopped before the worker is killed and restarted.
            startup_timeout_s: The number of seconds the worker may take to build its
                agent.
            preload: Modules imported in the worker before the agent is built, which
                register agent kinds that are not built in.
        """
        self.spec = spec
        self.rules = rules
        self.seed = seed
        self.grace_s = grace_s
        self.startup_timeout_s = startup_timeout_s
        self.preload = tuple(preload)
        self.restarts = 0
        self.fallback_rng = random.Random(seed)
        self.turn_id = STARTUP_TURN_ID
        self.process: BaseProcess | None = None
        self.conn: Connection | None = None
        self.stop_event: Event | None = None

    @property
    def label(self) -> str:
        """The label of the agent, or its kind if it has no label."""
        return self.spec.label or self.spec.kind

    @property
    def running(self) -> bool:
        """Whether the worker process is alive."""
        return self.process is not None and self.process.is_alive()

    def __enter__(self) -> Self:
        """Start the worker.

        Returns:
            The started worker.
        """
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the worker.

        Args:
            exc_type: The type of the exception that ended the block, if any.
            exc_value: The exception that ended the block, if any.
            traceback: The traceback of the exception, if any.
        """
        self.close()

    def start(self) -> None:
        """Start the worker process and wait until it built the agent.

        Raises:
            RuntimeError: If the worker is already started.
            AgentWorkerError: If building the agent raised, or took longer than
                `startup_timeout_s`.
        """
        if self.process is not None:
            msg = f"The worker of `{self.label}` is already started."
            raise RuntimeError(msg)

        context = worker_process_context()
        self.conn, worker_conn = context.Pipe()
        self.stop_event = context.Event()
        self.process = context.Process(
            target=run_worker_process,
            args=(worker_conn, self.stop_event, self.spec, self.rules, self.seed),
            kwargs={"preload": self.preload},
            name=f"hive-worker-{self.label}",
            daemon=True,
        )
        self.process.start()
        worker_conn.close()

        message = self.receive(self.startup_timeout_s)

        if not isinstance(message, IdleMessage):
            if isinstance(message, FailedMessage):
                # The worker exits on its own after reporting the failure.
                self.process.join(self.grace_s)

            self.kill()
            error = (
                message.error
                if isinstance(message, FailedMessage)
                else f"timed out after {self.startup_timeout_s} s"
            )
            msg = f"The worker of `{self.label}` failed to start: {error}"
            raise AgentWorkerError(msg)

    def decide(
        self,
        state: GameState,
        budget_s: float,
        *,
        message_callback: Callable[[WorkerMessage], None] | None = None,
    ) -> DecisionRecord:
        """Let the agent decide a move within a time budget.

        The turn closes at the deadline at the latest, with the latest legal candidate or
        a seeded random legal move if there is none. The agent is then stopped and given
        `grace_s` seconds to return; if it does not, or the worker died, the worker is
        restarted before this method returns.

        Args:
            state: The state to decide a move in, which is not modified.
            budget_s: The time budget in seconds.
            message_callback: Called with every legal submission and progress report as it
                arrives, for streaming the search to a user.

        Returns:
            The record of the decision, whose move is legal in `state`.

        Raises:
            RuntimeError: If the worker is not started.
            AgentWorkerError: If the worker has to be restarted and fails to start.
        """
        if self.conn is None or self.stop_event is None:
            msg = f"The worker of `{self.label}` is not started."
            raise RuntimeError(msg)

        self.turn_id += 1
        legal_moves = self.rules.legal_moves(state)
        self.stop_event.clear()
        start = time.monotonic()
        deadline = start + budget_s
        self.conn.send(ThinkMessage(turn_id=self.turn_id, state=state, deadline=deadline))

        selection = CandidateSelection.collect(
            turn_id=self.turn_id,
            legal_moves=legal_moves,
            deadline=deadline,
            messages=self.receive,
            message_callback=message_callback,
        )
        closed_at = time.monotonic()
        close_reason = selection.close_reason

        self.stop_event.set()
        failure = selection.failure

        if not selection.returned:
            self.wait_until_returned(selection)

            if not selection.returned:
                failure = (
                    f"The agent did not return within the grace period of {self.grace_s} "
                    "s after it was stopped."
                )

        returned_at = time.monotonic()

        restart = not selection.returned or not self.running

        if restart:
            logger.warning(
                "Restarting the worker of `%s` at ply %d: %s",
                self.label,
                state.current_ply,
                failure,
            )
            self.restart()

        move = selection.move

        if not selection.has_candidate:
            move = legal_moves[self.fallback_rng.randrange(len(legal_moves))]

        return DecisionRecord(
            ply=state.current_ply,
            player=state.current_player,
            agent_label=self.label,
            seed=self.seed,
            budget_s=budget_s,
            elapsed_s=closed_at - start,
            overrun_s=max(0.0, returned_at - deadline),
            close_reason=close_reason,
            candidates=selection.candidates,
            illegal_submissions=selection.illegal_submissions,
            move=move,
            last_info=selection.last_info,
            worker_restarted=restart,
            failure=None if failure is None else failure[:MAX_FAILURE_LENGTH],
        )

    def restart(self) -> None:
        """Kill the worker process and start a new one, which builds the agent again.

        Raises:
            AgentWorkerError: If the new worker fails to start.
        """
        self.kill()
        self.restarts += 1
        self.start()

    def close(self) -> None:
        """Ask the worker to exit, and kill it if it does not within the grace period."""
        if self.process is None or self.conn is None:
            return

        try:
            self.conn.send(None)
        except OSError:
            logger.debug("The worker of `%s` already exited.", self.label)

        self.process.join(self.grace_s)
        self.kill()

    def receive(self, timeout: float) -> WorkerMessage | None:
        """Receive the next message from the worker.

        Args:
            timeout: The maximum number of seconds to wait.

        Returns:
            The message, a `FailedMessage` of the current turn if the worker died, or
            `None` if no message arrived in time.
        """
        assert self.conn is not None

        try:
            if not self.conn.poll(timeout):
                return None

            return self.conn.recv()
        except (EOFError, OSError):
            # The pipe closes as the process exits, so joining it takes no time.
            exitcode = None

            if self.process is not None:
                self.process.join(self.grace_s)
                exitcode = self.process.exitcode

            return FailedMessage(
                turn_id=self.turn_id, error=f"The worker exited with code {exitcode}."
            )

    def wait_until_returned(self, selection: CandidateSelection) -> None:
        """Wait up to the grace period for the stopped agent to return.

        Messages that arrive in the meantime are ignored, except for `IdleMessage` and
        `FailedMessage`, which mark the selection as returned.

        Args:
            selection: The selection of the closed turn, updated when the agent returns.
        """
        grace_deadline = time.monotonic() + self.grace_s

        while (remaining := grace_deadline - time.monotonic()) > 0:
            message = self.receive(remaining)

            if (
                isinstance(message, IdleMessage | FailedMessage)
                and message.turn_id == self.turn_id
            ):
                selection.receive(message)
                return

    def kill(self) -> None:
        """Kill the worker process if it runs, and release the pipe and the event."""
        if self.process is not None:
            if self.process.is_alive():
                self.process.kill()

            self.process.join()
            self.process.close()

        if self.conn is not None:
            self.conn.close()

        self.process = None
        self.conn = None
        self.stop_event = None


def worker_process_context() -> ForkServerContext | SpawnContext:
    """Get the context that starts worker processes.

    Plain `fork` is never used, so workers do not inherit parent memory such as open
    database connections. The fork server preloads this module, so workers start without
    importing the package again.

    Returns:
        The `forkserver` context where the platform supports it, otherwise `spawn`.
    """
    if "forkserver" not in multiprocessing.get_all_start_methods():
        return multiprocessing.get_context("spawn")

    context = multiprocessing.get_context("forkserver")
    context.set_forkserver_preload([__name__])

    return context


def run_worker_process(
    conn: Connection,
    stop_event: Event,
    spec: AgentSpec,
    rules: Rules,
    seed: int,
    *,
    preload: Sequence[str],
) -> None:
    """Build the agent and decide moves until the runner closes the pipe.

    Runs in the worker process. Errors of the agent are reported as `FailedMessage`, so
    the worker survives an agent that raises during a turn.

    Args:
        conn: The worker end of the pipe to the runner.
        stop_event: The event the runner sets to stop the agent.
        spec: The agent to build.
        rules: The rules the agent is built with.
        seed: The seed the agent is built with.
        preload: Modules to import before building the agent.
    """
    # The runner handles Ctrl+C and closes the worker, so it ignores the interrupt.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    try:
        for module in preload:
            importlib.import_module(module)

        agent = build_agent(spec=spec, rules=rules, seed=seed)
    except Exception as e:
        conn.send(FailedMessage(turn_id=STARTUP_TURN_ID, error=describe_error(e)))
        return

    conn.send(IdleMessage(STARTUP_TURN_ID))

    while True:
        try:
            message: ThinkMessage | None = conn.recv()
        except EOFError:
            return

        if message is None:
            return

        turn = PipeTurnContext(
            conn=conn,
            stop_event=stop_event,
            turn_id=message.turn_id,
            deadline=message.deadline,
        )

        try:
            agent.think(state=message.state, turn=turn)
        except Exception as e:
            turn.flush()
            conn.send(FailedMessage(turn_id=message.turn_id, error=describe_error(e)))
        else:
            turn.flush()
            conn.send(IdleMessage(message.turn_id))


def describe_error(error: Exception) -> str:
    """Describe an error for a `FailedMessage`.

    Args:
        error: The error to describe.

    Returns:
        The type and message of the error, truncated to `MAX_FAILURE_LENGTH` characters.
    """
    return f"{type(error).__name__}: {error}"[:MAX_FAILURE_LENGTH]
