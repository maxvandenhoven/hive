"""Champion trials use real workers and retain colour-paired opening replays."""

from dataclasses import replace

import pytest

from hive.agents.factory import AgentSpec
from hive.match.champion import ChampionTrial
from hive.match.gauntlet import GauntletReport


def test_openings_are_paired_and_replays_round_trip() -> None:
    """Opening moves survive serialization and precede every timed decision."""
    spec = AgentSpec(kind="random")
    trial = ChampionTrial(
        champion=spec,
        candidate=spec,
        pairs=2,
        seed=100,
        budget_s=0.05,
        max_turns=6,
        jobs=1,
    )
    config = trial.config()
    scheduled = config.schedule()
    assert (
        config.match_runner(scheduled[0]).opening
        == config.match_runner(scheduled[1]).opening
    )
    assert (
        config.match_runner(scheduled[2]).opening
        == config.match_runner(scheduled[3]).opening
    )
    assert config.openings[0] != config.openings[1]
    report = config.run()
    restored = GauntletReport.from_json(report.to_json())
    assert restored.replays is not None

    for result in restored.replays:
        assert result.record.moves[:8] == list(result.opening)
        assert len(result.record.moves) == len(result.decisions) + 8
        assert result.decisions[0].ply == 8

    assessment = ChampionTrial.assessment(restored)
    assert assessment.score == 0.5
    assert not assessment.eligible

    with pytest.raises(ValueError, match="complete"):
        ChampionTrial.assessment(replace(restored, matches=restored.matches[:-1]))


def test_thread_budgets_must_match() -> None:
    trial = ChampionTrial(
        champion=AgentSpec(kind="negamax", params={"threads": 2}),
        candidate=AgentSpec(kind="negamax"),
        pairs=1,
        seed=0,
        budget_s=1,
    )
    with pytest.raises(ValueError, match="thread budgets"):
        trial.config()


def test_promotion_bound_requires_large_clean_ten_second_trial() -> None:
    """Even perfect screening results cannot promote; failed workers veto wins."""
    from hive.engine.state import Player
    from hive.match.records import MatchOutcome, MatchResult

    spec = AgentSpec(kind="random")
    config = ChampionTrial(
        champion=spec, candidate=spec, pairs=100, seed=20000, budget_s=10
    ).config()
    results = [
        MatchResult(
            rules=config.rules,
            white_spec=config.participants[match.white],
            black_spec=config.participants[match.black],
            seed=match.seed,
            budget_s=10,
            opening=config.match_runner(match).opening,
            winner=Player.WHITE if match.white == 1 else Player.BLACK,
            outcome=MatchOutcome.WIN,
        )
        for match in config.schedule()
    ]
    report = GauntletReport.from_results(config=config, results=results, duration_s=1)
    assert ChampionTrial.assessment(report).eligible
    assert not ChampionTrial.assessment(
        replace(report, config=replace(config, budget_s=1))
    ).eligible
    candidate = report.participants[1]
    broken = replace(
        candidate, decision_stats=replace(candidate.decision_stats, failures=1)
    )
    assert not ChampionTrial.assessment(
        replace(report, participants=[report.participants[0], broken])
    ).eligible
    illegal = replace(
        candidate, decision_stats=replace(candidate.decision_stats, illegal_submissions=1)
    )
    assert not ChampionTrial.assessment(
        replace(report, participants=[report.participants[0], illegal])
    ).eligible


def test_fast_gate_uses_the_normal_bound_of_pair_scores() -> None:
    """Split pairs lower the normal bound; the fast gate needs 50 pairs at a second."""
    from hive.engine.state import Player
    from hive.match.champion import FAST_CHAMPION_GATE
    from hive.match.records import MatchOutcome, MatchResult

    spec = AgentSpec(kind="random")
    config = ChampionTrial(
        champion=spec, candidate=spec, pairs=50, seed=0, budget_s=1
    ).config()
    results = []

    for match in config.schedule():
        candidate_white = match.white == 1
        # The candidate wins both games of even pairs and splits odd pairs by colour.
        wins = match.index // 2 % 2 == 0 or candidate_white
        candidate = Player.WHITE if candidate_white else Player.BLACK
        results.append(
            MatchResult(
                rules=config.rules,
                white_spec=config.participants[match.white],
                black_spec=config.participants[match.black],
                seed=match.seed,
                budget_s=1,
                opening=config.match_runner(match).opening,
                winner=candidate if wins else candidate.opponent,
                outcome=MatchOutcome.WIN,
            )
        )

    report = GauntletReport.from_results(config=config, results=results, duration_s=1)
    assert ChampionTrial.pair_scores(report)[:2] == [1.0, 0.5]
    assessment = ChampionTrial.assessment(report, gate=FAST_CHAMPION_GATE)
    assert assessment.score == 0.75
    assert (assessment.wins, assessment.losses) == (75, 25)
    assert assessment.bound == "normal"
    assert 0.5 < assessment.lower_bound < 0.75
    assert assessment.eligible
    assert not ChampionTrial.assessment(report).eligible
