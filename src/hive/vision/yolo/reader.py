"""A board reader running a YOLO model exported to ONNX, on the CPU with ONNX Runtime.

The model is trained with Ultralytics on synthetic renders (`scripts/train/train_yolo.py`)
and exported with its raw head: one output of shape `(1, 4 + classes [+ 32], anchors)`
with boxes as centre and size in input pixels, sigmoid class scores, and for segmentation
models 32 mask coefficients, plus mask prototypes of shape `(1, 32, h, w)` as a second
output. Pre- and post-processing are numpy and OpenCV only, so inference needs neither
Ultralytics nor torch.
"""

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np
import onnxruntime as ort

from hive.vision.classes import TileClass
from hive.vision.types import TileObservation

YOLO_PAD_VALUE: Final = 114
"""The grey that Ultralytics pads letterboxed images with."""

YOLO_MASK_COEFFICIENTS: Final = 32
"""The number of mask coefficients per detection of a segmentation model."""


@dataclass(frozen=True, slots=True)
class Letterbox:
    """How an image was resized and padded to the square model input.

    Attributes:
        scale: The factor the image was resized by.
        pad_x: The padding left of the resized image in input pixels.
        pad_y: The padding above the resized image in input pixels.
    """

    scale: float
    pad_x: float
    pad_y: float

    @classmethod
    def fit(cls, image: np.ndarray, size: int) -> tuple["Letterbox", np.ndarray]:
        """Resize an image to fit a square, keeping its aspect ratio, and pad it.

        Args:
            image: The BGR image.
            size: The side of the square input in pixels.

        Returns:
            The letterbox and the padded BGR image of shape `(size, size, 3)`.
        """
        height, width = image.shape[:2]
        scale = min(size / height, size / width)
        new_width, new_height = round(width * scale), round(height * scale)
        resized = cv2.resize(
            image, (new_width, new_height), interpolation=cv2.INTER_LINEAR
        )
        pad_x, pad_y = (size - new_width) / 2, (size - new_height) / 2
        top, left = round(pad_y - 0.1), round(pad_x - 0.1)
        padded = cv2.copyMakeBorder(
            resized,
            top,
            size - new_height - top,
            left,
            size - new_width - left,
            cv2.BORDER_CONSTANT,
            value=(YOLO_PAD_VALUE,) * 3,
        )

        return cls(scale=scale, pad_x=left, pad_y=top), padded

    def to_image(self, points: np.ndarray) -> np.ndarray:
        """Map points from input pixels back to image pixels.

        Args:
            points: An array whose last axis holds `x, y` pairs, for example boxes as
                `(n, 4)` with `x0, y0, x1, y1`.

        Returns:
            The points in image pixels, with the same shape.
        """
        offset = np.tile([self.pad_x, self.pad_y], points.shape[-1] // 2)

        return (points - offset) / self.scale


def non_max_suppression(
    boxes: np.ndarray, scores: np.ndarray, iou_threshold: float
) -> np.ndarray:
    """Keep the best boxes and drop the boxes that overlap a better one too much.

    Args:
        boxes: The boxes as an `(n, 4)` array of `x0, y0, x1, y1`.
        scores: The scores as an `(n,)` array.
        iou_threshold: The intersection over union above which a box is dropped.

    Returns:
        The indices of the kept boxes, best first.
    """
    order = np.argsort(-scores)
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    keep: list[int] = []

    while order.size > 0:
        best = order[0]
        keep.append(int(best))
        rest = order[1:]
        x0 = np.maximum(boxes[best, 0], boxes[rest, 0])
        y0 = np.maximum(boxes[best, 1], boxes[rest, 1])
        x1 = np.minimum(boxes[best, 2], boxes[rest, 2])
        y1 = np.minimum(boxes[best, 3], boxes[rest, 3])
        intersection = np.clip(x1 - x0, 0, None) * np.clip(y1 - y0, 0, None)
        union = areas[best] + areas[rest] - intersection
        order = rest[intersection / np.maximum(union, 1e-9) <= iou_threshold]

    return np.asarray(keep, dtype=np.int64)


class YoloReader:
    """Reads tile faces with a YOLO detection or segmentation model in ONNX format.

    Attributes:
        name: The reader name, `yolo`.
        session: The ONNX Runtime session.
        input_name: The name of the image input.
        input_size: The side of the square model input in pixels.
        score_threshold: The lowest class score that counts as a detection.
        iou_threshold: The overlap above which the weaker of two detections is dropped.
        segment: Whether the model predicts masks.
    """

    name = "yolo"

    def __init__(
        self, session: Any, score_threshold: float = 0.35, iou_threshold: float = 0.5
    ) -> None:
        """Wrap an ONNX Runtime session of a model.

        Args:
            session: The `onnxruntime.InferenceSession`, or an object with the same
                `get_inputs`, `get_outputs`, `get_modelmeta` and `run` methods.
            score_threshold: The lowest class score that counts as a detection.
            iou_threshold: The overlap above which the weaker of two detections is
                dropped.

        Raises:
            ValueError: If the model's class names do not match the tile classes.
        """
        self.session = session
        model_input = session.get_inputs()[0]
        self.input_name: str = model_input.name
        self.input_size: int = int(model_input.shape[2])
        self.score_threshold = score_threshold
        self.iou_threshold = iou_threshold
        self.segment = len(session.get_outputs()) > 1
        metadata = session.get_modelmeta().custom_metadata_map

        if "names" in metadata:
            names = ast.literal_eval(metadata["names"])
            expected = {tile_class.id: tile_class.name for tile_class in TileClass.all()}

            if names != expected:
                msg = f"The model classes {names} are not the tile classes {expected}."
                raise ValueError(msg)

    @classmethod
    def load(
        cls,
        model_path: Path,
        score_threshold: float = 0.35,
        iou_threshold: float = 0.5,
        threads: int | None = None,
    ) -> "YoloReader":
        """Load a model file into a CPU session.

        Args:
            model_path: The ONNX model file.
            score_threshold: The lowest class score that counts as a detection.
            iou_threshold: The overlap above which the weaker of two detections is
                dropped.
            threads: The number of CPU threads, or `None` for one per core.

        Returns:
            The reader.
        """
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads or os.cpu_count() or 1
        session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )

        return cls(
            session=session, score_threshold=score_threshold, iou_threshold=iou_threshold
        )

    def read(self, image: np.ndarray) -> list[TileObservation]:
        """Find the tile faces in a photo.

        Args:
            image: The photo as a BGR image.

        Returns:
            The observed tile faces, best first.
        """
        letterbox, padded = Letterbox.fit(image=image, size=self.input_size)
        tensor = padded[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255
        outputs = self.session.run(None, {self.input_name: tensor})

        return self.decode(outputs=outputs, letterbox=letterbox, image_shape=image.shape)

    def decode(
        self, outputs: list[Any], letterbox: Letterbox, image_shape: tuple[int, ...]
    ) -> list[TileObservation]:
        """Turn raw model outputs into observations in image pixels.

        Args:
            outputs: The model outputs: predictions of shape `(1, channels, anchors)`
                and, for segmentation models, mask prototypes.
            letterbox: How the image was fitted to the input.
            image_shape: The shape of the original image.

        Returns:
            The observations after thresholding and non-maximum suppression, best first.
        """
        class_count = len(TileClass.all())
        predictions = np.asarray(outputs[0])[0].T
        scores = predictions[:, 4 : 4 + class_count]
        class_ids = scores.argmax(axis=1)
        best_scores = scores[np.arange(len(scores)), class_ids]
        candidates = best_scores >= self.score_threshold
        predictions = predictions[candidates]
        scores = scores[candidates]
        class_ids = class_ids[candidates]
        best_scores = best_scores[candidates]

        centers, sizes = predictions[:, 0:2], predictions[:, 2:4]
        boxes = np.concatenate([centers - sizes / 2, centers + sizes / 2], axis=1)
        # Tiles never overlap, so suppression runs across classes: two classes on one
        # tile are one tile with an uncertain class.
        keep = non_max_suppression(
            boxes=boxes, scores=best_scores, iou_threshold=self.iou_threshold
        )
        height, width = image_shape[:2]
        image_boxes = letterbox.to_image(boxes[keep])
        image_boxes[:, 0::2] = image_boxes[:, 0::2].clip(0, width)
        image_boxes[:, 1::2] = image_boxes[:, 1::2].clip(0, height)
        polygons: list[list[tuple[float, float]] | None] = [None] * len(keep)
        mask_centers: list[tuple[float, float] | None] = [None] * len(keep)

        if self.segment and len(keep) > 0:
            coefficients = predictions[keep, 4 + class_count :]
            polygons, mask_centers = self.decode_masks(
                coefficients=coefficients,
                prototypes=np.asarray(outputs[1])[0],
                input_boxes=boxes[keep],
                letterbox=letterbox,
                image_shape=image_shape,
            )

        observations = []

        for index, box in enumerate(image_boxes):
            tile_class = TileClass.from_id(int(class_ids[keep[index]]))
            x0, y0, x1, y1 = (float(value) for value in box)
            center = mask_centers[index] or ((x0 + x1) / 2, (y0 + y1) / 2)
            observations.append(
                TileObservation(
                    center=center,
                    box=(x0, y0, x1, y1),
                    polygon=polygons[index],
                    piece_type=tile_class.piece_type,
                    owner=tile_class.owner,
                    score=float(best_scores[keep[index]]),
                    class_scores=tuple(float(value) for value in scores[keep[index]]),
                )
            )

        return observations

    def decode_masks(
        self,
        coefficients: np.ndarray,
        prototypes: np.ndarray,
        input_boxes: np.ndarray,
        letterbox: Letterbox,
        image_shape: tuple[int, ...],
    ) -> tuple[list[list[tuple[float, float]] | None], list[tuple[float, float] | None]]:
        """Combine mask prototypes into one outline and centre per detection.

        Args:
            coefficients: The mask coefficients as an `(n, 32)` array.
            prototypes: The mask prototypes as a `(32, h, w)` array.
            input_boxes: The detection boxes in input pixels, which crop the masks.
            letterbox: How the image was fitted to the input.
            image_shape: The shape of the original image.

        Returns:
            The outline and the mask centroid per detection in image pixels, or `None`
            where the mask is empty.
        """
        channels, mask_height, mask_width = prototypes.shape
        logits = coefficients @ prototypes.reshape(channels, -1)
        masks = 1 / (1 + np.exp(-logits.reshape(-1, mask_height, mask_width)))
        ratio = mask_width / self.input_size
        polygons: list[list[tuple[float, float]] | None] = []
        centers: list[tuple[float, float] | None] = []

        for mask, box in zip(masks, input_boxes, strict=True):
            x0, y0, x1, y1 = (box * ratio).round().astype(int)
            cropped = np.zeros_like(mask, dtype=np.uint8)
            region = mask[max(y0, 0) : max(y1, 0), max(x0, 0) : max(x1, 0)] > 0.5
            cropped[max(y0, 0) : max(y1, 0), max(x0, 0) : max(x1, 0)] = region
            contours, _ = cv2.findContours(
                cropped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            if not contours:
                polygons.append(None)
                centers.append(None)
                continue

            contour = max(contours, key=cv2.contourArea)
            moments = cv2.moments(contour)
            # Contour points are pixel corners of the prototype grid; pixel centres are
            # half a cell further, and one cell is `1 / ratio` input pixels.
            points = (contour.reshape(-1, 2).astype(np.float64) + 0.5) / ratio
            image_points = letterbox.to_image(points)
            height, width = image_shape[:2]
            image_points[:, 0] = image_points[:, 0].clip(0, width)
            image_points[:, 1] = image_points[:, 1].clip(0, height)
            polygons.append([(float(x), float(y)) for x, y in image_points])

            if moments["m00"] > 0:
                centroid = np.array(
                    [
                        moments["m10"] / moments["m00"] + 0.5,
                        moments["m01"] / moments["m00"] + 0.5,
                    ]
                )
                x, y = letterbox.to_image(centroid / ratio)
                centers.append((float(x), float(y)))
            else:
                centers.append(None)

        return polygons, centers
