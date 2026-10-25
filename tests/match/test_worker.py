"""Tests of persistent workers, which start real worker processes."""

from pathlib import Path

import pytest

from hive.agents.factory import AgentSpec
from hive.engine.rules import Rules
from hive.engine.serialization import JsonValue
from hive.engine.state import GameState
from hive.match.records import CloseReason, DecisionRecord
from hive.match.turn import Info, Submission, WorkerMessage
from hive.match.worker import Worker, WorkerError

_BUDGET_S = 0.1
_GRACE_S = 0.3

_TESTING_MODULE = "hive.match.testing"
"""The test agents, imported only in workers to keep them out of `list_agents`."""


def _worker(kind: str, rules: Rules, **params: JsonValue) -> Worker:
    """Build a worker for a test agent kind with a short grace period."""
    return Worker(
        AgentSpec(kind, params),
        rules,
        seed=0,
        grace_s=_GRACE_S,
        preload=[_TESTING_MODULE],
    )


def _decide(
    kind: str, rules: Rules, state: GameState, **params: JsonValue
) -> DecisionRecord:
    """Start a worker for a test agent kind, decide one move and close it."""
    with _worker(kind, rules, **params) as worker:
        return worker.decide(state, _BUDGET_S)


@pytest.fixture(scope="function")
def state(rules: Rules) -> GameState:
    """Build a position after two placements, where far away placements are illegal."""
    state = rules.create_initial_state()
    for _ in range(2):
        state.apply_move(rules.legal_moves(state)[0])
    return state


class TestWellBehaved:
    def test_search_closes_at_deadline(self, rules: Rules, state: GameState) -> None:
        with Worker(AgentSpec("negamax"), rules, seed=0, grace_s=_GRACE_S) as worker:
            decision = worker.decide(state, _BUDGET_S)

        assert decision.close_reason is CloseReason.DEADLINE
        assert decision.move in rules.legal_moves(state)
        assert decision.elapsed_s == pytest.approx(_BUDGET_S, abs=0.05)
        assert decision.overrun_s < 0.1
        assert decision.candidates >= 1
        assert decision.last_info is not None
        assert not decision.worker_restarted
        assert decision.failure is None
        assert (decision.ply, decision.player) == (
            state.current_ply,
            state.current_player,
        )

    def test_final_submission_returns_early(self, rules: Rules, state: GameState) -> None:
        with Worker(AgentSpec("random", label="rnd"), rules, seed=0) as worker:
            decisions = [worker.decide(state, 10.0) for _ in range(3)]

        assert all(d.close_reason is CloseReason.FINAL for d in decisions)
        assert all(d.elapsed_s < 1.0 for d in decisions)
        assert {d.agent_label for d in decisions} == {"rnd"}

    def test_streams_messages(self, rules: Rules, state: GameState) -> None:
        streamed: list[WorkerMessage] = []
        with Worker(AgentSpec("negamax", {"depth": 2}), rules, seed=0) as worker:
            decision = worker.decide(state, 10.0, on_message=streamed.append)

        assert decision.close_reason is CloseReason.FINAL
        assert any(isinstance(message, Info) for message in streamed)
        assert isinstance(streamed[-1], Submission)
        assert streamed[-1].move == decision.move
        assert decision.last_info is not None
        assert decision.last_info["depth"] == 2

    def test_does_not_modify_state(self, rules: Rules, state: GameState) -> None:
        before = state.copy()
        with Worker(AgentSpec("negamax"), rules, seed=0) as worker:
            worker.decide(state, _BUDGET_S)

        assert state.board == before.board
        assert state.current_ply == before.current_ply


class TestMisbehaving:
    def test_never_submits_falls_back(self, rules: Rules, state: GameState) -> None:
        decision = _decide("test-never-submits", rules, state)

        assert decision.close_reason is CloseReason.NO_CANDIDATE
        assert decision.move in rules.legal_moves(state)
        assert decision.candidates == 0
        assert not decision.worker_restarted

    def test_illegal_submissions_are_counted(
        self, rules: Rules, state: GameState
    ) -> None:
        decision = _decide("test-illegal", rules, state, count=2)

        assert decision.close_reason is CloseReason.NO_CANDIDATE
        assert decision.illegal_submissions == 2
        assert decision.move in rules.legal_moves(state)
        assert decision.elapsed_s < _BUDGET_S

    def test_illegal_then_legal(self, rules: Rules, state: GameState) -> None:
        decision = _decide("test-illegal", rules, state, then_legal=True)

        assert decision.close_reason is CloseReason.FINAL
        assert decision.illegal_submissions == 1
        assert decision.candidates == 1
        assert decision.move == rules.legal_moves(state)[0]

    def test_ignoring_stop_restarts_worker(self, rules: Rules, state: GameState) -> None:
        with _worker("test-lingers", rules) as worker:
            decision = worker.decide(state, _BUDGET_S)
            assert worker.restarts == 1
            assert worker.running
            again = worker.decide(state, _BUDGET_S)

        assert decision.close_reason is CloseReason.DEADLINE
        assert decision.move == rules.legal_moves(state)[0]
        assert decision.elapsed_s < _BUDGET_S + 0.05
        assert decision.overrun_s >= _GRACE_S
        assert decision.worker_restarted
        assert decision.failure is not None
        assert "grace period" in decision.failure
        assert again.worker_restarted

    def test_lingering_within_grace_is_overrun(
        self, rules: Rules, state: GameState
    ) -> None:
        decision = _decide("test-lingers", rules, state, linger_s=0.1)

        assert decision.close_reason is CloseReason.DEADLINE
        assert 0.1 <= decision.overrun_s < _GRACE_S
        assert not decision.worker_restarted
        assert decision.failure is None

    def test_raising_keeps_worker(self, rules: Rules, state: GameState) -> None:
        with _worker("test-crashes", rules) as worker:
            decisions = [worker.decide(state, _BUDGET_S) for _ in range(2)]
            assert worker.restarts == 0

        for decision in decisions:
            assert decision.close_reason is CloseReason.WORKER_FAILED
            assert decision.move == rules.legal_moves(state)[0]
            assert decision.failure == "RuntimeError: The agent crashed on purpose."
            assert not decision.worker_restarted

    def test_dying_restarts_worker(self, rules: Rules, state: GameState) -> None:
        with _worker("test-crashes", rules, exit_process=True) as worker:
            decision = worker.decide(state, _BUDGET_S)
            assert worker.restarts == 1

        assert decision.close_reason is CloseReason.WORKER_FAILED
        assert decision.move == rules.legal_moves(state)[0]
        assert decision.worker_restarted
        assert decision.failure == "The worker exited with code 3."


class TestLifecycle:
    def test_builds_agent_once(
        self, rules: Rules, state: GameState, tmp_path: Path
    ) -> None:
        path = tmp_path / "constructions.txt"
        with _worker("test-counting", rules, path=str(path)) as worker:
            for _ in range(3):
                worker.decide(state, _BUDGET_S)
            assert len(path.read_text().splitlines()) == 1

            worker.restart()
            worker.decide(state, _BUDGET_S)

        assert len(path.read_text().splitlines()) == 2

    @pytest.mark.parametrize(
        ("spec", "error"),
        [
            (AgentSpec("nope"), "Unknown agent kind `nope`"),
            (AgentSpec("negamax", {"depth": 0}), "params.depth"),
        ],
    )
    def test_start_fails_for_invalid_spec(
        self, rules: Rules, spec: AgentSpec, error: str
    ) -> None:
        worker = Worker(spec, rules, seed=0)

        with pytest.raises(WorkerError, match=error):
            worker.start()
        assert not worker.running

    def test_start_times_out(self, rules: Rules) -> None:
        worker = Worker(AgentSpec("random"), rules, seed=0, startup_timeout_s=0.0)

        with pytest.raises(WorkerError, match="timed out"):
            worker.start()

    def test_requires_start(self, rules: Rules, state: GameState) -> None:
        worker = Worker(AgentSpec("random"), rules, seed=0)

        with pytest.raises(RuntimeError, match="not started"):
            worker.decide(state, _BUDGET_S)
        worker.close()

    def test_start_twice_fails(self, rules: Rules) -> None:
        with Worker(AgentSpec("random"), rules, seed=0) as worker:
            with pytest.raises(RuntimeError, match="already started"):
                worker.start()

    def test_close_stops_process(self, rules: Rules) -> None:
        worker = Worker(AgentSpec("random"), rules, seed=0)
        worker.start()
        assert worker.running

        worker.close()
        worker.close()

        assert not worker.running
