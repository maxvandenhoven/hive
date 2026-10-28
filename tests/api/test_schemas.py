from typing import Any

import pytest
from pydantic import ValidationError

from hive.api.db.models import GameStatus
from hive.api.players import AgentPlayer, BoardLocation, HumanPlayer
from hive.api.schemas import GameCreate, GameUpdate
from hive.engine.rules import Rules

AGENT = {"type": "agent", "spec": {"kind": "random"}, "budget_s": 1.0}
HUMAN = {"type": "human"}
HINTED = {"type": "human", "hint": {"spec": {"kind": "random"}, "budget_s": 2.0}}


def game_create(**fields: Any) -> GameCreate:
    """Validate a create request for a human vs random agent game with some fields set."""
    return GameCreate.model_validate(
        {"name": "Game", "white": HUMAN, "black": AGENT, **fields}
    )


class TestGameCreate:
    def test_defaults_rules_and_setup(self) -> None:
        body = game_create()

        assert body.rules == Rules()
        assert body.setup is None
        assert isinstance(body.black, AgentPlayer)
        assert body.black.spec.kind == "random"

    def test_fills_in_missing_rule_fields(self) -> None:
        body = game_create(rules={"max_turns": 30})

        assert body.rules == Rules(max_turns=30)

    def test_agent_vs_agent(self) -> None:
        body = game_create(white=AGENT)

        assert isinstance(body.white, AgentPlayer)
        assert body.board_location is None
        assert body.location is BoardLocation.SCREEN

    def test_human_vs_agent_defaults_to_table(self) -> None:
        assert game_create().location is BoardLocation.TABLE

    def test_keeps_given_board_location(self) -> None:
        assert game_create(board_location="screen").location is BoardLocation.SCREEN

    def test_human_vs_human_with_hint(self) -> None:
        body = game_create(white=HINTED, black=HUMAN)

        assert isinstance(body.white, HumanPlayer)
        assert body.white.hint is not None
        assert body.white.hint.budget_s == 2.0
        assert body.location is BoardLocation.TABLE

    def test_rejects_human_vs_human_without_hint(self) -> None:
        with pytest.raises(ValidationError, match="human vs human"):
            game_create(black=HUMAN)

    def test_rejects_unsupported_location(self) -> None:
        with pytest.raises(ValidationError, match="played on the `screen`"):
            game_create(white=AGENT, board_location="table")

    def test_rejects_invalid_hint_spec(self) -> None:
        hint = {"type": "human", "hint": {"spec": {"kind": "nope"}}}

        with pytest.raises(ValidationError, match="Unknown agent kind `nope`"):
            game_create(white=hint)

    @pytest.mark.parametrize(
        ("spec", "message"),
        [
            ({"kind": "nope"}, "Unknown agent kind `nope`"),
            ({"kind": "negamax", "params": {"depth": 0}}, "depth"),
        ],
    )
    def test_rejects_invalid_agent_spec(self, spec: dict[str, Any], message: str) -> None:
        with pytest.raises(ValidationError, match=message):
            game_create(black={"type": "agent", "spec": spec})

    @pytest.mark.parametrize("budget_s", [0, float("inf"), float("nan")])
    def test_rejects_invalid_budget(self, budget_s: float) -> None:
        with pytest.raises(ValidationError, match="budget_s"):
            game_create(black={**AGENT, "budget_s": budget_s})

    def test_rejects_invalid_rules(self) -> None:
        with pytest.raises(ValidationError, match="unknown"):
            game_create(rules={"unknown": 1})

    def test_accepts_valid_setup(self) -> None:
        setup = {
            "board": [{"coord": [0, 0], "stack": [{"piece": "queen", "owner": "white"}]}],
            "current_player": "black",
        }

        body = game_create(setup=setup)

        assert body.setup is not None
        assert body.setup.to_json() == {**setup, "current_ply": None}

    def test_rejects_setup_invalid_under_rules(self) -> None:
        setup = {
            "board": [
                {"coord": [0, 0], "stack": [{"piece": "queen", "owner": "white"}]},
                {"coord": [5, 5], "stack": [{"piece": "queen", "owner": "black"}]},
            ],
            "current_player": "white",
        }

        with pytest.raises(ValidationError, match="Invalid setup"):
            game_create(setup=setup)

    @pytest.mark.parametrize("name", ["", "x" * 101])
    def test_rejects_bad_name_length(self, name: str) -> None:
        with pytest.raises(ValidationError, match="name"):
            game_create(name=name)


class TestGameUpdate:
    def test_rejects_unknown_status(self) -> None:
        with pytest.raises(ValidationError, match="status"):
            GameUpdate.model_validate({"status": "paused"})

    def test_parses_partial_update(self) -> None:
        body = GameUpdate.model_validate({"status": "finished"})

        assert body.name is None
        assert body.status is GameStatus.FINISHED
        assert body.board_location is None

    def test_rejects_unknown_board_location(self) -> None:
        with pytest.raises(ValidationError, match="board_location"):
            GameUpdate.model_validate({"board_location": "garden"})
