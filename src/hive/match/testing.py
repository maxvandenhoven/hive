"""Misbehaving agents for tests of workers and the match runner.

Importing this module registers agent kinds starting with `test-`. Import it only in
worker processes, with `AgentWorker(..., preload=["hive.match.testing"])`, so the kinds
stay out of the registry of the test process and out of `list_agents`.
"""

import os
import time
from pathlib import Path
from typing import override

from pydantic import Field

from hive.agents.base import Agent, TurnContext
from hive.agents.factory import register_agent
from hive.agents.params import AgentParams
from hive.engine.rules import Rules
from hive.engine.state import GameState, Move, PieceType

ILLEGAL_MOVE = Move(
    piece_type=PieceType.QUEEN, source_coord=None, target_coord=(100, 100)
)
"""A placement far away from every piece, which is never legal after the first ply."""

LINGER_POLL_INTERVAL_S = 0.001
"""The number of seconds the agents sleep between two checks of `should_stop`."""


@register_agent("test-never-submits")
class NeverSubmitsAgent(Agent[AgentParams]):
    """Agent that thinks until it is stopped without submitting anything."""

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Wait until the turn asks to stop.

        Args:
            state: A copy of the current game state.
            turn: The context of the turn.
        """
        while not turn.should_stop():
            time.sleep(LINGER_POLL_INTERVAL_S)


class IllegalAgentParams(AgentParams):
    """The params of `IllegalAgent`."""

    count: int = Field(default=1, description="The number of illegal moves to submit.")
    then_legal: bool = Field(
        default=False,
        description="Whether to submit the first legal move after the illegal ones.",
    )


@register_agent("test-illegal")
class IllegalAgent(Agent[IllegalAgentParams]):
    """Agent that submits illegal moves, optionally followed by a legal one."""

    Params = IllegalAgentParams

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Submit the illegal moves, then the first legal move if configured, and return.

        Args:
            state: A copy of the current game state.
            turn: The context to submit moves to.
        """
        for _ in range(self.params.count):
            turn.submit(ILLEGAL_MOVE)

        if self.params.then_legal:
            turn.submit(self.rules.legal_moves(state)[0])


class LingeringAgentParams(AgentParams):
    """The params of `LingeringAgent`."""

    linger_s: float = Field(
        default=float("inf"),
        description="The number of seconds to keep thinking after the turn asks to stop.",
    )


@register_agent("test-lingers")
class LingeringAgent(Agent[LingeringAgentParams]):
    """Agent that submits a legal move, then returns only some time after it is stopped.

    A linger longer than the grace period of the worker, including an infinite one,
    ignores the stop and gets the worker restarted.
    """

    Params = LingeringAgentParams

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Submit the first legal move, wait until stopped, then linger.

        Args:
            state: A copy of the current game state.
            turn: The context to submit the move to.
        """
        turn.submit(self.rules.legal_moves(state)[0])

        while not turn.should_stop():
            time.sleep(LINGER_POLL_INTERVAL_S)

        time.sleep(min(self.params.linger_s, 3600.0))


class CrashingAgentParams(AgentParams):
    """The params of `CrashingAgent`."""

    exit_process: bool = Field(
        default=False,
        description="Whether to exit the worker process instead of raising.",
    )


@register_agent("test-crashes")
class CrashingAgent(Agent[CrashingAgentParams]):
    """Agent that submits a legal move and then raises, or kills its own process."""

    Params = CrashingAgentParams

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Submit the first legal move, then fail.

        Args:
            state: A copy of the current game state.
            turn: The context to submit the move to.

        Raises:
            RuntimeError: Always, unless the process exits first.
        """
        turn.submit(self.rules.legal_moves(state)[0])

        if self.params.exit_process:
            os._exit(3)

        msg = "The agent crashed on purpose."
        raise RuntimeError(msg)


class CountingAgentParams(AgentParams):
    """The params of `CountingAgent`."""

    path: str = Field(description="The file to append a line to.")
    fail_reset: bool = Field(
        default=False, description="Whether resetting raises instead of writing a line."
    )


@register_agent("test-counting")
class CountingAgent(Agent[CountingAgentParams]):
    """Random agent that appends a line to a file when it is constructed or reset.

    A construction writes the process ID, a reset writes `reset`, and a reset raises
    instead when `fail_reset` is set.

    Attributes:
        path: The file the agent appends a line to.
    """

    Params = CountingAgentParams

    def __init__(self, rules: Rules, *, seed: int, params: CountingAgentParams) -> None:
        """Initialize the agent and count the construction.

        Args:
            rules: The rules governing the game.
            seed: The seed for the random number generator of the agent.
            params: The file to count in and whether a reset fails.
        """
        super().__init__(rules=rules, seed=seed, params=params)
        self.path = Path(params.path)

        with self.path.open("a") as file:
            file.write(f"{os.getpid()}\n")

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Submit a move chosen uniformly at random from the legal moves as final.

        Args:
            state: A copy of the current game state.
            turn: The context to submit the move to.
        """
        legal_moves = self.rules.legal_moves(state)
        turn.submit(move=legal_moves[self.rng.randrange(len(legal_moves))], final=True)

    @override
    def reset(self) -> None:
        """Count the reset, or raise if configured to.

        Raises:
            RuntimeError: If `fail_reset` is set.
        """
        if self.params.fail_reset:
            msg = "The agent failed to reset on purpose."
            raise RuntimeError(msg)

        with self.path.open("a") as file:
            file.write("reset\n")
