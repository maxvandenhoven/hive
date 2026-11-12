import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from hive.data.datasets import (
    DatasetExport,
    RenderMeta,
    TileLabel,
    apply_post_effects,
    dataset_split,
    decode_instance_map,
    draw_labels,
    polygon_area,
    read_image,
)
from hive.data.scenes import ScenePost
from hive.data.testing import TEST_RENDER_SIZE, rectangle, write_test_render
from hive.vision.classes import TileClass

WIDTH, HEIGHT = TEST_RENDER_SIZE


@pytest.fixture(scope="function")
def renders(tmp_path: Path) -> Path:
    """Write a render folder with three scenes."""
    folder = tmp_path / "renders"

    for scene_id in ("000000", "000001", "000002"):
        write_test_render(renders=folder, scene_id=scene_id)

    return folder


def test_labels_keep_visible_faces_only(renders: Path) -> None:
    meta = RenderMeta.from_json(
        json.loads((renders / "meta" / "000000.json").read_text())
    )
    image = read_image(
        path=renders / "instances" / "000000.png", flags=cv2.IMREAD_UNCHANGED
    )
    labels = meta.labels(instance_ids=decode_instance_map(image), min_visible=0.5)
    by_class = {TileClass.from_id(label.class_id).name: label for label in labels}

    assert sorted(by_class) == ["black_ant", "white_beetle", "white_queen"]
    assert by_class["white_queen"].visible == pytest.approx(1.0, abs=0.03)
    assert by_class["black_ant"].visible == pytest.approx(0.7, abs=0.03)
    assert by_class["black_ant"].box == (112, 20, 140, 60)
    assert by_class["white_queen"].coord == (1, 0)
    assert by_class["white_beetle"].coord == (3, 0)


def test_labels_threshold_is_exclusive(renders: Path) -> None:
    meta = RenderMeta.from_json(
        json.loads((renders / "meta" / "000000.json").read_text())
    )
    image = read_image(
        path=renders / "instances" / "000000.png", flags=cv2.IMREAD_UNCHANGED
    )
    labels = meta.labels(instance_ids=decode_instance_map(image), min_visible=0.3)

    assert "black_spider" in {TileClass.from_id(label.class_id).name for label in labels}


def test_yolo_lines() -> None:
    label = TileLabel(
        class_id=7,
        coord=None,
        visible=1.0,
        box=(10.0, 20.0, 30.0, 60.0),
        polygon=[(10.0, 20.0), (30.0, 20.0), (30.0, 60.0), (-5.0, 60.0)],
    )

    assert label.yolo_line(task="detect", width=100, height=100) == (
        "7 0.20000 0.40000 0.20000 0.40000"
    )
    assert label.yolo_line(task="segment", width=100, height=100) == (
        "7 0.10000 0.20000 0.30000 0.20000 0.30000 0.60000 0.00000 0.60000"
    )


def test_export_writes_an_ultralytics_dataset(renders: Path, tmp_path: Path) -> None:
    out = tmp_path / "synth-v001"
    export = DatasetExport(
        renders=renders, out=out, name="synth", version="v001", val_fraction=0.5
    )
    manifest = export.run(jobs=1)
    lines = [json.loads(line) for line in (out / "meta.jsonl").read_text().splitlines()]

    assert manifest.labels == 9
    assert manifest.classes["white_queen"] == 3
    assert manifest.classes["black_spider"] == 0
    assert manifest.tilesets == {"test-tiles": 3}
    assert sum(manifest.images.values()) == 3
    assert manifest.scene_ids == ("000000", "000002")
    assert json.loads((out / "manifest.json").read_text())["labels"] == 9
    assert [line["scene_id"] for line in lines] == ["000000", "000001", "000002"]

    for line in lines:
        split = line["split"]
        image = read_image(path=out / line["image"], flags=cv2.IMREAD_COLOR)
        labels = (out / "labels" / split / f"{line['scene_id']}.txt").read_text()

        assert line["image"] == f"images/{split}/{line['scene_id']}.jpg"
        assert image.shape == (HEIGHT, WIDTH, 3)
        assert len(labels.splitlines()) == 3
        assert all(len(row.split()) % 2 == 1 for row in labels.splitlines())

    data_yaml = (out / "data.yaml").read_text()

    assert "train: images/train" in data_yaml
    assert "  0: white_queen" in data_yaml
    assert "  9: black_ant" in data_yaml


def test_export_detect_task_writes_boxes(renders: Path, tmp_path: Path) -> None:
    out = tmp_path / "boxes"
    DatasetExport(renders=renders, out=out, name="b", version="1", task="detect").run(
        jobs=2
    )
    rows = [
        row.split()
        for path in sorted(out.glob("labels/*/*.txt"))
        for row in path.read_text().splitlines()
    ]

    assert len(rows) == 9
    assert all(len(row) == 5 for row in rows)


def test_export_refuses_existing_versions(renders: Path, tmp_path: Path) -> None:
    out = tmp_path / "taken"
    out.mkdir()

    with pytest.raises(FileExistsError, match="immutable"):
        DatasetExport(renders=renders, out=out, name="s", version="1").run(jobs=1)


def test_export_needs_renders(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="No renders"):
        DatasetExport(
            renders=tmp_path / "empty", out=tmp_path / "out", name="s", version="1"
        ).run(jobs=1)


def test_split_is_stable_and_near_the_fraction() -> None:
    splits = [
        dataset_split(scene_id=f"{index:06d}", val_fraction=0.2) for index in range(2000)
    ]

    assert splits == [
        dataset_split(scene_id=f"{i:06d}", val_fraction=0.2) for i in range(2000)
    ]
    assert 0.17 < splits.count("val") / len(splits) < 0.23
    assert dataset_split(scene_id="000001", val_fraction=0.0) == "train"


def test_post_effects_are_seeded() -> None:
    image = np.full((20, 30, 3), 128, dtype=np.uint8)
    post = ScenePost(blur_px=1.0, noise=0.02, jpeg_quality=90)
    first = apply_post_effects(image=image, post=post, seed=1)

    assert first.dtype == np.uint8
    assert np.array_equal(first, apply_post_effects(image=image, post=post, seed=1))
    assert not np.array_equal(first, apply_post_effects(image=image, post=post, seed=2))

    clean = ScenePost(blur_px=0.0, noise=0.0, jpeg_quality=90)

    assert np.array_equal(apply_post_effects(image=image, post=clean, seed=1), image)


def test_polygon_area() -> None:
    assert polygon_area(np.array(rectangle(0, 0, 4, 3))) == pytest.approx(12.0)


def test_draw_labels_leaves_the_input_unchanged() -> None:
    image = np.zeros((50, 50, 3), dtype=np.uint8)
    label = TileLabel(
        class_id=0,
        coord=(0, 0),
        visible=1.0,
        box=(5.0, 5.0, 40.0, 40.0),
        polygon=[(5.0, 5.0), (40.0, 5.0), (40.0, 40.0)],
    )
    drawn = draw_labels(image=image, labels=[label])

    assert drawn.any()
    assert not image.any()
