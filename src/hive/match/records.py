"""Records of timed decisions and matches, serializable to JSON-compatible values.

Both records convert to and from JSON through `JsonCodec`; engine values inside them use
their own JSON forms, and the agents of a match are written under `white` and `black`.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated

from pydantic import Field

from hive.agents.base import SearchInfoValue
from hive.agents.factory import AgentSpec
from hive.engine.codec import JsonCodec
from hive.engine.record import GameRecord
from hive.engine.rules import Rules
from hive.engine.state import Move, Player


class TurnCloseReason(StrEnum):
    """Why a turn closed, which also tells where the applied move came from."""

    FINAL = "final"
    """The agent submitted a final move, or returned with a legal candidate standing."""

    DEADLINE = "deadline"
    """The deadline passed and the latest legal candidate was taken."""

    WORKER_FAILED = "worker_failed"
    """The agent raised or the worker died, and the latest legal candidate was taken."""

    NO_CANDIDATE = "no_candidate"
    """The turn closed without a legal candidate, so a seeded random move was taken."""


class MatchOutcome(StrEnum):
    """How a match ended."""

    WIN = "win"
    """A queen was surrounded, so the other player won."""

    DRAW = "draw"
    """Both queens were surrounded at once, or the turn limit of the rules was passed."""

    TURN_CAP = "turn_cap"
    """The match runner stopped the game at its turn cap before a result."""


@dataclass(frozen=True, slots=True)
class DecisionRecord(JsonCodec):
    """Everything that happened in one timed decision of an agent.

    Attributes:
        ply: The ply the decision was made at.
        player: The player to move.
        agent_label: The label of the agent, or its kind if it has no label.
        seed: The seed the agent was built with.
        budget_s: The time budget of the turn in seconds.
        elapsed_s: The seconds from sending the state to closing the turn.
        overrun_s: The seconds past the deadline until the worker returned or was killed.
        close_reason: Why the turn closed.
        candidates: The number of legal submissions.
        illegal_submissions: The number of rejected submissions.
        move: The applied move, or `None` for a pass.
        last_info: The last progress report of the agent, or `None` if there was none.
        worker_restarted: Whether the worker was killed and restarted after the turn.
        failure: A truncated description of what went wrong, or `None` if nothing did.
    """

    ply: int
    player: Player
    agent_label: str
    seed: int
    budget_s: float
    elapsed_s: float
    overrun_s: float
    close_reason: TurnCloseReason
    candidates: int
    illegal_submissions: int
    move: Move | None
    last_info: dict[str, SearchInfoValue] | None = None
    worker_restarted: bool = False
    failure: str | None = None


@dataclass(slots=True)
class MatchResult(JsonCodec):
    """A played match: its configuration, the game, every decision and the result.

    Attributes:
        rules: The rules the match was played with.
        white_spec: The agent playing white.
        black_spec: The agent playing black.
        seed: The match seed, from which the seed of each seat is derived.
        budget_s: The time budget of every decision in seconds.
        record: The game, which replays to the final position.
        decisions: The decision behind every move of the game, in order.
        outcome: How the match ended.
        winner: The winning player, or `None` unless the outcome is a win.
        duration_s: The wall clock seconds of the whole match, including worker startup.
    """

    rules: Rules
    white_spec: Annotated[AgentSpec, Field(alias="white")]
    black_spec: Annotated[AgentSpec, Field(alias="black")]
    seed: int
    budget_s: float
    record: GameRecord
    decisions: list[DecisionRecord] = field(default_factory=list)
    outcome: MatchOutcome = MatchOutcome.TURN_CAP
    winner: Player | None = None
    duration_s: float = 0.0

    def spec(self, player: Player) -> AgentSpec:
        """Get the agent of a seat.

        Args:
            player: The seat.

        Returns:
            The spec of the agent playing `player`.
        """
        return self.white_spec if player is Player.WHITE else self.black_spec

    def add_decision(self, decision: DecisionRecord) -> None:
        """Record a decision and its move, keeping the decisions and the game in sync.

        Args:
            decision: The decision whose move was applied to the game.
        """
        self.decisions.append(decision)
        self.record.moves.append(decision.move)

    def thinking_s(self, player: Player) -> float:
        """Sum the decision times of one seat.

        Args:
            player: The seat.

        Returns:
            The total elapsed seconds of the decisions made for `player`.
        """
        return sum(
            decision.elapsed_s for decision in self.decisions if decision.player is player
        )
