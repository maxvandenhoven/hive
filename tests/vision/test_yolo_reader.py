from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from hive.engine.state import PieceType, Player
from hive.vision.classes import TileClass
from hive.vision.yolo.reader import Letterbox, YoloReader, non_max_suppression

INPUT_SIZE = 64
CLASS_COUNT = 10


@dataclass
class FakeNode:
    name: str
    shape: list[int]


@dataclass
class FakeSession:
    """An ONNX Runtime session that returns fixed outputs and records its inputs."""

    outputs: list[np.ndarray]
    metadata: dict[str, str] = field(default_factory=dict)
    feeds: dict[str, np.ndarray] = field(default_factory=dict)

    def get_inputs(self) -> list[FakeNode]:
        return [FakeNode(name="images", shape=[1, 3, INPUT_SIZE, INPUT_SIZE])]

    def get_outputs(self) -> list[FakeNode]:
        return [
            FakeNode(name=f"output{index}", shape=list(output.shape))
            for index, output in enumerate(self.outputs)
        ]

    def get_modelmeta(self) -> SimpleNamespace:
        return SimpleNamespace(custom_metadata_map=self.metadata)

    def run(self, names: list[str] | None, feeds: dict[str, np.ndarray]) -> list[Any]:
        self.feeds = feeds

        return self.outputs


def predictions(
    anchors: list[tuple[tuple[float, float, float, float], int, float]],
) -> np.ndarray:
    """Build a raw detection output from `(cx, cy, w, h), class id, score` anchors."""
    output = np.zeros((1, 4 + CLASS_COUNT, len(anchors)), dtype=np.float32)

    for index, (box, class_id, score) in enumerate(anchors):
        output[0, 0:4, index] = box
        output[0, 4 + class_id, index] = score

    return output


def test_letterbox_pads_and_maps_back() -> None:
    image = np.zeros((50, 100, 3), dtype=np.uint8)
    letterbox, padded = Letterbox.fit(image=image, size=INPUT_SIZE)

    assert padded.shape == (INPUT_SIZE, INPUT_SIZE, 3)
    assert letterbox.scale == pytest.approx(0.64)
    assert (letterbox.pad_x, letterbox.pad_y) == (0, 16)
    assert padded[0, 0].tolist() == [114, 114, 114]
    assert padded[INPUT_SIZE // 2, INPUT_SIZE // 2].tolist() == [0, 0, 0]

    points = np.array([[0.0, 16.0, 64.0, 48.0]])

    assert letterbox.to_image(points) == pytest.approx(
        np.array([[0.0, 0.0, 100.0, 50.0]])
    )


def test_non_max_suppression_drops_overlaps() -> None:
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [20, 20, 30, 30]], dtype=np.float64)
    scores = np.array([0.5, 0.9, 0.7])

    assert non_max_suppression(
        boxes=boxes, scores=scores, iou_threshold=0.5
    ).tolist() == [1, 2]
    assert non_max_suppression(
        boxes=boxes, scores=scores, iou_threshold=0.9
    ).tolist() == [1, 2, 0]


def test_read_detects_tiles_across_classes() -> None:
    output = predictions(
        [
            ((32.0, 32.0, 10.0, 10.0), 2, 0.9),
            ((33.0, 32.0, 10.0, 10.0), 7, 0.6),
            ((10.0, 50.0, 8.0, 8.0), 9, 0.2),
            ((50.0, 20.0, 8.0, 8.0), 9, 0.8),
        ]
    )
    session = FakeSession(outputs=[output])
    reader = YoloReader(session=session, score_threshold=0.35)
    # A 128 x 64 image is halved and padded by 16 rows above.
    observations = reader.read(np.zeros((64, 128, 3), dtype=np.uint8))

    assert [(o.piece_type, o.owner) for o in observations] == [
        (PieceType.GRASSHOPPER, Player.WHITE),
        (PieceType.ANT, Player.BLACK),
    ]
    assert observations[0].center == pytest.approx((64.0, 32.0))
    assert observations[0].box == pytest.approx((54.0, 22.0, 74.0, 42.0))
    assert observations[0].score == pytest.approx(0.9)
    assert observations[0].polygon is None
    assert observations[1].tile_class == TileClass.from_id(9)


def test_read_feeds_normalised_rgb() -> None:
    session = FakeSession(outputs=[predictions([])])
    reader = YoloReader(session=session)
    image = np.zeros((INPUT_SIZE, INPUT_SIZE, 3), dtype=np.uint8)
    image[..., 0] = 255

    assert reader.read(image) == []

    tensor = session.feeds["images"]

    assert tensor.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)
    assert tensor.dtype == np.float32
    assert tensor[0, 2].min() == 1.0
    assert tensor[0, 0].max() == 0.0


def test_read_decodes_masks() -> None:
    output = np.zeros((1, 4 + CLASS_COUNT + 32, 1), dtype=np.float32)
    output[0, 0:4, 0] = (32.0, 32.0, 36.0, 36.0)
    output[0, 4 + 5, 0] = 0.95
    output[0, 4 + CLASS_COUNT, 0] = 1.0
    # One prototype is positive on a square of mask cells 4 to 11, which is input
    # pixels 16 to 48 at a quarter of the input resolution.
    prototypes = np.full((1, 32, 16, 16), -10.0, dtype=np.float32)
    prototypes[0, 0, 4:12, 4:12] = 10.0
    reader = YoloReader(session=FakeSession(outputs=[output, prototypes]))
    observations = reader.read(np.zeros((INPUT_SIZE, INPUT_SIZE, 3), dtype=np.uint8))

    assert reader.segment
    assert len(observations) == 1
    assert observations[0].tile_class.name == "black_queen"
    assert observations[0].center == pytest.approx((32.0, 32.0), abs=2.5)

    polygon = np.asarray(observations[0].polygon)

    assert polygon.min(axis=0) == pytest.approx((18.0, 18.0), abs=2.5)
    assert polygon.max(axis=0) == pytest.approx((46.0, 46.0), abs=2.5)


def test_rejects_models_with_other_classes() -> None:
    session = FakeSession(outputs=[predictions([])], metadata={"names": "{0: 'person'}"})

    with pytest.raises(ValueError, match="not the tile classes"):
        YoloReader(session=session)


def test_accepts_models_with_the_tile_classes() -> None:
    names = {tile_class.id: tile_class.name for tile_class in TileClass.all()}
    session = FakeSession(outputs=[predictions([])], metadata={"names": str(names)})

    assert YoloReader(session=session).input_size == INPUT_SIZE
