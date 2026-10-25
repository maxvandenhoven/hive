"""Worker messages, the turn context of a worker and the policy that selects a move.

A turn is a `Think` message from the runner, answered by any number of `Submission` and
`Info` messages and closed by `Idle` when the agent returns or `Failed` when it raises.
Every message carries the id of its turn, so messages from an earlier turn are ignored.
Turn id 0 is the startup of the worker: `Idle` means the agent was built, `Failed` that
building it raised.
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.synchronize import Event
from typing import override

from hive.agents.base import SearchInfoValue, TurnContext
from hive.engine.state import GameState, Move
from hive.match.records import CloseReason

logger = logging.getLogger(__name__)

STARTUP_TURN_ID = 0
"""The turn id of the messages that report the startup of a worker."""

INFO_INTERVAL_S = 0.1
"""The minimum number of seconds between two progress reports sent over the pipe."""


@dataclass(frozen=True, slots=True)
class Think:
    """Ask the worker to decide a move.

    Attributes:
        turn_id: The id of the turn, counting from 1.
        state: The state to decide a move in.
        deadline: The end of the turn on the `time.monotonic` clock, which is shared by
            the processes of one machine.
    """

    turn_id: int
    state: GameState
    deadline: float


@dataclass(frozen=True, slots=True)
class Submission:
    """A move the agent proposed as its current answer.

    Attributes:
        turn_id: The id of the turn.
        move: The proposed move, or `None` to pass.
        final: Whether the agent is done, which closes the turn.
    """

    turn_id: int
    move: Move | None
    final: bool


@dataclass(frozen=True, slots=True)
class Info:
    """A progress report of the agent.

    Attributes:
        turn_id: The id of the turn.
        fields: The progress values, such as `depth`, `nodes` and `score`.
    """

    turn_id: int
    fields: dict[str, SearchInfoValue]


@dataclass(frozen=True, slots=True)
class Idle:
    """The agent returned, or was built at startup, and the worker waits for a turn.

    Attributes:
        turn_id: The id of the turn that ended.
    """

    turn_id: int


@dataclass(frozen=True, slots=True)
class Failed:
    """The agent raised, or building it raised at startup, or the worker died.

    The worker keeps running after an agent raised during a turn.

    Attributes:
        turn_id: The id of the turn that failed.
        error: A description of the error.
    """

    turn_id: int
    error: str


type WorkerMessage = Submission | Info | Idle | Failed
"""A message from a worker to the runner."""

type MessageSource = Callable[[float], WorkerMessage | None]
"""Receive the next message within a timeout in seconds, or `None` if none arrived."""


class PipeTurnContext(TurnContext):
    """The turn context of an agent in a worker process.

    Submissions and progress reports are sent to the runner over a pipe. `should_stop`
    reads a stop event shared with the runner, which sets it when it closes the turn.
    """

    def __init__(
        self,
        conn: Connection,
        stop_event: Event,
        turn_id: int,
        deadline: float,
        *,
        info_interval_s: float = INFO_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the context of one turn.

        Args:
            conn: The worker end of the pipe to the runner.
            stop_event: The event the runner sets to stop the agent.
            turn_id: The id of the turn, sent with every message.
            deadline: The end of the turn on `clock`.
            info_interval_s: The minimum number of seconds between two progress reports
                sent over the pipe. Reports in between are held back, and only the latest
                one is sent when the interval passed or the turn ends.
            clock: The clock the deadline is measured on, in seconds.
        """
        self._conn = conn
        self._stop_event = stop_event
        self._turn_id = turn_id
        self._deadline = deadline
        self._info_interval_s = info_interval_s
        self._clock = clock
        self._closed = False
        self._last_info_at = float("-inf")
        self._pending_info: dict[str, SearchInfoValue] | None = None

    @override
    def submit(self, move: Move | None, *, final: bool = False) -> None:
        """Send a proposed move to the runner, after a held back progress report.

        Args:
            move: The proposed move, or `None` to pass.
            final: Whether the agent is done, which closes the turn.
        """
        self.flush()
        self._conn.send(Submission(self._turn_id, move, final))
        self._closed = self._closed or final

    @override
    def remaining_seconds(self) -> float:
        """Get the time left until the deadline.

        Returns:
            The number of seconds until the deadline, which is negative once it passed.
        """
        return self._deadline - self._clock()

    @override
    def should_stop(self) -> bool:
        """Check whether the runner stopped the turn or a final move closed it.

        The deadline is not checked here: the runner sets the stop event when it closes
        the turn, so an agent that returns before that returned on its own.

        Returns:
            `True` if the agent should stop thinking and return.
        """
        return self._closed or self._stop_event.is_set()

    @override
    def info(self, **fields: SearchInfoValue) -> None:
        """Send a progress report, or hold it back if the last one was sent recently.

        Args:
            **fields: The progress values to report.
        """
        self._pending_info = fields
        if self._clock() - self._last_info_at >= self._info_interval_s:
            self.flush()

    def flush(self) -> None:
        """Send the progress report held back by the rate limit, if any."""
        if self._pending_info is not None:
            self._conn.send(Info(self._turn_id, self._pending_info))
            self._pending_info = None
            self._last_info_at = self._clock()


@dataclass(slots=True)
class CandidateSelection:
    """The selection policy of one turn, and what it saw.

    The latest legal submission is the candidate. A final submission closes the turn, as
    does the agent returning (`Idle`), the agent failing (`Failed`) or the deadline.
    Illegal submissions are counted and ignored, and messages of other turns are dropped.

    Attributes:
        turn_id: The id of the turn.
        legal_moves: The legal moves of the state the turn decides in.
        move: The latest legal candidate, which is `None` both for a pass and when there
            is no candidate (see `has_candidate`).
        has_candidate: Whether a legal move was submitted.
        candidates: The number of legal submissions.
        illegal_submissions: The number of rejected submissions.
        last_info: The latest progress report, or `None` if there was none.
        final: Whether a final submission closed the turn.
        returned: Whether the agent returned or failed, so the worker waits for a turn.
        failure: The error of a `Failed` message, or `None` if none arrived.
        on_message: Called with every legal submission and progress report as it
            arrives, for streaming the search to a user.
    """

    turn_id: int
    legal_moves: Sequence[Move | None]
    move: Move | None = None
    has_candidate: bool = False
    candidates: int = 0
    illegal_submissions: int = 0
    last_info: dict[str, SearchInfoValue] | None = None
    final: bool = False
    returned: bool = False
    failure: str | None = None
    on_message: Callable[[WorkerMessage], None] | None = None

    @classmethod
    def collect(
        cls,
        turn_id: int,
        legal_moves: Sequence[Move | None],
        deadline: float,
        messages: MessageSource,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_message: Callable[[WorkerMessage], None] | None = None,
    ) -> "CandidateSelection":
        """Receive messages until the turn closes.

        Args:
            turn_id: The id of the turn.
            legal_moves: The legal moves of the state the turn decides in.
            deadline: The end of the turn on `clock`.
            messages: The source of the worker messages.
            clock: The clock the deadline is measured on, in seconds.
            on_message: Called with every legal submission and progress report as it
                arrives, for streaming the search to a user.

        Returns:
            The selection when the turn closed.
        """
        selection = cls(turn_id, legal_moves, on_message=on_message)

        while not selection.closed:
            remaining = deadline - clock()
            if remaining <= 0:
                break
            message = messages(remaining)
            if message is not None:
                selection.receive(message)

        return selection

    @property
    def closed(self) -> bool:
        """Whether a message closed the turn before the deadline."""
        return self.final or self.returned

    @property
    def close_reason(self) -> CloseReason:
        """Why the turn closed, assuming the deadline closed it if no message did."""
        if not self.has_candidate:
            return CloseReason.NO_CANDIDATE
        if self.failure is not None:
            return CloseReason.WORKER_FAILED
        if self.closed:
            return CloseReason.FINAL
        return CloseReason.DEADLINE

    def receive(self, message: WorkerMessage) -> None:
        """Update the selection with a message from the worker.

        Args:
            message: The message to apply. Messages of other turns are ignored.
        """
        if message.turn_id != self.turn_id:
            logger.debug("Dropped a message of turn %d: %r", message.turn_id, message)
            return

        match message:
            case Submission(move=move, final=final) if move in self.legal_moves:
                self.move = move
                self.has_candidate = True
                self.candidates += 1
                self.final = final
                if self.on_message is not None:
                    self.on_message(message)
            case Submission(move=move):
                self.illegal_submissions += 1
                logger.warning("Rejected the illegal submission `%s`.", move)
            case Info(fields=fields):
                self.last_info = fields
                if self.on_message is not None:
                    self.on_message(message)
            case Idle():
                self.returned = True
            case Failed(error=error):
                self.returned = True
                self.failure = error
