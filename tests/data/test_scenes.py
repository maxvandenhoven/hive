import json
import math
from pathlib import Path

import pytest

from hive.data.scenes import (
    SCENE_SCHEMA_PATH,
    SCENE_TILE_CIRCUMRADIUS,
    Scene,
    ScenesConfig,
    derive_scene_seed,
)
from hive.engine.record import GameRecord
from hive.engine.rules import Rules

SCENE_COUNT = 150


@pytest.fixture(scope="module")
def scenes() -> list[Scene]:
    """Sample a batch of scenes with the default config."""
    config = ScenesConfig()

    return [
        config.sample_scene(
            rules=Rules(),
            scene_id=f"{index:06d}",
            seed=derive_scene_seed(seed=7, index=index),
        )
        for index in range(SCENE_COUNT)
    ]


def test_same_seed_gives_same_scene() -> None:
    config = ScenesConfig()
    first = config.sample_scene(rules=Rules(), scene_id="a", seed=42)
    second = config.sample_scene(rules=Rules(), scene_id="a", seed=42)
    other = config.sample_scene(rules=Rules(), scene_id="a", seed=43)

    assert first.to_json() == second.to_json()
    assert first.to_json() != other.to_json()


def test_derived_seeds_are_distinct() -> None:
    seeds = {
        derive_scene_seed(seed=seed, index=index)
        for seed in range(3)
        for index in range(100)
    }

    assert len(seeds) == 300
    assert all(0 <= seed < 2**63 for seed in seeds)


def test_boards_replay_from_the_moves(scenes: list[Scene]) -> None:
    for scene in scenes:
        state = GameRecord(rules=Rules(), moves=scene.moves).replay()
        board = {
            cell.coord: [(t.piece_type, t.owner) for t in cell.stack]
            for cell in scene.board
        }

        assert board == {
            coord: [(piece.type, piece.owner) for piece in stack]
            for coord, stack in state.board.items()
        }


def test_hive_sizes_and_stacks_are_spread(scenes: list[Scene]) -> None:
    sizes = [sum(len(cell.stack) for cell in scene.board) for scene in scenes]
    stacked = sum(any(len(cell.stack) > 1 for cell in scene.board) for scene in scenes)

    assert sum(size <= 7 for size in sizes) > SCENE_COUNT * 0.1
    assert sum(8 <= size <= 15 for size in sizes) > SCENE_COUNT * 0.25
    assert sum(size >= 16 for size in sizes) > SCENE_COUNT * 0.15
    assert stacked > SCENE_COUNT * 0.1


def test_board_is_centred_on_the_grid(scenes: list[Scene]) -> None:
    for scene in scenes:
        spacing = 1 + scene.tile_gap
        centre_x = sum(cell.x for cell in scene.board) / len(scene.board)
        centre_y = sum(cell.y for cell in scene.board) / len(scene.board)

        assert abs(centre_x) < 1e-9 and abs(centre_y) < 1e-9

        for cell in scene.board:
            q, r = cell.coord
            origin = scene.board[0]
            dx = spacing * ((q - origin.coord[0]) + (r - origin.coord[1]) / 2)
            dy = -spacing * math.sqrt(3) / 2 * (r - origin.coord[1])

            assert cell.x - origin.x == pytest.approx(dx)
            assert cell.y - origin.y == pytest.approx(dy)
            assert len(cell.jitter) == len(cell.stack)


def test_loose_pieces_come_from_the_hands_and_keep_clear(scenes: list[Scene]) -> None:
    with_loose = 0

    for scene in scenes:
        state = GameRecord(rules=Rules(), moves=scene.moves).replay()
        loose = scene.loose_pieces
        with_loose += bool(loose)

        for player in state.hand:
            for piece_type, count in state.hand[player].items():
                shown = sum(
                    p.owner == player and p.piece_type == piece_type for p in loose
                )

                assert shown <= count

        for index, piece in enumerate(loose):
            for cell in scene.board:
                assert (
                    math.dist((piece.x, piece.y), (cell.x, cell.y))
                    > 2 * SCENE_TILE_CIRCUMRADIUS
                )

            for other in loose[index + 1 :]:
                assert (
                    math.dist((piece.x, piece.y), (other.x, other.y))
                    > 2 * SCENE_TILE_CIRCUMRADIUS
                )

    assert with_loose > SCENE_COUNT * 0.3


def test_camera_follows_the_config(scenes: list[Scene]) -> None:
    config = ScenesConfig()

    for scene in scenes:
        camera = scene.camera

        assert config.tilt_deg[0] <= camera.tilt_deg <= config.tilt_deg[1]
        assert config.focal_mm[0] <= camera.focal_mm <= config.focal_mm[1]
        assert all(
            abs(offset) <= 1 + config.frame_offset_slack for offset in camera.frame_offset
        )
        assert camera.distance >= 3.0

    assert any(scene.camera.portrait for scene in scenes)
    assert any(not scene.camera.portrait for scene in scenes)
    assert len({scene.lighting.preset for scene in scenes}) == len(
        config.lighting_presets
    )
    assert len({scene.background.surface for scene in scenes}) == len(config.surfaces)


def test_scene_round_trips_through_json(scenes: list[Scene]) -> None:
    for scene in scenes[:20]:
        assert Scene.from_json(json.loads(json.dumps(scene.to_json()))) == scene


def test_committed_schema_is_up_to_date() -> None:
    assert json.loads(SCENE_SCHEMA_PATH.read_text()) == Scene.json_schema(), (
        "Regenerate the schema with `uv run hive data schema`."
    )


def test_config_loads_partial_toml(tmp_path: Path) -> None:
    path = tmp_path / "scenes.toml"
    path.write_text("tilt_deg = [0.0, 10.0]\n\n[surfaces]\nwood = 1.0\n")
    config = ScenesConfig.load(path)

    assert config.tilt_deg == (0.0, 10.0)
    assert config.surfaces == {"wood": 1.0}
    assert config.focal_mm == ScenesConfig().focal_mm
    assert ScenesConfig.load(None) == ScenesConfig()


def test_config_rejects_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "scenes.toml"
    path.write_text("tilt = [0.0, 10.0]\n")

    with pytest.raises(ValueError, match="tilt"):
        ScenesConfig.load(path)


def test_write_scenes_names_files_by_index(tmp_path: Path) -> None:
    config = ScenesConfig()
    paths = config.write_scenes(
        rules=Rules(), out=tmp_path, seed=3, indices=range(5, 8), jobs=1
    )

    assert [path.name for path in paths] == ["000005.json", "000006.json", "000007.json"]

    scene = Scene.from_json(json.loads(paths[0].read_text()))

    assert scene.seed == derive_scene_seed(seed=3, index=5)
    assert scene == config.sample_scene(rules=Rules(), scene_id="000005", seed=scene.seed)


def test_write_scenes_in_processes_matches_one_process(tmp_path: Path) -> None:
    config = ScenesConfig()
    serial = config.write_scenes(
        rules=Rules(), out=tmp_path / "serial", seed=1, indices=range(4), jobs=1
    )
    parallel = config.write_scenes(
        rules=Rules(), out=tmp_path / "parallel", seed=1, indices=range(4), jobs=2
    )

    assert [path.read_text() for path in serial] == [
        path.read_text() for path in parallel
    ]


def test_distractors_keep_clear_of_tiles_and_each_other(scenes: list[Scene]) -> None:
    config = ScenesConfig()
    kinds = set()

    for scene in scenes:
        tiles = [(cell.x, cell.y) for cell in scene.board] + [
            (piece.x, piece.y) for piece in scene.loose_pieces
        ]
        reaches = [math.hypot(d.size[0], d.size[1]) / 2 for d in scene.distractors]

        for index, (distractor, reach) in enumerate(
            zip(scene.distractors, reaches, strict=True)
        ):
            kinds.add(distractor.kind)

            for tile in tiles:
                assert math.dist((distractor.x, distractor.y), tile) > (
                    reach + SCENE_TILE_CIRCUMRADIUS
                )

            for other, other_reach in zip(
                scene.distractors[index + 1 :], reaches[index + 1 :], strict=True
            ):
                assert math.dist((distractor.x, distractor.y), (other.x, other.y)) > (
                    reach + other_reach
                )

        assert len(scene.distractors) <= config.distractor_count[1]

    assert sum(bool(scene.distractors) for scene in scenes) > SCENE_COUNT * 0.3
    assert kinds == set(config.distractor_kinds)


def test_camera_covers_steep_and_close_views(scenes: list[Scene]) -> None:
    config = ScenesConfig()

    assert any(scene.camera.tilt_deg > 45 for scene in scenes)
    assert all(
        config.aperture_f[0] <= scene.camera.aperture_f <= config.aperture_f[1]
        for scene in scenes
    )


def test_sequence_grows_one_legal_move_at_a_time() -> None:
    scenes = ScenesConfig().sample_sequence(
        rules=Rules(), sequence=2, seed=4, plies=30, takes=2
    )

    assert scenes[0].scene_id == "002-001-0"
    assert scenes[1].scene_id == "002-001-1"
    assert len(scenes) == 60

    for previous, scene in zip(scenes[::2], scenes[2::2], strict=False):
        assert scene.moves[:-1] == previous.moves
        GameRecord(rules=Rules(), moves=scene.moves).replay()

    takes = scenes[-2:]

    assert takes[0].moves == takes[1].moves
    assert takes[0].camera != takes[1].camera
    assert any(len(cell.stack) > 1 for scene in scenes for cell in scene.board)


def test_write_sequences_names_files_in_order(tmp_path: Path) -> None:
    paths = ScenesConfig().write_sequences(
        rules=Rules(), out=tmp_path, seed=0, count=2, plies=3, takes=2
    )

    assert [path.name for path in paths] == sorted(path.name for path in paths)
    assert len(paths) == 12
    assert paths[-1].name == "001-003-1.json"
