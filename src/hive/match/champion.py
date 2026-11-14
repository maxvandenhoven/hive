"""Colour-paired champion trials built on the production gauntlet and match runner."""

import json
import math
import random
import statistics
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal

from hive.agents.factory import AgentSpec
from hive.engine.rules import Rules
from hive.engine.state import Move, Player
from hive.match.gauntlet import GauntletConfig, GauntletReport


@dataclass(frozen=True)
class ChampionGate:
    """The evidence a promotion needs, fixed before the trial is played.

    Attributes:
        min_pairs: The least number of opening pairs.
        min_budget_s: The least time per decision.
        bound: The lower bound of the pair scores that must exceed one half:
            `"hoeffding"` is valid for any distribution and conservative, `"normal"` is
            the usual normal approximation of the mean of independent pair scores.
    """

    min_pairs: int
    min_budget_s: float
    bound: Literal["hoeffding", "normal"]


STRICT_CHAMPION_GATE = ChampionGate(min_pairs=100, min_budget_s=10.0, bound="hoeffding")
"""The final confirmation gate: 100 pairs at ten seconds with Hoeffding's bound."""

FAST_CHAMPION_GATE = ChampionGate(min_pairs=50, min_budget_s=1.0, bound="normal")
"""The fast ratchet: 50 pairs at one second with the normal bound, within half an hour."""


@dataclass(frozen=True)
class ChampionAssessment:
    """The result of a champion trial from the candidate's side.

    Attributes:
        pairs: The number of opening pairs.
        score: Wins plus half the draws, per game.
        wins: Games the candidate won.
        draws: Drawn games, including turn caps.
        losses: Games the candidate lost.
        turn_caps: The draws stopped at the turn cap.
        lower_bound: The bound of the gate, compared with one half.
        hoeffding_lower_bound: Hoeffding's lower bound of the pair scores.
        normal_lower_bound: The normal approximation's lower bound of the pair scores.
        bound: The name of the bound the gate uses.
        alpha: The one-sided error probability of the bounds.
        candidate_mean_depth: The candidate's mean completed search depth.
        champion_mean_depth: The champion's mean completed search depth.
        candidate_nodes_per_s: The candidate's mean search speed.
        champion_nodes_per_s: The champion's mean search speed.
        healthy: Whether no worker failed, overran or submitted an illegal move.
        eligible: Whether the trial meets the gate and may promote the candidate.
    """

    pairs: int
    score: float
    wins: int
    draws: int
    losses: int
    turn_caps: int
    lower_bound: float
    hoeffding_lower_bound: float
    normal_lower_bound: float
    bound: str
    alpha: float
    candidate_mean_depth: float | None
    champion_mean_depth: float | None
    candidate_nodes_per_s: float | None
    champion_nodes_per_s: float | None
    healthy: bool
    eligible: bool


@dataclass(frozen=True)
class ChampionTrial:
    """A predeclared comparison with the incumbent, using independent opening pairs.

    Attributes:
        champion: The incumbent's complete agent specification.
        candidate: The proposed replacement's complete agent specification.
        pairs: Number of independently generated openings, each played in both colours.
        seed: First opening seed; confirmation seeds must be unseen during tuning.
        budget_s: Equal wall time per decision for both agents.
        jobs: Concurrent matches, accounting for the agents' search threads.
        max_turns: Turn cap per player; capped games score half a point.
        opening_plies: Random legal moves before timed play.
    """

    champion: AgentSpec
    candidate: AgentSpec
    pairs: int
    seed: int
    budget_s: float
    jobs: int = 1
    max_turns: int = 60
    opening_plies: int = 8

    def config(self) -> GauntletConfig:
        """Create a paired gauntlet with validated, nonterminal opening sequences.

        Returns:
            A gauntlet using production workers, deadlines and replay records.

        Raises:
            ValueError: If pair counts, budget, threads or opening settings are invalid.
        """
        from hive.match.gauntlet import default_gauntlet_jobs

        if self.pairs < 1 or self.budget_s <= 0 or not math.isfinite(self.budget_s):
            msg = "Pairs and budget must be positive and finite."
            raise ValueError(msg)

        if not 0 < self.opening_plies < 2 * self.max_turns:
            msg = "Opening plies must be positive and below the turn cap."
            raise ValueError(msg)

        specs = (self.champion, self.candidate)

        for spec in specs:
            spec.validate_params()

        threads = [spec.params.get("threads", 1) for spec in specs]

        if threads[0] != threads[1]:
            msg = "Champion and candidate must have equal thread budgets."
            raise ValueError(msg)

        thread_count = threads[0]
        assert isinstance(thread_count, int)

        if not 1 <= self.jobs <= default_gauntlet_jobs(threads=thread_count):
            msg = "Jobs times search threads must fit the available CPUs."
            raise ValueError(msg)

        rules = Rules()
        openings: list[tuple[Move | None, ...]] = []

        for seed in range(self.seed, self.seed + self.pairs):
            rng = random.Random(seed)
            state = rules.create_initial_state()
            moves: list[Move | None] = []

            for _ in range(self.opening_plies):
                choices = []

                for move in rules.legal_moves(state):
                    state.apply_move(move)
                    finished = rules.is_finished(state)
                    state.undo_move(move)

                    if not finished:
                        choices.append(move)

                if not choices:
                    msg = "Opening reached a forced terminal position."
                    raise ValueError(msg)

                move = rng.choice(choices)
                rules.apply_checked_move(state=state, move=move)
                moves.append(move)

            openings.append(tuple(moves))

        return GauntletConfig(
            participants=(
                AgentSpec(
                    kind=self.champion.kind, params=self.champion.params, label="champion"
                ),
                AgentSpec(
                    kind=self.candidate.kind,
                    params=self.candidate.params,
                    label="candidate",
                ),
            ),
            games_per_pair=2 * self.pairs,
            budget_s=self.budget_s,
            max_turns=self.max_turns,
            seed=self.seed,
            jobs=self.jobs,
            rules=rules,
            replays=True,
            openings=tuple(openings),
        )

    @staticmethod
    def pair_scores(report: GauntletReport) -> list[float]:
        """Score the candidate on each opening, over both colours.

        Args:
            report: Complete two-participant report with candidate second.

        Returns:
            The candidate's mean points per opening pair, in schedule order. Games
            `2k` and `2k + 1` share opening `k`.
        """
        points = [0.0] * (len(report.matches) // 2)

        for match in report.matches:
            if match.winner is None:
                points[match.index // 2] += 0.25
            elif (match.white == "candidate") == (match.winner is Player.WHITE):
                points[match.index // 2] += 0.5

        return points

    @staticmethod
    def assessment(
        report: GauntletReport,
        alpha: float = 0.05,
        gate: ChampionGate = STRICT_CHAMPION_GATE,
    ) -> ChampionAssessment:
        """Assess one predeclared trial with a lower bound over opening pairs.

        Args:
            report: Complete two-participant report with candidate second.
            alpha: One-sided error probability, allocated before observing results.
            gate: The sample size, budget and bound a promotion needs. Screening
                results never promote under the default strict gate.

        Returns:
            The candidate's results, both lower bounds, the speed of both sides and
            whether the trial is healthy and eligible for promotion.

        Raises:
            ValueError: If the report is incomplete or has the wrong participants.
        """
        if not 0 < alpha < 1 or report.config.labels != ["champion", "candidate"]:
            msg = "Expected a champion/candidate trial and 0 < alpha < 1."
            raise ValueError(msg)

        pairs = report.config.games_per_pair // 2

        if len(report.matches) != 2 * pairs or len(report.config.openings) != pairs:
            msg = "A trial needs a complete, distinct opening pair schedule."
            raise ValueError(msg)

        openings = {
            json.dumps([None if move is None else move.to_json() for move in opening])
            for opening in report.config.openings
        }

        if len(openings) != pairs:
            msg = "Confirmation openings must be distinct."
            raise ValueError(msg)

        champion, candidate = report.participants
        score = (candidate.wins + 0.5 * candidate.draws) / candidate.games
        hoeffding = max(0.0, score - math.sqrt(math.log(1 / alpha) / (2 * pairs)))
        points = ChampionTrial.pair_scores(report)
        spread = statistics.stdev(points) if pairs > 1 else 0.5
        normal = score - NormalDist().inv_cdf(1 - alpha) * spread / math.sqrt(pairs)
        lower = hoeffding if gate.bound == "hoeffding" else max(0.0, normal)
        healthy = all(
            not participant.decision_stats.flagged
            and participant.decision_stats.illegal_submissions == 0
            for participant in report.participants
        )
        eligible = (
            pairs >= gate.min_pairs
            and report.config.budget_s >= gate.min_budget_s
            and lower > 0.5
            and healthy
        )
        return ChampionAssessment(
            pairs=pairs,
            score=score,
            wins=candidate.wins,
            draws=candidate.draws,
            losses=candidate.losses,
            turn_caps=candidate.turn_caps,
            lower_bound=lower,
            hoeffding_lower_bound=hoeffding,
            normal_lower_bound=normal,
            bound=gate.bound,
            alpha=alpha,
            candidate_mean_depth=candidate.decision_stats.mean_depth,
            champion_mean_depth=champion.decision_stats.mean_depth,
            candidate_nodes_per_s=candidate.decision_stats.nodes_per_s,
            champion_nodes_per_s=champion.decision_stats.nodes_per_s,
            healthy=healthy,
            eligible=eligible,
        )
