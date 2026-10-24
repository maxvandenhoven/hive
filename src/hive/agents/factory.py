"""Agent specifications, the registry of agent kinds and the agent factory."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hive.agents.base import Agent
from hive.agents.minimax import MinimaxAgent
from hive.agents.negamax import NegamaxAgent
from hive.agents.random import RandomAgent
from hive.engine.rules import Rules
from hive.engine.serialization import JsonValue


class AgentParams(BaseModel):
    """Base class for the parameters of an agent kind, which rejects unknown names."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RandomParams(AgentParams):
    """Parameters of the `random` agent, which has none."""


class SearchParams(AgentParams):
    """Parameters of the search agents: the depth limit and the evaluation weights."""

    depth: int | None = Field(
        default=None, ge=1, description="Maximum search depth in plies, or none."
    )
    queen_safety: float = Field(
        default=1.0, description="Weight of how surrounded each queen is."
    )
    mobility: float = Field(
        default=0.0, description="Weight of the difference in legal moves (slow)."
    )
    positioning: float = Field(
        default=0.0, description="Weight of own pieces next to the opponent's queen."
    )
    material_on_board: float = Field(
        default=0.0, description="Weight of the value of pieces on the board."
    )
    material_in_hand: float = Field(
        default=0.0, description="Weight of the value of pieces in hand."
    )


@dataclass(frozen=True, slots=True)
class AgentKindInfo:
    """A description of an agent kind, for listing agents and rendering param forms.

    Attributes:
        name: The kind name used in `AgentSpec.kind`.
        description: A one-line description of the agent.
        params_schema: The JSON schema of the parameters.
    """

    name: str
    description: str
    params_schema: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class _AgentKind:
    """A registered agent kind.

    Attributes:
        build: The agent constructor, called with the rules, a keyword `seed` and the
            validated parameters as keywords.
        params_model: The model that validates the parameters.
        description: A one-line description of the agent.
    """

    build: Callable[..., Agent]
    params_model: type[AgentParams]
    description: str


_KINDS: dict[str, _AgentKind] = {
    "random": _AgentKind(
        RandomAgent, RandomParams, "Plays a uniformly random legal move."
    ),
    "minimax": _AgentKind(
        MinimaxAgent, SearchParams, "Minimax search with iterative deepening."
    ),
    "negamax": _AgentKind(
        NegamaxAgent, SearchParams, "Negamax search with iterative deepening."
    ),
}


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """A named, configured agent, as chosen in the app or on the command line.

    Attributes:
        kind: The registered kind of the agent, for example `negamax`.
        params: The free-form JSON parameters, validated by the kind when building.
        label: The display name in reports and the UI, or `None` for none.
    """

    kind: str
    params: Mapping[str, JsonValue] = field(default_factory=dict)
    label: str | None = None

    @classmethod
    def parse(cls, text: str) -> "AgentSpec":
        """Parse a spec from a command line string like `negamax:depth=4,label=nm4`.

        The kind comes before the optional colon, followed by comma-separated `key=value`
        pairs. Values are read as JSON literals where possible (`4`, `0.5`, `true`,
        `null`), and as plain strings otherwise. The `label` key sets the label.

        Args:
            text: The string to parse.

        Returns:
            The parsed spec. Its parameters are not validated until it is built.

        Raises:
            ValueError: If the kind is empty, or a pair has no `=`, an empty key or a key
                that was given before.
        """
        kind, _, pairs = text.partition(":")
        kind = kind.strip()
        if not kind:
            msg = f"Missing agent kind in spec `{text}`."
            raise ValueError(msg)

        params: dict[str, JsonValue] = {}
        label: str | None = None
        for pair in pairs.split(",") if pairs.strip() else []:
            key, sep, value = pair.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or not key:
                msg = f"Expected `key=value` in spec `{text}`, but got `{pair}`."
                raise ValueError(msg)
            if key in params or (key == "label" and label is not None):
                msg = f"Duplicate key `{key}` in spec `{text}`."
                raise ValueError(msg)

            if key == "label":
                label = value
            else:
                params[key] = _parse_value(value)

        return cls(kind, params, label)


def build_agent(spec: AgentSpec, rules: Rules, *, seed: int) -> Agent:
    """Build an agent from a spec, validating its parameters.

    Args:
        spec: The kind and parameters of the agent.
        rules: The rules governing the game.
        seed: The seed for the random number generator of the agent.

    Returns:
        The configured agent.

    Raises:
        ValueError: If the kind is not registered or the parameters are invalid.
    """
    kind = _KINDS.get(spec.kind)
    if kind is None:
        msg = f"Unknown agent kind `{spec.kind}`, expected one of: {', '.join(_KINDS)}."
        raise ValueError(msg)

    try:
        params = kind.params_model.model_validate(dict(spec.params))
    except ValidationError as e:
        msg = f"Invalid parameters for agent kind `{spec.kind}`: {e}"
        raise ValueError(msg) from e

    return kind.build(rules, seed=seed, **params.model_dump())


def agent_kinds() -> list[AgentKindInfo]:
    """List the registered agent kinds with their descriptions and parameter schemas.

    Returns:
        One entry per registered kind, in registration order.
    """
    return [
        AgentKindInfo(name, kind.description, kind.params_model.model_json_schema())
        for name, kind in _KINDS.items()
    ]


def _parse_value(value: str) -> JsonValue:
    """Parse a spec value as a JSON literal, or keep it as a string.

    Args:
        value: The text after `=` in a `key=value` pair.

    Returns:
        The decoded JSON value, or `value` itself if it is not valid JSON.
    """
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
