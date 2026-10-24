from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, override

import pytest
from pydantic import Field

from hive.agents import factory
from hive.agents.base import Agent, TurnContext
from hive.agents.factory import (
    AgentSpec,
    InvalidAgentSpecError,
    build_agent,
    list_agents,
    register_agent,
)
from hive.agents.minimax import MinimaxAgent
from hive.agents.negamax import NegamaxAgent
from hive.agents.random import RandomAgent
from hive.engine.rules import Rules
from hive.engine.state import GameState


@dataclass(frozen=True, slots=True)
class _Network:
    hidden: int = 8
    blocks: int = 2


class _NeuralAgent(Agent):
    """Agent with a required param and a nested config, like a future neural agent."""

    def __init__(
        self,
        rules: Rules,
        *,
        seed: int,
        weights: str,
        network: _Network = _Network(),  # noqa: B008
        temperature: Annotated[float, Field(gt=0)] = 1.0,
    ) -> None:
        """Initialize the agent.

        Args:
            rules: The rules governing the game.
            seed: The seed for the random number generator of the agent.
            weights: The path to the model
                weights.
            network: The shape of the network.
            temperature: The sampling temperature.

        Raises:
            ValueError: If `weights` is empty, which this description must not extend
                into the description of `temperature`.
        """
        super().__init__(rules, seed=seed)
        if not weights:
            msg = "Missing weights."
            raise ValueError(msg)
        self.weights = weights
        self.network = network
        self.temperature = temperature

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        turn.submit(None, final=True)


@pytest.fixture(scope="function")
def registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register test agents in a copy of the registry that is restored afterwards."""
    monkeypatch.setattr(factory, "_REGISTRY", dict(factory._REGISTRY))


class TestSpecFromYaml:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("random", AgentSpec("random")),
            ("kind: random", AgentSpec("random")),
            (
                "kind: negamax\nlabel: nm3\nparams:\n  depth: 3\n  mobility: 0.5\n",
                AgentSpec("negamax", {"depth": 3, "mobility": 0.5}, label="nm3"),
            ),
            (
                "{kind: minimax, params: {depth: null}}",
                AgentSpec("minimax", {"depth": None}),
            ),
        ],
    )
    def test_reads_spec(self, text: str, expected: AgentSpec) -> None:
        assert AgentSpec.from_yaml(text) == expected

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("kind: [negamax", r"Invalid YAML(.|\n)*line 1"),
            ("label: nm3", r"kind: Field required\."),
            (
                "kind: negamax\nparms: {}",
                r"parms: Unknown key, expected kind, label or params",
            ),
            (
                "{kind: negamax, params: [1]}",
                r"params: Input should be a valid dictionary",
            ),
            ("kind: alphazero", r"Unknown agent kind `alphazero`, expected one of: "),
        ],
    )
    def test_rejects_invalid(self, text: str, match: str) -> None:
        with pytest.raises(InvalidAgentSpecError, match=match):
            AgentSpec.from_yaml(text)

    def test_lists_every_invalid_param(self) -> None:
        text = "kind: negamax\nparams: {depth: 0, depht: 2, mobility: high}"
        with pytest.raises(InvalidAgentSpecError) as excinfo:
            AgentSpec.from_yaml(text)

        assert str(excinfo.value).splitlines() == [
            "Invalid agent spec:",
            "  params.depth: Input should be greater than or equal to 1 (got 0).",
            "  params.mobility: Input should be a valid number, unable to parse string "
            "as a number (got 'high').",
            "  params.depht: Unknown param, expected one of: depth, queen_safety, "
            "mobility, positioning, material_on_board, material_in_hand.",
        ]


class TestSpecFile:
    def test_loads_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nm3.yaml"
        path.write_text("kind: negamax\nlabel: nm3\nparams:\n  depth: 3\n")

        assert AgentSpec.load(path) == AgentSpec("negamax", {"depth": 3}, label="nm3")

    def test_names_file_in_errors(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("kind: negamax\nparams:\n  depth: 0\n")

        with pytest.raises(
            InvalidAgentSpecError, match=f"Invalid agent spec in `{path}`"
        ):
            AgentSpec.load(path)

    @pytest.mark.parametrize(
        "spec",
        [AgentSpec("random"), AgentSpec("negamax", {"depth": 2, "mobility": 0.5}, "nm2")],
    )
    def test_round_trips(self, spec: AgentSpec) -> None:
        assert AgentSpec.from_dict(spec.to_dict()) == spec

    def test_serializes_without_label(self) -> None:
        assert AgentSpec("random").to_dict() == {"kind": "random", "params": {}}


class TestBuildAgent:
    @pytest.mark.parametrize(
        ("kind", "agent_class"),
        [("random", RandomAgent), ("minimax", MinimaxAgent), ("negamax", NegamaxAgent)],
    )
    def test_builds_registered_kind(self, kind: str, agent_class: type[Agent]) -> None:
        assert type(build_agent(AgentSpec(kind), Rules(), seed=0)) is agent_class

    def test_applies_params(self) -> None:
        spec = AgentSpec("negamax", {"depth": 3, "mobility": 0.5, "queen_safety": 0})
        agent = build_agent(spec, Rules(), seed=0)

        assert isinstance(agent, NegamaxAgent)
        assert (agent.depth, agent.mobility, agent.queen_safety) == (3, 0.5, 0.0)

    def test_coerces_strings(self) -> None:
        agent = build_agent(AgentSpec("negamax", {"depth": "2"}), Rules(), seed=0)

        assert isinstance(agent, NegamaxAgent)
        assert agent.depth == 2

    def test_passes_rules(self) -> None:
        rules = Rules(max_turns=10)

        assert build_agent(AgentSpec("random"), rules, seed=0).rules is rules

    @pytest.mark.parametrize(
        ("spec", "match"),
        [
            (AgentSpec("alphazero"), "Unknown agent kind `alphazero`"),
            (AgentSpec("random", {"depth": 1}), "params.depth: Unknown param"),
            (AgentSpec("negamax", {"depth": 0}), "params.depth: Input should be greater"),
        ],
    )
    def test_rejects_invalid(self, spec: AgentSpec, match: str) -> None:
        with pytest.raises(InvalidAgentSpecError, match=match):
            build_agent(spec, Rules(), seed=0)


class TestListAgents:
    def test_lists_all_kinds(self) -> None:
        assert {agent.name for agent in list_agents()} == {"random", "minimax", "negamax"}

    def test_describes_agents_from_docstrings(self) -> None:
        agents = {agent.name: agent for agent in list_agents()}

        assert agents["random"].description == (
            "Agent that selects moves uniformly at random from the set of legal moves."
        )
        assert agents["random"].params_schema["properties"] == {}

    def test_derives_schema_from_signature(self) -> None:
        agents = {agent.name: agent for agent in list_agents()}
        properties = agents["negamax"].params_schema["properties"]
        assert isinstance(properties, dict)

        assert list(properties) == [
            "depth",
            "queen_safety",
            "mobility",
            "positioning",
            "material_on_board",
            "material_in_hand",
        ]
        assert properties["depth"] == {
            "anyOf": [{"minimum": 1, "type": "integer"}, {"type": "null"}],
            "default": None,
            "description": "The maximum search depth in plies, or `None` to search until "
            "stopped.",
            "title": "Depth",
        }
        queen_safety = properties["queen_safety"]
        assert isinstance(queen_safety, dict)
        assert queen_safety["default"] == 1.0
        assert queen_safety["description"] == (
            "The weight of the occupied neighbours of the opponent's queen minus those "
            "of the player's own queen."
        )


@pytest.mark.usefixtures("registry")
class TestRegisterAgent:
    def test_registers_class_with_nested_params(self) -> None:
        assert register_agent("neural")(_NeuralAgent) is _NeuralAgent

        spec = AgentSpec.from_yaml(
            "kind: neural\nparams:\n  weights: s3://a.onnx\n  network: {hidden: 64}"
        )
        agent = build_agent(spec, Rules(), seed=0)

        assert isinstance(agent, _NeuralAgent)
        assert agent.weights == "s3://a.onnx"
        assert agent.network == _Network(hidden=64, blocks=2)
        assert agent.temperature == 1.0
        properties = list_agents()[-1].params_schema["properties"]
        assert isinstance(properties, dict)
        assert properties["temperature"] == {
            "default": 1.0,
            "description": "The sampling temperature.",
            "exclusiveMinimum": 0.0,
            "title": "Temperature",
            "type": "number",
        }

    def test_derives_required_and_constrained_params(self) -> None:
        register_agent("neural")(_NeuralAgent)
        schema = {agent.name: agent for agent in list_agents()}["neural"].params_schema

        assert schema["required"] == ["weights"]
        properties = schema["properties"]
        assert isinstance(properties, dict)
        assert properties["weights"] == {
            "description": "The path to the model weights.",
            "title": "Weights",
            "type": "string",
        }
        with pytest.raises(InvalidAgentSpecError, match="temperature: Input should be"):
            AgentSpec.from_dict(
                {"kind": "neural", "params": {"weights": "w", "temperature": 0}}
            )
        with pytest.raises(
            InvalidAgentSpecError, match=r"params\.weights: Field required"
        ):
            AgentSpec.from_dict({"kind": "neural"})

    def test_rejects_duplicate_kind(self) -> None:
        with pytest.raises(ValueError, match="`random` is already registered"):
            register_agent("random")(_NeuralAgent)

    def test_rejects_missing_seed(self) -> None:
        class _NoSeed(_NeuralAgent):
            def __init__(self, rules: Rules) -> None:
                super().__init__(rules, seed=0, weights="w")

        with pytest.raises(TypeError, match="must start with `rules` and `seed`"):
            register_agent("no-seed")(_NoSeed)

    def test_rejects_positional_param(self) -> None:
        class _Positional(_NeuralAgent):
            def __init__(self, rules: Rules, seed: int, depth: int) -> None:
                super().__init__(rules, seed=seed, weights="w")

        with pytest.raises(
            TypeError, match="`depth` of `_Positional` must be keyword-only"
        ):
            register_agent("positional")(_Positional)

    def test_rejects_missing_annotation(self) -> None:
        class _Unannotated(_NeuralAgent):
            def __init__(self, rules: Rules, *, seed: int, depth=1) -> None:  # noqa: ANN001
                super().__init__(rules, seed=seed, weights="w")

        with pytest.raises(
            TypeError, match="`depth` of `_Unannotated` has no annotation"
        ):
            register_agent("unannotated")(_Unannotated)
