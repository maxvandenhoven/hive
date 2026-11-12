"""A tiny render folder for tests of the dataset export, without Blender.

`write_test_render` writes what `blender/render.py` writes for one scene: a photo, a tile
instance map and the metadata, with tiles that are fully visible, partly covered by
another tile, mostly outside the frame, and hidden under a stack.
"""

import json
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np

TEST_RENDER_SIZE: Final = (200, 100)
"""The width and height of the test renders in pixels."""


def rectangle(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    """Get a rectangle as a clockwise polygon in image coordinates.

    Args:
        x0: The left edge.
        y0: The top edge.
        x1: The right edge.
        y1: The bottom edge.

    Returns:
        The four corners, starting at the top left.
    """
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def encode_instance_map(ids: np.ndarray) -> np.ndarray:
    """Encode instance ids as the BGRA instance map that the renderer writes.

    Args:
        ids: The instance id per pixel, 0 where there is no tile.

    Returns:
        The BGRA image with blue 255 on tiles and the id in red and green.
    """
    image = np.zeros((*ids.shape, 4), dtype=np.uint8)
    image[..., 2] = ids % 256
    image[..., 1] = ids // 256
    image[..., 0] = np.where(ids > 0, 255, 0)
    image[..., 3] = 255

    return image


def render_tile(
    instance_id: int, piece: str, owner: str, polygon: list[list[float]] | None
) -> dict[str, Any]:
    """Describe a tile as in the render metadata.

    Args:
        instance_id: The instance id; ids from 5 are loose tiles.
        piece: The piece name.
        owner: The owner name.
        polygon: The projected outline of the top face, or `None` for a tile that does
            not show its face.

    Returns:
        The tile as JSON-compatible values.
    """
    return {
        "instance_id": instance_id,
        "piece": piece,
        "owner": owner,
        "coord": [instance_id, 0] if instance_id < 5 else None,
        "level": 0,
        "labeled": polygon is not None,
        "polygon": polygon,
    }


def write_test_render(renders: Path, scene_id: str) -> None:
    """Write one render with tiles that are visible, covered, cut off and unlabeled.

    The white queen is fully visible, the left 30% of the black ant is covered by the
    white beetle, 60% of the black spider is outside the frame, and the black
    grasshopper is hidden.

    Args:
        renders: The render folder, created if needed.
        scene_id: The scene id.
    """
    width, height = TEST_RENDER_SIZE
    ids = np.zeros((height, width), dtype=np.int64)
    ids[20:60, 20:60] = 1
    ids[20:60, 100:140] = 2
    ids[20:60, 80:112] = 3
    ids[20:60, 180:200] = 4

    for folder in ("images", "instances", "meta"):
        (renders / folder).mkdir(parents=True, exist_ok=True)

    photo = np.random.default_rng(0).integers(0, 255, (height, width, 3), dtype=np.uint8)
    cv2.imwrite(str(renders / "images" / f"{scene_id}.png"), photo)
    cv2.imwrite(str(renders / "instances" / f"{scene_id}.png"), encode_instance_map(ids))
    meta = {
        "scene_id": scene_id,
        "seed": 5,
        "tileset_id": "test-tiles",
        "engine": "BLENDER_EEVEE",
        "blender_version": "5.3.0",
        "image": f"images/{scene_id}.png",
        "instance_map": f"instances/{scene_id}.png",
        "width": width,
        "height": height,
        "post": {"blur_px": 0.5, "noise": 0.01, "jpeg_quality": 80},
        "camera": {"tilt_deg": 10},
        "instances": [
            render_tile(1, "queen", "white", rectangle(20, 20, 60, 60)),
            render_tile(2, "ant", "black", rectangle(100, 20, 140, 60)),
            render_tile(3, "beetle", "white", rectangle(80, 20, 112, 60)),
            render_tile(4, "spider", "black", rectangle(180, 20, 230, 60)),
            render_tile(5, "grasshopper", "black", None),
        ],
    }
    (renders / "meta" / f"{scene_id}.json").write_text(json.dumps(meta))
