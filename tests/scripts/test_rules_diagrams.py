import json
from pathlib import Path

import pytest
from rules_diagrams import (
    RULES_DIAGRAMS,
    RULES_DIAGRAMS_PATH,
    RulesDiagram,
    RulesDiagramError,
    main,
    rules_diagrams_json,
)

from hive.engine.rules import Rules
from hive.engine.state import PieceType, Player


def test_committed_diagrams_are_up_to_date() -> None:
    committed = json.loads(RULES_DIAGRAMS_PATH.read_text())

    assert committed == rules_diagrams_json(Rules()), "Run `make rules-diagrams`."


def test_diagram_ids_are_unique() -> None:
    ids = [diagram.id for diagram in RULES_DIAGRAMS]

    assert len(ids) == len(set(ids))


def test_check_mode_passes_for_the_committed_file() -> None:
    assert main(["--check"]) == 0


def test_check_mode_fails_for_a_stale_file(tmp_path: Path) -> None:
    output = tmp_path / "rulesDiagrams.json"
    output.write_text('{"diagrams": []}\n')

    assert main(["--check", "--output", str(output)]) == 1


def test_write_mode_writes_every_diagram(tmp_path: Path) -> None:
    output = tmp_path / "rulesDiagrams.json"

    assert main(["--output", str(output)]) == 0
    assert len(json.loads(output.read_text())["diagrams"]) == len(RULES_DIAGRAMS)


def test_legal_forbidden_target_fails() -> None:
    diagram = RulesDiagram(
        id="wrong",
        caption="The queen may not step next to itself.",
        cells={(0, 0): "wQ", (1, 0): "bQ"},
        current_player=Player.WHITE,
        piece=PieceType.QUEEN,
        source=(0, 0),
        forbidden=((1, -1),),
    )

    with pytest.raises(RulesDiagramError, match="which is legal"):
        diagram.to_json(Rules())


@pytest.mark.parametrize(
    "path",
    [((0, 0), (2, -1)), ((1, 0), (1, -1)), ((0, 0), (-1, 0))],
    ids=["not-adjacent", "wrong-source", "illegal-target"],
)
def test_invalid_path_fails(path: tuple[tuple[int, int], ...]) -> None:
    diagram = RulesDiagram(
        id="wrong",
        caption="The queen steps around the black queen.",
        cells={(0, 0): "wQ", (1, 0): "bQ"},
        current_player=Player.WHITE,
        piece=PieceType.QUEEN,
        source=(0, 0),
        path=path,
    )

    with pytest.raises(RulesDiagramError, match="path"):
        diagram.to_json(Rules())


def test_targets_without_a_piece_fail() -> None:
    diagram = RulesDiagram(
        id="wrong",
        caption="Nothing moves.",
        cells={(0, 0): "wQ", (1, 0): "bQ"},
        current_player=Player.WHITE,
        forbidden=((1, -1),),
    )

    with pytest.raises(RulesDiagramError, match="without a piece"):
        diagram.to_json(Rules())


def test_stacked_cells_are_read_bottom_to_top() -> None:
    diagram = next(diagram for diagram in RULES_DIAGRAMS if diagram.id == "beetle-pin")
    board = diagram.to_json(Rules())["board"]

    assert isinstance(board, list)
    assert {
        "coord": [1, 0],
        "stack": [
            {"piece": "ant", "owner": "black"},
            {"piece": "beetle", "owner": "white"},
        ],
    } in board
