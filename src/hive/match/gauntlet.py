"""Gauntlets: round robins of timed matches between agents, and their reports.

A gauntlet plays every pair of participants a fixed, even number of times with both
colours equally often. Match seeds are derived from the gauntlet seed, so every match can
be reproduced. Matches run in parallel threads, each driving two worker processes, and
the report aggregates their results and decision records.
"""

import itertools
import math
import os
import time
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from hive.agents.factory import AgentSpec
from hive.engine.rules import Rules
from hive.engine.serialization import (
    JsonValue,
    deserialize_player,
    deserialize_rules,
    serialize_player,
    serialize_rules,
)
from hive.engine.state import Player
from hive.match.records import (
    DecisionRecord,
    MatchOutcome,
    MatchResult,
    TurnCloseReason,
    expect_mapping,
)
from hive.match.runner import MatchRunner, derive_seed
from hive.match.worker import DEFAULT_GRACE_S

GAUNTLET_REPORT_VERSION = 1
"""The version of the report schema, raised on every incompatible change."""

GAUNTLET_CONFIDENCE_Z = 1.959963984540054
"""The standard normal quantile of the 95% confidence interval of the win rate."""

GAUNTLET_OVERRUN_TOLERANCE_S = 0.05
"""The seconds past the deadline after which a decision counts as an overrun."""

GAUNTLET_ELO_PRIOR_GAMES = 1.0
"""Virtual drawn games added to every pairing, which keeps Elo finite for perfect play."""


def default_gauntlet_jobs() -> int:
    """Get the default and largest fair number of concurrent matches.

    A match has two worker processes, but only the seat to move thinks, so every match
    keeps about one CPU busy.

    Returns:
        The number of CPUs, and at least one.
    """
    return os.cpu_count() or 1


def wilson_interval(proportion: float, count: int, z: float) -> tuple[float, float]:
    """Compute the Wilson score interval of a proportion.

    Args:
        proportion: The observed proportion between 0 and 1.
        count: The number of observations.
        z: The standard normal quantile of the confidence level.

    Returns:
        The lower and upper bound, or `(0, 1)` without observations.
    """
    if count == 0:
        return 0.0, 1.0

    denominator = 1 + z**2 / count
    center = (proportion + z**2 / (2 * count)) / denominator
    margin = (
        z
        / denominator
        * math.sqrt(proportion * (1 - proportion) / count + z**2 / (4 * count**2))
    )

    return max(0.0, center - margin), min(1.0, center + margin)


def nearest_rank(ordered: Sequence[float], fraction: float) -> float:
    """Get a percentile of a sorted sample with the nearest-rank method.

    Args:
        ordered: The sample, sorted in ascending order and not empty.
        fraction: The percentile as a fraction between 0 and 1, for example 0.9.

    Returns:
        The smallest value with at least `fraction` of the sample at or below it.
    """
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def estimate_elo(
    points: Sequence[Sequence[float]],
    games: Sequence[Sequence[int]],
    prior_games: float = GAUNTLET_ELO_PRIOR_GAMES,
    iterations: int = 10_000,
    tolerance: float = 1e-10,
) -> list[float]:
    """Estimate Elo ratings from pairwise results with a Bradley-Terry model.

    The ratings are fitted with the minorization-maximization algorithm, counting a draw
    as half a win for both sides. Every pairing that was played gets `prior_games`
    virtual draws, so a participant that won or lost every game still gets a finite
    rating.

    Args:
        points: `points[i][j]` is the score of participant `i` against `j`.
        games: `games[i][j]` is the number of games between `i` and `j`.
        prior_games: The number of virtual drawn games added to every played pairing.
        iterations: The maximum number of iterations.
        tolerance: The largest relative change of a strength at which the fit stops.

    Returns:
        The rating of every participant, with a mean of 0. Participants without games
        are rated 0.
    """
    size = len(points)
    played = [
        [games[i][j] + prior_games if games[i][j] > 0 else 0.0 for j in range(size)]
        for i in range(size)
    ]
    wins = [
        sum(points[i][j] + prior_games / 2 for j in range(size) if games[i][j] > 0)
        for i in range(size)
    ]
    active = [i for i in range(size) if any(played[i])]
    strengths = [1.0] * size

    for _ in range(iterations):
        updated = list(strengths)

        for i in active:
            updated[i] = wins[i] / sum(
                played[i][j] / (strengths[i] + strengths[j])
                for j in range(size)
                if played[i][j] > 0
            )

        scale = math.exp(sum(math.log(updated[i]) for i in active) / max(len(active), 1))
        updated = [strength / scale for strength in updated]
        change = max(
            (abs(updated[i] - strengths[i]) / strengths[i] for i in active), default=0.0
        )
        strengths = updated

        if change < tolerance:
            break

    return [400 * math.log10(strengths[i]) if i in active else 0.0 for i in range(size)]


@dataclass(frozen=True, slots=True)
class ScheduledMatch:
    """One match of a gauntlet schedule.

    Attributes:
        index: The position of the match in the schedule.
        white: The index of the participant playing white.
        black: The index of the participant playing black.
        seed: The match seed, derived from the gauntlet seed and the index.
    """

    index: int
    white: int
    black: int
    seed: int


@dataclass(frozen=True, slots=True)
class GauntletConfig:
    """The participants and settings of a gauntlet, which reproduce it from its seed.

    Attributes:
        participants: The agents, with unique display labels.
        games_per_pair: The number of games between every pair, an even number so both
            colours are played equally often.
        budget_s: The time budget of every decision in seconds.
        max_turns: The number of turns per player after which a match stops without a
            result, or `None` to play every game to the end.
        seed: The gauntlet seed, from which every match seed is derived.
        jobs: The number of matches played at the same time.
        grace_s: The number of seconds an agent may take to return after it was stopped
            before its worker is restarted.
        rules: The rules of every match.
        replays: Whether the report keeps the full result of every match.
    """

    participants: tuple[AgentSpec, ...]
    games_per_pair: int
    budget_s: float
    max_turns: int | None
    seed: int
    jobs: int = 1
    grace_s: float = DEFAULT_GRACE_S
    rules: Rules = field(default_factory=Rules)
    replays: bool = False

    def __post_init__(self) -> None:
        """Check the participants and settings.

        Raises:
            ValueError: If there are fewer than two participants, two participants share
                a label, `games_per_pair` is not a positive even number or `jobs` is not
                positive.
        """
        if len(self.participants) < 2:
            msg = "A gauntlet needs at least two participants."
            raise ValueError(msg)

        duplicates = sorted(
            label for label, count in Counter(self.labels).items() if count > 1
        )

        if duplicates:
            msg = (
                f"Participant labels must be unique, but {', '.join(duplicates)} "
                "appear more than once. Give the participants distinct labels."
            )
            raise ValueError(msg)

        if self.games_per_pair < 2 or self.games_per_pair % 2:
            msg = (
                "The number of games per pair must be a positive even number, so both "
                f"colours are played equally often, but got {self.games_per_pair}."
            )
            raise ValueError(msg)

        if self.jobs < 1:
            msg = f"The number of jobs must be positive, but got {self.jobs}."
            raise ValueError(msg)

    @property
    def labels(self) -> list[str]:
        """The display label of every participant, in order."""
        return [spec.display_label for spec in self.participants]

    def schedule(self) -> list[ScheduledMatch]:
        """Schedule the round robin.

        The games are played in rounds: every pair plays once per round, and the colours
        of a pair swap from one round to the next.

        Returns:
            Every match, in order of its index.
        """
        pairs = list(itertools.combinations(range(len(self.participants)), 2))
        matches: list[ScheduledMatch] = []

        for game in range(self.games_per_pair):
            for first, second in pairs:
                white, black = (first, second) if game % 2 == 0 else (second, first)
                index = len(matches)
                matches.append(
                    ScheduledMatch(
                        index=index,
                        white=white,
                        black=black,
                        seed=derive_seed(self.seed, "match", index),
                    )
                )

        return matches

    def match_runner(self, match: ScheduledMatch) -> MatchRunner:
        """Configure the runner of a scheduled match.

        Args:
            match: The scheduled match.

        Returns:
            The runner, with the participants of the match and the gauntlet settings.
        """
        return MatchRunner(
            rules=self.rules,
            white_spec=self.participants[match.white],
            black_spec=self.participants[match.black],
            budget_s=self.budget_s,
            max_turns=self.max_turns,
            seed=match.seed,
            grace_s=self.grace_s,
        )

    def run(
        self,
        *,
        match_callback: Callable[[ScheduledMatch, MatchResult], None] | None = None,
    ) -> "GauntletReport":
        """Play every scheduled match, `jobs` at a time.

        Args:
            match_callback: Called in the calling thread with every finished match, in
                order of completion.

        Returns:
            The report.

        Raises:
            AgentWorkerError: If a worker fails to start. Matches that have not started
                are cancelled, and running matches are played to the end.
        """
        start = time.monotonic()
        schedule = self.schedule()
        results: dict[int, MatchResult] = {}

        with ThreadPoolExecutor(
            max_workers=self.jobs, thread_name_prefix="gauntlet"
        ) as executor:
            futures: dict[Future[MatchResult], ScheduledMatch] = {
                executor.submit(self.match_runner(match).run): match for match in schedule
            }

            try:
                for future in as_completed(futures):
                    match = futures[future]
                    results[match.index] = future.result()

                    if match_callback is not None:
                        match_callback(match, results[match.index])
            except BaseException:
                executor.shutdown(cancel_futures=True)
                raise

        return GauntletReport.from_results(
            config=self,
            results=[results[match.index] for match in schedule],
            duration_s=time.monotonic() - start,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize the config.

        Returns:
            An object with every field, where the participants are serialized specs.
        """
        return {
            "participants": [spec.to_dict() for spec in self.participants],
            "games_per_pair": self.games_per_pair,
            "budget_s": self.budget_s,
            "max_turns": self.max_turns,
            "seed": self.seed,
            "jobs": self.jobs,
            "grace_s": self.grace_s,
            "rules": serialize_rules(self.rules),
            "replays": self.replays,
        }

    @classmethod
    def from_dict(cls, data: object) -> "GauntletConfig":
        """Deserialize a config.

        Args:
            data: The serialized config.

        Returns:
            The config.

        Raises:
            ValueError: If `data` is not a valid serialized config.
        """
        fields = expect_mapping(data=data, kind="gauntlet config")

        try:
            max_turns = fields["max_turns"]
            return cls(
                participants=tuple(
                    AgentSpec.from_dict(spec) for spec in fields["participants"]
                ),
                games_per_pair=int(fields["games_per_pair"]),
                budget_s=float(fields["budget_s"]),
                max_turns=None if max_turns is None else int(max_turns),
                seed=int(fields["seed"]),
                jobs=int(fields["jobs"]),
                grace_s=float(fields["grace_s"]),
                rules=deserialize_rules(fields["rules"]),
                replays=bool(fields["replays"]),
            )
        except (KeyError, TypeError) as e:
            msg = f"Invalid gauntlet config: {e!r}."
            raise ValueError(msg) from e


@dataclass(frozen=True, slots=True)
class DecisionTimeSummary:
    """Summary statistics of a sample of non-negative values, such as overruns.

    Attributes:
        count: The number of values.
        mean: The mean, or 0 without values.
        p50: The median (nearest rank), or 0 without values.
        p90: The 90th percentile (nearest rank), or 0 without values.
        max: The largest value, or 0 without values.
    """

    count: int
    mean: float
    p50: float
    p90: float
    max: float

    @classmethod
    def from_values(cls, values: Sequence[float]) -> "DecisionTimeSummary":
        """Summarise a sample.

        Args:
            values: The sample.

        Returns:
            The summary.
        """
        if not values:
            return cls(count=0, mean=0.0, p50=0.0, p90=0.0, max=0.0)

        ordered = sorted(values)

        return cls(
            count=len(ordered),
            mean=sum(ordered) / len(ordered),
            p50=nearest_rank(ordered=ordered, fraction=0.5),
            p90=nearest_rank(ordered=ordered, fraction=0.9),
            max=ordered[-1],
        )

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize the summary.

        Returns:
            An object with every field.
        """
        return {
            "count": self.count,
            "mean": self.mean,
            "p50": self.p50,
            "p90": self.p90,
            "max": self.max,
        }

    @classmethod
    def from_dict(cls, data: object) -> "DecisionTimeSummary":
        """Deserialize a summary.

        Args:
            data: The serialized summary.

        Returns:
            The summary.

        Raises:
            KeyError: If a field is missing.
            ValueError: If `data` is not an object.
        """
        fields = expect_mapping(data=data, kind="distribution summary")
        return cls(
            count=int(fields["count"]),
            mean=float(fields["mean"]),
            p50=float(fields["p50"]),
            p90=float(fields["p90"]),
            max=float(fields["max"]),
        )


@dataclass(frozen=True, slots=True)
class DecisionStats:
    """Aggregated decision records of one participant, the observability of a gauntlet.

    Attributes:
        decisions: The number of decisions.
        depth_reached: The number of decisions by the last search depth the agent
            reported. Decisions without a reported depth are not counted.
        nodes_per_s: The mean reported search speed, or `None` if no speed was reported.
        close_reasons: The number of decisions by why their turn closed.
        elapsed_s: The seconds from sending the state to closing the turn.
        overrun_s: The seconds past the deadline until the worker returned.
        overruns: The number of decisions that overran the deadline by more than
            `GAUNTLET_OVERRUN_TOLERANCE_S`.
        failures: The number of decisions in which the agent raised or its worker failed.
        worker_restarts: The number of decisions after which the worker was restarted.
        illegal_submissions: The number of rejected submissions.
    """

    decisions: int
    depth_reached: dict[int, int]
    nodes_per_s: float | None
    close_reasons: dict[TurnCloseReason, int]
    elapsed_s: DecisionTimeSummary
    overrun_s: DecisionTimeSummary
    overruns: int
    failures: int
    worker_restarts: int
    illegal_submissions: int

    @classmethod
    def from_decisions(cls, decisions: Sequence[DecisionRecord]) -> "DecisionStats":
        """Aggregate decision records.

        Args:
            decisions: The decisions of one participant.

        Returns:
            The statistics.
        """
        depths: Counter[int] = Counter()
        speeds: list[float] = []

        for decision in decisions:
            info = decision.last_info or {}
            depth, nps = info.get("depth"), info.get("nps")

            if isinstance(depth, int) and not isinstance(depth, bool):
                depths[depth] += 1

            if isinstance(nps, int | float) and not isinstance(nps, bool):
                speeds.append(float(nps))

        close_reasons = dict.fromkeys(TurnCloseReason, 0)
        close_reasons.update(Counter(decision.close_reason for decision in decisions))

        return cls(
            decisions=len(decisions),
            depth_reached=dict(sorted(depths.items())),
            nodes_per_s=sum(speeds) / len(speeds) if speeds else None,
            close_reasons=close_reasons,
            elapsed_s=DecisionTimeSummary.from_values([d.elapsed_s for d in decisions]),
            overrun_s=DecisionTimeSummary.from_values([d.overrun_s for d in decisions]),
            overruns=sum(d.overrun_s > GAUNTLET_OVERRUN_TOLERANCE_S for d in decisions),
            failures=sum(d.failure is not None for d in decisions),
            worker_restarts=sum(d.worker_restarted for d in decisions),
            illegal_submissions=sum(d.illegal_submissions for d in decisions),
        )

    @property
    def mean_depth(self) -> float | None:
        """The mean reported search depth, or `None` if no depth was reported."""
        reported = sum(self.depth_reached.values())

        if not reported:
            return None

        return (
            sum(depth * count for depth, count in self.depth_reached.items()) / reported
        )

    @property
    def timeout_rate(self) -> float:
        """The fraction of decisions closed by the deadline rather than by the agent."""
        return self.rate(self.close_reasons[TurnCloseReason.DEADLINE])

    @property
    def overrun_rate(self) -> float:
        """The fraction of decisions that overran the deadline beyond the tolerance."""
        return self.rate(self.overruns)

    @property
    def flagged(self) -> bool:
        """Whether the agent failed, overran, needed a restart or never submitted."""
        return bool(
            self.failures
            or self.overruns
            or self.worker_restarts
            or self.close_reasons[TurnCloseReason.NO_CANDIDATE]
        )

    def rate(self, count: int) -> float:
        """Divide a count by the number of decisions.

        Args:
            count: The number of decisions with some property.

        Returns:
            The fraction of decisions, or 0 without decisions.
        """
        return count / self.decisions if self.decisions else 0.0

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize the statistics.

        Returns:
            An object with every field and the derived rates, mean depth and flag.
        """
        return {
            "decisions": self.decisions,
            "depth_reached": {str(depth): n for depth, n in self.depth_reached.items()},
            "mean_depth": self.mean_depth,
            "nodes_per_s": self.nodes_per_s,
            "close_reasons": {
                reason.value: count for reason, count in self.close_reasons.items()
            },
            "timeout_rate": self.timeout_rate,
            "elapsed_s": self.elapsed_s.to_dict(),
            "overrun_s": self.overrun_s.to_dict(),
            "overruns": self.overruns,
            "overrun_rate": self.overrun_rate,
            "failures": self.failures,
            "worker_restarts": self.worker_restarts,
            "illegal_submissions": self.illegal_submissions,
            "flagged": self.flagged,
        }

    @classmethod
    def from_dict(cls, data: object) -> "DecisionStats":
        """Deserialize statistics, ignoring the derived values.

        Args:
            data: The serialized statistics.

        Returns:
            The statistics.

        Raises:
            KeyError: If a field is missing.
            ValueError: If `data` is not an object or a close reason is unknown.
        """
        fields = expect_mapping(data=data, kind="decision stats")
        nodes_per_s = fields["nodes_per_s"]

        return cls(
            decisions=int(fields["decisions"]),
            depth_reached={
                int(depth): int(count) for depth, count in fields["depth_reached"].items()
            },
            nodes_per_s=None if nodes_per_s is None else float(nodes_per_s),
            close_reasons={
                TurnCloseReason(reason): int(count)
                for reason, count in fields["close_reasons"].items()
            },
            elapsed_s=DecisionTimeSummary.from_dict(fields["elapsed_s"]),
            overrun_s=DecisionTimeSummary.from_dict(fields["overrun_s"]),
            overruns=int(fields["overruns"]),
            failures=int(fields["failures"]),
            worker_restarts=int(fields["worker_restarts"]),
            illegal_submissions=int(fields["illegal_submissions"]),
        )


@dataclass(frozen=True, slots=True)
class ParticipantResult:
    """The results and decision statistics of one participant of a gauntlet.

    Attributes:
        label: The display label of the participant.
        spec: The agent.
        wins: The number of games won.
        draws: The number of games without a winner, including those stopped at the turn
            cap.
        losses: The number of games lost.
        turn_caps: The number of the draws that were stopped at the turn cap.
        elo: The Elo rating estimated from all results, relative to a field mean of 0.
        decision_stats: The aggregated decision records.
    """

    label: str
    spec: AgentSpec
    wins: int
    draws: int
    losses: int
    turn_caps: int
    elo: float
    decision_stats: DecisionStats

    @property
    def games(self) -> int:
        """The number of games played."""
        return self.wins + self.draws + self.losses

    @property
    def win_rate(self) -> float:
        """The score per game, counting a draw as half a win, or 0 without games."""
        return (self.wins + self.draws / 2) / self.games if self.games else 0.0

    @property
    def win_rate_interval(self) -> tuple[float, float]:
        """The 95% Wilson score interval of the win rate."""
        return wilson_interval(
            proportion=self.win_rate, count=self.games, z=GAUNTLET_CONFIDENCE_Z
        )

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize the result.

        Returns:
            An object with every field and the derived games, win rate and interval.
        """
        low, high = self.win_rate_interval
        return {
            "label": self.label,
            "spec": self.spec.to_dict(),
            "games": self.games,
            "wins": self.wins,
            "draws": self.draws,
            "losses": self.losses,
            "turn_caps": self.turn_caps,
            "win_rate": self.win_rate,
            "win_rate_interval": [low, high],
            "elo": self.elo,
            "decision_stats": self.decision_stats.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ParticipantResult":
        """Deserialize a result, ignoring the derived values.

        Args:
            data: The serialized result.

        Returns:
            The result.

        Raises:
            KeyError: If a field is missing.
            ValueError: If `data` is not a valid serialized result.
        """
        fields = expect_mapping(data=data, kind="participant result")
        return cls(
            label=str(fields["label"]),
            spec=AgentSpec.from_dict(fields["spec"]),
            wins=int(fields["wins"]),
            draws=int(fields["draws"]),
            losses=int(fields["losses"]),
            turn_caps=int(fields["turn_caps"]),
            elo=float(fields["elo"]),
            decision_stats=DecisionStats.from_dict(fields["decision_stats"]),
        )


@dataclass(frozen=True, slots=True)
class MatchSummary:
    """The outcome of one match of a gauntlet, without its moves and decisions.

    Attributes:
        index: The position of the match in the schedule.
        white: The label of the participant playing white.
        black: The label of the participant playing black.
        seed: The match seed.
        outcome: How the match ended.
        winner: The winning player, or `None` unless the outcome is a win.
        plies: The number of moves played.
        duration_s: The wall clock seconds of the match.
    """

    index: int
    white: str
    black: str
    seed: int
    outcome: MatchOutcome
    winner: Player | None
    plies: int
    duration_s: float

    @classmethod
    def from_result(cls, index: int, result: MatchResult) -> "MatchSummary":
        """Summarise a played match.

        Args:
            index: The position of the match in the schedule.
            result: The result of the match.

        Returns:
            The summary.
        """
        return cls(
            index=index,
            white=result.white_spec.display_label,
            black=result.black_spec.display_label,
            seed=result.seed,
            outcome=result.outcome,
            winner=result.winner,
            plies=len(result.decisions),
            duration_s=result.duration_s,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize the summary.

        Returns:
            An object with every field.
        """
        return {
            "index": self.index,
            "white": self.white,
            "black": self.black,
            "seed": self.seed,
            "outcome": self.outcome.value,
            "winner": None if self.winner is None else serialize_player(self.winner),
            "plies": self.plies,
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, data: object) -> "MatchSummary":
        """Deserialize a summary.

        Args:
            data: The serialized summary.

        Returns:
            The summary.

        Raises:
            KeyError: If a field is missing.
            ValueError: If `data` is not a valid serialized summary.
        """
        fields = expect_mapping(data=data, kind="match summary")
        winner = fields["winner"]

        return cls(
            index=int(fields["index"]),
            white=str(fields["white"]),
            black=str(fields["black"]),
            seed=int(fields["seed"]),
            outcome=MatchOutcome(fields["outcome"]),
            winner=None if winner is None else deserialize_player(winner),
            plies=int(fields["plies"]),
            duration_s=float(fields["duration_s"]),
        )


@dataclass(frozen=True, slots=True)
class GauntletReport:
    """The report of a played gauntlet, serialized as a versioned JSON document.

    Attributes:
        config: The config the gauntlet was played with.
        participants: The results of every participant, in the order of the config.
        matches: The summary of every match, in schedule order.
        replays: The full result of every match in schedule order, or `None` unless the
            config asks for replays.
        duration_s: The wall clock seconds of the whole gauntlet.
    """

    config: GauntletConfig
    participants: list[ParticipantResult]
    matches: list[MatchSummary]
    replays: list[MatchResult] | None
    duration_s: float

    @classmethod
    def from_results(
        cls, config: GauntletConfig, results: Sequence[MatchResult], duration_s: float
    ) -> "GauntletReport":
        """Aggregate the results of every scheduled match.

        Args:
            config: The config the gauntlet was played with.
            results: The result of every match, in schedule order.
            duration_s: The wall clock seconds of the whole gauntlet.

        Returns:
            The report.
        """
        size = len(config.participants)
        points = [[0.0] * size for _ in range(size)]
        games = [[0] * size for _ in range(size)]
        wins, draws, turn_caps = [0] * size, [0] * size, [0] * size
        decisions: list[list[DecisionRecord]] = [[] for _ in range(size)]

        for match, result in zip(config.schedule(), results, strict=True):
            seats = {Player.WHITE: match.white, Player.BLACK: match.black}
            games[match.white][match.black] += 1
            games[match.black][match.white] += 1

            if result.winner is not None:
                winner, loser = seats[result.winner], seats[result.winner.opponent]
                points[winner][loser] += 1.0
                wins[winner] += 1
            else:
                points[match.white][match.black] += 0.5
                points[match.black][match.white] += 0.5
                draws[match.white] += 1
                draws[match.black] += 1

            if result.outcome is MatchOutcome.TURN_CAP:
                turn_caps[match.white] += 1
                turn_caps[match.black] += 1

            for decision in result.decisions:
                decisions[seats[decision.player]].append(decision)

        elo = estimate_elo(points=points, games=games)
        participants = [
            ParticipantResult(
                label=spec.display_label,
                spec=spec,
                wins=wins[i],
                draws=draws[i],
                losses=sum(games[i]) - wins[i] - draws[i],
                turn_caps=turn_caps[i],
                elo=elo[i],
                decision_stats=DecisionStats.from_decisions(decisions[i]),
            )
            for i, spec in enumerate(config.participants)
        ]

        return cls(
            config=config,
            participants=participants,
            matches=[
                MatchSummary.from_result(index=index, result=result)
                for index, result in enumerate(results)
            ],
            replays=list(results) if config.replays else None,
            duration_s=duration_s,
        )

    def replay(self, index: int) -> MatchResult:
        """Get the full result of a match.

        Args:
            index: The position of the match in the schedule.

        Returns:
            The result, with every move and decision.

        Raises:
            ValueError: If the report has no replays or no match with this index.
        """
        if self.replays is None:
            msg = "The report has no replays. Run the gauntlet again with `--replays`."
            raise ValueError(msg)

        if not 0 <= index < len(self.replays):
            msg = f"No match {index}, expected 0 to {len(self.replays) - 1}."
            raise ValueError(msg)

        return self.replays[index]

    def summary_table(self) -> str:
        """Format the standings as a plain text table, best Elo first.

        Flagged participants (failures, overruns, restarts or missing submissions) are
        marked with `!`.

        Returns:
            The table, one line per participant below a header.
        """
        header = (
            f"{'agent':<16} {'games':>5} {'W':>4} {'D':>4} {'L':>4} {'win rate':>8} "
            f"{'95% CI':>11} {'Elo':>6} {'depth':>5} {'timeouts':>8} {'overruns':>8} "
            f"{'failures':>8} {'illegal':>7}"
        )
        lines = [header]

        for result in sorted(self.participants, key=lambda r: r.elo, reverse=True):
            stats = result.decision_stats
            low, high = result.win_rate_interval
            depth = "-" if stats.mean_depth is None else f"{stats.mean_depth:.1f}"
            label = f"{result.label}{' !' if stats.flagged else ''}"
            lines.append(
                f"{label:<16} {result.games:>5} {result.wins:>4} {result.draws:>4} "
                f"{result.losses:>4} {result.win_rate:>8.3f} {low:>5.2f}-{high:<5.2f} "
                f"{result.elo:>+6.0f} {depth:>5} {stats.timeout_rate:>8.1%} "
                f"{stats.overrun_rate:>8.1%} {stats.failures:>8} "
                f"{stats.illegal_submissions:>7}"
            )

        return "\n".join(lines)

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize the report.

        Returns:
            An object with the schema version, the config, the participant results, the
            match summaries, the replays (or `None`) and the duration.
        """
        return {
            "version": GAUNTLET_REPORT_VERSION,
            "config": self.config.to_dict(),
            "participants": [result.to_dict() for result in self.participants],
            "matches": [match.to_dict() for match in self.matches],
            "replays": None
            if self.replays is None
            else [result.to_dict() for result in self.replays],
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, data: object) -> "GauntletReport":
        """Deserialize a report.

        Args:
            data: The serialized report.

        Returns:
            The report.

        Raises:
            ValueError: If `data` is not a valid serialized report or has another schema
                version.
        """
        fields = expect_mapping(data=data, kind="gauntlet report")
        version = fields.get("version")

        if version != GAUNTLET_REPORT_VERSION:
            msg = (
                f"Unsupported gauntlet report version `{version}`, expected "
                f"{GAUNTLET_REPORT_VERSION}."
            )
            raise ValueError(msg)

        try:
            replays = fields["replays"]
            return cls(
                config=GauntletConfig.from_dict(fields["config"]),
                participants=[
                    ParticipantResult.from_dict(result)
                    for result in fields["participants"]
                ],
                matches=[MatchSummary.from_dict(match) for match in fields["matches"]],
                replays=None
                if replays is None
                else [MatchResult.from_dict(result) for result in replays],
                duration_s=float(fields["duration_s"]),
            )
        except (KeyError, TypeError, AttributeError) as e:
            msg = f"Invalid gauntlet report: {e!r}."
            raise ValueError(msg) from e
