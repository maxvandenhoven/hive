"""The interface every board reader implements, classical or learned."""

from typing import Protocol

import numpy as np

from hive.vision.types import TileObservation


class BoardReader(Protocol):
    """Finds the tile faces in a photo of a board.

    Attributes:
        name: The name of the reader, for example `yolo`.
    """

    name: str

    def read(self, image: np.ndarray) -> list[TileObservation]:
        """Find the tile faces in a photo.

        Args:
            image: The photo as a BGR image, as OpenCV reads it.

        Returns:
            The observed tile faces, in no particular order.
        """
        ...
