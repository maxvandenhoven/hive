import pytest

from hive.agents.factory import AgentKindInfo, AgentSpec, agent_kinds, build_agent
from hive.agents.minimax import MinimaxAgent
from hive.agents.negamax import NegamaxAgent
from hive.agents.random import RandomAgent
from hive.engine.rules import Rules


class TestParse:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("random", AgentSpec("random")),
            ("random:", AgentSpec("random")),
            (
                "negamax:depth=4,label=nm4",
                AgentSpec("negamax", {"depth": 4}, label="nm4"),
            ),
            (
                " minimax : depth = null , mobility=0.5 ",
                AgentSpec("minimax", {"depth": None, "mobility": 0.5}),
            ),
            (
                "neural:weights=s3://models/a.onnx",
                AgentSpec("neural", {"weights": "s3://models/a.onnx"}),
            ),
            (
                'neural:fast=true,name="x"',
                AgentSpec("neural", {"fast": True, "name": "x"}),
            ),
        ],
    )
    def test_parses(self, text: str, expected: AgentSpec) -> None:
        assert AgentSpec.parse(text) == expected

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("", "Missing agent kind"),
            (":depth=1", "Missing agent kind"),
            ("negamax:depth", "Expected `key=value`"),
            ("negamax:=3", "Expected `key=value`"),
            ("negamax:depth=1,", "Expected `key=value`"),
            ("negamax:depth=1,depth=2", "Duplicate key `depth`"),
            ("negamax:label=a,label=b", "Duplicate key `label`"),
        ],
    )
    def test_rejects_malformed(self, text: str, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            AgentSpec.parse(text)


class TestBuildAgent:
    @pytest.mark.parametrize(
        ("kind", "agent_class"),
        [("random", RandomAgent), ("minimax", MinimaxAgent), ("negamax", NegamaxAgent)],
    )
    def test_builds_registered_kind(self, kind: str, agent_class: type) -> None:
        assert type(build_agent(AgentSpec(kind), Rules(), seed=0)) is agent_class

    def test_applies_params(self) -> None:
        spec = AgentSpec.parse("negamax:depth=3,mobility=0.5,queen_safety=0")
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
            (AgentSpec("random", {"depth": 1}), "Invalid parameters"),
            (AgentSpec("negamax", {"depht": 1}), "Invalid parameters"),
            (AgentSpec("negamax", {"depth": 0}), "Invalid parameters"),
            (AgentSpec("negamax", {"mobility": "high"}), "Invalid parameters"),
        ],
    )
    def test_rejects_invalid(self, spec: AgentSpec, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            build_agent(spec, Rules(), seed=0)


class TestAgentKinds:
    def test_lists_all_kinds(self) -> None:
        assert [kind.name for kind in agent_kinds()] == ["random", "minimax", "negamax"]

    def test_describes_params(self) -> None:
        kinds = {kind.name: kind for kind in agent_kinds()}

        assert all(kind.description for kind in kinds.values())
        assert kinds["random"].params_schema.get("properties", {}) == {}
        properties = kinds["negamax"].params_schema["properties"]
        assert isinstance(properties, dict)
        assert set(properties) == {
            "depth",
            "queen_safety",
            "mobility",
            "positioning",
            "material_on_board",
            "material_in_hand",
        }

    @pytest.mark.parametrize("kind", agent_kinds(), ids=lambda kind: kind.name)
    def test_schema_defaults_match_agent(self, kind: AgentKindInfo) -> None:
        """Test that every parameter is an agent attribute with the schema default."""
        agent = build_agent(AgentSpec(kind.name), Rules(), seed=0)
        properties = kind.params_schema.get("properties", {})
        assert isinstance(properties, dict)

        for name, schema in properties.items():
            assert isinstance(schema, dict)
            assert getattr(agent, name) == schema["default"]
