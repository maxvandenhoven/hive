"""The photo service: storing photos of games at the table and reading what they show.

A photo after a person's move is matched against the position the game knows, so it
only has to tell which legal move was played (see `hive.vision.resolver`). Two things
help an unclear photo:

- Earlier photos: unclear photos of the same position, taken since the game last
  changed, are resolved together with the new one, so a retake adds evidence instead of
  starting over.
- The previous photo: the photo linked to the move before shows how the reader sees
  each physical tile, so a tile it misreads the same way again is still recognised.

While an agent move waits to be made on the table, a photo checks that move instead.
Nothing here changes the game: a person confirms the proposed move, which is then
played or confirmed through the game service with the photo linked to it.
"""

import logging
import time
import uuid
from functools import partial

import anyio.to_thread
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hive.api.db.models import GameRow, PhotoRow
from hive.api.errors import (
    NotAtTableError,
    PhotoMissingError,
    PhotoNotReadableError,
    PhotoTooLargeError,
    PlyConflictError,
    VisionUnavailableError,
)
from hive.api.games import GameService
from hive.api.metrics import ApiMetrics
from hive.api.players import BoardLocation
from hive.api.settings import ApiSettings
from hive.api.storage import ObjectStore
from hive.api.vision import (
    PHOTO_CONTENT_TYPE,
    BoardVision,
    PhotoImage,
    PhotoImageError,
    PhotoObservations,
    PhotoPurpose,
)
from hive.engine.rules import Rules
from hive.vision.estimate import BoardEstimate

logger = logging.getLogger(__name__)

UNREAD_OUTCOME = "unread"
"""The metric outcome of a photo stored without a reader."""

NO_VISION_DETAIL = "Set `HIVE_VISION_MODEL` to a vision model to read photos."
"""Why a photo cannot be read when no reader model is configured."""


class PhotoService:
    """Stores photos of games and reads what they show, in one database session.

    Attributes:
        session: The database session.
        store: The object store holding the photo images.
        vision: The board reader of the app.
        settings: The settings, with the upload limits.
        metrics: The metrics the photo reads are recorded in.
        games: The game service on the same session.
    """

    def __init__(
        self,
        session: AsyncSession,
        store: ObjectStore,
        vision: BoardVision,
        settings: ApiSettings,
        metrics: ApiMetrics,
    ) -> None:
        """Create the service.

        Args:
            session: The database session.
            store: The object store holding the photo images.
            vision: The board reader of the app.
            settings: The settings, with the upload limits.
            metrics: The metrics the photo reads are recorded in.
        """
        self.session = session
        self.store = store
        self.vision = vision
        self.settings = settings
        self.metrics = metrics
        self.games = GameService(session=session, store=store)

    async def decode(self, data: bytes) -> PhotoImage:
        """Check the size of an upload and decode it in a worker thread.

        Args:
            data: The uploaded file.

        Returns:
            The upright photo, at most the longest stored side.

        Raises:
            PhotoTooLargeError: If the upload is larger than the limit.
            PhotoNotReadableError: If the upload is not an image.
        """
        if len(data) > self.settings.photo_max_bytes:
            raise PhotoTooLargeError(self.settings.photo_max_bytes)

        try:
            return await anyio.to_thread.run_sync(
                partial(
                    PhotoImage.decode, data=data, max_side=self.settings.photo_max_side
                )
            )
        except PhotoImageError as e:
            raise PhotoNotReadableError(str(e)) from e

    async def add_photo(
        self, game_id: uuid.UUID, data: bytes, expected_ply: int
    ) -> PhotoRow:
        """Store a photo of a game at the table and match it against the game.

        Without a pending agent move, the photo shows the next move of a person; with
        one, it checks that the pending move was made.

        Args:
            game_id: The game ID.
            data: The uploaded image file.
            expected_ply: The `ply_count` of the game the client saw.

        Returns:
            The stored photo, with what it shows if the app has a reader.

        Raises:
            GameNotFoundError: If there is no game with the ID.
            NotAtTableError: If the game is played on the screen.
            PlyConflictError: If the game is not at the expected ply.
            GameNotActiveError: If the game is finished or abandoned without a pending
                move to check.
            PhotoTooLargeError: If the upload is larger than the limit.
            PhotoNotReadableError: If the upload is not an image.
        """
        game = await self.games.get_game(game_id)

        if game.board_location is not BoardLocation.TABLE:
            raise NotAtTableError(game_id)

        if expected_ply != len(game.moves):
            raise PlyConflictError(expected_ply=expected_ply, ply_count=len(game.moves))

        verifying = bool(game.moves) and game.moves[-1].pending

        if not verifying:
            self.games.check_active(game=game, state=game.replay())

        image = await self.decode(data)
        photo_id = uuid.uuid4()
        ply = len(game.moves) - 1 if verifying else len(game.moves)
        photo = PhotoRow(
            id=photo_id,
            game_id=game.id,
            ply=ply,
            object_key=game.photo_key(photo_id),
            width=image.width,
            height=image.height,
        )
        await self.store.put(
            key=photo.object_key, data=image.jpeg, content_type=PHOTO_CONTENT_TYPE
        )

        if self.vision.reader is not None:
            await self.read_photo(
                game=game, photo=photo, image=image, verifying=verifying
            )
        else:
            self.metrics.photo_match.labels(outcome=UNREAD_OUTCOME).inc()

        self.session.add(photo)
        await self.session.commit()
        logger.info(
            "Stored photo `%s` of game `%s` for ply %d.",
            photo.id,
            game.id,
            ply,
            extra={"game_id": str(game.id), "photo_id": str(photo.id)},
        )

        return photo

    async def read_photo(
        self, game: GameRow, photo: PhotoRow, image: PhotoImage, verifying: bool
    ) -> None:
        """Read a new photo and match it against its game, filling in the photo row.

        Args:
            game: The game, with its moves loaded.
            photo: The new photo, not yet added to the session.
            image: The decoded image of the photo.
            verifying: Whether the photo checks the pending last move.
        """
        assert self.vision.reader is not None
        reader_name = self.vision.reader.name
        observations, read_s = await self.vision.read(image)
        self.metrics.photo_read_seconds.labels(reader=reader_name).observe(read_s)
        photo.reader = reader_name
        photo.model_version = self.vision.model_version
        photo.detections = observations
        purpose = PhotoPurpose.VERIFICATION if verifying else PhotoPurpose.MOVE
        start = time.perf_counter()
        match = await self.vision.match(
            rules=game.rules,
            state=game.replay(photo.ply),
            purpose=purpose,
            expected=game.moves[photo.ply].move if verifying else None,
            photo=PhotoObservations(
                photo_id=photo.id,
                observations=observations,
                image_size=(photo.width, photo.height),
            ),
            earlier=await self.waiting_photos(game=game, ply=photo.ply, purpose=purpose),
            previous=await self.previous_photo(game=game, ply=photo.ply),
        )
        match_s = time.perf_counter() - start
        photo.match = match
        self.metrics.photo_match_seconds.observe(match_s)
        self.metrics.photo_match.labels(outcome=match.outcome).inc()
        best = match.resolution.best
        candidates = match.resolution.candidates
        logger.info(
            "Read photo `%s` of game `%s`: %s.",
            photo.id,
            game.id,
            match.outcome,
            extra={
                "game_id": str(game.id),
                "photo_id": str(photo.id),
                "reader": reader_name,
                "model_version": self.vision.model_version,
                "purpose": purpose.value,
                "outcome": match.outcome,
                "read_s": round(read_s, 4),
                "match_s": round(match_s, 4),
                "tiles": match.tile_count,
                "photos": len(match.photo_ids),
                "previous_photo": match.previous_photo_id is not None,
                "top_probability": best.probability if best is not None else None,
                "margin": (
                    candidates[0].log_likelihood - candidates[1].log_likelihood
                    if len(candidates) > 1
                    else None
                ),
            },
        )

    async def waiting_photos(
        self, game: GameRow, ply: int, purpose: PhotoPurpose
    ) -> list[PhotoObservations]:
        """Find the unclear photos of a position that the next photo is resolved with.

        These are the photos for the same ply and purpose taken since the game last
        changed, whose resolution asked for another photo. A move, undo or confirmation
        changes the game, so photos from before it never count.

        Args:
            game: The game.
            ply: The ply of the move the photos show.
            purpose: What the photos are for.

        Returns:
            Their detections, oldest first.
        """
        rows = await self.session.scalars(
            select(PhotoRow)
            .where(
                PhotoRow.game_id == game.id,
                PhotoRow.ply == ply,
                PhotoRow.created_at > game.updated_at,
                PhotoRow.confirmed.is_(False),
            )
            .order_by(PhotoRow.created_at)
        )

        return [
            PhotoObservations(
                photo_id=row.id,
                observations=row.detections,
                image_size=(row.width, row.height),
            )
            for row in rows
            if row.match is not None
            and row.match.purpose is purpose
            and row.match.waiting
            and row.detections is not None
        ]

    async def previous_photo(self, game: GameRow, ply: int) -> PhotoObservations | None:
        """Find the photo of the position before a move, to recognise its tiles.

        It is the photo linked to the move before: the photo the move was read from, or
        the photo that confirmed an agent move.

        Args:
            game: The game, with its moves loaded.
            ply: The ply of the move the new photo shows.

        Returns:
            Its detections, or `None` if the move before has no read photo.
        """
        if ply == 0 or game.moves[ply - 1].photo_id is None:
            return None

        row = await self.session.get(PhotoRow, game.moves[ply - 1].photo_id)

        if row is None or row.detections is None:
            return None

        return PhotoObservations(
            photo_id=row.id,
            observations=row.detections,
            image_size=(row.width, row.height),
        )

    async def get_image(self, photo_id: uuid.UUID) -> bytes:
        """Load the stored image of a photo.

        Args:
            photo_id: The photo ID.

        Returns:
            The JPEG image.

        Raises:
            PhotoMissingError: If there is no photo with the ID or its image is gone.
        """
        photo = await self.session.get(PhotoRow, photo_id)

        if photo is None:
            raise PhotoMissingError(photo_id)

        try:
            return await self.store.get(photo.object_key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise PhotoMissingError(photo_id) from e

            raise

    async def estimate_board(self, data: bytes, rules: Rules) -> BoardEstimate:
        """Read a whole position from one photo, to start a game from it.

        The photo is not stored, since it belongs to no game yet.

        Args:
            data: The uploaded image file.
            rules: The rules the board must be valid under.

        Returns:
            The estimated board and how sure it is.

        Raises:
            VisionUnavailableError: If the app has no reader.
            PhotoTooLargeError: If the upload is larger than the limit.
            PhotoNotReadableError: If the upload is not an image.
        """
        if self.vision.reader is None:
            raise VisionUnavailableError(self.vision.error or NO_VISION_DETAIL)

        image = await self.decode(data)
        estimate = await self.vision.estimate(rules=rules, image=image)
        self.metrics.board_estimates.labels(status=estimate.status.value).inc()
        logger.info(
            "Read a board of %d tiles from a photo: %s.",
            len(estimate.tiles),
            estimate.status,
            extra={"status": estimate.status.value, "tiles": len(estimate.tiles)},
        )

        return estimate
