import io
import json
import uuid
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from hive.api.vision import (
    BoardVision,
    PhotoImage,
    PhotoImageError,
    PhotoObservations,
    PhotoPurpose,
)
from hive.engine.rules import Rules
from hive.vision.resolver import ResolutionStatus

EXIF_ORIENTATION = 0x0112
"""The EXIF tag of the orientation of a photo."""


def phone_jpeg(width: int, height: int, orientation: int) -> bytes:
    """Encode an image as a JPEG with an EXIF orientation, as phone cameras store them.

    The left half is black and the right half white, so turning the image shows.
    """
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    pixels[:, width // 2 :] = 255
    exif = Image.Exif()
    exif[EXIF_ORIENTATION] = orientation
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="JPEG", exif=exif)

    return buffer.getvalue()


class TestPhotoImage:
    def test_turns_phone_photos_upright(self) -> None:
        # Orientation 6: the camera was turned, so the image is shown turned clockwise.
        image = PhotoImage.decode(data=phone_jpeg(80, 40, orientation=6), max_side=1000)
        stored = Image.open(io.BytesIO(image.jpeg))

        assert (image.width, image.height) == (40, 80)
        assert stored.size == (40, 80)
        assert EXIF_ORIENTATION not in stored.getexif()
        # The white right half is at the bottom after turning clockwise.
        assert image.pixels[70, 20].mean() > 200
        assert image.pixels[10, 20].mean() < 50

    def test_scales_down_to_the_longest_side(self) -> None:
        image = PhotoImage.decode(data=phone_jpeg(800, 600, orientation=1), max_side=400)

        assert (image.width, image.height) == (400, 300)

    def test_rejects_other_files(self) -> None:
        with pytest.raises(PhotoImageError, match="not an image"):
            PhotoImage.decode(data=b"GIF89a broken", max_side=400)


class TestBoardVision:
    def test_without_a_model_photos_are_not_read(self) -> None:
        vision = BoardVision.load(model_path=None, score_threshold=0.25)

        assert (vision.reader, vision.configured, vision.error) == (None, False, None)

    def test_a_missing_model_is_reported(self, tmp_path: Path) -> None:
        vision = BoardVision.load(
            model_path=tmp_path / "model.onnx", score_threshold=0.25
        )

        assert vision.reader is None
        assert vision.configured
        assert vision.error is not None
        assert "could not be loaded" in vision.error

    def test_model_version_from_its_metadata(self, tmp_path: Path) -> None:
        onnx = pytest.importorskip("onnx")
        model_path = tmp_path / "model.onnx"
        graph = onnx.helper.make_graph(
            [onnx.helper.make_node("Identity", ["images"], ["output0"])],
            "fake",
            [onnx.helper.make_tensor_value_info("images", 1, [1, 3, 64, 64])],
            [onnx.helper.make_tensor_value_info("output0", 1, [1, 3, 64, 64])],
        )
        model = onnx.helper.make_model(
            graph, opset_imports=[onnx.helper.make_opsetid("", 13)], ir_version=9
        )
        onnx.save(model, model_path)
        (tmp_path / "model.json").write_text(
            json.dumps({"name": "hive-yolo", "version": "v9"})
        )
        vision = BoardVision.load(model_path=model_path, score_threshold=0.25)

        assert vision.reader is not None
        assert vision.model_version == "hive-yolo/v9"
        assert vision.error is None

    def test_a_photo_without_tiles_fails(self) -> None:
        vision = BoardVision(reader=None)
        rules = Rules()
        photo = PhotoObservations(
            photo_id=uuid.uuid4(), observations=[], image_size=(64, 48)
        )
        match = vision.match_blocking(
            rules=rules,
            state=rules.create_initial_state(),
            purpose=PhotoPurpose.VERIFICATION,
            expected=None,
            photo=photo,
            earlier=[],
            previous=None,
        )

        assert match.resolution.status is ResolutionStatus.FAILED
        assert match.verification is not None
        assert match.outcome == "unclear"
        assert match.photo_ids == [photo.photo_id]
        assert not match.waiting
