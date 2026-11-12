"""JSON forms of the values of the Rust core.

`Move` and `Rules` are classes of the Rust core (`hive._core`), so pydantic cannot read
their fields. Each has a plain dataclass here with the same name, fields and docstring,
which defines its JSON form: the field aliases and strict types that validation,
serialization and the published JSON schema use (D25). The Rust classes describe
themselves to pydantic with `core_schema`, which converts between a value and its form.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Annotated

from pydantic import (
    Field,
    GetCoreSchemaHandler,
    PlainSerializer,
    StrictBool,
    StrictInt,
    ValidatorFunctionWrapHandler,
)
from pydantic_core import CoreSchema, core_schema

from hive import _core
from hive.engine.codec import JsonCodec
from hive.engine.grid import Coordinate
from hive.engine.rules import BASE_PIECE_COUNTS, PieceCount
from hive.engine.state import PieceType, Player


@dataclass(slots=True)
class Move(JsonCodec):
    """The JSON form of `hive.engine.state.Move`, whose docstring replaces this one."""

    piece_type: Annotated[PieceType, Field(alias="piece")]
    source_coord: Annotated[Coordinate | None, Field(alias="from")]
    target_coord: Annotated[Coordinate, Field(alias="to")]


@dataclass(slots=True)
class Rules(JsonCodec):
    """The JSON form of `hive.engine.rules.Rules`, whose docstring replaces this one."""

    piece_counts: Annotated[
        Mapping[PieceType, PieceCount],
        PlainSerializer(dict, return_type=dict[PieceType, PieceCount]),
    ] = field(default_factory=lambda: BASE_PIECE_COUNTS)
    starting_player: Player = Player.WHITE
    queen_by_turn: StrictInt | None = 4
    allow_queen_first_turn: StrictBool = True
    move_before_queen: StrictBool = False
    max_turns: StrictInt | None = None


# The JSON schema describes a value with the docstring of its class, which lives in Rust.
Move.__doc__ = _core.Move.__doc__
Rules.__doc__ = _core.Rules.__doc__

FORMS: dict[type, type[Move | Rules]] = {_core.Move: Move, _core.Rules: Rules}
"""The JSON form of each value class of the Rust core."""


def core_schema_of(value_type: type, handler: GetCoreSchemaHandler) -> CoreSchema:
    """Build the pydantic schema of a value class of the Rust core from its JSON form.

    JSON is validated as the form and converted to the value. Python input may also be a
    value already, which passes unchanged, so validation errors keep the locations of the
    form. Serialization converts the value to its form, so the JSON and its schema are
    those of the form.

    Args:
        value_type: The value class, `hive._core.Move` or `hive._core.Rules`.
        handler: Builds the schemas of other types.

    Returns:
        The pydantic core schema of the value class.
    """
    form_type = FORMS[value_type]
    names = [form_field.name for form_field in fields(form_type)]
    form_schema = handler.generate_schema(form_type)

    def to_value(form: object) -> object:
        """Convert a validated form to the value.

        Args:
            form: An instance of the form class.

        Returns:
            The value with the fields of the form.
        """
        return value_type(**{name: getattr(form, name) for name in names})

    def to_form(value: object) -> object:
        """Convert a value to its form for serialization.

        Args:
            value: An instance of the value class.

        Returns:
            The form with the fields of the value.
        """
        return form_type(**{name: getattr(value, name) for name in names})

    def accept_value(data: object, validate_form: ValidatorFunctionWrapHandler) -> object:
        """Pass a value through unchanged, and validate anything else as the form.

        Args:
            data: The input, a value or the JSON form.
            validate_form: Validates the input as the form and converts it to a value.

        Returns:
            The value.
        """
        if isinstance(data, value_type):
            return data

        return validate_form(data)

    return core_schema.no_info_wrap_validator_function(
        accept_value,
        core_schema.no_info_after_validator_function(to_value, form_schema),
        serialization=core_schema.plain_serializer_function_ser_schema(
            to_form, return_schema=form_schema
        ),
    )
