"""JSON serialization of values, with pydantic as the only codec.

Values stay plain dataclasses, so the engine keeps its speed and its freedom to change
representation; pydantic only runs when a value is written or read. A dataclass inherits
`JsonCodec` for `to_json` and `from_json`, and declares its JSON form with annotations:
field aliases such as `Field(alias="from")`, `StrictInt` where the JSON must hold a real
integer, and `NamedIntEnum` members, which are written as their lower case names. The same
annotations give the JSON schema that the API publishes.
"""

from enum import IntEnum
from functools import cache
from typing import Any, Self

from pydantic import GetCoreSchemaHandler, JsonValue, TypeAdapter
from pydantic_core import core_schema


@cache
def json_adapter(kind: Any) -> TypeAdapter[Any]:
    """Get the pydantic adapter of a type, built once per type.

    Args:
        kind: A type or type expression, for example `Rules` or `Move | None`.

    Returns:
        The adapter that validates, serializes and describes values of the type.
    """
    return TypeAdapter(kind)


class JsonCodec:
    """A mixin that converts a dataclass to and from its JSON-compatible form."""

    __slots__ = ()

    def to_json(self) -> JsonValue:
        """Serialize the value.

        Returns:
            The JSON-compatible form, with field aliases and enums as names.
        """
        return json_adapter(type(self)).dump_python(self, mode="json", by_alias=True)

    @classmethod
    def from_json(cls, data: object) -> Self:
        """Deserialize and validate a value.

        Args:
            data: The JSON-compatible form, for example from `json.loads`.

        Returns:
            The value.

        Raises:
            pydantic.ValidationError: If `data` does not describe a valid value. It is a
                `ValueError` that lists the location of every problem.
        """
        return json_adapter(cls).validate_python(data)


class NamedIntEnum(IntEnum):
    """An integer enum whose JSON form is the lower case member name, such as `ant`."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """Describe the enum to pydantic: members are read and written as their names.

        Args:
            source: The annotated type, the enum itself.
            handler: Builds the schemas of other types; unused.

        Returns:
            A schema that accepts a member name (and, in Python, a member) and writes the
            name.
        """
        names = core_schema.literal_schema([member.name.lower() for member in cls])
        from_name = core_schema.no_info_after_validator_function(
            lambda name: cls[name.upper()], names
        )

        return core_schema.json_or_python_schema(
            json_schema=from_name,
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(cls), from_name]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda member: member.name.lower(), return_schema=names
            ),
        )
