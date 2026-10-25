"""Tests of gauntlet schedules, statistics and reports, partly with worker processes."""

import json
import math
from collections import Counter
from typing import Any

import pytest

from hive.agents.factory import AgentSpec
from hive.engine.rules import Rules
from hive.engine.serialization import GameRecord
from hive.engine.state import Player
from hive.match.gauntlet import (
    GAUNTLET_REPORT_VERSION,
    DecisionStats,
    DecisionTimeSummary,
    GauntletConfig,
    GauntletReport,
    estimate_elo,
    wilson_interval,
)
from hive.match.records import DecisionRecord, MatchOutcome, MatchResult, TurnCloseReason
from hive.match.worker import AgentWorkerError

RANDOM = AgentSpec("random")
NEGAMAX = AgentSpec(kind="negamax", params={"depth": 1}, label="nm1")


def make_config(
    participants: tuple[AgentSpec, ...] = (RANDOM, NEGAMAX), **overrides: Any
) -> GauntletConfig:
    """Build a small config with short matches, overriding any field."""
    fields: dict[str, Any] = {
        "participants": participants,
        "games_per_pair": 2,
        "budget_s": 1.0,
        "max_turns": 5,
        "seed": 0,
    }
    fields.update(overrides)

    return GauntletConfig(**fields)


def make_decision(
    player: Player = Player.WHITE,
    close_reason: TurnCloseReason = TurnCloseReason.FINAL,
    overrun_s: float = 0.0,
    last_info: dict | None = None,
    failure: str | None = None,
    worker_restarted: bool = False,
    illegal_submissions: int = 0,
) -> DecisionRecord:
    """Build a decision record with a pass and the given details."""
    return DecisionRecord(
        ply=0,
        player=player,
        agent_label="agent",
        seed=0,
        budget_s=1.0,
        elapsed_s=0.5,
        overrun_s=overrun_s,
        close_reason=close_reason,
        candidates=1,
        illegal_submissions=illegal_submissions,
        move=None,
        last_info=last_info,
        worker_restarted=worker_restarted,
        failure=failure,
    )


def make_result(
    config: GauntletConfig,
    index: int,
    outcome: MatchOutcome,
    winner: Player | None = None,
    decisions: list[DecisionRecord] | None = None,
) -> MatchResult:
    """Build the result of a scheduled match without playing it."""
    match = config.schedule()[index]
    return MatchResult(
        rules=config.rules,
        white_spec=config.participants[match.white],
        black_spec=config.participants[match.black],
        seed=match.seed,
        budget_s=config.budget_s,
        record=GameRecord(config.rules),
        decisions=decisions or [],
        outcome=outcome,
        winner=winner,
    )


class TestGauntletConfig:
    def test_schedule_is_balanced(self) -> None:
        config = make_config(
            participants=(RANDOM, NEGAMAX, AgentSpec(kind="random", label="r2")),
            games_per_pair=4,
        )

        schedule = config.schedule()

        assert [match.index for match in schedule] == list(range(12))
        assert Counter((match.white, match.black) for match in schedule) == {
            (0, 1): 2,
            (1, 0): 2,
            (0, 2): 2,
            (2, 0): 2,
            (1, 2): 2,
            (2, 1): 2,
        }
        assert Counter(m.white for m in schedule) == Counter(m.black for m in schedule)
        assert len({match.seed for match in schedule}) == 12

    def test_seeds_are_deterministic(self) -> None:
        def seeds(seed: int) -> list[int]:
            return [match.seed for match in make_config(seed=seed).schedule()]

        assert seeds(1) == seeds(1)
        assert seeds(1) != seeds(2)

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"participants": (RANDOM,)}, "at least two participants"),
            ({"participants": (RANDOM, RANDOM)}, "random appear more than once"),
            ({"games_per_pair": 3}, "positive even number"),
            ({"games_per_pair": 0}, "positive even number"),
            ({"jobs": 0}, "jobs must be positive"),
        ],
    )
    def test_rejects_invalid(self, overrides: dict[str, Any], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            make_config(**overrides)

    def test_round_trip(self) -> None:
        config = make_config(
            max_turns=None, jobs=3, replays=True, rules=Rules(max_turns=9)
        )

        assert (
            GauntletConfig.from_dict(json.loads(json.dumps(config.to_dict()))) == config
        )

    def test_from_dict_rejects_missing_field(self) -> None:
        data = make_config().to_dict()
        del data["seed"]

        with pytest.raises(ValueError, match="Invalid gauntlet config"):
            GauntletConfig.from_dict(data)


class TestStatistics:
    @pytest.mark.parametrize(
        ("proportion", "count", "expected"),
        [
            (0.5, 0, (0.0, 1.0)),
            (1.0, 4, (0.5101, 1.0)),
            (0.0, 4, (0.0, 0.4899)),
            (0.5, 100, (0.4038, 0.5962)),
        ],
    )
    def test_wilson_interval(
        self, proportion: float, count: int, expected: tuple[float, float]
    ) -> None:
        low, high = wilson_interval(proportion=proportion, count=count, z=1.96)

        assert low == pytest.approx(expected[0], abs=1e-4)
        assert high == pytest.approx(expected[1], abs=1e-4)

    def test_elo_of_a_perfect_score_is_finite(self) -> None:
        elo = estimate_elo(points=[[0, 4], [0, 0]], games=[[0, 4], [4, 0]])

        # With one virtual draw the winner scores 4.5 of 5, odds of 9 to 1.
        assert elo[0] - elo[1] == pytest.approx(400 * math.log10(9))
        assert sum(elo) == pytest.approx(0)

    def test_elo_of_equal_participants_and_absent_ones(self) -> None:
        elo = estimate_elo(
            points=[[0, 1, 0], [1, 0, 0], [0, 0, 0]],
            games=[[0, 2, 0], [2, 0, 0], [0, 0, 0]],
        )

        assert elo == pytest.approx([0, 0, 0])

    def test_elo_orders_a_transitive_field(self) -> None:
        points = [[0, 3, 4], [1, 0, 3], [0, 1, 0]]
        games = [[0, 4, 4], [4, 0, 4], [4, 4, 0]]

        elo = estimate_elo(points=points, games=games)

        assert elo[0] > elo[1] > elo[2]

    def test_distribution_summary(self) -> None:
        summary = DecisionTimeSummary.from_values([0.4, 0.1, 0.3, 0.2])

        assert summary == DecisionTimeSummary(
            count=4, mean=0.25, p50=0.2, p90=0.4, max=0.4
        )
        assert DecisionTimeSummary.from_values([]).count == 0

    def test_decision_stats(self) -> None:
        decisions = [
            make_decision(last_info={"depth": 2, "nps": 100}),
            make_decision(
                close_reason=TurnCloseReason.DEADLINE,
                overrun_s=0.2,
                last_info={"depth": 3, "nps": 300},
                illegal_submissions=2,
            ),
            make_decision(
                close_reason=TurnCloseReason.WORKER_FAILED,
                failure="boom",
                worker_restarted=True,
                last_info={"depth": True, "nps": None},
            ),
            make_decision(close_reason=TurnCloseReason.DEADLINE, overrun_s=0.01),
        ]

        stats = DecisionStats.from_decisions(decisions)

        assert stats.depth_reached == {2: 1, 3: 1}
        assert stats.mean_depth == 2.5
        assert stats.nodes_per_s == 200
        assert stats.close_reasons[TurnCloseReason.DEADLINE] == 2
        assert stats.close_reasons[TurnCloseReason.NO_CANDIDATE] == 0
        assert stats.timeout_rate == 0.5
        assert stats.overruns == 1
        assert stats.overrun_rate == 0.25
        assert stats.overrun_s.max == 0.2
        assert (stats.failures, stats.worker_restarts) == (1, 1)
        assert stats.illegal_submissions == 2
        assert stats.flagged

    def test_empty_decision_stats(self) -> None:
        stats = DecisionStats.from_decisions([])

        assert stats.mean_depth is None
        assert stats.nodes_per_s is None
        assert stats.timeout_rate == 0
        assert not stats.flagged


class TestGauntletReport:
    def test_aggregates_results(self) -> None:
        config = make_config(games_per_pair=4)
        results = [
            make_result(
                config=config,
                index=0,
                outcome=MatchOutcome.WIN,
                winner=Player.BLACK,
                decisions=[
                    make_decision(player=Player.WHITE),
                    make_decision(player=Player.BLACK, failure="boom"),
                ],
            ),
            make_result(
                config=config, index=1, outcome=MatchOutcome.WIN, winner=Player.WHITE
            ),
            make_result(config=config, index=2, outcome=MatchOutcome.DRAW),
            make_result(config=config, index=3, outcome=MatchOutcome.TURN_CAP),
        ]

        report = GauntletReport.from_results(
            config=config, results=results, duration_s=2.0
        )

        random_result, negamax_result = report.participants
        assert (random_result.wins, random_result.losses) == (0, 2)
        assert random_result.draws == 2
        assert (negamax_result.wins, negamax_result.draws) == (2, 2)
        assert random_result.turn_caps == negamax_result.turn_caps == 1
        assert negamax_result.win_rate == 0.75
        assert negamax_result.elo > 0 > random_result.elo
        assert random_result.decision_stats.decisions == 1
        assert negamax_result.decision_stats.failures == 1
        assert [match.winner for match in report.matches[:2]] == [
            Player.BLACK,
            Player.WHITE,
        ]
        assert report.replays is None

        table = report.summary_table().splitlines()
        assert table[1].startswith("nm1 !")
        assert table[2].startswith("random ")

    def test_round_trip_with_replays(self, tiny_report: GauntletReport) -> None:
        data = json.loads(json.dumps(tiny_report.to_dict()))

        assert data["version"] == GAUNTLET_REPORT_VERSION
        assert data["participants"][0]["decision_stats"]["close_reasons"]["final"] > 0
        assert GauntletReport.from_dict(data) == tiny_report

    def test_round_trip_without_replays(self) -> None:
        config = make_config()
        results = [
            make_result(config=config, index=index, outcome=MatchOutcome.TURN_CAP)
            for index in range(2)
        ]
        report = GauntletReport.from_results(config=config, results=results, duration_s=1)

        assert (
            GauntletReport.from_dict(json.loads(json.dumps(report.to_dict()))) == report
        )

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"version": 0}, "Unsupported gauntlet report version `0`"),
            ({"matches": None}, "Invalid gauntlet report"),
        ],
    )
    def test_from_dict_rejects_invalid(
        self, tiny_report: GauntletReport, change: dict[str, object], message: str
    ) -> None:
        data = {**tiny_report.to_dict(), **change}

        with pytest.raises(ValueError, match=message):
            GauntletReport.from_dict(data)

    def test_replay(self, tiny_report: GauntletReport) -> None:
        assert tiny_report.replays is not None
        assert tiny_report.replay(1) is tiny_report.replays[1]

        with pytest.raises(ValueError, match="No match 2, expected 0 to 1"):
            tiny_report.replay(2)

    def test_replay_without_replays(self) -> None:
        config = make_config()
        results = [
            make_result(config=config, index=index, outcome=MatchOutcome.DRAW)
            for index in range(2)
        ]
        report = GauntletReport.from_results(config=config, results=results, duration_s=1)

        with pytest.raises(ValueError, match="has no replays"):
            report.replay(0)


@pytest.fixture(scope="module")
def tiny_report() -> GauntletReport:
    """Play a tiny real gauntlet between two random agents, keeping the replays."""
    config = make_config(
        participants=(RANDOM, AgentSpec(kind="random", label="r2")),
        budget_s=0.2,
        max_turns=4,
        jobs=2,
        replays=True,
    )
    return config.run()


class TestRun:
    def test_tiny_gauntlet(self, tiny_report: GauntletReport) -> None:
        assert tiny_report.replays is not None
        assert len(tiny_report.matches) == 2
        assert [m.white for m in tiny_report.matches] == ["random", "r2"]
        assert all(m.outcome is MatchOutcome.TURN_CAP for m in tiny_report.matches)
        assert all(r.draws == 2 for r in tiny_report.participants)
        assert [len(r.decisions) for r in tiny_report.replays] == [8, 8]
        assert all(r.decision_stats.decisions == 8 for r in tiny_report.participants)

    def test_same_seed_reproduces_results(self) -> None:
        seen = []

        def play(seed: int) -> list[tuple[object, ...]]:
            report = make_config(
                seed=seed, max_turns=8, jobs=2, replays=True, budget_s=2.0
            ).run(match_callback=lambda match, result: seen.append(match.index))
            assert report.replays is not None

            return [
                (m.white, m.black, m.seed, m.outcome, m.winner, r.record.moves)
                for m, r in zip(report.matches, report.replays, strict=True)
            ]

        first = play(7)

        assert play(7) == first
        assert play(8) != first
        assert sorted(seen) == [0, 0, 0, 1, 1, 1]

    def test_worker_error_stops_the_gauntlet(self) -> None:
        config = make_config(participants=(RANDOM, AgentSpec("unregistered")))

        with pytest.raises(AgentWorkerError):
            config.run()
