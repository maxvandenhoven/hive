import random
from abc import ABC, abstractmethod
from typing import ClassVar, Protocol

from pydantic import JsonValue

from hive.agents.params import AgentParams
from hive.engine.rules import Rules
from hive.engine.state import GameState, Move

type SearchInfoValue = JsonValue
"""A value in a search progress report, such as a depth, a score or a serialized move."""


class TurnContext(Protocol):
    """The whole capability an agent holds during one decision.

    The runner creates one context per turn and hands it to `Agent.think`. Submissions
    are proposals: the runner keeps the latest legal one and closes the turn at the
    deadline, or as soon as a submission is marked final.
    """

    def submit(self, move: Move | None, *, final: bool = False) -> None:
        """Propose a move as the current answer for this turn.

        Illegal submissions are rejected and logged by the runner, leaving the previous
        candidate standing.

        Args:
            move: The proposed move, or `None` to pass.
            final: Whether the agent is done, which closes the turn immediately.
        """
        ...

    def remaining_seconds(self) -> float:
        """Get the time left until the deadline of this turn.

        Returns:
            The number of seconds until the deadline, which is negative once it passed.
        """
        ...

    def should_stop(self) -> bool:
        """Check whether the agent should stop thinking and return.

        Returns:
            `True` once the deadline passed, the runner cancelled the turn or a final move
            was submitted.
        """
        ...

    def info(self, **fields: SearchInfoValue) -> None:
        """Report search progress, modelled on UCI `info` lines.

        Common fields are `depth`, `nodes`, `score`, `pv` (the principal variation as
        serialized moves) and `nps`; agents may add free-form extras. The call is
        fire-and-forget and may be rate-limited by the context.

        Args:
            **fields: The progress values to report.
        """
        ...


class Agent[P: AgentParams](ABC):
    """Base class for all agents, generic over the params model of the kind.

    An agent decides moves under a time budget through `think`, which submits candidate
    moves to a `TurnContext` as the search improves. The contract every agent follows:

    - `think` receives a copy of the state, which it may mutate freely while searching.
    - `think` submits a cheap legal move immediately, then improves on it. Returning is
      the answer, since the latest candidate is already submitted.
    - `think` checks `TurnContext.should_stop` regularly (every few nodes or between
      iterative deepening iterations) and returns soon after it turns `True`.
    - All randomness comes from `rng`, so a fixed seed gives reproducible decisions.

    An agent object lives for a whole match, so it may keep caches across turns. `reset`
    is called between matches when the agent is reused.

    A kind with params declares them as a subclass of `AgentParams`, names it in
    `Params` and passes it as the type argument, for example
    `class SearchAgent(Agent[SearchParams])` with `Params = SearchParams`.

    Attributes:
        rules: The rules governing the game, used to search the game tree.
        rng: The random number generator seeded at construction, the only source of
            randomness of the agent.
        params: The validated params of the agent.
    """

    Params: ClassVar[type[AgentParams]] = AgentParams
    """The params model of the kind, which validates the params of its specs."""

    def __init__(self, rules: Rules, *, seed: int, params: P) -> None:
        """Initialize the agent.

        Args:
            rules: The rules governing the game.
            seed: The seed for the random number generator of the agent.
            params: The validated params of the agent, an instance of `Params`.
        """
        self.rules = rules
        self.rng = random.Random(seed)
        self.params = params

    @abstractmethod
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Decide a move for the current player by submitting candidates to `turn`.

        Args:
            state: A copy of the current game state, which the agent may mutate.
            turn: The context to submit moves and report progress to.
        """

    def reset(self) -> None:  # noqa: B027
        """Clear state kept across turns before the agent plays a new match.

        The default keeps nothing across turns, so there is nothing to clear.
        """
