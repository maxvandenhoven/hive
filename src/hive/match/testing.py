"""Misbehaving agents for tests of workers and the match runner.

Importing this module registers agent kinds starting with `test-`. Import it only in
worker processes, with `AgentWorker(..., preload=["hive.match.testing"])`, so the kinds
stay out of the registry of the test process and out of `list_agents`.
"""

import os
import time
from pathlib import Path
from typing import override

from hive.agents.base import Agent, TurnContext
from hive.agents.factory import register_agent
from hive.agents.random import RandomAgent
from hive.engine.rules import Rules
from hive.engine.state import GameState, Move, PieceType

ILLEGAL_MOVE = Move(
    piece_type=PieceType.QUEEN, source_coord=None, target_coord=(100, 100)
)
"""A placement far away from every piece, which is never legal after the first ply."""

POLL_INTERVAL_S = 0.001
"""The number of seconds the agents sleep between two checks of `should_stop`."""


@register_agent("test-never-submits")
class NeverSubmitsAgent(Agent):
    """Agent that thinks until it is stopped without submitting anything."""

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Wait until the turn asks to stop.

        Args:
            state: A copy of the current game state.
            turn: The context of the turn.
        """
        while not turn.should_stop():
            time.sleep(POLL_INTERVAL_S)


@register_agent("test-illegal")
class IllegalAgent(Agent):
    """Agent that submits illegal moves, optionally followed by a legal one."""

    def __init__(
        self, rules: Rules, *, seed: int, count: int = 1, then_legal: bool = False
    ) -> None:
        """Initialize the agent.

        Args:
            rules: The rules governing the game.
            seed: The seed for the random number generator of the agent.
            count: The number of illegal moves to submit.
            then_legal: Whether to submit the first legal move after the illegal ones.
        """
        super().__init__(rules, seed=seed)
        self.count = count
        self.then_legal = then_legal

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Submit the illegal moves, then the first legal move if configured, and return.

        Args:
            state: A copy of the current game state.
            turn: The context to submit moves to.
        """
        for _ in range(self.count):
            turn.submit(ILLEGAL_MOVE)

        if self.then_legal:
            turn.submit(self.rules.legal_moves(state)[0])


@register_agent("test-lingers")
class LingeringAgent(Agent):
    """Agent that submits a legal move, then returns only some time after it is stopped.

    A linger longer than the grace period of the worker, including an infinite one,
    ignores the stop and gets the worker restarted.
    """

    def __init__(
        self, rules: Rules, *, seed: int, linger_s: float = float("inf")
    ) -> None:
        """Initialize the agent.

        Args:
            rules: The rules governing the game.
            seed: The seed for the random number generator of the agent.
            linger_s: The number of seconds to keep thinking after the turn asks to stop.
        """
        super().__init__(rules, seed=seed)
        self.linger_s = linger_s

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Submit the first legal move, wait until stopped, then linger.

        Args:
            state: A copy of the current game state.
            turn: The context to submit the move to.
        """
        turn.submit(self.rules.legal_moves(state)[0])

        while not turn.should_stop():
            time.sleep(POLL_INTERVAL_S)

        time.sleep(min(self.linger_s, 3600.0))


@register_agent("test-crashes")
class CrashingAgent(Agent):
    """Agent that submits a legal move and then raises, or kills its own process."""

    def __init__(self, rules: Rules, *, seed: int, exit_process: bool = False) -> None:
        """Initialize the agent.

        Args:
            rules: The rules governing the game.
            seed: The seed for the random number generator of the agent.
            exit_process: Whether to exit the worker process instead of raising.
        """
        super().__init__(rules, seed=seed)
        self.exit_process = exit_process

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

        if self.exit_process:
            os._exit(3)

        msg = "The agent crashed on purpose."
        raise RuntimeError(msg)


@register_agent("test-counting")
class CountingAgent(RandomAgent):
    """Random agent that appends a line to a file every time it is constructed."""

    def __init__(self, rules: Rules, *, seed: int, path: str) -> None:
        """Initialize the agent and count the construction.

        Args:
            rules: The rules governing the game.
            seed: The seed for the random number generator of the agent.
            path: The file to append a line to.
        """
        super().__init__(rules, seed=seed)

        with Path(path).open("a") as file:
            file.write(f"{os.getpid()}\n")
