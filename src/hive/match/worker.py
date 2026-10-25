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
    Failed,
    Idle,
    PipeTurnContext,
    Think,
    WorkerMessage,
)

logger = logging.getLogger(__name__)

DEFAULT_GRACE_S = 1.0
"""The default number of seconds an agent may take to return after it was stopped."""

DEFAULT_STARTUP_TIMEOUT_S = 60.0
"""The default number of seconds a worker may take to build its agent."""

MAX_FAILURE_LENGTH = 500
"""The maximum number of characters of a recorded failure description."""


class WorkerError(RuntimeError):
    """Raised when a worker cannot start, for example because its agent fails to build."""


class Worker:
    """A handle to a persistent worker process that decides moves for one agent.

    Use it as a context manager, or call `start` and `close`:

    ```python
    with Worker(AgentSpec("negamax"), rules, seed=0) as worker:
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
        self._fallback_rng = random.Random(seed)
        self._turn_id = STARTUP_TURN_ID
        self._process: BaseProcess | None = None
        self._conn: Connection | None = None
        self._stop_event: Event | None = None

    @property
    def label(self) -> str:
        """The label of the agent, or its kind if it has no label."""
        return self.spec.label or self.spec.kind

    @property
    def running(self) -> bool:
        """Whether the worker process is alive."""
        return self._process is not None and self._process.is_alive()

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
            WorkerError: If building the agent raised, or took longer than
                `startup_timeout_s`.
        """
        if self._process is not None:
            msg = f"The worker of `{self.label}` is already started."
            raise RuntimeError(msg)

        context = _multiprocessing_context()
        self._conn, worker_conn = context.Pipe()
        self._stop_event = context.Event()
        self._process = context.Process(
            target=_run_worker,
            args=(worker_conn, self._stop_event, self.spec, self.rules, self.seed),
            kwargs={"preload": self.preload},
            name=f"hive-worker-{self.label}",
            daemon=True,
        )
        self._process.start()
        worker_conn.close()

        message = self._receive(self.startup_timeout_s)
        if not isinstance(message, Idle):
            if isinstance(message, Failed):
                # The worker exits on its own after reporting the failure.
                self._process.join(self.grace_s)
            self._kill()
            error = (
                message.error
                if isinstance(message, Failed)
                else f"timed out after {self.startup_timeout_s} s"
            )
            msg = f"The worker of `{self.label}` failed to start: {error}"
            raise WorkerError(msg)

    def decide(
        self,
        state: GameState,
        budget_s: float,
        *,
        on_message: Callable[[WorkerMessage], None] | None = None,
    ) -> DecisionRecord:
        """Let the agent decide a move within a time budget.

        The turn closes at the deadline at the latest, with the latest legal candidate or
        a seeded random legal move if there is none. The agent is then stopped and given
        `grace_s` seconds to return; if it does not, or the worker died, the worker is
        restarted before this method returns.

        Args:
            state: The state to decide a move in, which is not modified.
            budget_s: The time budget in seconds.
            on_message: Called with every legal submission and progress report as it
                arrives, for streaming the search to a user.

        Returns:
            The record of the decision, whose move is legal in `state`.

        Raises:
            RuntimeError: If the worker is not started.
            WorkerError: If the worker has to be restarted and fails to start.
        """
        if self._conn is None or self._stop_event is None:
            msg = f"The worker of `{self.label}` is not started."
            raise RuntimeError(msg)

        self._turn_id += 1
        legal_moves = self.rules.legal_moves(state)
        self._stop_event.clear()
        start = time.monotonic()
        deadline = start + budget_s
        self._conn.send(Think(self._turn_id, state, deadline))

        selection = CandidateSelection.collect(
            self._turn_id, legal_moves, deadline, self._receive, on_message=on_message
        )
        closed_at = time.monotonic()
        close_reason = selection.close_reason

        self._stop_event.set()
        failure = selection.failure
        if not selection.returned:
            self._wait_returned(selection)
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
            move = legal_moves[self._fallback_rng.randrange(len(legal_moves))]

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
            WorkerError: If the new worker fails to start.
        """
        self._kill()
        self.restarts += 1
        self.start()

    def close(self) -> None:
        """Ask the worker to exit, and kill it if it does not within the grace period."""
        if self._process is None or self._conn is None:
            return

        try:
            self._conn.send(None)
        except OSError:
            logger.debug("The worker of `%s` already exited.", self.label)
        self._process.join(self.grace_s)
        self._kill()

    def _receive(self, timeout: float) -> WorkerMessage | None:
        """Receive the next message from the worker.

        Args:
            timeout: The maximum number of seconds to wait.

        Returns:
            The message, a `Failed` message of the current turn if the worker died, or
            `None` if no message arrived in time.
        """
        assert self._conn is not None
        try:
            if not self._conn.poll(timeout):
                return None
            return self._conn.recv()
        except (EOFError, OSError):
            # The pipe closes as the process exits, so joining it takes no time.
            exitcode = None
            if self._process is not None:
                self._process.join(self.grace_s)
                exitcode = self._process.exitcode
            return Failed(self._turn_id, f"The worker exited with code {exitcode}.")

    def _wait_returned(self, selection: CandidateSelection) -> None:
        """Wait up to the grace period for the stopped agent to return.

        Messages that arrive in the meantime are ignored, except for `Idle` and `Failed`,
        which mark the selection as returned.

        Args:
            selection: The selection of the closed turn, updated when the agent returns.
        """
        grace_deadline = time.monotonic() + self.grace_s
        while (remaining := grace_deadline - time.monotonic()) > 0:
            message = self._receive(remaining)
            if isinstance(message, Idle | Failed) and message.turn_id == self._turn_id:
                selection.receive(message)
                return

    def _kill(self) -> None:
        """Kill the worker process if it runs, and release the pipe and the event."""
        if self._process is not None:
            if self._process.is_alive():
                self._process.kill()
            self._process.join()
            self._process.close()
        if self._conn is not None:
            self._conn.close()
        self._process = None
        self._conn = None
        self._stop_event = None


def _multiprocessing_context() -> ForkServerContext | SpawnContext:
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


def _run_worker(
    conn: Connection,
    stop_event: Event,
    spec: AgentSpec,
    rules: Rules,
    seed: int,
    *,
    preload: Sequence[str],
) -> None:
    """Build the agent and decide moves until the runner closes the pipe.

    Runs in the worker process. Errors of the agent are reported as `Failed` messages, so
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
        agent = build_agent(spec, rules, seed=seed)
    except Exception as e:
        conn.send(Failed(STARTUP_TURN_ID, _describe(e)))
        return
    conn.send(Idle(STARTUP_TURN_ID))

    while True:
        try:
            message: Think | None = conn.recv()
        except EOFError:
            return
        if message is None:
            return

        turn = PipeTurnContext(conn, stop_event, message.turn_id, message.deadline)
        try:
            agent.think(message.state, turn)
        except Exception as e:
            turn.flush()
            conn.send(Failed(message.turn_id, _describe(e)))
        else:
            turn.flush()
            conn.send(Idle(message.turn_id))


def _describe(error: Exception) -> str:
    """Describe an error for a `Failed` message.

    Args:
        error: The error to describe.

    Returns:
        The type and message of the error, truncated to `MAX_FAILURE_LENGTH` characters.
    """
    return f"{type(error).__name__}: {error}"[:MAX_FAILURE_LENGTH]
