from hive.engine.codec import json_adapter
from hive.engine.rules import Rules
from hive.engine.state import Move, PieceType, Player


def test_adapter_is_built_once() -> None:
    assert json_adapter(Rules) is json_adapter(Rules)


class TestNamedIntEnum:
    def test_reads_names_and_members(self) -> None:
        adapter = json_adapter(dict[PieceType, Player])

        assert adapter.validate_python(
            {"ant": "black", PieceType.QUEEN: Player.WHITE}
        ) == {PieceType.ANT: Player.BLACK, PieceType.QUEEN: Player.WHITE}

    def test_writes_names_also_as_keys(self) -> None:
        adapter = json_adapter(dict[PieceType, Player])

        assert adapter.dump_python({PieceType.ANT: Player.BLACK}, mode="json") == {
            "ant": "black"
        }

    def test_json_schema_lists_the_names(self) -> None:
        assert json_adapter(Player).json_schema() == {
            "enum": ["white", "black"],
            "type": "string",
        }


def test_json_schema_uses_aliases() -> None:
    schema = json_adapter(Move).json_schema(by_alias=True)

    assert schema["required"] == ["piece", "from", "to"]
    assert schema["additionalProperties"] is False
