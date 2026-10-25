import json

import pytest

from hive.agents.factory import AgentSpec
from hive.engine.rules import Rules
from hive.engine.state import Move, PieceType, Player
from hive.match.records import DecisionRecord, MatchOutcome, MatchResult, TurnCloseReason


def make_decision(player: Player, elapsed_s: float, move: Move | None) -> DecisionRecord:
    """Build a decision record with the given player, time and move."""
    return DecisionRecord(
        ply=0 if player is Player.WHITE else 1,
        player=player,
        agent_label=player.name.lower(),
        seed=7,
        budget_s=1.0,
        elapsed_s=elapsed_s,
        overrun_s=0.01,
        close_reason=TurnCloseReason.DEADLINE,
        candidates=3,
        illegal_submissions=1,
        move=move,
        last_info={"depth": 2, "pv": [{"piece": "ant", "from": None, "to": [1, 0]}]},
        worker_restarted=True,
        failure="boom",
    )


@pytest.fixture(scope="function")
def result() -> MatchResult:
    """Build a match result with two decisions."""
    moves: list[Move | None] = [
        Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0)),
        Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0)),
    ]
    return MatchResult(
        rules=Rules(max_turns=50),
        white_spec=AgentSpec(kind="negamax", params={"depth": 2}, label="nm2"),
        black_spec=AgentSpec("random"),
        seed=42,
        budget_s=1.0,
        decisions=[
            make_decision(player=Player.WHITE, elapsed_s=0.5, move=moves[0]),
            make_decision(player=Player.BLACK, elapsed_s=0.25, move=moves[1]),
        ],
        outcome=MatchOutcome.WIN,
        winner=Player.BLACK,
        duration_s=1.5,
    )


class TestDecisionRecord:
    @pytest.mark.parametrize(
        "move",
        [None, Move(piece_type=PieceType.ANT, source_coord=(0, 0), target_coord=(1, 0))],
    )
    def test_round_trip(self, move: Move | None) -> None:
        decision = make_decision(player=Player.WHITE, elapsed_s=0.5, move=move)

        data = json.loads(json.dumps(decision.to_json()))

        assert DecisionRecord.from_json(data) == decision
        assert data["close_reason"] == "deadline"
        assert data["player"] == "white"

    @pytest.mark.parametrize("data", [[], {"ply": 0}])
    def test_rejects_invalid(self, data: object) -> None:
        with pytest.raises(ValueError, match="DecisionRecord"):
            DecisionRecord.from_json(data)


class TestMatchResult:
    def test_round_trip(self, result: MatchResult) -> None:
        data = json.loads(json.dumps(result.to_json()))

        assert MatchResult.from_json(data) == result
        assert data["white"]["label"] == "nm2"

    def test_record_is_built_from_decisions(self, result: MatchResult) -> None:
        assert result.record.rules == result.rules
        assert result.record.setup is None
        assert result.record.moves == [decision.move for decision in result.decisions]

    def test_json_stores_the_moves_once(self, result: MatchResult) -> None:
        data = result.to_json()

        assert isinstance(data, dict)
        assert "record" not in data

    def test_thinking_time_per_seat(self, result: MatchResult) -> None:
        assert result.thinking_s(Player.WHITE) == 0.5
        assert result.thinking_s(Player.BLACK) == 0.25
        assert result.spec(Player.WHITE).label == "nm2"

    @pytest.mark.parametrize("data", [None, {"seed": 1}])
    def test_rejects_invalid(self, data: object) -> None:
        with pytest.raises(ValueError, match="MatchResult"):
            MatchResult.from_json(data)
