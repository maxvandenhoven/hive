"""Records of timed decisions and matches, serializable to JSON-compatible values."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from hive.agents.base import SearchInfoValue
from hive.agents.factory import AgentSpec
from hive.engine.rules import Rules
from hive.engine.serialization import (
    GameRecord,
    JsonValue,
    deserialize_move,
    deserialize_player,
    deserialize_record,
    deserialize_rules,
    serialize_move,
    serialize_player,
    serialize_record,
    serialize_rules,
)
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
class DecisionRecord:
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

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize the record.

        Returns:
            An object with every field, where the player, close reason and move are
            serialized like the engine values.
        """
        return {
            "ply": self.ply,
            "player": serialize_player(self.player),
            "agent_label": self.agent_label,
            "seed": self.seed,
            "budget_s": self.budget_s,
            "elapsed_s": self.elapsed_s,
            "overrun_s": self.overrun_s,
            "close_reason": self.close_reason.value,
            "candidates": self.candidates,
            "illegal_submissions": self.illegal_submissions,
            "move": serialize_move(self.move),
            "last_info": self.last_info,
            "worker_restarted": self.worker_restarted,
            "failure": self.failure,
        }

    @classmethod
    def from_dict(cls, data: object) -> "DecisionRecord":
        """Deserialize a record.

        Args:
            data: The serialized record.

        Returns:
            The record.

        Raises:
            ValueError: If `data` is not a valid serialized record.
        """
        fields = expect_mapping(data=data, kind="decision record")

        try:
            return cls(
                ply=int(fields["ply"]),
                player=deserialize_player(fields["player"]),
                agent_label=str(fields["agent_label"]),
                seed=int(fields["seed"]),
                budget_s=float(fields["budget_s"]),
                elapsed_s=float(fields["elapsed_s"]),
                overrun_s=float(fields["overrun_s"]),
                close_reason=TurnCloseReason(fields["close_reason"]),
                candidates=int(fields["candidates"]),
                illegal_submissions=int(fields["illegal_submissions"]),
                move=deserialize_move(fields["move"]),
                last_info=fields["last_info"],
                worker_restarted=bool(fields["worker_restarted"]),
                failure=fields["failure"],
            )
        except (KeyError, TypeError) as e:
            msg = f"Invalid decision record: {e!r}."
            raise ValueError(msg) from e


@dataclass(slots=True)
class MatchResult:
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
    white_spec: AgentSpec
    black_spec: AgentSpec
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

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize the result.

        Returns:
            An object with every field, where the game record and decisions are
            serialized objects.
        """
        return {
            "rules": serialize_rules(self.rules),
            "white": self.white_spec.to_dict(),
            "black": self.black_spec.to_dict(),
            "seed": self.seed,
            "budget_s": self.budget_s,
            "record": serialize_record(self.record),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "outcome": self.outcome.value,
            "winner": None if self.winner is None else serialize_player(self.winner),
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, data: object) -> "MatchResult":
        """Deserialize a result.

        Args:
            data: The serialized result.

        Returns:
            The result.

        Raises:
            ValueError: If `data` is not a valid serialized result, including specs of
                agent kinds that are not registered.
        """
        fields = expect_mapping(data=data, kind="match result")

        try:
            winner = fields["winner"]
            return cls(
                rules=deserialize_rules(fields["rules"]),
                white_spec=AgentSpec.from_dict(fields["white"]),
                black_spec=AgentSpec.from_dict(fields["black"]),
                seed=int(fields["seed"]),
                budget_s=float(fields["budget_s"]),
                record=deserialize_record(fields["record"]),
                decisions=[
                    DecisionRecord.from_dict(decision) for decision in fields["decisions"]
                ],
                outcome=MatchOutcome(fields["outcome"]),
                winner=None if winner is None else deserialize_player(winner),
                duration_s=float(fields["duration_s"]),
            )
        except (KeyError, TypeError) as e:
            msg = f"Invalid match result: {e!r}."
            raise ValueError(msg) from e


def expect_mapping(data: object, kind: str) -> Mapping[str, Any]:
    """Check that a serialized value is an object.

    Args:
        data: The value to check.
        kind: The name of the object in error messages, for example `match result`.

    Returns:
        The value as a mapping.

    Raises:
        ValueError: If `data` is not a mapping.
    """
    if not isinstance(data, Mapping):
        msg = f"Expected a {kind} object, but got `{data!r}`."
        raise ValueError(msg)

    return data
