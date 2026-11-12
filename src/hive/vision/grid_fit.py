"""Board fitting: place the tiles seen in a photo on the hex lattice.

The top faces of the tiles on the table lie in one plane, so a homography maps the
lattice plane (see `lattice`) to the photo, whatever the camera angle. The fit works from
the detections alone:

1. Seeds: the outline of a detected face is a hexagon seen in perspective, so its shape
   tells the local foreshortening. Undoing it around a tile turns the offset to a
   neighbouring tile into a lattice step, and a 60 degree turn gives the second step.
2. Growth: from each seed, detections that land near the centre of a hex next to the
   hexes found so far are added, and the model is refitted: affine at first, a full
   homography once enough tiles span the plane.
3. Final fit: the best grown set gives a robust homography. Faces on stacks are higher
   than the plane, which shifts them away from the camera in steep views, so the camera
   position is estimated from the homography and every detection is snapped at the
   stack level that fits it best.
4. The largest connected group of hexes is the hive; other detections (tiles in hand,
   clutter) are kept apart as off the grid.

The result is an `ObservedBoard` in its own lattice frame, which the move resolver aligns
to the engine coordinates.
"""

import math
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from hive.engine.grid import Coordinate, get_neighbors
from hive.vision.lattice import axial_to_plane, plane_to_axial, round_axial
from hive.vision.types import TileObservation

HEXAGON_VARIANCE: float = 5 / 72
"""The variance of a uniform regular hexagon along any axis, per squared across-flats
width, which turns the shape of a face outline into its scale."""


class BoardFitError(Exception):
    """Raised when the detections of a photo do not form a hive on the lattice."""


@dataclass(frozen=True, slots=True)
class BoardFitConfig:
    """Settings of the board fit, in lattice units (the distance between hex centres).

    Attributes:
        tile_height: The height of a tile, 10 mm for tiles 34.6 mm wide with small gaps.
        snap_tolerance: The largest distance from a hex centre at which a detection is
            placed on that hex.
        near_tolerance: The largest distance at which a detection that is not placed is
            still kept as near a hex, so the resolver can match it to an expected tile.
        max_level: The highest stack level that is tried for a face.
        level_penalty: The distance added per stack level, so a face is only placed on a
            stack when that fits clearly better.
        flat_tolerance: The distance from a hex centre within which a face is taken to
            lie on the table without trying stack levels.
        max_seeds: The most seeds that are grown.
        prior_focal: The focal length of the camera as a fraction of the long image
            side, used when the homography does not tell it.
    """

    tile_height: float = 0.28
    snap_tolerance: float = 0.33
    near_tolerance: float = 0.5
    max_level: int = 4
    level_penalty: float = 0.1
    flat_tolerance: float = 0.18
    max_seeds: int = 24
    prior_focal: float = 0.75


@dataclass(frozen=True, slots=True)
class ObservedTile:
    """A detection placed on a hex of the observed lattice.

    Attributes:
        observation: The detection.
        coord: The hex in the lattice frame of the photo.
        level: The stack level of the face that fits best, 0 for a tile on the table.
        residual: The distance from the detection to the hex centre.
        level_shift: How far one stack level moves the face in the lattice plane here;
            the level is only telling where this is a good part of a hex.
    """

    observation: TileObservation
    coord: Coordinate
    level: int
    residual: float
    level_shift: float = 0.0


@dataclass(slots=True)
class ObservedBoard:
    """The tiles of one photo on the hex lattice, in the lattice frame of the photo.

    Attributes:
        tiles: The detection on each hex of the hive.
        off_grid: The detections that are not part of the hive.
        near: Detections off the grid that are close to a hex, by that hex.
        homography: The map from the lattice plane at the height of a tile on the table
            to image pixels, as a 3 x 3 matrix.
        camera: The camera centre over the lattice plane `(x, y, height)`, or `None`
            when the view is too close to an affine one to tell.
        image_size: The image width and height in pixels.
        tile_size: The median size of a detected face in pixels.
        config: The settings of the fit.
    """

    tiles: dict[Coordinate, ObservedTile]
    off_grid: list[TileObservation]
    homography: np.ndarray
    camera: np.ndarray | None
    image_size: tuple[int, int]
    tile_size: float
    config: BoardFitConfig = field(default_factory=BoardFitConfig)
    near: dict[Coordinate, ObservedTile] = field(default_factory=dict)

    @classmethod
    def fit(
        cls,
        observations: list[TileObservation],
        image_size: tuple[int, int],
        config: BoardFitConfig | None = None,
    ) -> "ObservedBoard":
        """Place the detections of a photo on the hex lattice.

        Args:
            observations: The detected tile faces.
            image_size: The image width and height in pixels.
            config: The settings, or `None` for the defaults.

        Returns:
            The observed board.

        Raises:
            BoardFitError: If nothing was detected.
        """
        config = config or BoardFitConfig()

        if not observations:
            msg = "No tiles were detected."
            raise BoardFitError(msg)

        points = np.array([o.center for o in observations], dtype=np.float64)
        sizes = np.array([face_size(o) for o in observations])
        metrics = [face_metric(o) for o in observations]
        best: tuple[int, float, dict[Coordinate, int], np.ndarray] | None = None

        for seed, model in seed_models(points=points, metrics=metrics, config=config):
            assigned, grown = grow_lattice(
                points=points, seed=seed, model=model, config=config
            )
            residual = mean_residual(points=points, assigned=assigned, model=grown)
            rank = (len(assigned), -residual)

            if best is None or rank > (best[0], -best[1]):
                best = (len(assigned), residual, assigned, grown)

        assert best is not None
        assigned, model = best[2], best[3]
        homography = final_model(
            points=points,
            assigned=assigned,
            model=model,
            tile_size=float(np.median(sizes)),
        )
        camera = estimate_camera(
            homography=homography, image_size=image_size, prior_focal=config.prior_focal
        )
        board = cls(
            tiles={},
            off_grid=[],
            homography=homography,
            camera=camera,
            image_size=image_size,
            tile_size=float(np.median(sizes)),
            config=config,
        )
        board.snap(observations)
        board.refine(observations)

        return board

    def refine(self, observations: list[TileObservation], rounds: int = 2) -> None:
        """Refit the homography to every face on the table and snap again.

        The growth fits the hive near its seed best; refitting to all faces at table
        height evens the error out over the whole hive, which matters at the far side of
        steep views.

        Args:
            observations: The detected tile faces.
            rounds: The number of refits.
        """
        for _ in range(rounds):
            flat = [tile for tile in self.tiles.values() if tile.level == 0]
            plane = np.array(
                [axial_to_plane(tile.coord) for tile in flat], dtype=np.float64
            )

            if len(flat) < 6 or plane_spread(plane) <= 0.4:
                return

            image = np.array([tile.observation.center for tile in flat], dtype=np.float64)
            homography, _ = cv2.findHomography(plane, image, 0)

            if homography is None or not orientation_kept(homography, plane):
                return

            self.homography = homography
            self.camera = estimate_camera(
                homography=homography,
                image_size=self.image_size,
                prior_focal=self.config.prior_focal,
            )
            self.snap(observations)

    def snap(self, observations: list[TileObservation]) -> None:
        """Place every detection on its hex and stack level, keeping the hive apart.

        Args:
            observations: The detected tile faces.
        """
        inverse = np.linalg.inv(self.homography)
        claims: dict[Coordinate, ObservedTile] = {}
        off_grid: list[TileObservation] = []

        for observation in observations:
            placed = self.place(observation=observation, inverse=inverse)

            if placed is None:
                off_grid.append(observation)
                continue

            other = claims.get(placed.coord)

            if other is None or observation.score > other.observation.score:
                claims[placed.coord] = placed

                if other is not None:
                    off_grid.append(other.observation)
            else:
                off_grid.append(observation)

        hive = self.hive_component(claims)
        self.tiles = {coord: tile for coord, tile in claims.items() if coord in hive}
        self.off_grid = off_grid + [
            tile.observation for coord, tile in claims.items() if coord not in hive
        ]
        self.near = {}

        for observation in self.off_grid:
            placed = self.place(
                observation=observation,
                inverse=inverse,
                tolerance=self.config.near_tolerance,
            )

            if placed is not None and placed.coord not in self.tiles:
                known = self.near.get(placed.coord)

                if known is None or placed.residual < known.residual:
                    self.near[placed.coord] = placed

    def hive_component(self, claims: dict[Coordinate, ObservedTile]) -> set[Coordinate]:
        """Pick the hive among the connected groups of placed detections.

        The largest group is the hive; between groups of equal size, such as a first tile
        and the tiles in hand, the one nearest the image centre wins.

        Args:
            claims: The placed detection on each hex.

        Returns:
            The hexes of the hive.
        """
        width, height = self.image_size
        best: set[Coordinate] = set()
        best_rank = (0, -math.inf)

        for component in connected_components(set(claims)):
            centre = np.mean([claims[c].observation.center for c in component], axis=0)
            distance = math.dist(centre, (width / 2, height / 2))
            rank = (len(component), -distance)

            if rank > best_rank:
                best, best_rank = component, rank

        return best

    def place(
        self,
        observation: TileObservation,
        inverse: np.ndarray,
        tolerance: float | None = None,
    ) -> ObservedTile | None:
        """Find the hex and stack level that fit a detection best.

        Args:
            observation: The detection.
            inverse: The inverse of the homography.
            tolerance: The largest distance from the hex centre, or `None` for the snap
                tolerance.

        Returns:
            The placed tile, or `None` if no hex is within the tolerance.
        """
        config = self.config
        tolerance = config.snap_tolerance if tolerance is None else tolerance
        base = apply_homography(matrix=inverse, points=np.array([observation.center]))[0]
        best: ObservedTile | None = None
        best_cost = math.inf
        level_shift = 0.0

        if self.camera is not None:
            level_shift = float(
                np.linalg.norm(base - self.camera[:2])
                * config.tile_height
                / self.camera[2]
            )

        for level in range(config.max_level + 1):
            if level > 0 and self.camera is None:
                break

            point = base

            if level > 0:
                assert self.camera is not None
                elevation = level * config.tile_height

                if self.camera[2] <= elevation:
                    break

                # A raised face is seen where the ray through it meets the plane, further
                # from the point below the camera than the face itself.
                point = self.camera[:2] + (base - self.camera[:2]) * (
                    1 - elevation / self.camera[2]
                )

            coord = round_axial(*plane_to_axial(float(point[0]), float(point[1])))
            residual = math.dist(point, axial_to_plane(coord))
            cost = residual + config.level_penalty * level

            if (
                level > 0
                and best is not None
                and best.level == 0
                and best.residual < (config.flat_tolerance)
            ):
                break

            if residual < tolerance and cost < best_cost:
                best_cost = cost
                best = ObservedTile(
                    observation=observation,
                    coord=coord,
                    level=level,
                    residual=residual,
                    level_shift=level_shift,
                )

        return best

    def project(self, coord: Coordinate, level: int = 0) -> tuple[float, float] | None:
        """Project the face centre of a hex at a stack level into the image.

        Args:
            coord: The hex in the lattice frame of the photo.
            level: The stack level of the face.

        Returns:
            The pixel position, or `None` if the point is behind the camera.
        """
        point = np.array(axial_to_plane(coord), dtype=np.float64)

        if level > 0 and self.camera is not None:
            elevation = level * self.config.tile_height

            if self.camera[2] <= elevation:
                return None

            point = self.camera[:2] + (point - self.camera[:2]) / (
                1 - elevation / self.camera[2]
            )

        mapped = self.homography @ np.array([point[0], point[1], 1.0])

        if mapped[2] <= 1e-9:
            return None

        return float(mapped[0] / mapped[2]), float(mapped[1] / mapped[2])

    def visibility(self, coord: Coordinate, level: int = 0) -> float:
        """Estimate how fully a face on a hex would be in the photo.

        Args:
            coord: The hex in the lattice frame of the photo.
            level: The stack level of the face.

        Returns:
            1 when the face is well inside the frame, 0.5 when its centre is on the edge,
            and 0 when it is outside or behind the camera.
        """
        projected = self.project(coord=coord, level=level)

        if projected is None:
            return 0.0

        x, y = projected
        width, height = self.image_size
        margin = min(x, y, width - x, height - y)

        return min(max(0.5 + margin / self.tile_size, 0.0), 1.0)


def face_size(observation: TileObservation) -> float:
    """Get the size of a detected face in pixels.

    Args:
        observation: The detection.

    Returns:
        The longer side of its bounding box.
    """
    x0, y0, x1, y1 = observation.box

    return max(x1 - x0, y1 - y0, 1.0)


def face_metric(observation: TileObservation) -> np.ndarray:
    """Get the map from image offsets near a face to lattice units, up to a rotation.

    A regular hexagon has the same spread in every direction, so the covariance of the
    face outline is that spread distorted by the local perspective; its inverse square
    root undoes the distortion. Without an outline the bounding box stands in for it.

    Args:
        observation: The detection.

    Returns:
        The 2 x 2 matrix that maps an image offset to lattice units.
    """
    covariance = None

    if observation.polygon is not None and len(observation.polygon) >= 5:
        moments = cv2.moments(np.asarray(observation.polygon, dtype=np.float32))

        if moments["m00"] > 1.0:
            covariance = (
                np.array(
                    [
                        [moments["mu20"], moments["mu11"]],
                        [moments["mu11"], moments["mu02"]],
                    ]
                )
                / moments["m00"]
            )

    if covariance is None:
        x0, y0, x1, y1 = observation.box
        # The box of a hexagon is about 1.07 times its across-flats width on average.
        covariance = np.diag([((x1 - x0) / 1.07) ** 2, ((y1 - y0) / 1.07) ** 2]) * (
            HEXAGON_VARIANCE
        )

    values, vectors = np.linalg.eigh(covariance / HEXAGON_VARIANCE)
    values = np.maximum(values, 1e-6)

    return vectors @ np.diag(1 / np.sqrt(values)) @ vectors.T


def seed_models(
    points: np.ndarray, metrics: list[np.ndarray], config: BoardFitConfig
) -> list[tuple[int, np.ndarray]]:
    """Make starting lattice models from tiles and their nearest neighbours.

    Args:
        points: The detection centres as an `(n, 2)` array.
        metrics: The local metric of every detection (see `face_metric`).
        config: The settings of the fit.

    Returns:
        Pairs of the seed detection and an affine model from the lattice plane to the
        image, which puts the seed at the origin.
    """
    seeds: list[tuple[int, np.ndarray]] = []
    rotation = np.array(
        [
            [math.cos(math.pi / 3), -math.sin(math.pi / 3)],
            [math.sin(math.pi / 3), math.cos(math.pi / 3)],
        ]
    )

    for index, (point, metric) in enumerate(zip(points, metrics, strict=True)):
        offsets = (points - point) @ metric.T
        distances = np.linalg.norm(offsets, axis=1)
        distances[index] = math.inf
        neighbour = int(np.argmin(distances))
        local = np.linalg.inv(metric)

        if 0.75 <= distances[neighbour] <= 1.35:
            # The neighbour is one step east; the step to the south-east is 60 degrees
            # further, measured where the perspective is undone.
            east = points[neighbour] - point
            south_east = local @ (rotation @ offsets[neighbour])
        else:
            east = local @ np.array([1.0, 0.0])
            south_east = local @ (rotation @ np.array([1.0, 0.0]))

        # The south-east step is half an east step plus a step straight south.
        south = (south_east - east / 2) / (math.sqrt(3) / 2)
        model = np.array(
            [
                [east[0], south[0], point[0]],
                [east[1], south[1], point[1]],
                [0.0, 0.0, 1.0],
            ]
        )
        seeds.append((index, model))

    # Seeds with a neighbour first, so a lone tile in hand does not crowd out the hive.
    seeds.sort(
        key=lambda seed: (
            -np.count_nonzero(
                np.linalg.norm((points - points[seed[0]]) @ metrics[seed[0]].T, axis=1)
                < 1.35
            )
        )
    )

    return seeds[: config.max_seeds]


def grow_lattice(
    points: np.ndarray, seed: int, model: np.ndarray, config: BoardFitConfig
) -> tuple[dict[Coordinate, int], np.ndarray]:
    """Grow a set of hexes from a seed, refitting the model as tiles are added.

    Args:
        points: The detection centres as an `(n, 2)` array.
        seed: The detection at the origin hex.
        model: The starting map from the lattice plane to the image.
        config: The settings of the fit.

    Returns:
        The detection on each hex, and the refitted model.
    """
    assigned: dict[Coordinate, int] = {(0, 0): seed}

    while True:
        plane = apply_homography(matrix=np.linalg.inv(model), points=points)
        used = set(assigned.values())
        candidates = []

        for index, (x, y) in enumerate(plane):
            if index in used:
                continue

            coord = round_axial(*plane_to_axial(float(x), float(y)))
            residual = math.dist((x, y), axial_to_plane(coord))

            if (
                residual < config.snap_tolerance
                and coord not in assigned
                and any(neighbor in assigned for neighbor in get_neighbors(coord))
            ):
                candidates.append((residual, index, coord))

        if not candidates:
            return assigned, model

        for _, index, coord in sorted(candidates):
            if coord not in assigned and index not in assigned.values():
                assigned[coord] = index

        model = refit_model(points=points, assigned=assigned, model=model)


def refit_model(
    points: np.ndarray, assigned: dict[Coordinate, int], model: np.ndarray
) -> np.ndarray:
    """Fit the lattice model to the assigned detections.

    A homography needs six tiles spread over the plane, an affine model three; with
    tiles in a line only the step along the line and the position are refitted.

    Args:
        points: The detection centres as an `(n, 2)` array.
        assigned: The detection on each hex.
        model: The current model, which is kept where the tiles do not determine it.

    Returns:
        The refitted model.
    """
    plane = np.array([axial_to_plane(coord) for coord in assigned], dtype=np.float64)
    image = points[list(assigned.values())]
    spread = plane_spread(plane)

    if len(assigned) >= 6 and spread > 0.4:
        homography, _ = cv2.findHomography(plane, image, 0)

        if homography is not None and orientation_kept(homography, plane):
            return homography

    if len(assigned) >= 3 and spread > 0.3:
        return fit_affine(plane=plane, image=image)

    if len(assigned) >= 2:
        return fit_along_line(plane=plane, image=image, model=model)

    return model


def final_model(
    points: np.ndarray,
    assigned: dict[Coordinate, int],
    model: np.ndarray,
    tile_size: float,
) -> np.ndarray:
    """Fit the final model robustly, so faces on stacks do not bend the plane.

    Args:
        points: The detection centres as an `(n, 2)` array.
        assigned: The detection on each hex.
        model: The model of the growth.
        tile_size: The median face size in pixels.

    Returns:
        The map from the lattice plane to the image.
    """
    plane = np.array([axial_to_plane(coord) for coord in assigned], dtype=np.float64)
    image = points[list(assigned.values())]

    if len(assigned) >= 6 and plane_spread(plane) > 0.4:
        homography, _ = cv2.findHomography(
            plane, image, cv2.RANSAC, ransacReprojThreshold=0.12 * tile_size
        )

        if homography is not None and orientation_kept(homography, plane):
            return homography

    return model


def fit_affine(plane: np.ndarray, image: np.ndarray) -> np.ndarray:
    """Fit an affine map by least squares.

    Args:
        plane: The lattice plane points as an `(n, 2)` array, not all on a line.
        image: The image points as an `(n, 2)` array.

    Returns:
        The map as a 3 x 3 matrix.
    """
    design = np.hstack([plane, np.ones((len(plane), 1))])
    solution, *_ = np.linalg.lstsq(design, image, rcond=None)

    return np.vstack([solution.T, [0.0, 0.0, 1.0]])


def fit_along_line(plane: np.ndarray, image: np.ndarray, model: np.ndarray) -> np.ndarray:
    """Refit the step along a line of tiles and the position, keeping the cross step.

    Args:
        plane: The lattice plane points on one line as an `(n, 2)` array.
        image: The image points as an `(n, 2)` array.
        model: The current affine model, whose step across the line is kept.

    Returns:
        The refitted affine model.
    """
    origin = plane[0]
    direction = plane[-1] - origin
    direction = direction / max(np.linalg.norm(direction), 1e-9)
    across = np.array([-direction[1], direction[0]])
    steps = (plane - origin) @ direction
    design = np.vstack([steps, np.ones(len(steps))]).T
    solution, *_ = np.linalg.lstsq(design, image, rcond=None)
    along_image, start = solution[0], solution[1]
    across_image = model[:2, :2] @ across
    linear = np.column_stack([along_image, across_image]) @ np.linalg.inv(
        np.column_stack([direction, across])
    )

    return np.vstack(
        [np.hstack([linear, (start - linear @ origin)[:, None]]), [0.0, 0.0, 1.0]]
    )


def plane_spread(plane: np.ndarray) -> float:
    """Measure how far lattice points are from lying on one line.

    Args:
        plane: The points as an `(n, 2)` array.

    Returns:
        The smaller standard deviation of the points along their principal axes.
    """
    if len(plane) < 3:
        return 0.0

    centred = plane - plane.mean(axis=0)

    return float(np.linalg.svd(centred, compute_uv=False)[-1] / math.sqrt(len(plane)))


def orientation_kept(homography: np.ndarray, plane: np.ndarray) -> bool:
    """Check that a homography maps the hive without mirroring or folding it.

    Args:
        homography: The map from the lattice plane to the image.
        plane: The lattice plane points of the hive.

    Returns:
        Whether the map keeps orientation and stays in front of the camera there.
    """
    for x, y in plane:
        w = homography[2, 0] * x + homography[2, 1] * y + homography[2, 2]

        if w * homography[2, 2] <= 0:
            return False

    centre = plane.mean(axis=0)
    step = 1e-3
    base = apply_homography(matrix=homography, points=centre[None])[0]
    east = apply_homography(matrix=homography, points=(centre + [step, 0.0])[None])[0]
    south = apply_homography(matrix=homography, points=(centre + [0.0, step])[None])[0]
    jacobian = np.column_stack([east - base, south - base])

    return float(np.linalg.det(jacobian)) > 0


def apply_homography(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Map points with a 3 x 3 matrix in homogeneous coordinates.

    Args:
        matrix: The map.
        points: The points as an `(n, 2)` array.

    Returns:
        The mapped points as an `(n, 2)` array.
    """
    homogeneous = np.hstack([points, np.ones((len(points), 1))]) @ matrix.T

    return homogeneous[:, :2] / homogeneous[:, 2:3]


def mean_residual(
    points: np.ndarray, assigned: dict[Coordinate, int], model: np.ndarray
) -> float:
    """Measure how well a model places the assigned detections on their hexes.

    Args:
        points: The detection centres as an `(n, 2)` array.
        assigned: The detection on each hex.
        model: The map from the lattice plane to the image.

    Returns:
        The mean distance between detections and hex centres in lattice units.
    """
    plane = apply_homography(
        matrix=np.linalg.inv(model), points=points[list(assigned.values())]
    )
    centres = np.array([axial_to_plane(coord) for coord in assigned])

    return float(np.linalg.norm(plane - centres, axis=1).mean())


def estimate_camera(
    homography: np.ndarray, image_size: tuple[int, int], prior_focal: float
) -> np.ndarray | None:
    """Estimate the camera centre from the homography of the lattice plane.

    The principal point is assumed at the image centre with square pixels. The focal
    length follows from the homography when the view is tilted enough; otherwise the
    prior is used.

    Args:
        homography: The map from the lattice plane to the image.
        image_size: The image width and height in pixels.
        prior_focal: The focal length as a fraction of the long image side.

    Returns:
        The camera centre `(x, y, height)` in lattice units, or `None` for an affine
        model or an impossible decomposition.
    """
    if np.allclose(homography[2, :2], 0.0):
        return None

    width, height = image_size
    long_side = max(width, height)
    shift = np.array([[1.0, 0.0, -width / 2], [0.0, 1.0, -height / 2], [0.0, 0.0, 1.0]])
    g = shift @ homography
    g1, g2 = g[:, 0], g[:, 1]
    estimates = []

    if abs(g1[2] * g2[2]) > 1e-12:
        estimates.append(-(g1[0] * g2[0] + g1[1] * g2[1]) / (g1[2] * g2[2]))

    if abs(g1[2] ** 2 - g2[2] ** 2) > 1e-12:
        estimates.append(
            (g2[0] ** 2 + g2[1] ** 2 - g1[0] ** 2 - g1[1] ** 2)
            / (g1[2] ** 2 - g2[2] ** 2)
        )

    valid = [
        math.sqrt(value)
        for value in estimates
        if value > 0 and 0.3 * long_side <= math.sqrt(value) <= 4 * long_side
    ]
    focal = float(np.median(valid)) if valid else prior_focal * long_side
    m = np.diag([1 / focal, 1 / focal, 1.0]) @ g
    scale = (np.linalg.norm(m[:, 0]) + np.linalg.norm(m[:, 1])) / 2
    m = m / scale

    if m[2, 2] < 0:
        m = -m

    rotation = np.column_stack([m[:, 0], m[:, 1], np.cross(m[:, 0], m[:, 1])])
    u, _, vt = np.linalg.svd(rotation)
    rotation = u @ vt
    centre = -rotation.T @ m[:, 2]

    if abs(centre[2]) < 1e-6:
        return None

    return np.array([centre[0], centre[1], abs(centre[2])])


def connected_components(coords: set[Coordinate]) -> list[set[Coordinate]]:
    """Split hexes into groups connected through neighbours.

    Args:
        coords: The hexes.

    Returns:
        The connected groups.
    """
    remaining = set(coords)
    components = []

    while remaining:
        start = remaining.pop()
        component = {start}
        queue = deque([start])

        while queue:
            for neighbor in get_neighbors(queue.popleft()):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)

        components.append(component)

    return components
