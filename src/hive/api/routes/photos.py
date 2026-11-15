"""Routes that serve stored photos and read a whole board from one photo."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile

from hive.api.dependencies import PhotoServiceDependency
from hive.api.errors import (
    PhotoMissingError,
    PhotoNotReadableError,
    PhotoTooLargeError,
    VisionUnavailableError,
    error_responses,
)
from hive.api.routes import API_PREFIX
from hive.api.vision import PHOTO_CONTENT_TYPE
from hive.engine.rules import Rules
from hive.vision.estimate import BoardEstimate

router = APIRouter(prefix=API_PREFIX, tags=["photos"])

PHOTO_CACHE_CONTROL = "private, max-age=31536000, immutable"
"""Stored photos never change, so browsers keep them."""


@router.get(
    "/photos/{photo_id}/image",
    response_class=Response,
    description="Get the stored image of a photo, upright, as a JPEG.",
    responses={
        200: {
            "content": {PHOTO_CONTENT_TYPE: {"schema": {"type": "string"}}},
            "description": "The JPEG image.",
        },
        **error_responses(PhotoMissingError),
    },
)
async def read_photo_image(
    photo_id: uuid.UUID, photos: PhotoServiceDependency
) -> Response:
    """Get the stored image of a photo.

    Args:
        photo_id: The photo ID.
        photos: The photo service.

    Returns:
        The JPEG image, which browsers may cache.

    Raises:
        PhotoMissingError: If there is no photo with the ID or its image is gone.
    """
    content = await photos.get_image(photo_id)

    return Response(
        content=content,
        media_type=PHOTO_CONTENT_TYPE,
        headers={"Cache-Control": PHOTO_CACHE_CONTROL},
    )


@router.post(
    "/board-estimates",
    description="Read a whole position from one photo of a physical board, without the "
    "history of a game, to start a game from it with the default rules. Says how sure "
    "the reading is: `confident`, `uncertain` (check the tiles before using it) or "
    "`failed` (no valid board, for example with stacks). The photo is not stored.",
    responses=error_responses(
        VisionUnavailableError, PhotoTooLargeError, PhotoNotReadableError
    ),
)
async def estimate_board(
    photos: PhotoServiceDependency,
    image: Annotated[UploadFile, File(description="The photo, a JPEG or PNG image.")],
) -> BoardEstimate:
    """Read a whole position from one photo of a physical board.

    Args:
        photos: The photo service.
        image: The uploaded photo.

    Returns:
        The estimated board and how sure it is.

    Raises:
        VisionUnavailableError: If the app has no board reader.
        PhotoTooLargeError: If the upload is larger than the limit.
        PhotoNotReadableError: If the upload is not an image.
    """
    data = await image.read(photos.settings.photo_max_bytes + 1)

    return await photos.estimate_board(data=data, rules=Rules())
