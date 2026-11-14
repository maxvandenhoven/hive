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
from typing import ClassVar, Final, Literal

from pydantic import ConfigDict, computed_field

from hive.agents.factory import AgentSpec
from hive.engine.codec import JsonCodec
from hive.engine.rules import Rules
from hive.engine.state import Move, Player
from hive.match.records import DecisionRecord, MatchOutcome, MatchResult, TurnCloseReason
from hive.match.runner import MatchRunner, derive_seed
from hive.match.worker import DEFAULT_GRACE_S

GAUNTLET_REPORT_VERSION: Final = 2
"""The version of the report schema, raised on every incompatible change. Version 2 writes
the initial setup of a replayed game as `null` instead of `"initial"`."""

GAUNTLET_CONFIDENCE_Z = 1.959963984540054
"""The standard normal quantile of the 95% confidence interval of the win rate."""

GAUNTLET_OVERRUN_TOLERANCE_S = 0.05
"""The seconds past the deadline after which a decision counts as an overrun."""

GAUNTLET_ELO_PRIOR_GAMES = 1.0
"""Virtual drawn games added to every pairing, which keeps Elo finite for perfect play."""


def default_gauntlet_jobs(threads: int = 1) -> int:
    """Get the default and largest fair number of concurrent matches.

    A match has two worker processes, but only the seat to move thinks, so every match
    keeps `threads` CPUs busy at most.

    Args:
        threads: The largest search thread count of any participant.

    Returns:
        The number of matches that fit the CPUs, and at least one.
    """
    return max(1, (os.cpu_count() or 1) // threads)


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
class GauntletConfig(JsonCodec):
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
        openings: Opening sequences, shared by both colours of each pair.
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
    openings: tuple[tuple[Move | None, ...], ...] = ()

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
            opening=(
                self.openings[
                    (
                        match.index
                        // (len(self.participants) * (len(self.participants) - 1) // 2)
                        // 2
                    )
                    % len(self.openings)
                ]
                if self.openings
                else ()
            ),
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


@dataclass(frozen=True, slots=True)
class DecisionTimeSummary(JsonCodec):
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


@dataclass(frozen=True, slots=True)
class DecisionStats(JsonCodec):
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

    # The JSON form also holds the computed fields, which are not read back.
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

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

    @computed_field
    @property
    def mean_depth(self) -> float | None:
        """The mean reported search depth, or `None` if no depth was reported."""
        reported = sum(self.depth_reached.values())

        if not reported:
            return None

        return (
            sum(depth * count for depth, count in self.depth_reached.items()) / reported
        )

    @computed_field
    @property
    def timeout_rate(self) -> float:
        """The fraction of decisions closed by the deadline rather than by the agent."""
        return self.rate(self.close_reasons[TurnCloseReason.DEADLINE])

    @computed_field
    @property
    def overrun_rate(self) -> float:
        """The fraction of decisions that overran the deadline beyond the tolerance."""
        return self.rate(self.overruns)

    @computed_field
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


@dataclass(frozen=True, slots=True)
class ParticipantResult(JsonCodec):
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

    # The JSON form also holds the computed fields, which are not read back.
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    label: str
    spec: AgentSpec
    wins: int
    draws: int
    losses: int
    turn_caps: int
    elo: float
    decision_stats: DecisionStats

    @computed_field
    @property
    def games(self) -> int:
        """The number of games played."""
        return self.wins + self.draws + self.losses

    @computed_field
    @property
    def win_rate(self) -> float:
        """The score per game, counting a draw as half a win, or 0 without games."""
        return (self.wins + self.draws / 2) / self.games if self.games else 0.0

    @computed_field
    @property
    def win_rate_interval(self) -> tuple[float, float]:
        """The 95% Wilson score interval of the win rate."""
        return wilson_interval(
            proportion=self.win_rate, count=self.games, z=GAUNTLET_CONFIDENCE_Z
        )


@dataclass(frozen=True, slots=True)
class MatchSummary(JsonCodec):
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
            plies=len(result.opening) + len(result.decisions),
            duration_s=result.duration_s,
        )


@dataclass(frozen=True, slots=True)
class GauntletReport(JsonCodec):
    """The report of a played gauntlet, serialized as a versioned JSON document.

    Attributes:
        config: The config the gauntlet was played with.
        participants: The results of every participant, in the order of the config.
        matches: The summary of every match, in schedule order.
        replays: The full result of every match in schedule order, or `None` unless the
            config asks for replays.
        duration_s: The wall clock seconds of the whole gauntlet.
        version: The version of the report schema, which must be
            `GAUNTLET_REPORT_VERSION` when reading a report.
    """

    config: GauntletConfig
    participants: list[ParticipantResult]
    matches: list[MatchSummary]
    replays: list[MatchResult] | None
    duration_s: float
    version: Literal[2] = GAUNTLET_REPORT_VERSION

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
