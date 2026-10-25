"""Agent specifications, the registry of agent kinds and the agent factory.

Agent classes register a kind name with `register_agent`. The parameters of a kind are
the keyword-only parameters of its constructor after `seed`: their annotations (with
`Annotated` constraints such as `Field(ge=1)`) and defaults define a pydantic model that
validates specs, and the `Args:` section of the constructor docstring describes them.
"""

import inspect
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_type_hints

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from hive.agents.base import Agent
from hive.engine.rules import Rules
from hive.engine.serialization import JsonValue

INJECTED_AGENT_PARAMS = ("rules", "seed")
"""The constructor parameters the factory passes itself, which are not agent params."""

_ARG_PATTERN = re.compile(r"^    (\w+)(?: \(.*\))?: (.*)$")
"""A line starting an argument description in a cleaned Google-style docstring."""


class InvalidAgentSpecError(ValueError):
    """Raised when an agent spec has an unknown kind, a bad shape or invalid params."""


@dataclass(frozen=True, slots=True)
class AgentRegistration:
    """A registered agent kind: the agent class and the model that validates its params.

    Attributes:
        kind: The kind name used in `AgentSpec.kind`.
        agent_class: The agent class, called with the rules, a keyword `seed` and the
            validated params as keywords.
        params_model: The model that validates the params, derived from the signature of
            the agent constructor.
    """

    kind: str
    agent_class: type[Agent]
    params_model: type[BaseModel]

    @classmethod
    def from_class(cls, kind: str, agent_class: type[Agent]) -> "AgentRegistration":
        """Register an agent class, deriving its params model from the constructor.

        The keyword-only parameters after `seed` become the fields of the model: their
        annotations (including `Annotated` constraints) and defaults define validation,
        and the `Args:` section of the constructor docstring gives the descriptions.

        Args:
            kind: The kind name used in `AgentSpec.kind`.
            agent_class: The agent class to inspect.

        Returns:
            The registration, with a frozen params model that rejects unknown params.

        Raises:
            TypeError: If the constructor does not start with `rules` and `seed`, or an
                agent param is not keyword-only or has no annotation.
        """
        init = agent_class.__init__
        parameters = list(inspect.signature(init).parameters.values())[1:]
        if [p.name for p in parameters[:2]] != list(INJECTED_AGENT_PARAMS):
            msg = f"`{agent_class.__name__}.__init__` must start with `rules` and `seed`."
            raise TypeError(msg)

        hints = get_type_hints(init, include_extras=True)
        descriptions = _arg_descriptions(inspect.getdoc(init))
        fields: dict[str, Any] = {}
        for parameter in parameters[2:]:
            if parameter.kind is not inspect.Parameter.KEYWORD_ONLY:
                msg = (
                    f"Agent param `{parameter.name}` of `{agent_class.__name__}` must be "
                    "keyword-only."
                )
                raise TypeError(msg)
            if parameter.name not in hints:
                msg = (
                    f"Agent param `{parameter.name}` of `{agent_class.__name__}` has no "
                    "annotation."
                )
                raise TypeError(msg)

            default = (
                ... if parameter.default is inspect.Parameter.empty else parameter.default
            )
            fields[parameter.name] = (
                hints[parameter.name],
                Field(default, description=descriptions.get(parameter.name)),
            )

        params_model = create_model(
            f"{agent_class.__name__}Params",
            __config__=ConfigDict(frozen=True, extra="forbid"),
            **fields,
        )
        return cls(kind, agent_class, params_model)

    @property
    def description(self) -> str:
        """The summary line of the agent class docstring."""
        return (inspect.getdoc(self.agent_class) or "").partition("\n")[0]

    @property
    def params_schema(self) -> dict[str, JsonValue]:
        """The JSON schema of the params, for rendering parameter forms."""
        return self.params_model.model_json_schema()


AGENT_REGISTRY: dict[str, AgentRegistration] = {}
"""The registered agent kinds by kind name, filled by `register_agent`."""


class AgentSpecDocument(BaseModel):
    """The serialized form of an `AgentSpec`, checking its shape but not its params."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    label: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """A named, configured agent, as chosen in the app, a config file or the CLI.

    The serialized form is a mapping with `kind`, an optional `label` and optional
    `params`, for example in YAML:

    ```yaml
    kind: negamax
    label: nm3
    params:
      depth: 3
      mobility: 0.5
    ```

    Attributes:
        kind: The registered kind of the agent, for example `negamax`.
        params: The JSON parameters, validated against the kind when loading or building.
        label: The display name in reports and the UI, or `None` for none.
    """

    kind: str
    params: Mapping[str, JsonValue] = field(default_factory=dict)
    label: str | None = None

    @classmethod
    def from_dict(cls, data: object, *, source: str | None = None) -> "AgentSpec":
        """Read and validate a spec from its serialized form.

        Args:
            data: The decoded spec, a mapping with `kind`, `label` and `params`.
            source: Where the spec came from, such as a file path, for error messages.

        Returns:
            The spec, with the params as given (defaults are not filled in).

        Raises:
            InvalidAgentSpecError: If the shape is wrong, the kind is not registered or
                the params are invalid. All problems are listed in the message.
        """
        try:
            document = AgentSpecDocument.model_validate(data)
        except ValidationError as e:
            raise InvalidAgentSpecError(_format_errors(source, e.errors())) from e

        spec = cls(document.kind, document.params, document.label)
        spec.validate_params(source=source)
        return spec

    @classmethod
    def from_yaml(cls, text: str, *, source: str | None = None) -> "AgentSpec":
        """Read and validate a spec from YAML text.

        A plain kind name such as `random` is a spec with default params, so the same
        text works for a command line option and for the contents of a config file.

        Args:
            text: A YAML mapping in the serialized form, or a YAML string with the kind.
            source: Where the text came from, such as a file path, for error messages.

        Returns:
            The spec.

        Raises:
            InvalidAgentSpecError: If the text is not valid YAML or not a valid spec.
        """
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            msg = f"Invalid YAML{_in(source)}: {e}"
            raise InvalidAgentSpecError(msg) from e

        if isinstance(data, str):
            data = {"kind": data}
        return cls.from_dict(data, source=source)

    @classmethod
    def load(cls, path: Path) -> "AgentSpec":
        """Read and validate a spec from a YAML file.

        Args:
            path: The YAML file with the serialized spec.

        Returns:
            The spec.

        Raises:
            InvalidAgentSpecError: If the file is not valid YAML or not a valid spec.
            OSError: If the file cannot be read.
        """
        return cls.from_yaml(path.read_text(), source=f"`{path}`")

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize the spec.

        Returns:
            A mapping with `kind`, `label` if set, and `params`.
        """
        data: dict[str, JsonValue] = {"kind": self.kind}
        if self.label is not None:
            data["label"] = self.label
        data["params"] = dict(self.params)
        return data

    def validate_params(self, *, source: str | None = None) -> BaseModel:
        """Check that the kind is registered and the params are valid for it.

        Args:
            source: Where the spec came from, such as a file path, for error messages.

        Returns:
            The validated params, with defaults filled in.

        Raises:
            InvalidAgentSpecError: If the kind is not registered or the params are
                invalid. All invalid params are listed in the message.
        """
        registration = AGENT_REGISTRY.get(self.kind)
        if registration is None:
            msg = (
                f"Unknown agent kind `{self.kind}`{_in(source)}, expected one of: "
                f"{', '.join(AGENT_REGISTRY)}."
            )
            raise InvalidAgentSpecError(msg)

        try:
            return registration.params_model.model_validate(dict(self.params))
        except ValidationError as e:
            errors = [{**error, "loc": ("params", *error["loc"])} for error in e.errors()]
            raise InvalidAgentSpecError(
                _format_errors(source, errors, kind=self.kind)
            ) from e


def register_agent[A: Agent](kind: str) -> Callable[[type[A]], type[A]]:
    """Register an agent class under a kind name, making it available to specs.

    The constructor must take `rules` as its first parameter and everything else as
    keyword-only parameters with annotations: `seed`, then the agent params.

    Args:
        kind: The kind name used in `AgentSpec.kind`.

    Returns:
        A class decorator that registers the class and returns it unchanged.

    Raises:
        ValueError: If `kind` is already registered.
        TypeError: If the constructor does not have the expected parameters.
    """

    def register(agent_class: type[A]) -> type[A]:
        if kind in AGENT_REGISTRY:
            msg = f"Agent kind `{kind}` is already registered."
            raise ValueError(msg)

        AGENT_REGISTRY[kind] = AgentRegistration.from_class(kind, agent_class)
        return agent_class

    return register


def build_agent(spec: AgentSpec, rules: Rules, *, seed: int) -> Agent:
    """Build an agent from a spec, validating its params.

    Args:
        spec: The kind and params of the agent.
        rules: The rules governing the game.
        seed: The seed for the random number generator of the agent.

    Returns:
        The configured agent.

    Raises:
        InvalidAgentSpecError: If the kind is not registered or the params are invalid.
    """
    params = spec.validate_params()
    agent_class = AGENT_REGISTRY[spec.kind].agent_class
    return agent_class(rules, seed=seed, **dict(params))


def list_agents() -> list[AgentRegistration]:
    """List the registered agent kinds, with their descriptions and params schemas.

    Returns:
        One registration per kind, in registration order.
    """
    return list(AGENT_REGISTRY.values())


def _arg_descriptions(docstring: str | None) -> dict[str, str]:
    """Read the argument descriptions from the `Args:` section of a Google docstring.

    Args:
        docstring: The cleaned docstring, as returned by `inspect.getdoc`.

    Returns:
        The description of each argument, with continuation lines joined by spaces.
    """
    descriptions: dict[str, str] = {}
    in_args = False
    name: str | None = None
    for line in (docstring or "").splitlines():
        if line == "Args:":
            in_args = True
        elif in_args and line and not line.startswith(" "):
            break
        elif in_args and (match := _ARG_PATTERN.match(line)):
            name = match[1]
            descriptions[name] = match[2]
        elif in_args and name is not None and line.strip():
            descriptions[name] += " " + line.strip()

    return descriptions


def _format_errors(
    source: str | None, errors: Sequence[Mapping[str, Any]], *, kind: str | None = None
) -> str:
    """Format validation errors as one line per problem, with the path to the value.

    Args:
        source: Where the spec came from, such as a file path.
        errors: The validation errors, with locations relative to the spec.
        kind: The kind of the spec, to list the known params for an unknown one.

    Returns:
        The error message.
    """
    lines = [f"Invalid agent spec{_in(source)}:"]
    for error in errors:
        location = ".".join(str(part) for part in error["loc"]) or "spec"
        if error["type"] == "extra_forbidden" and kind is not None:
            known = ", ".join(AGENT_REGISTRY[kind].params_model.model_fields) or "none"
            lines.append(f"  {location}: Unknown param, expected one of: {known}.")
        elif error["type"] == "missing":
            lines.append(f"  {location}: Field required.")
        elif error["type"] == "extra_forbidden":
            lines.append(f"  {location}: Unknown key, expected kind, label or params.")
        else:
            lines.append(f"  {location}: {error['msg']} (got {error['input']!r}).")

    return "\n".join(lines)


def _in(source: str | None) -> str:
    """Describe where a spec came from, for the start of an error message.

    Args:
        source: Where the spec came from, such as a file path, or `None` if unknown.

    Returns:
        ` in <source>`, or an empty string if the source is unknown.
    """
    return "" if source is None else f" in {source}"
