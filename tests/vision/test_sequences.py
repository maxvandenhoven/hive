import json
import random
from pathlib import Path

import cv2
import numpy as np

from hive.data.scenes import ScenesConfig
from hive.engine.record import GameRecord
from hive.engine.rules import Rules
from hive.vision.sequences import SequenceTracker, draw_board
from hive.vision.testing import SimulatedCamera, SimulatedDetector, simulate_observations
from hive.vision.types import TileObservation

IMAGE_SIZE = (640, 480)


class ScriptedReader:
    """A board reader that returns prepared detections in order."""

    name = "scripted"

    def __init__(self, detections: list[list[TileObservation]]) -> None:
        self.detections = detections

    def read(self, image: np.ndarray) -> list[TileObservation]:
        return self.detections.pop(0)


def write_dataset(folder: Path, plies: int) -> list[list[TileObservation]]:
    """Write a dataset of a game with a photo per move, and simulate its detections."""
    rules = Rules()
    scenes = ScenesConfig().sample_sequence(
        rules=rules, sequence=0, seed=3, plies=plies, takes=1
    )
    rng = random.Random(0)
    detections = []
    (folder / "images").mkdir(parents=True)

    with (folder / "meta.jsonl").open("w") as file:
        for scene in scenes:
            image = f"images/{scene.scene_id}.jpg"
            cv2.imwrite(str(folder / image), np.zeros((480, 640, 3), dtype=np.uint8))
            moves = [None if move is None else move.to_json() for move in scene.moves]
            render = {"seed": scene.seed, "moves": moves}
            line = {
                "scene_id": scene.scene_id,
                "split": "val",
                "image": image,
                "tileset_id": "test",
                "engine": "test",
                "blender_version": "test",
                "width": IMAGE_SIZE[0],
                "height": IMAGE_SIZE[1],
                "labels": [],
                "render": render,
            }
            file.write(json.dumps(line) + "\n")
            state = GameRecord(rules=rules, moves=scene.moves).replay()
            camera = SimulatedCamera(
                tilt_deg=rng.uniform(0, 40),
                azimuth_deg=rng.uniform(0, 360),
                roll_deg=0,
                distance=16,
                focal=500,
                image_size=IMAGE_SIZE,
            )
            detections.append(
                simulate_observations(
                    board=state.board,
                    camera=camera,
                    detector=SimulatedDetector(),
                    rng=rng,
                )
            )

    return detections


def test_replays_a_game_and_draws_frames(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    detections = write_dataset(folder=dataset, plies=8)
    tracker = SequenceTracker(
        dataset=dataset,
        reader=ScriptedReader(detections),
        rules=Rules(),
        frames=tmp_path / "frames",
    )
    report = tracker.run()

    assert [ply.ply for ply in report.plies] == list(range(1, 9))
    assert report.summary.get("wrong", 0) == 0
    assert report.summary.get("resolved", 0) + report.summary.get("manual", 0) == 8
    assert len(list((tmp_path / "frames" / "000").glob("*.jpg"))) == 8


def test_draw_board_shows_tiles() -> None:
    state = GameRecord(rules=Rules(), moves=[]).replay()
    empty = draw_board(board=state.board, changed=set(), size=100)
    rng = random.Random(1)
    game = ScenesConfig().play_game(rules=Rules(), rng=rng)[0]
    drawn = draw_board(board=game.board, changed={next(iter(game.board))}, size=300)

    assert empty.shape == (100, 100, 3)
    assert drawn.shape == (300, 300, 3)
    assert len(np.unique(drawn.reshape(-1, 3), axis=0)) > len(
        np.unique(empty.reshape(-1, 3), axis=0)
    )
