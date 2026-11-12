"""Dataset export: turn Blender renders into a YOLO dataset with labels and a manifest.

The renderer writes a photo, a tile instance map and metadata per scene (see
`blender/render.py`). The export computes the labels from them and applies the camera
effects of the scene:

- The label of a tile is the visible part of its top face: the projected outline of the
  face, minus the pixels where other tiles cover it or it leaves the frame. Tiles with
  `min_visible` or less of their face visible are not labeled.
- `segment` labels are the polygon of the visible face (`class x1 y1 x2 y2 ...`), which
  Ultralytics also trains detection models on; `detect` labels are boxes
  (`class cx cy w h`). Coordinates are normalised to the image size.
- Blur, noise and JPEG compression come from the scene's `post` effects.

The dataset has the Ultralytics layout (`images/{train,val}`, `labels/{train,val}`,
`data.yaml`), plus `meta.jsonl` with the labels and board of every image and a
`manifest.json` describing the dataset. Needs the `vision` extra (numpy and OpenCV).
"""

import hashlib
import json
import multiprocessing
import random
import subprocess
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, Literal

import cv2
import numpy as np
from pydantic import ConfigDict, Field

from hive.data.scenes import ScenePost
from hive.engine.codec import JsonCodec
from hive.engine.grid import Coordinate
from hive.engine.state import PieceType, Player
from hive.vision.classes import TileClass

DATASET_MANIFEST_VERSION: Final = 1
"""The version of `manifest.json` and `meta.jsonl`, raised on incompatible changes."""

type DatasetTask = Literal["segment", "detect"]
"""The label format: polygons for segmentation, or boxes for detection."""

type DatasetSplit = Literal["train", "val"]
"""The part of the dataset an image belongs to."""


@dataclass(frozen=True, slots=True)
class RenderedTile(JsonCodec):
    """A tile in the metadata of a render.

    Attributes:
        instance_id: The id of the tile in the instance map.
        piece_type: The insect on the tile.
        owner: The player the tile belongs to.
        coord: The axial coordinate on the board, or `None` for a loose tile.
        level: The height in the stack, 0 for the bottom tile.
        labeled: Whether the tile shows its face.
        polygon: The projected outline of the top face in pixels, for labeled tiles.
    """

    instance_id: int
    piece_type: Annotated[PieceType, Field(alias="piece")]
    owner: Player
    coord: Coordinate | None
    level: int
    labeled: bool
    polygon: list[tuple[float, float]] | None = None


@dataclass(frozen=True, slots=True)
class TileLabel(JsonCodec):
    """The label of one visible tile face.

    Attributes:
        class_id: The detection class id (see `TileClass`).
        coord: The axial coordinate on the board, or `None` for a loose tile.
        visible: The visible fraction of the face.
        box: The bounding box `(x0, y0, x1, y1)` of the visible face in pixels.
        polygon: The outline of the visible face in pixels.
    """

    class_id: int
    coord: Coordinate | None
    visible: float
    box: tuple[float, float, float, float]
    polygon: list[tuple[float, float]]

    def yolo_line(self, task: DatasetTask, width: int, height: int) -> str:
        """Format the label as a line of a YOLO label file.

        Args:
            task: Whether to write the polygon (`segment`) or the box (`detect`).
            width: The image width in pixels.
            height: The image height in pixels.

        Returns:
            The class id and the normalised coordinates, separated by spaces.
        """
        if task == "segment":
            values = [
                value
                for x, y in self.polygon
                for value in (
                    min(max(x / width, 0.0), 1.0),
                    min(max(y / height, 0.0), 1.0),
                )
            ]
        else:
            x0, y0, x1, y1 = self.box
            values = [
                (x0 + x1) / 2 / width,
                (y0 + y1) / 2 / height,
                (x1 - x0) / width,
                (y1 - y0) / height,
            ]

        return " ".join([str(self.class_id), *(f"{value:.5f}" for value in values)])


@dataclass(frozen=True, slots=True)
class RenderMeta(JsonCodec):
    """The metadata the renderer writes for one scene.

    Only the fields the export reads are declared; the others are kept in the raw JSON
    and copied to `meta.jsonl`.

    Attributes:
        scene_id: The scene id.
        seed: The scene seed.
        tileset_id: The tileset the scene was rendered with.
        engine: The Blender render engine.
        blender_version: The Blender version.
        image: The photo, relative to the render folder.
        instance_map: The tile instance map, relative to the render folder.
        width: The image width in pixels.
        height: The image height in pixels.
        post: The camera effects to apply.
        instances: Every tile of the scene.
    """

    __pydantic_config__ = ConfigDict(extra="ignore", serialize_by_alias=True)

    scene_id: str
    seed: int
    tileset_id: str
    engine: str
    blender_version: str
    image: str
    instance_map: str
    width: int
    height: int
    post: ScenePost
    instances: list[RenderedTile]

    def labels(self, instance_ids: np.ndarray, min_visible: float) -> list[TileLabel]:
        """Compute the labels of the visible tile faces.

        Args:
            instance_ids: The decoded instance map, with the tile instance id per pixel
                and 0 elsewhere.
            min_visible: The visible fraction of a face at or below which it is not
                labeled.

        Returns:
            The labels, in instance order.
        """
        labels: list[TileLabel] = []

        for tile in self.instances:
            if not tile.labeled or tile.polygon is None:
                continue

            outline = np.asarray(tile.polygon, dtype=np.float64)
            area = polygon_area(outline)

            if area < 1.0:
                continue

            low = np.floor(outline.min(axis=0))
            high = np.ceil(outline.max(axis=0))
            x0, y0 = max(int(low[0]), 0), max(int(low[1]), 0)
            x1, y1 = min(int(high[0]), self.width - 1), min(int(high[1]), self.height - 1)

            if x1 <= x0 or y1 <= y0:
                continue

            face = np.zeros((y1 - y0 + 1, x1 - x0 + 1), dtype=np.uint8)
            # Sub-pixel vertices: OpenCV reads fixed-point coordinates with 4 fraction
            # bits when `shift=4`.
            points = np.round((outline - [x0, y0]) * 16).astype(np.int32)
            cv2.fillPoly(face, [points], color=1, lineType=cv2.LINE_8, shift=4)
            own = instance_ids[y0 : y1 + 1, x0 : x1 + 1] == tile.instance_id
            visible = (face.astype(bool) & own).astype(np.uint8)
            visible_fraction = float(visible.sum()) / area

            if visible_fraction <= min_visible:
                continue

            contours, _ = cv2.findContours(
                visible, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            contour = max(contours, key=cv2.contourArea)
            contour = cv2.approxPolyDP(contour, epsilon=0.7, closed=True)
            box_x, box_y, box_w, box_h = cv2.boundingRect(visible)
            labels.append(
                TileLabel(
                    class_id=TileClass(piece_type=tile.piece_type, owner=tile.owner).id,
                    coord=tile.coord,
                    visible=round(min(visible_fraction, 1.0), 4),
                    box=(x0 + box_x, y0 + box_y, x0 + box_x + box_w, y0 + box_y + box_h),
                    polygon=[
                        (float(x0 + x + 0.5), float(y0 + y + 0.5))
                        for x, y in contour.reshape(-1, 2)
                    ],
                )
            )

        return labels


def polygon_area(points: np.ndarray) -> float:
    """Get the area of a simple polygon with the shoelace formula.

    Args:
        points: The corners as an `(n, 2)` array, in order.

    Returns:
        The absolute area.
    """
    x, y = points[:, 0], points[:, 1]

    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2)


def read_image(path: Path, flags: int) -> np.ndarray:
    """Read an image with OpenCV, failing loudly instead of returning `None`.

    Args:
        path: The image file.
        flags: The OpenCV read flags, for example `cv2.IMREAD_COLOR`.

    Returns:
        The image.

    Raises:
        FileNotFoundError: If the file is missing or not a readable image.
    """
    image = cv2.imread(str(path), flags)

    if image is None:
        msg = f"Cannot read the image `{path}`."
        raise FileNotFoundError(msg)

    return image


def decode_instance_map(image: np.ndarray) -> np.ndarray:
    """Decode a tile instance map read by OpenCV.

    Args:
        image: The BGRA image: tile pixels have blue 255 and the id in red (low byte)
            and green (high byte).

    Returns:
        The instance id per pixel, 0 where there is no tile.
    """
    ids = image[..., 2].astype(np.int32) + 256 * image[..., 1].astype(np.int32)

    return np.where(image[..., 0] == 255, ids, 0)


def apply_post_effects(image: np.ndarray, post: ScenePost, seed: int) -> np.ndarray:
    """Blur and add sensor noise to an image, as a phone camera would.

    JPEG compression is applied when the image is written.

    Args:
        image: The BGR image.
        post: The effects of the scene.
        seed: The seed of the noise.

    Returns:
        The processed image.
    """
    if post.blur_px > 0.05:
        image = cv2.GaussianBlur(image, ksize=(0, 0), sigmaX=post.blur_px)

    if post.noise > 0:
        rng = np.random.default_rng(seed)
        # Mostly luminance noise with a little colour noise, as in phone sensors.
        luminance = rng.normal(0.0, post.noise * 255, image.shape[:2])[..., None]
        colour = rng.normal(0.0, post.noise * 80, image.shape)
        image = np.clip(image + luminance + colour, 0, 255).astype(np.uint8)

    return image


def dataset_split(scene_id: str, val_fraction: float) -> DatasetSplit:
    """Assign a scene to the training or validation split by hashing its id.

    The split of a scene does not change when scenes are added to a batch.

    Args:
        scene_id: The scene id.
        val_fraction: The fraction of scenes in the validation split.

    Returns:
        `val` or `train`.
    """
    digest = hashlib.sha256(scene_id.encode()).digest()

    return "val" if int.from_bytes(digest[:4]) / 2**32 < val_fraction else "train"


@dataclass(frozen=True, slots=True)
class DatasetImage(JsonCodec):
    """One exported image and its labels, a line of `meta.jsonl`.

    Attributes:
        scene_id: The scene id.
        split: The split of the image.
        image: The image path relative to the dataset.
        tileset_id: The tileset the image was rendered with.
        engine: The Blender render engine.
        blender_version: The Blender version.
        width: The image width in pixels.
        height: The image height in pixels.
        labels: The labels of the visible tile faces.
        render: The full metadata of the render, including the board.
    """

    scene_id: str
    split: DatasetSplit
    image: str
    tileset_id: str
    engine: str
    blender_version: str
    width: int
    height: int
    labels: list[TileLabel]
    render: dict[str, object]


@dataclass(frozen=True, slots=True)
class DatasetManifest(JsonCodec):
    """The description of a dataset, written to its `manifest.json`.

    Attributes:
        manifest_version: The version of the manifest and `meta.jsonl`.
        name: The dataset name.
        version: The dataset version.
        task: The label format.
        created_at: When the dataset was exported, in ISO 8601 format.
        renderer_commit: The Git commit of the working tree, or `None` outside Git.
        scenes: The number of scenes.
        scene_ids: The first and the last scene id.
        images: The number of images per split.
        labels: The number of labels.
        classes: The number of labels per class name, in class id order.
        tilesets: The number of images per tileset.
        engines: The number of images per render engine.
        blender_versions: The Blender versions the images were rendered with.
        min_visible: The visible fraction of a face at or below which it is not labeled.
    """

    manifest_version: int
    name: str
    version: str
    task: DatasetTask
    created_at: str
    renderer_commit: str | None
    scenes: int
    scene_ids: tuple[str, str]
    images: dict[DatasetSplit, int]
    labels: int
    classes: dict[str, int]
    tilesets: dict[str, int]
    engines: dict[str, int]
    blender_versions: list[str]
    min_visible: float


@dataclass(frozen=True, slots=True)
class DatasetExport:
    """Settings of a dataset export.

    Attributes:
        renders: The render folder written by `blender/render.py`.
        out: The dataset folder, which must not exist yet.
        name: The dataset name.
        version: The dataset version.
        task: The label format.
        val_fraction: The fraction of scenes in the validation split.
        min_visible: The visible fraction of a face at or below which it is not labeled.
    """

    renders: Path
    out: Path
    name: str
    version: str
    task: DatasetTask = "segment"
    val_fraction: float = 0.1
    min_visible: float = 0.5

    @property
    def class_names(self) -> list[str]:
        """The class names in class id order."""
        return [tile_class.name for tile_class in TileClass.all()]

    def run(self, jobs: int) -> DatasetManifest:
        """Export every render with metadata into the dataset folder.

        Args:
            jobs: The number of worker processes.

        Returns:
            The manifest, which is also written to `manifest.json`.

        Raises:
            FileExistsError: If the dataset folder already exists, since versions are
                immutable.
            FileNotFoundError: If the render folder holds no metadata.
        """
        if self.out.exists():
            msg = f"The dataset `{self.out}` already exists; versions are immutable."
            raise FileExistsError(msg)

        meta_paths = sorted((self.renders / "meta").glob("*.json"))

        if not meta_paths:
            msg = f"No renders with metadata in `{self.renders}`."
            raise FileNotFoundError(msg)

        for split in ("train", "val"):
            (self.out / "images" / split).mkdir(parents=True)
            (self.out / "labels" / split).mkdir(parents=True)

        if jobs <= 1:
            images = [self.export_image(path) for path in meta_paths]
        else:
            with ProcessPoolExecutor(
                max_workers=jobs, mp_context=multiprocessing.get_context("spawn")
            ) as executor:
                images = list(executor.map(self.export_image, meta_paths, chunksize=8))

        with (self.out / "meta.jsonl").open("w") as file:
            for image in images:
                file.write(json.dumps(image.to_json()) + "\n")

        self.write_data_yaml()
        manifest = self.manifest(images)
        manifest_json = json.dumps(manifest.to_json(), indent=2)
        (self.out / "manifest.json").write_text(manifest_json + "\n")

        return manifest

    def export_image(self, meta_path: Path) -> DatasetImage:
        """Label one render, apply its camera effects and write the image and labels.

        Args:
            meta_path: The metadata file of the render.

        Returns:
            The exported image with its labels.
        """
        raw = json.loads(meta_path.read_text())
        meta = RenderMeta.from_json(raw)
        photo = read_image(path=self.renders / meta.image, flags=cv2.IMREAD_COLOR)
        instance_map = read_image(
            path=self.renders / meta.instance_map, flags=cv2.IMREAD_UNCHANGED
        )
        labels = meta.labels(
            instance_ids=decode_instance_map(instance_map), min_visible=self.min_visible
        )
        split = dataset_split(scene_id=meta.scene_id, val_fraction=self.val_fraction)
        photo = apply_post_effects(image=photo, post=meta.post, seed=meta.seed)
        image_path = f"images/{split}/{meta.scene_id}.jpg"
        cv2.imwrite(
            str(self.out / image_path),
            photo,
            [cv2.IMWRITE_JPEG_QUALITY, meta.post.jpeg_quality],
        )
        lines = [
            label.yolo_line(task=self.task, width=meta.width, height=meta.height)
            for label in labels
        ]
        label_path = self.out / "labels" / split / f"{meta.scene_id}.txt"
        label_path.write_text("".join(f"{line}\n" for line in lines))

        return DatasetImage(
            scene_id=meta.scene_id,
            split=split,
            image=image_path,
            tileset_id=meta.tileset_id,
            engine=meta.engine,
            blender_version=meta.blender_version,
            width=meta.width,
            height=meta.height,
            labels=labels,
            render=raw,
        )

    def write_data_yaml(self) -> None:
        """Write the Ultralytics dataset description with the class names in id order."""
        lines = [
            f"# {self.name} {self.version}: synthetic Hive tiles, written by "
            "`hive data export`.",
            "train: images/train",
            "val: images/val",
            "names:",
            *(f"  {index}: {name}" for index, name in enumerate(self.class_names)),
        ]
        (self.out / "data.yaml").write_text("\n".join(lines) + "\n")

    def manifest(self, images: list[DatasetImage]) -> DatasetManifest:
        """Describe the dataset: its origin and what it contains.

        Args:
            images: The exported images, at least one.

        Returns:
            The manifest.
        """
        class_counts = Counter(
            self.class_names[label.class_id] for image in images for label in image.labels
        )

        return DatasetManifest(
            manifest_version=DATASET_MANIFEST_VERSION,
            name=self.name,
            version=self.version,
            task=self.task,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            renderer_commit=git_commit(),
            scenes=len(images),
            scene_ids=(images[0].scene_id, images[-1].scene_id),
            images=dict(Counter(image.split for image in images)),
            labels=sum(len(image.labels) for image in images),
            classes={name: class_counts[name] for name in self.class_names},
            tilesets=dict(Counter(image.tileset_id for image in images)),
            engines=dict(Counter(image.engine for image in images)),
            blender_versions=sorted({image.blender_version for image in images}),
            min_visible=self.min_visible,
        )


def git_commit() -> str | None:
    """Get the commit of the working tree, to record which renderer made a dataset.

    Returns:
        The commit hash, with `-dirty` if there are uncommitted changes, or `None`
        outside a Git checkout.
    """
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None

    return f"{commit}-dirty" if dirty else commit


def draw_labels(image: np.ndarray, labels: list[TileLabel]) -> np.ndarray:
    """Draw labels onto an image for visual inspection.

    Args:
        image: The BGR image.
        labels: The labels to draw.

    Returns:
        A copy of the image with the polygons, boxes and class names drawn.
    """
    canvas = image.copy()
    palette = random.Random(0)
    colors = [
        (
            palette.randrange(60, 256),
            palette.randrange(60, 256),
            palette.randrange(60, 256),
        )
        for _ in TileClass.all()
    ]

    for label in labels:
        color = colors[label.class_id]
        points = np.round(np.asarray(label.polygon)).astype(np.int32)
        cv2.polylines(canvas, [points], isClosed=True, color=color, thickness=2)
        x0, y0, x1, y1 = (round(value) for value in label.box)
        cv2.rectangle(canvas, (x0, y0), (x1, y1), color=color, thickness=1)
        name = TileClass.from_id(label.class_id).name
        cv2.putText(
            canvas,
            name,
            (x0, max(y0 - 3, 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            color,
            1,
            cv2.LINE_AA,
        )

    return canvas
