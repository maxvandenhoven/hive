"""The board reader of the app, and what a photo shows about a game.

A photo taken at the table is decoded once (EXIF orientation applied, scaled down to the
longest stored side) and stored as a JPEG. The reader finds the tile faces; the board fit
places them on the hex lattice; the move resolver compares the result with the position
the game knows. Reading and resolving block for tens to hundreds of milliseconds, so they
run in worker threads, one photo at a time, and never stall the event loop.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path

import anyio.to_thread
import cv2
import numpy as np
from anyio import CapacityLimiter

from hive.engine.codec import JsonCodec
from hive.engine.rules import Rules
from hive.engine.state import GameState, Move
from hive.vision.estimate import BoardEstimate
from hive.vision.grid_fit import BoardFitError, ObservedBoard
from hive.vision.reader import BoardReader
from hive.vision.resolver import (
    MoveResolution,
    MoveResolver,
    MoveVerification,
    ResolutionStatus,
)
from hive.vision.types import TileObservation

logger = logging.getLogger(__name__)

PHOTO_CONTENT_TYPE = "image/jpeg"
"""The media type photos are stored and served as."""

PHOTO_JPEG_QUALITY = 90
"""The JPEG quality photos are stored at, high enough to label them later."""

NO_TILES_REASON = "No tiles were found. Take a photo with every tile of the hive in view."
"""Why a photo without any detected tile shows nothing."""


class PhotoImageError(Exception):
    """Raised when uploaded bytes are not an image that can be decoded."""


@dataclass(frozen=True, slots=True)
class PhotoImage:
    """A decoded photo, upright and at most the longest stored side.

    Attributes:
        pixels: The BGR image, as OpenCV reads it.
        jpeg: The image encoded as the JPEG that is stored.
    """

    pixels: np.ndarray
    jpeg: bytes

    @property
    def width(self) -> int:
        """The width in pixels."""
        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        """The height in pixels."""
        return int(self.pixels.shape[0])

    @classmethod
    def decode(cls, data: bytes, max_side: int) -> "PhotoImage":
        """Decode an uploaded photo, turn it upright and scale it down if needed.

        OpenCV applies the EXIF orientation of phone photos when it decodes them, so the
        stored image is upright and has no orientation tag left.

        Args:
            data: The uploaded file, for example a JPEG from a phone camera.
            max_side: The longest side in pixels; larger images are scaled down.

        Returns:
            The decoded image with its JPEG encoding.

        Raises:
            PhotoImageError: If the data is not an image OpenCV can decode.
        """
        pixels = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)

        if pixels is None:
            msg = "The upload is not an image that can be read; send a JPEG or PNG photo."
            raise PhotoImageError(msg)

        height, width = pixels.shape[:2]
        scale = max_side / max(width, height)

        if scale < 1:
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            pixels = cv2.resize(pixels, size, interpolation=cv2.INTER_AREA)

        encoded, buffer = cv2.imencode(
            ".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, PHOTO_JPEG_QUALITY]
        )

        if not encoded:
            msg = "The photo could not be encoded as a JPEG."
            raise PhotoImageError(msg)

        return cls(pixels=pixels, jpeg=buffer.tobytes())


class PhotoPurpose(StrEnum):
    """What a photo taken in a game is for."""

    MOVE = "move"
    """Find the move a person played since the position the game knows."""

    VERIFICATION = "verification"
    """Check that the pending agent move was made on the physical board."""


@dataclass(frozen=True, slots=True)
class PhotoObservations:
    """The tiles a reader found in a photo, which give its observed board again.

    Stored photos keep their detections, so an earlier photo can be fitted again when a
    later one is resolved, without reading its image.

    Attributes:
        photo_id: The photo ID.
        observations: The detected tile faces.
        image_size: The image width and height in pixels.
    """

    photo_id: uuid.UUID
    observations: list[TileObservation]
    image_size: tuple[int, int]

    def fit(self) -> ObservedBoard | None:
        """Place the detections on the hex lattice.

        Returns:
            The observed board, or `None` if no tile was detected.
        """
        try:
            return ObservedBoard.fit(
                observations=self.observations, image_size=self.image_size
            )
        except BoardFitError:
            return None


@dataclass(frozen=True, slots=True)
class PhotoMatch(JsonCodec):
    """What a photo shows about a game, stored with the photo.

    Attributes:
        purpose: Whether the photo finds a person's move or checks a pending agent move.
        resolution: The legal moves that explain the photo, best first, and whether one
            of them is clear. For a verification, the moves from the position before the
            pending move.
        verification: Whether the photo shows the pending agent move, for verifications
            only.
        photo_ids: The photos of the same position that were resolved together, oldest
            first and ending with this one. Earlier photos count when they were unclear.
        previous_photo_id: The photo of the position before the move, whose readings of
            the tiles helped to recognise them, or `None` if there is none.
        tile_count: The number of tiles found on the hive.
        edge: Whether the hive touches the edge of the photo, so tiles may be cut off.
    """

    purpose: PhotoPurpose
    resolution: MoveResolution
    verification: MoveVerification | None
    photo_ids: list[uuid.UUID]
    previous_photo_id: uuid.UUID | None
    tile_count: int
    edge: bool

    @property
    def outcome(self) -> str:
        """The outcome for metrics and logs, such as `resolved` or `matched`."""
        if self.verification is not None:
            return self.verification.status.value

        return self.resolution.status.value

    @property
    def waiting(self) -> bool:
        """Whether the photo is unclear and is resolved again with the next photo."""
        return self.resolution.status is ResolutionStatus.AMBIGUOUS


class BoardVision:
    """The board reader of the app, with the limit of one photo read at a time.

    Attributes:
        reader: The board reader, or `None` if none is configured or it failed to load.
        model_version: The name and version of the reader's model, for example
            `hive-yolo-seg/v001`, or `None` without a reader.
        configured: Whether a reader model was configured, so readiness checks it.
        error: Why the configured reader is not available, or `None`.
        limiter: Limits reading and resolving to one photo at a time, since the reader
            already uses every CPU core.
    """

    def __init__(
        self,
        reader: BoardReader | None,
        model_version: str | None = None,
        configured: bool | None = None,
        error: str | None = None,
    ) -> None:
        """Wrap a board reader.

        Args:
            reader: The board reader, or `None` to store photos without reading them.
            model_version: The name and version of the reader's model, or `None`.
            configured: Whether a reader model was configured, or `None` for whether a
                reader is given.
            error: Why the configured reader is not available, or `None`.
        """
        self.reader = reader
        self.model_version = model_version
        self.configured = reader is not None if configured is None else configured
        self.error = error
        self.limiter = CapacityLimiter(1)

    @classmethod
    def load(cls, model_path: Path | None, score_threshold: float) -> "BoardVision":
        """Load the YOLO reader from an ONNX model file, which blocks for a moment.

        A model that is missing or does not load leaves the app without a reader, so
        photos are still stored; the error is logged and fails the readiness check.

        Args:
            model_path: The ONNX model, with an optional `model.json` beside it that
                names the model and its version, or `None` for no reader.
            score_threshold: The lowest class score that counts as a detection.

        Returns:
            The vision of the app.
        """
        if model_path is None:
            logger.info("No vision model is configured; photos are stored, not read.")

            return cls(reader=None)

        # Imported here, so the app starts without loading ONNX Runtime when unused.
        from hive.vision.yolo.reader import YoloReader  # noqa: PLC0415

        try:
            reader = YoloReader.load(
                model_path=model_path, score_threshold=score_threshold
            )
        except Exception as e:
            logger.exception("Could not load the vision model `%s`.", model_path)

            return cls(
                reader=None,
                configured=True,
                error=f"The vision model `{model_path}` could not be loaded: {e}",
            )

        model_version = model_path.stem
        metadata = model_path.with_name("model.json")

        if metadata.is_file():
            info = json.loads(metadata.read_text(encoding="utf-8"))
            model_version = f"{info['name']}/{info['version']}"

        logger.info("Loaded the vision model `%s` from `%s`.", model_version, model_path)

        return cls(reader=reader, model_version=model_version)

    async def read(self, image: PhotoImage) -> tuple[list[TileObservation], float]:
        """Find the tile faces in a photo.

        Args:
            image: The decoded photo.

        Returns:
            The detected faces and the seconds the reader took.

        Raises:
            RuntimeError: If the app has no reader.
        """
        reader = self.reader

        if reader is None:
            msg = "The app has no board reader."
            raise RuntimeError(msg)

        def read_blocking() -> tuple[list[TileObservation], float]:
            """Run the reader and time it.

            Returns:
                The detected faces and the seconds the reader took.
            """
            start = time.perf_counter()
            observations = reader.read(image.pixels)

            return observations, time.perf_counter() - start

        return await anyio.to_thread.run_sync(read_blocking, limiter=self.limiter)

    async def match(
        self,
        rules: Rules,
        state: GameState,
        purpose: PhotoPurpose,
        expected: Move | None,
        photo: PhotoObservations,
        earlier: list[PhotoObservations],
        previous: PhotoObservations | None,
    ) -> PhotoMatch:
        """Resolve a photo, with unclear earlier photos of the same position.

        Args:
            rules: The rules of the game.
            state: The position before the move the photo shows.
            purpose: Whether the photo finds a move or checks the pending agent move.
            expected: The pending agent move, for verifications; ignored otherwise.
            photo: The detections of the new photo.
            earlier: The detections of unclear earlier photos of the same position.
            previous: The detections of the photo of `state`, or `None`.

        Returns:
            What the photo shows.
        """
        return await anyio.to_thread.run_sync(
            partial(
                self.match_blocking,
                rules=rules,
                state=state,
                purpose=purpose,
                expected=expected,
                photo=photo,
                earlier=earlier,
                previous=previous,
            ),
            limiter=self.limiter,
        )

    def match_blocking(
        self,
        rules: Rules,
        state: GameState,
        purpose: PhotoPurpose,
        expected: Move | None,
        photo: PhotoObservations,
        earlier: list[PhotoObservations],
        previous: PhotoObservations | None,
    ) -> PhotoMatch:
        """Resolve a photo in the calling thread; see `match`.

        Args:
            rules: The rules of the game.
            state: The position before the move the photo shows.
            purpose: Whether the photo finds a move or checks the pending agent move.
            expected: The pending agent move, for verifications; ignored otherwise.
            photo: The detections of the new photo.
            earlier: The detections of unclear earlier photos of the same position.
            previous: The detections of the photo of `state`, or `None`.

        Returns:
            What the photo shows.
        """
        resolver = MoveResolver(rules)
        observed = photo.fit()
        fitted = [(item.photo_id, item.fit()) for item in earlier]
        combined = [(item_id, board) for item_id, board in fitted if board is not None]
        previous_board = previous.fit() if previous is not None else None

        if observed is None:
            resolution = MoveResolution(
                status=ResolutionStatus.FAILED, candidates=[], reason=NO_TILES_REASON
            )
            combined = []
        else:
            resolution = resolver.resolve(
                state=state,
                photos=[board for _, board in combined] + [observed],
                previous=previous_board,
            )

        verification = (
            resolver.verify(state=state, expected=expected, resolution=resolution)
            if purpose is PhotoPurpose.VERIFICATION
            else None
        )

        return PhotoMatch(
            purpose=purpose,
            resolution=resolution,
            verification=verification,
            photo_ids=[item_id for item_id, _ in combined] + [photo.photo_id],
            previous_photo_id=(
                previous.photo_id
                if previous is not None and previous_board is not None
                else None
            ),
            tile_count=len(observed.tiles) if observed is not None else 0,
            edge=bool(observed.edge_coords()) if observed is not None else False,
        )

    async def estimate(self, rules: Rules, image: PhotoImage) -> BoardEstimate:
        """Read a whole position from one photo, without the history of a game.

        Args:
            rules: The rules, which give the pieces of the set and the valid boards.
            image: The decoded photo.

        Returns:
            The estimated board and how sure it is.

        Raises:
            RuntimeError: If the app has no reader.
        """
        observations, _ = await self.read(image)
        photo = PhotoObservations(
            photo_id=uuid.uuid4(),
            observations=observations,
            image_size=(image.width, image.height),
        )

        def estimate_blocking() -> BoardEstimate:
            """Fit the detections and read the board.

            Returns:
                The estimate.
            """
            observed = photo.fit()

            if observed is None:
                return BoardEstimate.failed(NO_TILES_REASON)

            return BoardEstimate.from_observed(observed=observed, rules=rules)

        return await anyio.to_thread.run_sync(estimate_blocking, limiter=self.limiter)
