from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, override

import pytest
from pydantic import Field

from hive.agents import factory
from hive.agents.base import Agent, TurnContext
from hive.agents.factory import (
    AgentRegistration,
    AgentSpec,
    InvalidAgentSpecError,
    build_agent,
    list_agents,
    list_presets,
    register_agent,
)
from hive.agents.minimax import MinimaxAgent
from hive.agents.negamax import NegamaxAgent
from hive.agents.random import RandomAgent
from hive.engine.codec import json_adapter
from hive.engine.rules import Rules
from hive.engine.state import GameState


@dataclass(frozen=True, slots=True)
class Network:
    hidden: int = 8
    blocks: int = 2


class NeuralAgent(Agent):
    """Agent with a required param and a nested config, like a future neural agent."""

    def __init__(
        self,
        rules: Rules,
        *,
        seed: int,
        weights: str,
        network: Network = Network(),  # noqa: B008
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
        super().__init__(rules=rules, seed=seed)

        if not weights:
            msg = "Missing weights."
            raise ValueError(msg)

        self.weights = weights
        self.network = network
        self.temperature = temperature

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        turn.submit(move=None, final=True)


@pytest.fixture(scope="function")
def agent_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register test agents in a copy of the registry that is restored afterwards."""
    monkeypatch.setattr(factory, "AGENT_REGISTRY", dict(factory.AGENT_REGISTRY))


class TestAgentSpecFromYaml:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("random", AgentSpec("random")),
            ("kind: random", AgentSpec("random")),
            (
                "kind: negamax\nlabel: nm3\nparams:\n  depth: 3\n  mobility: 0.5\n",
                AgentSpec(
                    kind="negamax", params={"depth": 3, "mobility": 0.5}, label="nm3"
                ),
            ),
            (
                "{kind: minimax, params: {depth: null}}",
                AgentSpec(kind="minimax", params={"depth": None}),
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


class TestAgentSpecFile:
    def test_loads_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nm3.yaml"
        path.write_text("kind: negamax\nlabel: nm3\nparams:\n  depth: 3\n")

        assert AgentSpec.load(path) == AgentSpec(
            kind="negamax", params={"depth": 3}, label="nm3"
        )

    def test_names_file_in_errors(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("kind: negamax\nparams:\n  depth: 0\n")

        with pytest.raises(
            InvalidAgentSpecError, match=f"Invalid agent spec in `{path}`"
        ):
            AgentSpec.load(path)

    @pytest.mark.parametrize(
        "spec",
        [
            AgentSpec("random"),
            AgentSpec(kind="negamax", params={"depth": 2, "mobility": 0.5}, label="nm2"),
        ],
    )
    def test_round_trips(self, spec: AgentSpec) -> None:
        assert AgentSpec.parse(spec.to_json()) == spec

    def test_json_form(self) -> None:
        assert AgentSpec("random").to_json() == {
            "kind": "random",
            "params": {},
            "label": None,
        }

    def test_from_json_checks_only_the_shape(self) -> None:
        assert AgentSpec.from_json({"kind": "unregistered"}).kind == "unregistered"

        with pytest.raises(ValueError, match="kind"):
            AgentSpec.from_json({"params": {}})

    def test_registration_json_form(self) -> None:
        registration = {agent.kind: agent for agent in list_agents()}["negamax"]
        adapter = json_adapter(AgentRegistration)
        data = adapter.dump_python(registration, mode="json")
        schema = adapter.json_schema(mode="serialization")

        assert isinstance(data, dict)
        assert sorted(data) == ["description", "kind", "params_schema"]
        assert data["params_schema"] == registration.params_model.model_json_schema()
        assert sorted(schema["properties"]) == ["description", "kind", "params_schema"]

    def test_display_label(self) -> None:
        assert AgentSpec("random").display_label == "random"
        assert AgentSpec(kind="random", label="r").display_label == "r"


class TestPresets:
    def test_lists_presets(self) -> None:
        assert {"nm2", "nm3"} <= set(list_presets())
        assert list_presets() == sorted(list_presets())

    @pytest.mark.parametrize("name", list_presets())
    def test_every_preset_is_valid(self, name: str) -> None:
        spec = AgentSpec.from_preset(name)

        build_agent(spec=spec, rules=Rules(), seed=0)
        assert spec.label is not None

    def test_labels_preset_with_its_name(self) -> None:
        assert AgentSpec.from_preset("nm3") == AgentSpec(
            kind="negamax", params={"depth": 3}, label="nm3"
        )

    def test_rejects_unknown_preset(self) -> None:
        with pytest.raises(InvalidAgentSpecError, match="Unknown agent preset `nope`"):
            AgentSpec.from_preset("nope")


class TestAgentSpecResolve:
    def test_prefers_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "nm3").write_text("kind: negamax\nlabel: mine\n")
        monkeypatch.chdir(tmp_path)

        assert AgentSpec.resolve("nm3") == AgentSpec(kind="negamax", label="mine")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("nm2", AgentSpec(kind="negamax", params={"depth": 2}, label="nm2")),
            ("random", AgentSpec("random")),
            (
                "{kind: negamax, params: {depth: 2}}",
                AgentSpec(kind="negamax", params={"depth": 2}),
            ),
            (
                "{kind: random, label: " + "x" * 300 + "}",
                AgentSpec(kind="random", label="x" * 300),
            ),
        ],
    )
    def test_reads_preset_or_inline_yaml(self, value: str, expected: AgentSpec) -> None:
        assert AgentSpec.resolve(value) == expected

    def test_rejects_invalid(self) -> None:
        with pytest.raises(InvalidAgentSpecError, match="Unknown agent kind `nm4`"):
            AgentSpec.resolve("nm4")


class TestBuildAgent:
    @pytest.mark.parametrize(
        ("kind", "agent_class"),
        [("random", RandomAgent), ("minimax", MinimaxAgent), ("negamax", NegamaxAgent)],
    )
    def test_builds_registered_kind(self, kind: str, agent_class: type[Agent]) -> None:
        assert (
            type(build_agent(spec=AgentSpec(kind), rules=Rules(), seed=0)) is agent_class
        )

    def test_applies_params(self) -> None:
        spec = AgentSpec(
            kind="negamax", params={"depth": 3, "mobility": 0.5, "queen_safety": 0}
        )
        agent = build_agent(spec=spec, rules=Rules(), seed=0)

        assert isinstance(agent, NegamaxAgent)
        assert (agent.depth, agent.mobility, agent.queen_safety) == (3, 0.5, 0.0)

    def test_coerces_strings(self) -> None:
        agent = build_agent(
            spec=AgentSpec(kind="negamax", params={"depth": "2"}), rules=Rules(), seed=0
        )

        assert isinstance(agent, NegamaxAgent)
        assert agent.depth == 2

    def test_passes_rules(self) -> None:
        rules = Rules(max_turns=10)

        assert build_agent(spec=AgentSpec("random"), rules=rules, seed=0).rules is rules

    @pytest.mark.parametrize(
        ("spec", "match"),
        [
            (AgentSpec("alphazero"), "Unknown agent kind `alphazero`"),
            (
                AgentSpec(kind="random", params={"depth": 1}),
                "params.depth: Unknown param",
            ),
            (
                AgentSpec(kind="negamax", params={"depth": 0}),
                "params.depth: Input should be greater",
            ),
        ],
    )
    def test_rejects_invalid(self, spec: AgentSpec, match: str) -> None:
        with pytest.raises(InvalidAgentSpecError, match=match):
            build_agent(spec=spec, rules=Rules(), seed=0)


class TestListAgents:
    def test_lists_all_kinds(self) -> None:
        assert {agent.kind for agent in list_agents()} == {"random", "minimax", "negamax"}

    def test_describes_agents_from_docstrings(self) -> None:
        agents = {agent.kind: agent for agent in list_agents()}

        assert agents["random"].description == (
            "Agent that selects moves uniformly at random from the set of legal moves."
        )
        assert agents["random"].params_schema["properties"] == {}

    def test_derives_schema_from_signature(self) -> None:
        agents = {agent.kind: agent for agent in list_agents()}
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


@pytest.mark.usefixtures("agent_registry")
class TestRegisterAgent:
    def test_registers_class_with_nested_params(self) -> None:
        assert register_agent("neural")(NeuralAgent) is NeuralAgent

        spec = AgentSpec.from_yaml(
            "kind: neural\nparams:\n  weights: s3://a.onnx\n  network: {hidden: 64}"
        )
        agent = build_agent(spec=spec, rules=Rules(), seed=0)

        assert isinstance(agent, NeuralAgent)
        assert agent.weights == "s3://a.onnx"
        assert agent.network == Network(hidden=64, blocks=2)
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
        register_agent("neural")(NeuralAgent)
        schema = {agent.kind: agent for agent in list_agents()}["neural"].params_schema

        assert schema["required"] == ["weights"]
        properties = schema["properties"]
        assert isinstance(properties, dict)
        assert properties["weights"] == {
            "description": "The path to the model weights.",
            "title": "Weights",
            "type": "string",
        }

        with pytest.raises(InvalidAgentSpecError, match="temperature: Input should be"):
            AgentSpec.parse(
                {"kind": "neural", "params": {"weights": "w", "temperature": 0}}
            )

        with pytest.raises(
            InvalidAgentSpecError, match=r"params\.weights: Field required"
        ):
            AgentSpec.parse({"kind": "neural"})

    def test_rejects_duplicate_kind(self) -> None:
        with pytest.raises(ValueError, match="`random` is already registered"):
            register_agent("random")(NeuralAgent)

    def test_rejects_missing_seed(self) -> None:
        class NoSeedAgent(NeuralAgent):
            def __init__(self, rules: Rules) -> None:
                super().__init__(rules=rules, seed=0, weights="w")

        with pytest.raises(TypeError, match="must start with `rules` and `seed`"):
            register_agent("no-seed")(NoSeedAgent)

    def test_rejects_positional_param(self) -> None:
        class PositionalAgent(NeuralAgent):
            def __init__(self, rules: Rules, seed: int, depth: int) -> None:
                super().__init__(rules=rules, seed=seed, weights="w")

        with pytest.raises(
            TypeError, match="`depth` of `PositionalAgent` must be keyword-only"
        ):
            register_agent("positional")(PositionalAgent)

    def test_rejects_missing_annotation(self) -> None:
        class UnannotatedAgent(NeuralAgent):
            def __init__(self, rules: Rules, *, seed: int, depth=1) -> None:  # noqa: ANN001
                super().__init__(rules=rules, seed=seed, weights="w")

        with pytest.raises(
            TypeError, match="`depth` of `UnannotatedAgent` has no annotation"
        ):
            register_agent("unannotated")(UnannotatedAgent)
