"""The match runner, which plays a timed game between two agents in worker processes."""

import hashlib
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass

from hive.agents.factory import AgentSpec
from hive.engine.record import GameRecord
from hive.engine.rules import Rules
from hive.engine.state import Player
from hive.match.records import DecisionRecord, MatchOutcome, MatchResult
from hive.match.worker import DEFAULT_GRACE_S, AgentWorker


def derive_seed(seed: int, *parts: str | int) -> int:
    """Derive an independent seed from a base seed and a path, such as a seat.

    The derivation is a hash, so it is stable across processes and Python versions,
    unlike `hash`.

    Args:
        seed: The base seed.
        *parts: The path that identifies the derived seed, for example `("white",)`.

    Returns:
        A non-negative 63-bit seed.
    """
    key = ":".join(str(part) for part in (seed, *parts)).encode()
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest()) >> 1


@dataclass(frozen=True, slots=True)
class MatchRunner:
    """Plays one timed match between two agents, each in its own persistent worker.

    Every decision gets the same time budget. The seat seeds are derived from the match
    seed, so a match is reproducible up to the timing of the agents.

    Attributes:
        rules: The rules of the game.
        white_spec: The agent playing white.
        black_spec: The agent playing black.
        budget_s: The time budget of every decision in seconds.
        max_turns: The number of turns per player after which the match stops without a
            result, or `None` to play until the game ends.
        seed: The match seed.
        grace_s: The number of seconds an agent may take to return after it was stopped
            before its worker is restarted.
        preload: Modules imported in the workers before the agents are built, which
            register agent kinds that are not built in.
    """

    rules: Rules
    white_spec: AgentSpec
    black_spec: AgentSpec
    budget_s: float
    max_turns: int | None
    seed: int
    grace_s: float = DEFAULT_GRACE_S
    preload: Sequence[str] = ()

    def seat_seed(self, player: Player) -> int:
        """Get the seed of the agent of a seat.

        Args:
            player: The seat.

        Returns:
            The seed derived from the match seed and the seat.
        """
        return derive_seed(self.seed, player.name.lower())

    def run(
        self, *, decision_callback: Callable[[DecisionRecord], None] | None = None
    ) -> MatchResult:
        """Play the match from the initial state.

        Args:
            decision_callback: Called with every decision after its move is applied.

        Returns:
            The result, with the game record and every decision.

        Raises:
            AgentWorkerError: If a worker fails to start, for example because its agent
                spec is invalid.
        """
        start = time.monotonic()
        state = self.rules.create_initial_state()
        result = MatchResult(
            rules=self.rules,
            white_spec=self.white_spec,
            black_spec=self.black_spec,
            seed=self.seed,
            budget_s=self.budget_s,
            record=GameRecord(self.rules),
        )

        with ExitStack() as stack:
            workers: dict[Player, AgentWorker] = {
                player: stack.enter_context(
                    AgentWorker(
                        spec=result.spec(player),
                        rules=self.rules,
                        seed=self.seat_seed(player),
                        grace_s=self.grace_s,
                        preload=self.preload,
                    )
                )
                for player in Player
            }

            while not self.rules.is_finished(state):
                if self.max_turns is not None and state.current_ply >= 2 * self.max_turns:
                    break

                decision = workers[state.current_player].decide(
                    state=state, budget_s=self.budget_s
                )
                self.rules.apply_checked_move(state=state, move=decision.move)
                result.add_decision(decision)

                if decision_callback is not None:
                    decision_callback(decision)

        winners = self.rules.winners(state)

        if winners is not None and len(winners) == 1:
            result.outcome = MatchOutcome.WIN
            result.winner = winners[0]
        elif winners is not None:
            result.outcome = MatchOutcome.DRAW

        result.duration_s = time.monotonic() - start

        return result
