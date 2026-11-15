"""Board estimates: read a whole position from one photo, without the game's history.

The move resolver needs the position before the photo and finds the move played since.
Without a known position, for example to start a game from a board already on the table,
the photo is all there is, so each face on the hive is read as the tile on that hex:

- Classes: every tile gets the class its scores make most likely, as long as the set
  has a piece of that class left; the clearest readings choose first, so two faces read
  as the one white queen leave the less certain of them its next most likely class.
- Stacks: the tiles under a beetle are hidden, so a face that sits clearly higher than
  the table makes the estimate fail rather than guess what is below it. Where the camera
  angle does not show heights (a flat view, or too few tiles to tell the angle), every
  beetle is doubtful, since it may be on a stack.
- Validity: the board must be a legal position under the rules (counts, one hive, queen
  placed in time) for at least one side to move.

The estimate says how sure it is. It is `confident` only when every tile reads clearly
and the photo shows the whole hive, `uncertain` when the board is valid but some reading
or the framing is doubtful, and `failed` when no valid board follows from the photo.
"""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from hive.engine.codec import JsonCodec
from hive.engine.errors import InvalidBoardError
from hive.engine.grid import Coordinate, get_neighbors
from hive.engine.rules import Rules
from hive.engine.state import SHARED_PIECES, GameBoard, Piece, PieceType, Player
from hive.vision.classes import TileClass
from hive.vision.grid_fit import ObservedBoard
from hive.vision.resolver import class_probabilities


class BoardEstimateStatus(StrEnum):
    """How sure a board estimate from one photo is."""

    CONFIDENT = "confident"
    UNCERTAIN = "uncertain"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BoardEstimateConfig:
    """Settings of board estimates.

    Attributes:
        min_probability: The probability below which the reading of a tile is doubtful.
        raised_shift: How far one stack level must move a face in the lattice plane, in
            hex distances, before a face read above the table counts as a stack.
        edge_margin: How close to the edge of the photo a tile counts as cut off, as a
            share of the longer image side.
    """

    min_probability: float = 0.8
    raised_shift: float = 0.15
    edge_margin: float = 0.01


@dataclass(frozen=True, slots=True)
class EstimatedTile(JsonCodec):
    """A tile of an estimated board.

    Attributes:
        coord: The hex of the tile, in the coordinates of the estimated board.
        piece: The tile read on the hex.
        probability: How likely the reading is, from the class scores of the reader.
        raised: Whether the face looks higher than the table, so it is on a stack.
        origin: The hex of the tile in the lattice frame of the photo.
    """

    coord: Coordinate
    piece: Piece
    probability: float
    raised: bool
    origin: Coordinate


@dataclass(frozen=True, slots=True)
class BoardEstimate(JsonCodec):
    """A position read from a single photo, with how sure the reading is.

    Attributes:
        status: Whether the board can be trusted, should be checked, or is not valid.
        tiles: The tiles read on the hive, sorted by coordinate.
        board: The board of the tiles, one piece per hex, centred near `(0, 0)`.
        lowest_probability: How likely the most doubtful reading of a tile is.
        players: The sides that may be to move on the board under the rules; empty if
            the board is not valid.
        ignored: The number of detections that are not part of the hive, such as tiles
            in hand.
        reasons: What makes the estimate uncertain or failed, for the person taking the
            photo.
    """

    status: BoardEstimateStatus
    tiles: list[EstimatedTile]
    board: GameBoard
    lowest_probability: float
    players: list[Player]
    ignored: int
    reasons: list[str]

    @classmethod
    def failed(cls, reason: str) -> "BoardEstimate":
        """Describe a photo from which no board could be read.

        Args:
            reason: Why, for the person taking the photo.

        Returns:
            A failed estimate without tiles.
        """
        return cls(
            status=BoardEstimateStatus.FAILED,
            tiles=[],
            board={},
            lowest_probability=0.0,
            players=[],
            ignored=0,
            reasons=[reason],
        )

    @classmethod
    def from_observed(
        cls,
        observed: ObservedBoard,
        rules: Rules,
        config: BoardEstimateConfig | None = None,
    ) -> "BoardEstimate":
        """Read the position on the hive of an observed board.

        Args:
            observed: The tiles of the photo on the hex lattice.
            rules: The rules, which give the pieces of the set and what a valid board is.
            config: The settings, or `None` for the defaults.

        Returns:
            The estimate.
        """
        config = config or BoardEstimateConfig()

        if not observed.tiles:
            return cls.failed("No hive was found. Take a photo with all tiles in view.")

        set_size = len(Player) * sum(rules.piece_counts.values())

        if len(observed.tiles) > set_size:
            return cls.failed(
                f"The photo shows {len(observed.tiles)} tiles on the hive, more than the "
                f"{set_size} of the set."
            )

        tiles = cls.assign_tiles(observed=observed, rules=rules, config=config)
        board: GameBoard = {tile.coord: [tile.piece] for tile in tiles}
        lowest_probability = min(tile.probability for tile in tiles)
        ignored = len(observed.off_grid)
        failures: list[str] = []
        doubts: list[str] = []

        for tile in tiles:
            if tile.raised:
                failures.append(
                    f"The {describe_piece(tile.piece)} at {tile.coord} looks like it is "
                    "on a stack. The tiles under a stack are hidden, so start from a "
                    "position without stacks."
                )

        players: list[Player] = []
        errors: list[str] = []

        for player in Player:
            try:
                rules.from_board(board=board, current_player=player, current_ply=None)
            except InvalidBoardError as e:
                errors.append(str(e))
            else:
                players.append(player)

        if not players:
            failures.append(f"The board read from the photo is not valid: {errors[0]}")

        doubtful = [tile for tile in tiles if tile.probability < config.min_probability]

        if doubtful:
            listed = ", ".join(
                f"the {describe_piece(tile.piece)} at {tile.coord} "
                f"({tile.probability:.0%})"
                for tile in doubtful[:3]
            )
            more = f" and {len(doubtful) - 3} more" if len(doubtful) > 3 else ""
            doubts.append(f"Not sure about {listed}{more}.")

        doubts += cls.missing_queens(tiles=tiles, rules=rules)

        # Where the photo cannot tell levels apart, a beetle may hide a tile under it.
        hidden = [
            tile
            for tile in tiles
            if tile.piece.type is PieceType.BEETLE
            and not tile.raised
            and observed.tiles[tile.origin].level_shift < config.raised_shift
        ]

        if hidden:
            listed = ", ".join(str(tile.coord) for tile in hidden)
            doubts.append(
                f"The photo cannot show whether the beetle at {listed} is on top of "
                "another tile. Check it, or take the photo at more of an angle."
            )

        if observed.edge_coords(margin=config.edge_margin):
            doubts.append(
                "The hive touches the edge of the photo, so tiles may be missing. Take "
                "the photo from further away."
            )

        stray = [
            coord
            for coord in observed.near
            if any(neighbor in observed.tiles for neighbor in get_neighbors(coord))
        ]

        if stray:
            doubts.append(
                f"{len(stray)} tiles next to the hive could not be placed on the grid. "
                "Push the tiles together and take another photo."
            )

        if failures:
            status = BoardEstimateStatus.FAILED
        elif doubts:
            status = BoardEstimateStatus.UNCERTAIN
        else:
            status = BoardEstimateStatus.CONFIDENT

        return cls(
            status=status,
            tiles=tiles,
            board=board,
            lowest_probability=lowest_probability,
            players=players,
            ignored=ignored,
            reasons=failures + doubts,
        )

    @classmethod
    def missing_queens(cls, tiles: list[EstimatedTile], rules: Rules) -> list[str]:
        """Find sides with more tiles than they may place before their queen.

        `Rules.from_board` accepts such boards, since it cannot know when the tiles were
        placed, but no legal game reaches them: the reader most likely took a queen for
        another insect.

        Args:
            tiles: The tiles read on the hive.
            rules: The rules, with the turn by which a queen must be placed.

        Returns:
            One doubt per such side, for the person taking the photo.
        """
        if rules.queen_by_turn is None:
            return []

        doubts = []

        for player in Player:
            own = [tile for tile in tiles if tile.piece.owner is player]
            queens = [tile for tile in own if tile.piece.type is PieceType.QUEEN]

            if not queens and len(own) >= rules.queen_by_turn:
                side = player.name.lower()
                doubts.append(
                    f"No {side} queen was found, but {side} has {len(own)} tiles on "
                    "the board and the queen must be one of its first "
                    f"{rules.queen_by_turn}. A queen was probably read as another insect."
                )

        return doubts

    @classmethod
    def assign_tiles(
        cls, observed: ObservedBoard, rules: Rules, config: BoardEstimateConfig
    ) -> list[EstimatedTile]:
        """Give every hive tile the most likely class the set has a piece of left.

        The clearest readings choose first, so a doubtful face does not take the piece
        of a clear one.

        Args:
            observed: The tiles of the photo on the hex lattice.
            rules: The rules with the number of pieces of each type per side.
            config: The settings.

        Returns:
            The tiles, centred near `(0, 0)` and sorted by coordinate.
        """
        classes = TileClass.all()
        left = {
            tile_class.id: rules.piece_counts.get(tile_class.piece_type, 0)
            for tile_class in classes
        }
        probabilities = {
            coord: class_probabilities(tile) for coord, tile in observed.tiles.items()
        }
        options = sorted(
            (
                (float(row[class_id]), coord, class_id)
                for coord, row in probabilities.items()
                for class_id in range(len(classes))
            ),
            reverse=True,
        )
        chosen: dict[Coordinate, tuple[int, float]] = {}

        for probability, coord, class_id in options:
            if coord in chosen or left[class_id] == 0:
                continue

            chosen[coord] = (class_id, probability)
            left[class_id] -= 1

        centre = np.mean(np.array(list(observed.tiles), dtype=np.float64), axis=0)
        shift = (round(float(centre[0])), round(float(centre[1])))
        tiles = []

        # Every tile gets a class, since there are no more tiles than pieces.
        for coord, (class_id, probability) in chosen.items():
            tile = observed.tiles[coord]
            tile_class = TileClass.from_id(class_id)
            tiles.append(
                EstimatedTile(
                    coord=(coord[0] - shift[0], coord[1] - shift[1]),
                    piece=SHARED_PIECES[(tile_class.owner, tile_class.piece_type)],
                    probability=probability,
                    raised=tile.level > 0 and tile.level_shift >= config.raised_shift,
                    origin=coord,
                )
            )

        return sorted(tiles, key=lambda tile: tile.coord)


def describe_piece(piece: Piece) -> str:
    """Describe a piece briefly for a message.

    Args:
        piece: The piece.

    Returns:
        For example `white ant`.
    """
    return f"{piece.owner.name.lower()} {piece.type.name.lower()}"
