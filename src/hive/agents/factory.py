"""Agent specifications, the registry of agent kinds and the agent factory.

Agent classes register a kind name with `register_agent`. The params of a kind are the
fields of the params model its class names in `Agent.Params` (`hive.agents.params`),
which validates specs and gives the params schema with its constraints, defaults and
descriptions.
"""

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import Field, JsonValue, ValidationError, computed_field
from pydantic.json_schema import SkipJsonSchema

from hive.agents.base import Agent
from hive.agents.params import AgentParams
from hive.engine.codec import JsonCodec
from hive.engine.rules import Rules

AGENT_PRESET_PACKAGE = "hive.agents.presets"
"""The package holding the preset spec files, one `<name>.yaml` per preset."""

ERROR_TYPE_ALIASES = {
    "unexpected_keyword_argument": "extra_forbidden",
    "missing_argument": "missing",
}
"""The pydantic error types of dataclasses, by the matching error type of models."""


class InvalidAgentSpecError(ValueError):
    """Raised when an agent spec has an unknown kind, a bad shape or invalid params."""


@dataclass(frozen=True, slots=True)
class AgentRegistration:
    """A registered agent kind: the agent class and the model that validates its params.

    Its JSON form, which the API lists for the agent picker, has the `kind`, the
    `description` and the `params_schema`; the class and the model are left out.

    Attributes:
        kind: The kind name used in `AgentSpec.kind`.
        agent_class: The agent class, called with the rules, a keyword `seed` and the
            validated params as the keyword `params`.
    """

    kind: str
    agent_class: Annotated[SkipJsonSchema[type[Agent]], Field(exclude=True)]

    @property
    def params_model(self) -> type[AgentParams]:
        """The model that validates the params, which the agent class declares."""
        return self.agent_class.Params

    @computed_field
    @property
    def description(self) -> str:
        """The summary line of the agent class docstring."""
        return (inspect.getdoc(self.agent_class) or "").partition("\n")[0]

    @computed_field
    @property
    def params_schema(self) -> dict[str, JsonValue]:
        """The JSON schema of the params, for rendering parameter forms."""
        schema = self.params_model.model_json_schema()
        # Kinds that share a params model keep a title of their own, and the docstring of
        # the model stays out of the forms.
        schema.pop("description", None)

        return {**schema, "title": f"{self.agent_class.__name__}Params"}


AGENT_REGISTRY: dict[str, AgentRegistration] = {}
"""The registered agent kinds by kind name, filled by `register_agent`."""


@dataclass(frozen=True, slots=True)
class AgentSpec(JsonCodec):
    """A named, configured agent, as chosen in the app, a config file or the CLI.

    The JSON form is a mapping with `kind`, an optional `label` and optional `params`,
    for example in YAML:

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
    def parse(cls, data: object, *, source: str | None = None) -> "AgentSpec":
        """Read a spec from user input and check its params against its kind.

        `from_json` only checks the shape, which is enough for stored records; this also
        checks that the kind is registered and the params are valid, with readable errors.

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
            spec = cls.from_json(data)
        except ValidationError as e:
            raise InvalidAgentSpecError(
                format_spec_errors(source=source, errors=e.errors())
            ) from e

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
            msg = f"Invalid YAML{describe_source(source)}: {e}"
            raise InvalidAgentSpecError(msg) from e

        if isinstance(data, str):
            data = {"kind": data}

        return cls.parse(data=data, source=source)

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
        return cls.from_yaml(text=path.read_text(), source=f"`{path}`")

    @classmethod
    def from_preset(cls, name: str) -> "AgentSpec":
        """Read and validate a preset spec shipped in `hive.agents.presets`.

        Args:
            name: The name of the preset, which is its file name without `.yaml`.

        Returns:
            The spec, labelled with the preset name unless the file sets a label.

        Raises:
            InvalidAgentSpecError: If there is no such preset or the preset is invalid.
        """
        return AgentPreset.load(name).spec

    @classmethod
    def resolve(cls, value: str) -> "AgentSpec":
        """Read a spec from a YAML file, a preset name or inline YAML, in that order.

        Args:
            value: The path of a YAML spec file, the name of a preset, or inline YAML such
                as `random` or `{kind: negamax, params: {depth: 2}}`.

        Returns:
            The validated spec.

        Raises:
            InvalidAgentSpecError: If the spec is invalid.
            OSError: If the file exists but cannot be read.
        """
        try:
            is_file = Path(value).is_file()
        except OSError:
            # Long inline YAML is not a valid file name.
            is_file = False

        if is_file:
            return cls.load(Path(value))

        if value in list_presets():
            return cls.from_preset(value)

        return cls.from_yaml(value)

    @property
    def display_label(self) -> str:
        """The label of the agent, or its kind if it has no label."""
        return self.label or self.kind

    def validate_params(self, *, source: str | None = None) -> AgentParams:
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
                f"Unknown agent kind `{self.kind}`{describe_source(source)}, expected "
                f"one of: {', '.join(AGENT_REGISTRY)}."
            )
            raise InvalidAgentSpecError(msg)

        try:
            return registration.params_model.model_validate(dict(self.params))
        except ValidationError as e:
            errors = [{**error, "loc": ("params", *error["loc"])} for error in e.errors()]
            raise InvalidAgentSpecError(
                format_spec_errors(source=source, errors=errors, kind=self.kind)
            ) from e


@dataclass(frozen=True, slots=True)
class AgentPreset(JsonCodec):
    """A tuned agent shipped in `hive.agents.presets`, offered by name.

    A preset file is a spec in YAML with a `description` next to `kind`, `label` and
    `params`.

    Attributes:
        name: The name of the preset, which is its file name without `.yaml`.
        description: What the agent is like, in one short sentence.
        spec: The agent, labelled with the preset name unless the file sets a label.
    """

    name: str
    description: str
    spec: AgentSpec

    @classmethod
    def load(cls, name: str) -> "AgentPreset":
        """Read and validate a preset.

        Args:
            name: The name of the preset.

        Returns:
            The preset.

        Raises:
            InvalidAgentSpecError: If there is no such preset, it has no description or
                its spec is invalid.
        """
        presets = list_presets()

        if name not in presets:
            msg = f"Unknown agent preset `{name}`, expected one of: {', '.join(presets)}."
            raise InvalidAgentSpecError(msg)

        source = f"preset `{name}`"
        text = files(AGENT_PRESET_PACKAGE).joinpath(f"{name}.yaml").read_text()
        data = yaml.safe_load(text)
        description = data.pop("description", None) if isinstance(data, dict) else None

        if not isinstance(description, str):
            msg = f"The {source} needs a `description` string."
            raise InvalidAgentSpecError(msg)

        spec = AgentSpec.parse(data=data, source=source)

        return cls(
            name=name,
            description=description,
            spec=spec if spec.label is not None else replace(spec, label=name),
        )

    @classmethod
    def load_all(cls) -> list["AgentPreset"]:
        """Read and validate every shipped preset.

        Returns:
            The presets, sorted by name.

        Raises:
            InvalidAgentSpecError: If a preset is invalid.
        """
        return [cls.load(name) for name in list_presets()]


def register_agent[A: Agent](kind: str) -> Callable[[type[A]], type[A]]:
    """Register an agent class under a kind name, making it available to specs.

    The params of the kind are the fields of the params model of the class
    (`Agent.Params`).

    Args:
        kind: The kind name used in `AgentSpec.kind`.

    Returns:
        A class decorator that registers the class and returns it unchanged.

    Raises:
        ValueError: If `kind` is already registered.
    """

    def register(agent_class: type[A]) -> type[A]:
        if kind in AGENT_REGISTRY:
            msg = f"Agent kind `{kind}` is already registered."
            raise ValueError(msg)

        AGENT_REGISTRY[kind] = AgentRegistration(kind=kind, agent_class=agent_class)

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

    return agent_class(rules=rules, seed=seed, params=params)


def list_agents() -> list[AgentRegistration]:
    """List the registered agent kinds, with their descriptions and params schemas.

    Returns:
        One registration per kind, in registration order.
    """
    return list(AGENT_REGISTRY.values())


def list_presets() -> list[str]:
    """List the preset specs shipped in `hive.agents.presets`.

    Returns:
        The preset names, sorted.
    """
    return sorted(
        resource.name.removesuffix(".yaml")
        for resource in files(AGENT_PRESET_PACKAGE).iterdir()
        if resource.name.endswith(".yaml")
    )


def format_spec_errors(
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
    lines = [f"Invalid agent spec{describe_source(source)}:"]

    for error in errors:
        location = ".".join(str(part) for part in error["loc"]) or "spec"

        error_type = ERROR_TYPE_ALIASES.get(error["type"], error["type"])

        if error_type == "extra_forbidden" and kind is not None:
            known = ", ".join(AGENT_REGISTRY[kind].params_model.model_fields) or "none"
            lines.append(f"  {location}: Unknown param, expected one of: {known}.")
        elif error_type == "missing":
            lines.append(f"  {location}: Field required.")
        elif error_type == "extra_forbidden":
            lines.append(f"  {location}: Unknown key, expected kind, label or params.")
        else:
            lines.append(f"  {location}: {error['msg']} (got {error['input']!r}).")

    return "\n".join(lines)


def describe_source(source: str | None) -> str:
    """Describe where a spec came from, for the start of an error message.

    Args:
        source: Where the spec came from, such as a file path, or `None` if unknown.

    Returns:
        ` in <source>`, or an empty string if the source is unknown.
    """
    return "" if source is None else f" in {source}"
