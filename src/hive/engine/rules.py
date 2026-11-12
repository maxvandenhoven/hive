"""The rules of the game: `Rules` from the Rust core and the counts of the base game.

`Rules` holds the configuration of a game and all rule behaviour: legal moves, validated
entry points, the end of the game and explanations of illegal moves. It is a class of the
Rust core (`hive._core`), re-exported here with its documentation in `hive/_core.pyi`.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated

from pydantic import Field, StrictInt

from hive._core import Rules
from hive.engine.state import PieceType

__all__ = ["BASE_PIECE_COUNTS", "PieceCount", "Rules"]

BASE_PIECE_COUNTS: Mapping[PieceType, int] = MappingProxyType(
    {
        PieceType.QUEEN: 1,
        PieceType.BEETLE: 2,
        PieceType.GRASSHOPPER: 3,
        PieceType.SPIDER: 2,
        PieceType.ANT: 3,
    }
)
"""The number of copies of each piece type a player receives in the base game."""


type PieceCount = Annotated[StrictInt, Field(ge=0)]
"""The number of copies of a piece type. The same type is read and written, so the JSON
schema of `Rules` is the same for requests and responses."""
