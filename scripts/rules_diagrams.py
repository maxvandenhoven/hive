"""Write the rule diagrams of the help, with their targets checked against the engine.

Each diagram is a small position with one piece (or a placement) picked out. The allowed
targets are computed by the engine, and the forbidden ones are listed by hand and must be
illegal. The result is committed as `frontend/src/components/help/rulesDiagrams.json`,
and a test fails when that file is stale, like the API client.

Run it with `make rules-diagrams`.
"""

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from hive.engine.grid import Coordinate, get_neighbors
from hive.engine.rules import Rules
from hive.engine.state import (
    BoardCell,
    GameBoard,
    GameState,
    Move,
    Piece,
    PieceType,
    Player,
)

logger = logging.getLogger(__name__)

RULES_DIAGRAMS_PATH = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "src"
    / "components"
    / "help"
    / "rulesDiagrams.json"
)
"""Where the diagrams are written, next to the rules reference that shows them."""

PIECE_CODES: dict[str, PieceType] = {
    "Q": PieceType.QUEEN,
    "B": PieceType.BEETLE,
    "G": PieceType.GRASSHOPPER,
    "S": PieceType.SPIDER,
    "A": PieceType.ANT,
}
"""The letter of each piece type in the compact board notation of the diagrams."""

PLAYER_CODES: dict[str, Player] = {"w": Player.WHITE, "b": Player.BLACK}
"""The letter of each player in the compact board notation of the diagrams."""


class RulesDiagramError(Exception):
    """A rule diagram does not match the engine."""


def parse_board(cells: dict[Coordinate, str]) -> GameBoard:
    """Read a board from the compact notation of the diagrams.

    Args:
        cells: The stack on each coordinate as pieces from bottom to top separated by
            spaces, each a player and a piece letter, for example `"bA wB"` for a white
            beetle on a black ant.

    Returns:
        The board.
    """
    return {
        coord: [
            Piece(type=PIECE_CODES[code[1]], owner=PLAYER_CODES[code[0]])
            for code in stack.split()
        ]
        for coord, stack in cells.items()
    }


@dataclass(frozen=True, slots=True)
class RulesDiagram:
    """A position that shows one rule, with the move it is about.

    Attributes:
        id: The name the rules reference uses for the diagram.
        caption: One or two sentences on what the diagram shows.
        cells: The board in the notation of `parse_board`.
        current_player: The player to move.
        piece: The piece type that moves or is placed, or `None` for a diagram without a
            move, such as a finished game.
        source: The coordinate of the piece that moves, or `None` for a placement.
        forbidden: Targets of the move that must be illegal, chosen because they explain
            the rule.
        path: The hexes the piece passes through, from its source to an allowed target,
            to step through the move. Empty when the move is not stepped.
    """

    id: str
    caption: str
    cells: dict[Coordinate, str]
    current_player: Player
    piece: PieceType | None = None
    source: Coordinate | None = None
    forbidden: tuple[Coordinate, ...] = ()
    path: tuple[Coordinate, ...] = field(default=())

    def create_state(self, rules: Rules) -> GameState:
        """Create the validated game state of the diagram.

        Args:
            rules: The rules the board is validated against.

        Returns:
            The game state at the lowest ply consistent with the board.
        """
        return rules.from_board(
            board=parse_board(self.cells), current_player=self.current_player
        )

    def allowed_targets(self, rules: Rules, state: GameState) -> list[Coordinate]:
        """Get the targets the engine allows for the move of the diagram.

        Args:
            rules: The rules of the game.
            state: The game state of the diagram.

        Returns:
            The sorted targets of the legal moves of `piece` from `source`.
        """
        return sorted(
            move.target_coord
            for move in rules.legal_moves(state)
            if move is not None
            and move.piece_type is self.piece
            and move.source_coord == self.source
        )

    def check(self, rules: Rules, state: GameState, allowed: list[Coordinate]) -> None:
        """Check that the forbidden targets are illegal and the path is a real move.

        Args:
            rules: The rules of the game.
            state: The game state of the diagram.
            allowed: The allowed targets of the move.

        Raises:
            RulesDiagramError: If a forbidden target is legal, a forbidden target or path
                is given without a piece, or the path does not lead from the source to an
                allowed target one step at a time (a grasshopper jumps in one step).
        """
        piece = self.piece

        if piece is None:
            if self.forbidden or self.path:
                msg = f"Diagram `{self.id}` marks targets without a piece to move."
                raise RulesDiagramError(msg)

            return

        legal_moves = rules.legal_moves(state)

        for target in self.forbidden:
            move = Move(piece_type=piece, source_coord=self.source, target_coord=target)

            if move in legal_moves:
                msg = f"Diagram `{self.id}` forbids `{move}`, which is legal."
                raise RulesDiagramError(msg)

        if not self.path:
            return

        jumps = piece is PieceType.GRASSHOPPER
        steps_valid = all(
            jumps or after in get_neighbors(before)
            for before, after in zip(self.path, self.path[1:], strict=False)
        )

        leads_to_target = self.path[0] == self.source and self.path[-1] in allowed

        if not leads_to_target or not steps_valid:
            msg = (
                f"Diagram `{self.id}` has a path that is not a move from its source to "
                "an allowed target."
            )
            raise RulesDiagramError(msg)

    def to_json(self, rules: Rules) -> dict[str, object]:
        """Check the diagram against the engine and convert it for the frontend.

        Args:
            rules: The rules of the game.

        Returns:
            The board as API cells, the move, its allowed and forbidden targets, the
            path, whether the player must pass and the result of the position.
        """
        state = self.create_state(rules)
        allowed = (
            [] if self.piece is None else self.allowed_targets(rules=rules, state=state)
        )
        self.check(rules=rules, state=state, allowed=allowed)
        winners = rules.winners(state)

        if winners is None:
            result = None
        elif len(winners) == 2:
            result = "draw"
        else:
            result = winners[0].name.lower()

        return {
            "id": self.id,
            "caption": self.caption,
            "board": [cell.to_json() for cell in BoardCell.split_board(state.board)],
            "current_player": state.current_player.name.lower(),
            "piece": None if self.piece is None else self.piece.name.lower(),
            "source": None if self.source is None else list(self.source),
            "allowed": [list(coord) for coord in allowed],
            "forbidden": [list(coord) for coord in self.forbidden],
            "path": [list(coord) for coord in self.path],
            "must_pass": rules.legal_moves(state) == [None],
            "result": result,
        }


RULES_DIAGRAMS: tuple[RulesDiagram, ...] = (
    RulesDiagram(
        id="goal",
        caption=(
            "The black queen is surrounded on all six sides, by pieces of both colours, "
            "so white wins."
        ),
        cells={
            (0, 0): "bQ",
            (1, 0): "wA",
            (1, -1): "wG",
            (0, -1): "bA",
            (-1, 0): "wS",
            (-1, 1): "bG",
            (0, 1): "wA",
            (2, -1): "wQ",
        },
        current_player=Player.BLACK,
    ),
    RulesDiagram(
        id="placement-second",
        caption=(
            "The second piece of the game goes next to the first, so it touches the "
            "other colour. This is the only time a placement may touch the opponent."
        ),
        cells={(0, 0): "wG"},
        current_player=Player.BLACK,
        piece=PieceType.GRASSHOPPER,
    ),
    RulesDiagram(
        id="placement-own-colour",
        caption=(
            "After that a new piece may only touch pieces of its own colour, so white "
            "may place on the green hexes but never next to a black piece."
        ),
        cells={(0, 0): "wG", (1, 0): "bG", (-1, 0): "wA", (2, 0): "bA"},
        current_player=Player.WHITE,
        piece=PieceType.SPIDER,
        forbidden=((1, -1), (0, 1)),
    ),
    RulesDiagram(
        id="placement-queen",
        caption=(
            "The queen must be on the board by your fourth turn. White has not placed "
            "it in its first three turns, so the queen is now the only piece white may "
            "place."
        ),
        cells={
            (0, 0): "wG",
            (1, 0): "bQ",
            (-1, 0): "wA",
            (2, 0): "bA",
            (-2, 0): "wS",
            (3, 0): "bG",
        },
        current_player=Player.WHITE,
        piece=PieceType.QUEEN,
    ),
    RulesDiagram(
        id="placement-no-moves",
        caption=(
            "Pieces may only move once their queen is placed, so the white ant cannot "
            "move while white has no queen on the board."
        ),
        cells={(0, 0): "wG", (1, 0): "bQ", (-1, 0): "wA", (2, 0): "bA"},
        current_player=Player.WHITE,
        piece=PieceType.ANT,
        source=(-1, 0),
        forbidden=((-1, 1), (0, -1), (3, 0)),
    ),
    RulesDiagram(
        id="one-hive-split",
        caption=(
            "Taking the white ant away would split the hive in two, so the ant cannot "
            "move, not even to a hex where the hive would join up again."
        ),
        cells={(0, 0): "wQ", (1, 0): "wA", (2, 0): "bQ", (3, 0): "bA"},
        current_player=Player.WHITE,
        piece=PieceType.ANT,
        source=(1, 0),
        forbidden=((1, -1), (2, -1), (4, 0)),
    ),
    RulesDiagram(
        id="one-hive-end",
        caption=(
            "A piece at the end of the hive can move, since the rest stays together."
        ),
        cells={(0, 0): "wA", (1, 0): "wQ", (2, 0): "bQ", (3, 0): "bA"},
        current_player=Player.WHITE,
        piece=PieceType.ANT,
        source=(0, 0),
    ),
    RulesDiagram(
        id="freedom-gate",
        caption=(
            "The empty hex in the middle is enclosed, and its only opening is a gate "
            "too narrow to slide through, so the ant cannot get in."
        ),
        cells={
            (1, 0): "wQ",
            (1, -1): "wG",
            (0, 1): "bS",
            (-1, 1): "bG",
            (-1, 0): "bQ",
            (2, 0): "wA",
        },
        current_player=Player.WHITE,
        piece=PieceType.ANT,
        source=(2, 0),
        forbidden=((0, 0),),
    ),
    RulesDiagram(
        id="queen",
        caption="The queen moves one hex at a time, sliding around the hive.",
        cells={(0, 0): "wQ", (1, 0): "bQ", (2, 0): "bA"},
        current_player=Player.WHITE,
        piece=PieceType.QUEEN,
        source=(0, 0),
        forbidden=((2, -1), (-1, 0)),
        path=((0, 0), (1, -1)),
    ),
    RulesDiagram(
        id="beetle-climb",
        caption=(
            "The beetle moves one hex at a time like the queen, but may also climb onto "
            "the hive and move on top of it."
        ),
        cells={(0, 0): "wB", (1, 0): "bQ", (0, 1): "wQ", (2, 0): "bA"},
        current_player=Player.WHITE,
        piece=PieceType.BEETLE,
        source=(0, 0),
        path=((0, 0), (1, 0)),
    ),
    RulesDiagram(
        id="beetle-pin",
        caption=(
            "The white beetle on top pins the black ant below it, so the ant cannot "
            "move until the beetle leaves."
        ),
        cells={(0, 0): "wQ", (1, 0): "bA wB", (2, 0): "bQ", (3, 0): "bA"},
        current_player=Player.BLACK,
        piece=PieceType.ANT,
        source=(1, 0),
        forbidden=((1, -1), (1, 1)),
    ),
    RulesDiagram(
        id="beetle-colour",
        caption=(
            "A stack counts as the colour of its top piece, so with the white beetle "
            "on top black may not place next to the stack."
        ),
        cells={(0, 0): "wQ", (1, 0): "bA wB", (2, 0): "bQ", (3, 0): "bA"},
        current_player=Player.BLACK,
        piece=PieceType.SPIDER,
        forbidden=((1, -1), (2, -1), (1, 1)),
    ),
    RulesDiagram(
        id="grasshopper",
        caption=(
            "The grasshopper jumps in a straight line over one or more pieces to the "
            "first empty hex, but it cannot walk to a hex next to it or jump over a gap."
        ),
        cells={(0, 0): "wG", (1, 0): "bA", (2, 0): "bQ", (0, 1): "wQ"},
        current_player=Player.WHITE,
        piece=PieceType.GRASSHOPPER,
        source=(0, 0),
        forbidden=((1, -1), (-1, 0)),
        path=((0, 0), (3, 0)),
    ),
    RulesDiagram(
        id="spider",
        caption=(
            "The spider slides exactly three hexes around the hive, never fewer and "
            "never back to a hex it passed."
        ),
        cells={(-1, 0): "wS", (0, 0): "wQ", (1, 0): "bQ", (2, 0): "bA"},
        current_player=Player.WHITE,
        piece=PieceType.SPIDER,
        source=(-1, 0),
        forbidden=((0, -1), (1, -1)),
        path=((-1, 0), (0, -1), (1, -1), (2, -1)),
    ),
    RulesDiagram(
        id="ant",
        caption=(
            "The ant slides any number of hexes around the hive, so it can reach every "
            "green hex."
        ),
        cells={(-1, 0): "wA", (0, 0): "wQ", (1, 0): "bQ", (2, 0): "bA"},
        current_player=Player.WHITE,
        piece=PieceType.ANT,
        source=(-1, 0),
    ),
    RulesDiagram(
        id="pass",
        caption=(
            "White cannot place next to a black piece and the queen cannot slide out "
            "through the gate, so white has no legal move and must pass."
        ),
        cells={
            (0, 0): "wQ",
            (1, 0): "bQ",
            (1, -1): "bA",
            (-1, 0): "bA",
            (-1, 1): "bG",
            (0, 1): "bS",
        },
        current_player=Player.WHITE,
        piece=PieceType.QUEEN,
        source=(0, 0),
        forbidden=((0, -1),),
    ),
    RulesDiagram(
        id="draw",
        caption="Both queens are surrounded at once, so the game is a draw.",
        cells={
            (0, 0): "wQ",
            (1, 0): "bQ",
            (1, -1): "wA",
            (0, -1): "bA",
            (-1, 0): "wA",
            (-1, 1): "bA",
            (0, 1): "wG",
            (1, 1): "bG",
            (2, 0): "wA",
            (2, -1): "bA",
        },
        current_player=Player.WHITE,
    ),
)
"""Every rule diagram, in the order of the rules reference."""


def rules_diagrams_json(rules: Rules) -> dict[str, object]:
    """Check every diagram against the engine and collect them for the frontend.

    Args:
        rules: The rules of the game.

    Returns:
        The diagrams under `diagrams`, in the order of the rules reference.
    """
    return {"diagrams": [diagram.to_json(rules) for diagram in RULES_DIAGRAMS]}


def main(argv: list[str] | None = None) -> int:
    """Write the rule diagrams, or check that the committed file is up to date.

    Args:
        argv: The command line arguments, or `None` to read `sys.argv`.

    Returns:
        The exit code, 1 when checking finds a stale file.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RULES_DIAGRAMS_PATH)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    content = json.dumps(rules_diagrams_json(Rules()), indent=2) + "\n"

    if arguments.check:
        if json.loads(arguments.output.read_text()) != json.loads(content):
            logger.error("%s is stale, run `make rules-diagrams`.", arguments.output)
            return 1

        return 0

    arguments.output.write_text(content)
    logger.info("Wrote %d diagrams to %s.", len(RULES_DIAGRAMS), arguments.output)

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
