"""Tracking evaluation: follow rendered games photo by photo and check every move.

`hive data sequences` makes scenes of games after every move, with several photos per
move from independent cameras, lighting, tables and clutter. Rendered and exported, they
are replayed here through the whole pipeline: the board reader, the board fit and the
game tracker. A move that stays unclear after every photo is entered by hand, as a
person would, and a wrong move is corrected so the next moves are judged on their own.
Every photo becomes a frame showing the detections next to the tracked board.
"""

import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from hive.data.datasets import DatasetImage, read_image
from hive.engine.codec import JsonCodec, json_adapter
from hive.engine.grid import Coordinate
from hive.engine.record import GameRecord
from hive.engine.rules import Rules
from hive.engine.state import GameBoard, GameState, Move, PieceType, Player
from hive.vision.grid_fit import BoardFitError, ObservedBoard
from hive.vision.lattice import axial_to_plane
from hive.vision.reader import BoardReader
from hive.vision.resolver import (
    MoveResolution,
    ResolutionStatus,
    board_key,
    changed_hexes,
    describe_move,
)
from hive.vision.tracking import GameTracker
from hive.vision.types import TileObservation

INSECT_COLORS: dict[PieceType, tuple[int, int, int]] = {
    PieceType.QUEEN: (77, 203, 254),
    PieceType.BEETLE: (235, 176, 188),
    PieceType.GRASSHOPPER: (87, 207, 111),
    PieceType.SPIDER: (90, 105, 168),
    PieceType.ANT: (215, 182, 112),
}
"""The BGR colours of the insects on the drawn board."""

TILE_COLORS: dict[Player, tuple[int, int, int]] = {
    Player.WHITE: (214, 229, 237),
    Player.BLACK: (40, 38, 36),
}
"""The BGR body colours of the tiles on the drawn board."""

FRAME_HEIGHT = 720
"""The height of a frame in pixels; the photo and the board are drawn side by side."""


@dataclass(frozen=True, slots=True)
class TrackedPhoto(JsonCodec):
    """What the tracker made of one photo.

    Attributes:
        scene_id: The scene id of the photo.
        status: `resolved`, `ambiguous`, `failed`, or `no_hive` when no board fit.
        detections: The number of detected faces.
        on_grid: The number of faces placed on the hive.
        best: The best candidate's moves described, if any.
        probability: The best candidate's probability, if any.
        seconds: The time to read, fit and resolve the photo.
    """

    scene_id: str
    status: str
    detections: int
    on_grid: int
    best: str | None
    probability: float | None
    seconds: float


@dataclass(frozen=True, slots=True)
class TrackedPly(JsonCodec):
    """The tracking of one move.

    Attributes:
        sequence: The game id.
        ply: The number of the move, from 1.
        true_move: The move that was played.
        outcome: `resolved` with the photos, `manual` when entered by hand, or `wrong`
            when a resolved move does not give the true position.
        photos: What the tracker made of each photo used.
    """

    sequence: str
    ply: int
    true_move: Move | None
    outcome: str
    photos: list[TrackedPhoto]


@dataclass(frozen=True, slots=True)
class TrackingReport(JsonCodec):
    """The tracking of rendered games.

    Attributes:
        reader: The name of the board reader.
        plies: Every tracked move.
        summary: The counts of the outcomes, and of the photos needed when resolved.
    """

    reader: str
    plies: list[TrackedPly]
    summary: dict[str, int]


class SequenceTracker:
    """Replays rendered games through the board reader, the board fit and the tracker.

    Attributes:
        dataset: The exported dataset of the rendered sequences.
        reader: The board reader.
        rules: The rules of the games.
        frames: The folder for the frames, or `None` to not draw them.
    """

    def __init__(
        self, dataset: Path, reader: BoardReader, rules: Rules, frames: Path | None
    ) -> None:
        """Prepare the replay.

        Args:
            dataset: The exported dataset folder with `meta.jsonl`.
            reader: The board reader.
            rules: The rules of the games.
            frames: The folder for the frames, or `None` to not draw them.
        """
        self.dataset = dataset
        self.reader = reader
        self.rules = rules
        self.frames = frames

    def images(self) -> dict[str, dict[int, list[DatasetImage]]]:
        """Group the photos of the dataset by game and move.

        Returns:
            Per game id, per move number, the photos in take order.
        """
        games: dict[str, dict[int, list[DatasetImage]]] = {}

        with (self.dataset / "meta.jsonl").open() as file:
            for line in file:
                image = DatasetImage.from_json(json.loads(line))
                sequence, ply, _ = image.scene_id.split("-")
                games.setdefault(sequence, {}).setdefault(int(ply), []).append(image)

        for plies in games.values():
            for photos in plies.values():
                photos.sort(key=lambda image: image.scene_id)

        return games

    def run(self) -> TrackingReport:
        """Track every game of the dataset.

        Returns:
            The report.
        """
        plies: list[TrackedPly] = []

        for sequence, photos_by_ply in sorted(self.images().items()):
            plies += self.track_game(sequence=sequence, photos_by_ply=photos_by_ply)

        summary = Counter(ply.outcome for ply in plies)

        for ply in plies:
            if ply.outcome == "resolved":
                summary[f"resolved with {len(ply.photos)} photo(s)"] += 1

        return TrackingReport(reader=self.reader.name, plies=plies, summary=dict(summary))

    def track_game(
        self, sequence: str, photos_by_ply: dict[int, list[DatasetImage]]
    ) -> list[TrackedPly]:
        """Track one game move by move.

        Args:
            sequence: The game id.
            photos_by_ply: The photos of every move, in take order.

        Returns:
            The tracking of every move.
        """
        last = photos_by_ply[max(photos_by_ply)][0]
        moves = json_adapter(list[Move | None]).validate_python(last.render["moves"])
        tracker = GameTracker(rules=self.rules)
        tracked: list[TrackedPly] = []

        for ply in sorted(photos_by_ply):
            truth = GameRecord(rules=self.rules, moves=moves[:ply]).replay()
            photos: list[TrackedPhoto] = []
            observed: ObservedBoard | None = None
            resolved = False

            for image in photos_by_ply[ply]:
                begin = time.perf_counter()
                photo = read_image(
                    path=self.dataset / image.image, flags=cv2.IMREAD_COLOR
                )
                observations = self.reader.read(photo)

                try:
                    observed = ObservedBoard.fit(
                        observations=observations, image_size=(image.width, image.height)
                    )
                except BoardFitError:
                    observed = None

                state_before = tracker.state.copy()
                resolution = tracker.add_photo(observed) if observed is not None else None
                seconds = time.perf_counter() - begin
                photos.append(
                    tracked_photo(
                        scene_id=image.scene_id,
                        resolution=resolution,
                        detections=len(observations),
                        observed=observed,
                        seconds=seconds,
                    )
                )
                resolved = (
                    resolution is not None
                    and resolution.status is ResolutionStatus.RESOLVED
                )
                outcome = None

                if resolved:
                    correct = board_key(tracker.state.board) == board_key(truth.board)
                    outcome = "resolved" if correct else "wrong"

                self.draw(
                    sequence=sequence,
                    ply=ply,
                    image=image,
                    photo=photo,
                    observed=observed,
                    observations=observations,
                    state_before=state_before,
                    tracker=tracker,
                    resolution=resolution,
                    outcome=outcome,
                )

                if resolved:
                    break

            if not resolved:
                tracker.confirm(moves=[moves[ply - 1]], photo=observed)
                outcome = "manual"
            elif board_key(tracker.state.board) == board_key(truth.board):
                outcome = "resolved"
            else:
                outcome = "wrong"
                # Continue from the true position, so later moves are judged alone.
                tracker.state = truth.copy()
                tracker.previous = None

            tracked.append(
                TrackedPly(
                    sequence=sequence,
                    ply=ply,
                    true_move=moves[ply - 1],
                    outcome=outcome,
                    photos=photos,
                )
            )

        return tracked

    def draw(
        self,
        sequence: str,
        ply: int,
        image: DatasetImage,
        photo: np.ndarray,
        observed: ObservedBoard | None,
        observations: list[TileObservation],
        state_before: GameState,
        tracker: GameTracker,
        resolution: MoveResolution | None,
        outcome: str | None,
    ) -> None:
        """Draw a frame: the photo with its detections next to the tracked board.

        Args:
            sequence: The game id.
            ply: The move number.
            image: The photo's dataset entry.
            photo: The photo.
            observed: The observed board, or `None` if no hive was found.
            observations: The detections.
            state_before: The tracked position before the photo.
            tracker: The tracker after the photo.
            resolution: The resolution of the photo, or `None` if no hive was found.
            outcome: `resolved` or `wrong` for a resolved photo, otherwise `None`.
        """
        if self.frames is None:
            return

        canvas = photo.copy()
        on_grid = (
            {id(tile.observation) for tile in observed.tiles.values()}
            if observed
            else set()
        )

        for observation in observations:
            if id(observation) in on_grid:
                observation.draw(canvas)
            else:
                x0, y0, x1, y1 = (round(value) for value in observation.box)
                cv2.rectangle(canvas, (x0, y0), (x1, y1), (150, 150, 150), 1)

        scale = FRAME_HEIGHT / canvas.shape[0]
        canvas = cv2.resize(canvas, (round(canvas.shape[1] * scale), FRAME_HEIGHT))
        changed: set[Coordinate] = set()
        board = tracker.state.board

        if resolution is not None and resolution.best is not None:
            if resolution.status is ResolutionStatus.RESOLVED:
                changed = changed_hexes(tuple(resolution.best.moves))
            else:
                # Show the best guess on the position before the photo.
                guess = state_before.copy()

                for move in resolution.best.moves:
                    guess.apply_move(move)

                board = guess.board
                changed = changed_hexes(tuple(resolution.best.moves))

        drawing = draw_board(board=board, changed=changed, size=FRAME_HEIGHT)
        frame = np.hstack([canvas, drawing])
        lines = frame_caption(
            sequence=sequence,
            ply=ply,
            take=image.scene_id.rsplit("-", 1)[1],
            resolution=resolution,
            outcome=outcome,
        )
        cv2.rectangle(
            frame, (0, 0), (frame.shape[1], 26 * len(lines) + 10), (0, 0, 0), -1
        )

        for index, (text, color) in enumerate(lines):
            cv2.putText(
                frame,
                text,
                (10, 26 * (index + 1)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                1,
                cv2.LINE_AA,
            )

        folder = self.frames / sequence
        folder.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(folder / f"{image.scene_id}.jpg"), frame)


def tracked_photo(
    scene_id: str,
    resolution: MoveResolution | None,
    detections: int,
    observed: ObservedBoard | None,
    seconds: float,
) -> TrackedPhoto:
    """Summarise what the tracker made of a photo.

    Args:
        scene_id: The scene id of the photo.
        resolution: The resolution, or `None` if no hive was found.
        detections: The number of detected faces.
        observed: The observed board, or `None`.
        seconds: The time to read, fit and resolve the photo.

    Returns:
        The summary.
    """
    best = resolution.best if resolution is not None else None

    return TrackedPhoto(
        scene_id=scene_id,
        status=str(resolution.status) if resolution is not None else "no_hive",
        detections=detections,
        on_grid=len(observed.tiles) if observed is not None else 0,
        best=" then ".join(describe_move(move) for move in best.moves) if best else None,
        probability=best.probability if best else None,
        seconds=round(seconds, 3),
    )


def frame_caption(
    sequence: str,
    ply: int,
    take: str,
    resolution: MoveResolution | None,
    outcome: str | None,
) -> list[tuple[str, tuple[int, int, int]]]:
    """Write the caption of a frame.

    Args:
        sequence: The game id.
        ply: The move number.
        take: The photo number of the move, from 0.
        resolution: The resolution, or `None` if no hive was found.
        outcome: `resolved` or `wrong` for a resolved photo, otherwise `None`.

    Returns:
        The lines with their BGR colours.
    """
    header = f"Game {sequence}, move {ply}, photo {int(take) + 1}"

    if resolution is None:
        return [
            (header, (255, 255, 255)),
            ("No hive found: take another photo", (80, 80, 255)),
        ]

    best = resolution.best
    described = " then ".join(describe_move(m) for m in best.moves) if best else "-"
    probability = f" (p = {best.probability:.2f})" if best else ""

    if resolution.status is ResolutionStatus.RESOLVED:
        verdict = "matches the game" if outcome == "resolved" else "WRONG"
        color = (120, 220, 120) if outcome == "resolved" else (60, 60, 255)

        return [
            (header, (255, 255, 255)),
            (f"Resolved: {described}{probability}, {verdict}", color),
        ]

    return [
        (header, (255, 255, 255)),
        (
            f"{resolution.status.value.capitalize()}: best {described}{probability}; "
            "asking for another photo",
            (80, 200, 255),
        ),
    ]


def draw_board(board: GameBoard, changed: set[Coordinate], size: int) -> np.ndarray:
    """Draw a board from above: tile colours, insect initials and stack heights.

    Args:
        board: The board.
        changed: The hexes to highlight.
        size: The width and height of the drawing in pixels.

    Returns:
        The BGR drawing.
    """
    canvas = np.full((size, size, 3), (58, 52, 47), dtype=np.uint8)
    coords = list(board) + list(changed)

    if not coords:
        return canvas

    points = np.array([axial_to_plane(coord) for coord in coords])
    low, high = points.min(axis=0) - 0.8, points.max(axis=0) + 0.8
    scale = min(
        (size - 40) / max(high[0] - low[0], 1.0),
        (size - 40) / max(high[1] - low[1], 1.0),
        80,
    )
    centre = (low + high) / 2

    def to_pixel(x: float, y: float) -> tuple[int, int]:
        """Map a lattice plane point to the drawing.

        Args:
            x: The position to the east.
            y: The position to the south.

        Returns:
            The pixel position.
        """
        return round(size / 2 + (x - centre[0]) * scale), round(
            size / 2 + (y - centre[1]) * scale
        )

    for coord in set(coords):
        x, y = axial_to_plane(coord)
        corners = np.array(
            [
                to_pixel(
                    x + 0.55 * math.cos(math.pi / 6 + k * math.pi / 3),
                    y + 0.55 * math.sin(math.pi / 6 + k * math.pi / 3),
                )
                for k in range(6)
            ],
            dtype=np.int32,
        )
        stack = board.get(coord)

        if stack:
            top = stack[-1]
            cv2.fillPoly(canvas, [corners], TILE_COLORS[top.owner], lineType=cv2.LINE_AA)
            label = top.type.name[0]
            font_scale = scale / 60
            (width, height), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_DUPLEX, font_scale, 2
            )
            cx, cy = to_pixel(x, y)
            cv2.putText(
                canvas,
                label,
                (cx - width // 2, cy + height // 2),
                cv2.FONT_HERSHEY_DUPLEX,
                font_scale,
                INSECT_COLORS[top.type],
                2,
                cv2.LINE_AA,
            )

            if len(stack) > 1:
                cv2.putText(
                    canvas,
                    f"x{len(stack)}",
                    (cx + width // 2, cy + height),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale * 0.5,
                    (60, 200, 255),
                    1,
                    cv2.LINE_AA,
                )

        highlight = coord in changed
        cv2.polylines(
            canvas,
            [corners],
            isClosed=True,
            color=(60, 200, 255) if highlight else (110, 104, 98),
            thickness=3 if highlight else 1,
            lineType=cv2.LINE_AA,
        )

    return canvas
