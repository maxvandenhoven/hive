"""In-process turn context and a fake clock for unit tests of agents."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import override

from hive.agents.base import Agent, SearchInfoValue, TurnContext
from hive.engine.state import GameState, Move


@dataclass(slots=True)
class FakeClock:
    """A clock that only moves when told to, or by a fixed step every time it is read.

    A step makes deadlines depend on how often an agent checks the time instead of on
    the speed of the machine, so timed tests are deterministic.

    Attributes:
        now: The current time in seconds.
        step: The number of seconds the clock advances after every read.
    """

    now: float = 0.0
    step: float = 0.0

    def __call__(self) -> float:
        """Read the clock, then advance it by `step`.

        Returns:
            The current time in seconds.
        """
        now = self.now
        self.now += self.step

        return now

    def advance(self, seconds: float) -> None:
        """Move the clock forward.

        Args:
            seconds: The number of seconds to advance.
        """
        self.now += seconds


@dataclass(frozen=True, slots=True)
class TurnSubmission:
    """A move submitted to a `LocalTurnContext`.

    Attributes:
        move: The submitted move, or `None` for a pass.
        final: Whether the submission closed the turn.
        after_stop: Whether the move was submitted after `should_stop` returned `True`.
    """

    move: Move | None
    final: bool
    after_stop: bool


@dataclass(slots=True)
class LocalTurnContext(TurnContext):
    """A turn context that records submissions and progress reports in memory.

    The turn has a budget measured on `clock` from construction. `should_stop` turns
    `True` once the budget is used up, after `stop` is called or after a final
    submission. Unlike the match runner, the context does not check move legality.

    Attributes:
        budget_s: The time budget of the turn in seconds.
        clock: The clock that measures the budget, in seconds.
        submissions: Every submission in order.
        infos: Every progress report in order.
    """

    budget_s: float = float("inf")
    clock: Callable[[], float] = time.monotonic
    submissions: list[TurnSubmission] = field(default_factory=list)
    infos: list[dict[str, SearchInfoValue]] = field(default_factory=list)
    _deadline: float = field(init=False)
    _stopped: bool = field(default=False, init=False)
    _stop_seen: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        """Start the turn by fixing the deadline on the clock."""
        self._deadline = self.clock() + self.budget_s

    @property
    def move(self) -> Move | None:
        """The latest submitted move, or `None` if it is a pass.

        Raises:
            LookupError: If nothing was submitted.
        """
        if not self.submissions:
            msg = "No move was submitted."
            raise LookupError(msg)

        return self.submissions[-1].move

    @property
    def closed(self) -> bool:
        """Whether a final move was submitted."""
        return any(submission.final for submission in self.submissions)

    def run(self, agent: Agent, state: GameState) -> Move | None:
        """Let an agent think on a copy of a state in this turn.

        Args:
            agent: The agent to decide the move.
            state: The game state to decide a move in, which is not modified.

        Returns:
            The latest submitted move, or `None` if it is a pass.

        Raises:
            LookupError: If the agent submitted nothing.
        """
        agent.think(state.copy(), self)
        return self.move

    def stop(self) -> None:
        """Ask the agent to stop, as the runner does when it cancels a turn."""
        self._stopped = True

    @override
    def submit(self, move: Move | None, *, final: bool = False) -> None:
        """Record a submitted move.

        Args:
            move: The proposed move, or `None` to pass.
            final: Whether the agent is done, which closes the turn.
        """
        self.submissions.append(TurnSubmission(move, final, after_stop=self._stop_seen))

    @override
    def remaining_seconds(self) -> float:
        """Get the time left until the deadline on `clock`.

        Returns:
            The number of seconds until the deadline, which is negative once it passed.
        """
        return self._deadline - self.clock()

    @override
    def should_stop(self) -> bool:
        """Check whether the budget is used up, the turn was stopped or closed.

        Returns:
            `True` if the agent should stop thinking and return.
        """
        stop = self._stopped or self.closed or self.remaining_seconds() <= 0
        self._stop_seen = self._stop_seen or stop

        return stop

    @override
    def info(self, **fields: SearchInfoValue) -> None:
        """Record a progress report.

        Args:
            **fields: The progress values to report.
        """
        self.infos.append(fields)
