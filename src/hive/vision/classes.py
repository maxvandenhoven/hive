"""Detection classes: one class per owner and piece type, shared by every tileset.

The class id is `owner * 5 + piece_type`, matching the `Player` and `PieceType` values, so
`white_queen` is 0 and `black_ant` is 9. This module only depends on the engine, so the
dataset export can use it without the `vision` extra.
"""

from dataclasses import dataclass
from typing import Self

from hive.engine.state import PieceType, Player


@dataclass(frozen=True, slots=True)
class TileClass:
    """The detection class of a tile face: the colour of the tile and its insect.

    Attributes:
        piece_type: The insect on the tile.
        owner: The player the tile belongs to, which is its colour.
    """

    piece_type: PieceType
    owner: Player

    @property
    def id(self) -> int:
        """The class id, `owner * 5 + piece_type`."""
        return self.owner * len(PieceType) + self.piece_type

    @property
    def name(self) -> str:
        """The class name, for example `white_queen`."""
        return f"{self.owner.name.lower()}_{self.piece_type.name.lower()}"

    @classmethod
    def from_id(cls, class_id: int) -> Self:
        """Get the class with an id.

        Args:
            class_id: The class id between 0 and 9.

        Returns:
            The class.

        Raises:
            ValueError: If the id is out of range.
        """
        owner, piece_type = divmod(class_id, len(PieceType))

        if not 0 <= class_id < len(Player) * len(PieceType):
            msg = f"Unknown tile class id `{class_id}`."
            raise ValueError(msg)

        return cls(piece_type=PieceType(piece_type), owner=Player(owner))

    @classmethod
    def all(cls) -> list[Self]:
        """Get every class in id order.

        Returns:
            The ten classes, white then black, each in piece type order.
        """
        return [
            cls(piece_type=piece_type, owner=owner)
            for owner in Player
            for piece_type in PieceType
        ]
