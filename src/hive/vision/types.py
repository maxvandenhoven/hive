"""Values shared by the board readers: what a reader observes in a photo."""

from dataclasses import dataclass

import cv2
import numpy as np

from hive.engine.codec import JsonCodec
from hive.engine.state import PieceType, Player
from hive.vision.classes import TileClass

TILE_CLASS_COLORS: dict[Player, tuple[int, int, int]] = {
    Player.WHITE: (60, 200, 255),
    Player.BLACK: (255, 120, 40),
}
"""The BGR colours observations are drawn in, by owner."""


@dataclass(frozen=True, slots=True)
class TileObservation(JsonCodec):
    """A tile face seen in a photo.

    Attributes:
        center: The centre of the tile face in pixels.
        box: The bounding box `(x0, y0, x1, y1)` of the face in pixels.
        polygon: The outline of the face in pixels, if the reader finds it.
        piece_type: The insect on the tile.
        owner: The player the tile belongs to, which is its colour.
        score: The confidence between 0 and 1.
        class_scores: The score of every tile class in class id order, if the reader
            gives them; they tell how likely the other classes are when the best one is
            wrong.
    """

    center: tuple[float, float]
    box: tuple[float, float, float, float]
    polygon: list[tuple[float, float]] | None
    piece_type: PieceType
    owner: Player
    score: float
    class_scores: tuple[float, ...] | None = None

    @property
    def tile_class(self) -> TileClass:
        """The detection class of the observed face."""
        return TileClass(piece_type=self.piece_type, owner=self.owner)

    def draw(self, canvas: np.ndarray) -> None:
        """Draw the observation onto an image: outline or box, centre and class name.

        Args:
            canvas: The BGR image to draw on, changed in place.
        """
        color = TILE_CLASS_COLORS[self.owner]
        x0, y0, x1, y1 = (round(value) for value in self.box)

        if self.polygon is not None:
            points = np.round(np.asarray(self.polygon)).astype(np.int32)
            cv2.polylines(canvas, [points], isClosed=True, color=color, thickness=2)
        else:
            cv2.rectangle(canvas, (x0, y0), (x1, y1), color=color, thickness=2)

        center = (round(self.center[0]), round(self.center[1]))
        cv2.circle(canvas, center, radius=3, color=color, thickness=-1)
        text = f"{self.piece_type.name.lower()} {self.score:.2f}"
        scale = max(0.35, min(0.7, (x1 - x0) / 160))
        cv2.putText(
            canvas,
            text,
            (x0, max(y0 - 4, 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            text,
            (x0, max(y0 - 4, 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color,
            1,
            cv2.LINE_AA,
        )
