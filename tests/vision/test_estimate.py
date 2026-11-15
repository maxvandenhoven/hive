import dataclasses
import random
from collections import Counter

from hive.engine.record import GameRecord
from hive.engine.rules import Rules
from hive.engine.state import SHARED_PIECES, GameBoard, Move, PieceType, Player
from hive.vision.classes import TileClass
from hive.vision.estimate import BoardEstimate, BoardEstimateStatus
from hive.vision.grid_fit import ObservedBoard
from hive.vision.testing import SimulatedCamera, SimulatedDetector, simulate_observations
from hive.vision.types import TileObservation

IMAGE_SIZE = (1024, 768)

CAMERA = SimulatedCamera(
    tilt_deg=30, azimuth_deg=40, roll_deg=2, distance=14, focal=900, image_size=IMAGE_SIZE
)

MOVES: list[Move | None] = [
    Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0)),
    Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0)),
    Move(piece_type=PieceType.SPIDER, source_coord=None, target_coord=(-1, 0)),
    Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(2, 0)),
]
"""Both queens, an ant and a spider in a line."""


def observe(
    board: GameBoard, camera: SimulatedCamera = CAMERA, loose_tiles: int = 0
) -> list[TileObservation]:
    """Detect the top faces of a board."""
    return simulate_observations(
        board=board,
        camera=camera,
        detector=SimulatedDetector(position_noise=0.02, loose_tiles=loose_tiles),
        rng=random.Random(0),
    )


def estimate(observations: list[TileObservation]) -> BoardEstimate:
    """Fit detections and estimate the board."""
    observed = ObservedBoard.fit(observations=observations, image_size=IMAGE_SIZE)

    return BoardEstimate.from_observed(observed=observed, rules=Rules())


def pieces(board: GameBoard) -> Counter[tuple[PieceType, Player]]:
    """Count the top pieces of a board."""
    return Counter((stack[-1].type, stack[-1].owner) for stack in board.values())


def test_reads_every_tile_of_a_clear_photo() -> None:
    board = GameRecord(rules=Rules(), moves=MOVES).replay().board
    result = estimate(observe(board, loose_tiles=2))

    assert result.status is BoardEstimateStatus.CONFIDENT
    assert result.reasons == []
    assert pieces(result.board) == pieces(board)
    assert set(result.players) == set(Player)
    assert result.lowest_probability > 0.8
    assert result.ignored == 2
    Rules().from_board(board=result.board, current_player=Player.WHITE, current_ply=None)


def test_set_counts_correct_a_doubtful_reading() -> None:
    board = GameRecord(rules=Rules(), moves=MOVES).replay().board
    observations = observe(board)
    white_queen = TileClass(piece_type=PieceType.QUEEN, owner=Player.WHITE)
    white_spider = TileClass(piece_type=PieceType.SPIDER, owner=Player.WHITE)
    scores = [0.0] * len(TileClass.all())
    # The spider reads a little more like a second white queen than like a spider.
    scores[white_queen.id], scores[white_spider.id] = 0.55, 0.45
    observations = [
        dataclasses.replace(
            observation,
            piece_type=PieceType.QUEEN,
            score=0.55,
            class_scores=tuple(scores),
        )
        if observation.tile_class == white_spider
        else observation
        for observation in observations
    ]
    result = estimate(observations)

    assert pieces(result.board) == pieces(board)
    assert result.status is BoardEstimateStatus.UNCERTAIN
    assert "white spider" in result.reasons[0]


def test_a_stack_fails() -> None:
    board = GameRecord(rules=Rules(), moves=MOVES).replay().board | {
        (0, 1): [SHARED_PIECES[(Player.WHITE, PieceType.ANT)]],
        (1, 1): [SHARED_PIECES[(Player.BLACK, PieceType.SPIDER)]],
        (-1, 1): [
            SHARED_PIECES[(Player.WHITE, PieceType.GRASSHOPPER)],
            SHARED_PIECES[(Player.BLACK, PieceType.BEETLE)],
        ],
        (2, -1): [SHARED_PIECES[(Player.BLACK, PieceType.GRASSHOPPER)]],
    }
    steep = dataclasses.replace(CAMERA, tilt_deg=45, distance=10)
    result = estimate(observe(board, camera=steep))

    assert result.status is BoardEstimateStatus.FAILED
    assert any("black beetle at" in reason for reason in result.reasons)
    assert [tile.piece.type for tile in result.tiles if tile.raised] == [PieceType.BEETLE]


def test_a_beetle_whose_height_is_unknown_is_doubtful() -> None:
    board = GameRecord(rules=Rules(), moves=MOVES).replay().board | {
        (3, 0): [SHARED_PIECES[(Player.BLACK, PieceType.BEETLE)]]
    }
    result = estimate(observe(board))

    assert result.status is BoardEstimateStatus.UNCERTAIN
    assert any("beetle" in reason for reason in result.reasons)
    assert pieces(result.board) == pieces(board)


def test_a_cut_off_hive_is_uncertain() -> None:
    board = GameRecord(rules=Rules(), moves=MOVES).replay().board
    off_centre = dataclasses.replace(CAMERA, target=(4.0, 0.0), distance=6)
    result = estimate(observe(board, camera=off_centre))

    assert result.status is BoardEstimateStatus.UNCERTAIN
    assert any("edge" in reason for reason in result.reasons)


def test_failed_estimate() -> None:
    result = BoardEstimate.failed("No hive.")

    assert (result.status, result.tiles, result.board) == (
        BoardEstimateStatus.FAILED,
        [],
        {},
    )
    assert result.reasons == ["No hive."]


def test_a_side_without_its_queen_is_doubtful() -> None:
    board = GameRecord(rules=Rules(), moves=MOVES).replay().board | {
        (q, 1): [SHARED_PIECES[(Player.WHITE, PieceType.ANT)]] for q in range(-1, 2)
    }
    # The white queen reads clearly as a spider.
    observations = [
        dataclasses.replace(
            observation, piece_type=PieceType.SPIDER, score=0.97, class_scores=None
        )
        if observation.tile_class
        == TileClass(piece_type=PieceType.QUEEN, owner=Player.WHITE)
        else observation
        for observation in observe(board)
    ]
    result = estimate(observations)

    assert result.status is BoardEstimateStatus.UNCERTAIN
    assert any("No white queen" in reason for reason in result.reasons)
