import math
import random

import cv2
import numpy as np
import pytest

from hive.data.scenes import ScenesConfig
from hive.engine.rules import Rules
from hive.engine.state import GameBoard, Piece, PieceType, Player
from hive.vision.grid_fit import BoardFitError, ObservedBoard, estimate_camera
from hive.vision.lattice import LatticeTransform, axial_to_plane
from hive.vision.testing import SimulatedCamera, SimulatedDetector, simulate_observations

IMAGE_SIZE = (1024, 768)


def random_camera(rng: random.Random, max_tilt: float) -> SimulatedCamera:
    """Sample a phone-like camera."""
    return SimulatedCamera(
        tilt_deg=rng.uniform(0, max_tilt),
        azimuth_deg=rng.uniform(0, 360),
        roll_deg=rng.uniform(-8, 8),
        distance=rng.uniform(9, 18),
        focal=rng.uniform(700, 1200),
        image_size=IMAGE_SIZE,
    )


def matches_up_to_motion(board: GameBoard, observed: ObservedBoard) -> bool:
    """Check that one rigid motion puts every observed face on its engine tile."""
    first = next(iter(observed.tiles))

    for rotation in range(6):
        for target in board:
            q, r = LatticeTransform(rotation=rotation, translation=(0, 0)).apply(first)
            transform = LatticeTransform(
                rotation=rotation, translation=(target[0] - q, target[1] - r)
            )

            if all(
                transform.apply(coord) in board
                and board[transform.apply(coord)][-1].type == tile.observation.piece_type
                for coord, tile in observed.tiles.items()
            ):
                return True

    return False


def test_fit_places_tiles_on_their_hexes_at_any_angle() -> None:
    rules = Rules()
    config = ScenesConfig()
    exact = 0
    games = 60

    for seed in range(games):
        rng = random.Random(seed)
        state, _ = config.play_game(rules=rules, rng=rng)

        if not state.board:
            exact += 1
            continue

        observations = simulate_observations(
            board=state.board,
            camera=random_camera(rng=rng, max_tilt=60),
            detector=SimulatedDetector(loose_tiles=rng.randint(0, 3)),
            rng=rng,
        )
        observed = ObservedBoard.fit(observations=observations, image_size=IMAGE_SIZE)
        exact += matches_up_to_motion(board=state.board, observed=observed)

    assert exact >= 0.93 * games


def test_tiles_in_hand_stay_off_the_grid() -> None:
    rng = random.Random(3)
    board = {
        (q, r): [Piece(type=PieceType.ANT, owner=Player.WHITE)]
        for q, r in [(0, 0), (1, 0), (0, 1), (-1, 1), (-1, 0)]
    }
    observations = simulate_observations(
        board=board,
        camera=SimulatedCamera(
            tilt_deg=20,
            azimuth_deg=40,
            roll_deg=0,
            distance=14,
            focal=900,
            image_size=IMAGE_SIZE,
        ),
        detector=SimulatedDetector(loose_tiles=4),
        rng=rng,
    )
    observed = ObservedBoard.fit(observations=observations, image_size=IMAGE_SIZE)

    assert len(observed.tiles) == 5
    assert len(observed.off_grid) == len(observations) - 5


def test_raised_face_in_a_steep_view_lands_on_its_hex() -> None:
    rng = random.Random(4)
    coords = [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (-1, 1), (-1, 2), (0, 2), (1, -1)]
    board: GameBoard = {
        coord: [Piece(type=PieceType.GRASSHOPPER, owner=Player.BLACK)] for coord in coords
    }
    board[(1, 1)] = [
        Piece(type=PieceType.ANT, owner=Player.WHITE),
        Piece(type=PieceType.BEETLE, owner=Player.WHITE),
    ]
    observations = simulate_observations(
        board=board,
        camera=SimulatedCamera(
            tilt_deg=55,
            azimuth_deg=200,
            roll_deg=0,
            distance=8,
            focal=800,
            image_size=IMAGE_SIZE,
        ),
        detector=SimulatedDetector(position_noise=0.01),
        rng=rng,
    )
    observed = ObservedBoard.fit(observations=observations, image_size=IMAGE_SIZE)
    beetles = [
        tile
        for tile in observed.tiles.values()
        if tile.observation.piece_type is PieceType.BEETLE
    ]

    assert matches_up_to_motion(board=board, observed=observed)
    assert len(beetles) == 1
    assert beetles[0].level == 1
    assert observed.camera is not None


def test_camera_height_follows_from_the_homography() -> None:
    camera = SimulatedCamera(
        tilt_deg=40,
        azimuth_deg=30,
        roll_deg=5,
        distance=12,
        focal=900,
        image_size=IMAGE_SIZE,
    )
    plane = np.array(
        [axial_to_plane((q, r)) for q in range(-3, 4) for r in range(-3, 4)], dtype=float
    )
    image = np.array([camera.project(x=x, y=y, height=0.0) for x, y in plane])
    homography, _ = cv2.findHomography(plane, image, 0)
    centre = estimate_camera(
        homography=homography, image_size=IMAGE_SIZE, prior_focal=0.75
    )

    assert centre is not None
    assert centre[2] == pytest.approx(12 * math.cos(math.radians(40)), rel=0.02)


def test_visibility_drops_outside_the_frame() -> None:
    rng = random.Random(5)
    board = {
        (q, r): [Piece(type=PieceType.SPIDER, owner=Player.WHITE)]
        for q, r in [(0, 0), (1, 0), (0, 1), (1, -1), (-1, 1), (-1, 0), (0, -1)]
    }
    observations = simulate_observations(
        board=board,
        camera=SimulatedCamera(
            tilt_deg=10,
            azimuth_deg=0,
            roll_deg=0,
            distance=12,
            focal=900,
            image_size=IMAGE_SIZE,
        ),
        detector=SimulatedDetector(),
        rng=rng,
    )
    observed = ObservedBoard.fit(observations=observations, image_size=IMAGE_SIZE)
    inside = next(iter(observed.tiles))

    assert observed.visibility(inside) == 1.0
    assert observed.visibility((inside[0] + 40, inside[1])) == 0.0


def test_fit_needs_detections() -> None:
    with pytest.raises(BoardFitError, match="No tiles"):
        ObservedBoard.fit(observations=[], image_size=IMAGE_SIZE)
