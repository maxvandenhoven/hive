import pytest

from hive.engine.state import PieceType, Player
from hive.vision.classes import TileClass


def test_ids_follow_owner_then_piece_type() -> None:
    classes = TileClass.all()

    assert [tile_class.id for tile_class in classes] == list(range(10))
    assert classes[0] == TileClass(piece_type=PieceType.QUEEN, owner=Player.WHITE)
    assert classes[9] == TileClass(piece_type=PieceType.ANT, owner=Player.BLACK)
    assert classes[6].name == "black_beetle"


def test_from_id_inverts_id() -> None:
    for tile_class in TileClass.all():
        assert TileClass.from_id(tile_class.id) == tile_class


@pytest.mark.parametrize("class_id", [-1, 10])
def test_from_id_rejects_unknown_ids(class_id: int) -> None:
    with pytest.raises(ValueError, match="Unknown tile class"):
        TileClass.from_id(class_id)
