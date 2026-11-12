"""Simulated photos for tests of the board fit and the move resolver, without images.

`SimulatedCamera` is a pinhole camera over the table; `simulate_observations` projects
the top face of every stack of an engine board through it, with faces on stacks raised
by the tile height, and adds what a detector gets wrong: position noise, missed tiles,
wrong classes and tiles in hand next to the hive.
"""

import math
import random
from dataclasses import dataclass

import numpy as np

from hive.engine.grid import Coordinate
from hive.engine.state import GameBoard, PieceType, Player
from hive.vision.classes import TileClass
from hive.vision.lattice import axial_to_plane
from hive.vision.types import TileObservation


@dataclass(frozen=True, slots=True)
class SimulatedCamera:
    """A pinhole camera looking at a point of the table, in lattice units.

    Attributes:
        tilt_deg: The angle between the view direction and straight down.
        azimuth_deg: The direction the camera is in, seen from the target.
        roll_deg: The rotation around the view direction.
        distance: The distance from the camera to the target.
        focal: The focal length in pixels.
        image_size: The image width and height in pixels.
        target: The point of the table plane in the image centre, x east and y south.
    """

    tilt_deg: float
    azimuth_deg: float
    roll_deg: float
    distance: float
    focal: float
    image_size: tuple[int, int]
    target: tuple[float, float] = (0.0, 0.0)

    @property
    def rotation(self) -> np.ndarray:
        """The camera axes (right, up, backwards) as columns, in a world with z up."""
        azimuth = math.radians(self.azimuth_deg + 90)
        tilt = math.radians(self.tilt_deg)
        roll = math.radians(self.roll_deg)
        about_z = np.array(
            [
                [math.cos(azimuth), -math.sin(azimuth), 0.0],
                [math.sin(azimuth), math.cos(azimuth), 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        about_x = np.array(
            [
                [1.0, 0.0, 0.0],
                [0.0, math.cos(tilt), -math.sin(tilt)],
                [0.0, math.sin(tilt), math.cos(tilt)],
            ]
        )
        rolled = np.array(
            [
                [math.cos(roll), -math.sin(roll), 0.0],
                [math.sin(roll), math.cos(roll), 0.0],
                [0.0, 0.0, 1.0],
            ]
        )

        return about_z @ about_x @ rolled

    def project(self, x: float, y: float, height: float) -> tuple[float, float] | None:
        """Project a point above the table into the image.

        Args:
            x: The position to the east.
            y: The position to the south.
            height: The height above the plane of the faces of tiles on the table.

        Returns:
            The pixel position, or `None` if the point is behind the camera.
        """
        # The world has y to the north and z up, so it is right-handed.
        target = np.array([self.target[0], -self.target[1], 0.0])
        rotation = self.rotation
        centre = target + rotation[:, 2] * self.distance
        offset = np.array([x, -y, height]) - centre
        right, up, backwards = rotation.T @ offset

        if backwards >= 0:
            return None

        width, image_height = self.image_size

        return (
            width / 2 + self.focal * right / -backwards,
            image_height / 2 - self.focal * up / -backwards,
        )


@dataclass(frozen=True, slots=True)
class SimulatedDetector:
    """How often and how badly the simulated detector errs.

    Attributes:
        position_noise: The standard deviation of the centre noise per face size.
        miss_rate: The chance that a visible face is not detected.
        confusion_rate: The chance that a face gets a wrong class.
        loose_tiles: The number of tiles in hand placed next to the hive.
        tile_height: The height of a tile in lattice units.
    """

    position_noise: float = 0.03
    miss_rate: float = 0.0
    confusion_rate: float = 0.0
    loose_tiles: int = 0
    tile_height: float = 0.28


def simulate_observations(
    board: GameBoard,
    camera: SimulatedCamera,
    detector: SimulatedDetector,
    rng: random.Random,
    offset: Coordinate = (0, 0),
) -> list[TileObservation]:
    """Detect the top faces of a board as a detector would see them in a photo.

    Args:
        board: The engine board.
        camera: The camera.
        detector: The errors of the detector.
        rng: The random number generator.
        offset: An axial offset added to every coordinate before projecting, so the hive
            need not be centred on the camera target.

    Returns:
        The detections of the faces that are at least half in the image.
    """
    observations = []

    for coord, stack in board.items():
        if rng.random() < detector.miss_rate:
            continue

        top = stack[-1]
        observation = observe_face(
            coord=(coord[0] + offset[0], coord[1] + offset[1]),
            level=len(stack) - 1,
            tile_class=TileClass(piece_type=top.type, owner=top.owner),
            camera=camera,
            detector=detector,
            rng=rng,
        )

        if observation is not None:
            observations.append(observation)

    occupied = [axial_to_plane((q + offset[0], r + offset[1])) for q, r in board]
    centre = np.mean(occupied, axis=0) if occupied else np.zeros(2)
    radius = max((math.dist(point, centre) for point in occupied), default=0.0)

    for _ in range(detector.loose_tiles):
        angle = rng.uniform(0, 2 * math.pi)
        distance = radius + rng.uniform(2.0, 3.5)
        x = centre[0] + distance * math.cos(angle)
        y = centre[1] + distance * math.sin(angle)
        tile_class = TileClass(
            piece_type=rng.choice(list(PieceType)), owner=rng.choice(list(Player))
        )
        observation = observe_point(
            x=x,
            y=y,
            level=0,
            tile_class=tile_class,
            camera=camera,
            detector=detector,
            rng=rng,
        )

        if observation is not None:
            observations.append(observation)

    return observations


def observe_face(
    coord: Coordinate,
    level: int,
    tile_class: TileClass,
    camera: SimulatedCamera,
    detector: SimulatedDetector,
    rng: random.Random,
) -> TileObservation | None:
    """Detect one face on a hex.

    Args:
        coord: The hex in the frame of the camera target.
        level: The stack level of the face.
        tile_class: The true class of the face.
        camera: The camera.
        detector: The errors of the detector.
        rng: The random number generator.

    Returns:
        The detection, or `None` if the face is not half in the image.
    """
    x, y = axial_to_plane(coord)

    return observe_point(
        x=x,
        y=y,
        level=level,
        tile_class=tile_class,
        camera=camera,
        detector=detector,
        rng=rng,
    )


def observe_point(
    x: float,
    y: float,
    level: int,
    tile_class: TileClass,
    camera: SimulatedCamera,
    detector: SimulatedDetector,
    rng: random.Random,
) -> TileObservation | None:
    """Detect a face centred on a point of the table plane.

    Args:
        x: The position to the east.
        y: The position to the south.
        level: The stack level of the face.
        tile_class: The true class of the face.
        camera: The camera.
        detector: The errors of the detector.
        rng: The random number generator.

    Returns:
        The detection, or `None` if the face is not half in the image.
    """
    height = level * detector.tile_height
    turn = rng.uniform(0, math.pi / 3)
    corners = []

    for corner in range(6):
        angle = turn + math.pi / 6 + corner * math.pi / 3
        projected = camera.project(
            x=x + 0.55 * math.cos(angle), y=y + 0.55 * math.sin(angle), height=height
        )

        if projected is None:
            return None

        corners.append(projected)

    centre = camera.project(x=x, y=y, height=height)

    if centre is None:
        return None

    width, image_height = camera.image_size
    inside = sum(0 <= u <= width and 0 <= v <= image_height for u, v in corners)

    if inside < 4 or not (0 <= centre[0] <= width and 0 <= centre[1] <= image_height):
        return None

    xs = [u for u, _ in corners]
    ys = [v for _, v in corners]
    size = max(max(xs) - min(xs), max(ys) - min(ys))
    noisy_centre = (
        centre[0] + rng.gauss(0, detector.position_noise * size),
        centre[1] + rng.gauss(0, detector.position_noise * size),
    )
    seen_class = tile_class

    if rng.random() < detector.confusion_rate:
        seen_class = rng.choice([c for c in TileClass.all() if c != tile_class])

    # Real models give the other classes tiny scores, around 1e-4 and rarely 1e-2.
    scores = [10 ** rng.uniform(-4.5, -2.0) for _ in TileClass.all()]
    scores[seen_class.id] = rng.uniform(0.6, 0.97)

    if seen_class != tile_class:
        scores[tile_class.id] = 10 ** rng.uniform(-3.0, -0.5)

    return TileObservation(
        center=noisy_centre,
        box=(min(xs), min(ys), max(xs), max(ys)),
        polygon=corners,
        piece_type=seen_class.piece_type,
        owner=seen_class.owner,
        score=scores[seen_class.id],
        class_scores=tuple(scores),
    )
