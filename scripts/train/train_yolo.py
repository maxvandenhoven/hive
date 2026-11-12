"""Train a YOLO model on a synthetic dataset and export it to ONNX for the `YoloReader`.

Needs the `train` extra. For example, from the repository root:

    uv run python scripts/train/train_yolo.py --dataset data/synth/datasets/synth-v001 \
        --model yolo26n.pt --epochs 60 --name hive-yolo --version v001

The model folder `<out>/<name>/<version>/` gets `model.onnx` (fixed input size, raw head
with non-maximum suppression left to the reader), `best.pt`, `model.json` (dataset,
training settings, class names, input size) and `metrics.json` (validation metrics on the
synthetic validation split, overall and per class). Ultralytics run files are kept in
`<out>/<name>/<version>/run/` and the plots of the final validation in `val/`.
"""

import argparse
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
from ultralytics import YOLO

logger = logging.getLogger(__name__)

TRAIN_AUGMENTATION: dict[str, float] = {
    "hsv_h": 0.015,
    "hsv_s": 0.6,
    "hsv_v": 0.4,
    "degrees": 15.0,
    "translate": 0.15,
    "scale": 0.5,
    "perspective": 0.0005,
    "fliplr": 0.5,
    "flipud": 0.5,
    "mosaic": 1.0,
    "close_mosaic": 10,
}
"""Ultralytics augmentations on top of the rendered variation. Photos are taken from
above, so vertical flips are as plausible as horizontal ones, and mirrored insects stay
recognisable."""


def pick_device(requested: str | None) -> str:
    """Choose the training device.

    Args:
        requested: A device such as `cpu` or `0`, or `None` to pick one.

    Returns:
        The requested device, or the first GPU if CUDA works, or `cpu`.
    """
    if requested is not None:
        return requested

    return "0" if torch.cuda.is_available() else "cpu"


def write_json(path: Path, value: Any) -> None:
    """Write a value as indented JSON.

    Args:
        path: The file to write.
        value: The JSON-compatible value.
    """
    path.write_text(json.dumps(value, indent=2) + "\n")


def collect_metrics(validation: Any, class_names: dict[int, str]) -> dict[str, Any]:
    """Collect the validation metrics of an Ultralytics run.

    Args:
        validation: The metrics object returned by `YOLO.val`.
        class_names: The class names by id.

    Returns:
        The overall box (and mask) metrics and the per-class box mAP.
    """
    metrics: dict[str, Any] = {
        "box": {
            "precision": float(validation.box.mp),
            "recall": float(validation.box.mr),
            "map50": float(validation.box.map50),
            "map50_95": float(validation.box.map),
        },
        "per_class_box_map50_95": {
            class_names[int(class_id)]: float(value)
            for class_id, value in zip(
                validation.box.ap_class_index, validation.box.maps, strict=False
            )
        },
        "speed_ms": {key: float(value) for key, value in validation.speed.items()},
    }

    if hasattr(validation, "seg"):
        metrics["mask"] = {
            "precision": float(validation.seg.mp),
            "recall": float(validation.seg.mr),
            "map50": float(validation.seg.map50),
            "map50_95": float(validation.seg.map),
        }

    return metrics


def train(args: argparse.Namespace) -> Path:
    """Train, validate and export a model.

    Args:
        args: The parsed command line.

    Returns:
        The model folder.

    Raises:
        FileExistsError: If the model version already exists.
    """
    folder = args.out / args.name / args.version

    if folder.exists():
        msg = f"The model `{folder}` already exists; versions are immutable."
        raise FileExistsError(msg)

    folder.mkdir(parents=True)
    device = pick_device(args.device)
    data_yaml = args.dataset.resolve() / "data.yaml"
    manifest_path = args.dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    settings = {
        "data": str(data_yaml),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "workers": args.workers,
        "device": device,
        "patience": args.patience,
        "seed": args.seed,
        "project": str(folder.resolve()),
        "name": "run",
        "exist_ok": True,
        "plots": True,
        **TRAIN_AUGMENTATION,
    }
    logger.info("Training `%s` on `%s` with device `%s`.", args.model, data_yaml, device)
    model = YOLO(args.model)
    model.train(**settings)

    best = folder / "run" / "weights" / "best.pt"
    shutil.copy(best, folder / "best.pt")
    trained = YOLO(folder / "best.pt")
    validation = trained.val(
        data=str(data_yaml),
        imgsz=args.imgsz,
        device=device,
        project=str(folder.resolve()),
        name="val",
        exist_ok=True,
    )
    class_names = {int(key): value for key, value in trained.names.items()}
    onnx_path = Path(trained.export(format="onnx", imgsz=args.imgsz, simplify=True))
    shutil.move(onnx_path, folder / "model.onnx")

    write_json(folder / "metrics.json", collect_metrics(validation, class_names))
    write_json(
        folder / "model.json",
        {
            "name": args.name,
            "version": args.version,
            "task": trained.task,
            "base_model": args.model,
            "input_size": args.imgsz,
            "class_names": class_names,
            "dataset": {key: manifest.get(key) for key in ("name", "version", "images")},
            "training": {
                key: value for key, value in settings.items() if key not in ("project",)
            },
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
    logger.info("Wrote the model to `%s`.", folder)

    return folder


def main() -> None:
    """Parse the command line and train."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Dataset folder.")
    parser.add_argument("--model", default="yolo26n.pt", help="Pretrained weights.")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", help="For example `cpu` or `0`; default: auto.")
    parser.add_argument("--out", type=Path, default=Path("data/models"))
    parser.add_argument("--name", default="hive-yolo")
    parser.add_argument("--version", required=True)
    train(parser.parse_args())


if __name__ == "__main__":
    main()
