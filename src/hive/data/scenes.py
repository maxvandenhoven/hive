"""Synthetic scenes: random valid boards with loose tiles, a camera, lighting and effects.

A scene describes one image for the Blender renderer (`blender/render.py`). The board
comes from a random game played with `Rules`, so every board is reachable and legal,
including beetle stacks. Lengths are in tile widths (the across-flats width of a tile),
so a scene renders the same with every tileset; the renderer scales it by the measured
tile size. Everything is sampled from the scene seed, so generating a scene twice gives
the same JSON. The JSON Schema of a scene is `schemas/scene.schema.json`.
"""

import hashlib
import json
import math
import multiprocessing
import random
import tomllib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import Field, StrictInt

from hive.engine.codec import JsonCodec, json_adapter
from hive.engine.grid import Coordinate
from hive.engine.rules import Rules
from hive.engine.state import GameState, Move, PieceType, Player

SCENE_SCHEMA_VERSION: Final = 1
"""The version of the scene JSON, raised on every incompatible change."""

SCENE_SCHEMA_PATH: Final = Path(__file__).parent / "schemas" / "scene.schema.json"
"""The committed JSON Schema of a scene, which `hive data schema` writes."""

SCENE_SENSOR_MM: Final = (34.6, 25.95)
"""The sensor size of a 4:3 camera whose focal lengths are 35 mm equivalents: the size
with the diagonal of a full-frame sensor."""

SCENE_TILE_CIRCUMRADIUS: Final = 1 / math.sqrt(3)
"""The distance from the centre to a corner of a tile, in tile widths."""

SCENE_MIN_CAMERA_DISTANCE: Final = 3.0
"""The closest a camera gets to the hive, in tile widths, about the closest focus of a
phone camera."""

type SceneRange = tuple[float, float]
"""A closed range `(low, high)` that a value is sampled from uniformly."""


@dataclass(frozen=True, slots=True)
class SceneTile(JsonCodec):
    """One tile of a stack on the board.

    Attributes:
        piece_type: The insect on the tile.
        owner: The player the tile belongs to.
        turn: The orientation of the insect in steps of 60 degrees, anti-clockwise.
    """

    piece_type: Annotated[PieceType, Field(alias="piece")]
    owner: Player
    turn: Annotated[StrictInt, Field(ge=0, le=5)]


@dataclass(frozen=True, slots=True)
class SceneJitter(JsonCodec):
    """The deviation of a tile from its exact grid position.

    Attributes:
        dx: The offset to the east in tile widths.
        dy: The offset to the north in tile widths.
        rot_deg: The rotation in degrees, anti-clockwise.
    """

    dx: float
    dy: float
    rot_deg: float


@dataclass(frozen=True, slots=True)
class SceneCell(JsonCodec):
    """An occupied cell of the board.

    Attributes:
        coord: The axial coordinate of the cell in the engine.
        x: The grid position to the east of the hive centre, in tile widths.
        y: The grid position to the north of the hive centre, in tile widths.
        stack: The tiles of the cell, bottom to top.
        jitter: The deviation of every tile of the stack, bottom to top.
    """

    coord: Coordinate
    x: float
    y: float
    stack: list[SceneTile]
    jitter: list[SceneJitter]


@dataclass(frozen=True, slots=True)
class SceneLoosePiece(JsonCodec):
    """An unplayed tile lying next to the hive.

    Attributes:
        piece_type: The insect on the tile.
        owner: The player the tile belongs to.
        x: The position to the east of the hive centre, in tile widths.
        y: The position to the north of the hive centre, in tile widths.
        rot_deg: The rotation in degrees, anti-clockwise.
        flipped: Whether the tile lies upside down, showing its plain bottom.
    """

    piece_type: Annotated[PieceType, Field(alias="piece")]
    owner: Player
    x: float
    y: float
    rot_deg: float
    flipped: bool


@dataclass(frozen=True, slots=True)
class SceneCamera(JsonCodec):
    """A phone camera looking at the hive.

    Attributes:
        distance: The distance from the camera to the hive centre in tile widths.
        tilt_deg: The angle between the view direction and straight down.
        azimuth_deg: The direction the camera is in, seen from the hive, anti-clockwise
            from the east.
        roll_deg: The rotation of the camera around its view direction.
        focal_mm: The 35 mm equivalent focal length.
        frame_offset: Where the hive centre appears in the frame, from -1 (left, bottom)
            to 1 (right, top).
        portrait: Whether the image is taller than wide.
    """

    distance: float
    tilt_deg: float
    azimuth_deg: float
    roll_deg: float
    focal_mm: float
    frame_offset: tuple[float, float]
    portrait: bool


type SceneLightingPreset = Literal["window", "ceiling", "lamp", "flash", "environment"]
"""How a scene is lit: daylight from a window, overhead lights, a lamp, the phone flash,
or only the environment."""


@dataclass(frozen=True, slots=True)
class SceneLighting(JsonCodec):
    """The light sources of a scene.

    Attributes:
        preset: The kind of lighting, which the renderer turns into lights.
        color_temp_k: The colour temperature of the main light in kelvin.
        intensity: The brightness relative to the preset's normal exposure.
        direction_deg: The direction the main light comes from, anti-clockwise from east.
        elevation_deg: The height of the main light above the table in degrees.
        environment_strength: The brightness of the surrounding room light.
    """

    preset: SceneLightingPreset
    color_temp_k: float
    intensity: float
    direction_deg: float
    elevation_deg: float
    environment_strength: float


@dataclass(frozen=True, slots=True)
class SceneBackground(JsonCodec):
    """The table surface the hive lies on.

    Attributes:
        surface: The kind of surface, for example `wood`; the renderer picks a texture of
            that kind.
        variant_seed: Picks the texture and its colour variation.
        rotation_deg: The rotation of the texture.
        scale: The scale of the texture relative to its real size.
    """

    surface: str
    variant_seed: int
    rotation_deg: float
    scale: float


@dataclass(frozen=True, slots=True)
class ScenePost(JsonCodec):
    """Camera effects applied to the rendered image.

    Attributes:
        blur_px: The standard deviation of a Gaussian blur in pixels.
        noise: The standard deviation of sensor noise, relative to full scale.
        jpeg_quality: The JPEG quality of the saved image.
    """

    blur_px: float
    noise: float
    jpeg_quality: int


@dataclass(frozen=True, slots=True)
class Scene(JsonCodec):
    """Everything the renderer needs for one image, in tile widths.

    Attributes:
        schema_version: The version of the scene JSON.
        scene_id: The unique id, also the file name.
        seed: The seed of the scene, which the renderer also uses for its own choices
            such as the tileset.
        moves: The moves of the random game, which replay to the board.
        board: The occupied cells, ordered by coordinate.
        loose_pieces: The unplayed tiles next to the hive.
        tile_gap: The space between neighbouring tiles in tile widths.
        camera: The camera.
        lighting: The lighting.
        background: The table surface.
        post: The camera effects.
    """

    schema_version: Literal[1]
    scene_id: str
    seed: int
    moves: list[Move | None]
    board: list[SceneCell]
    loose_pieces: list[SceneLoosePiece]
    tile_gap: float
    camera: SceneCamera
    lighting: SceneLighting
    background: SceneBackground
    post: ScenePost

    def write(self, directory: Path) -> Path:
        """Write the scene as JSON into a directory.

        Args:
            directory: The directory, which must exist.

        Returns:
            The path of the written file, named after the scene id.
        """
        path = directory / f"{self.scene_id}.json"
        path.write_text(json.dumps(self.to_json(), indent=1))

        return path

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        """Get the JSON Schema of a scene.

        Returns:
            The schema, with field aliases as property names.
        """
        return json_adapter(cls).json_schema(by_alias=True, mode="serialization")


@dataclass(frozen=True, slots=True)
class ScenesConfig(JsonCodec):
    """The sampling ranges of the scene generator, readable from a TOML file.

    Every field has a default, so a config file only lists the values it changes. Lengths
    are in tile widths.

    Attributes:
        ply: The range of game lengths in plies; a game stops early when it ends.
        movement_bias: The range of the per-game chance to move a tile when that is
            legal instead of picking any legal move, which spreads the hive sizes.
        tile_gap: The range of the space between neighbouring tiles.
        jitter_offset: The largest offset of a tile from its grid position.
        jitter_rot_deg: The largest rotation of a tile from its grid orientation.
        stack_jitter_offset: The largest offset of a tile on top of another tile.
        loose_probability: The chance that unplayed tiles lie next to the hive.
        loose_fraction: The range of the fraction of unplayed tiles that is shown.
        loose_distance: The range of the space between the hive and the unplayed tiles.
        flipped_probability: The chance that an unplayed tile lies upside down.
        tilt_deg: The range of camera tilts from straight down.
        roll_deg: The range of camera rolls around the view direction.
        focal_mm: The range of 35 mm equivalent focal lengths.
        fill: The range of the fraction of the half frame height the hive radius fills.
        frame_offset_slack: How far past the frame edge the hive may be pushed, as a
            fraction of the half frame.
        portrait_probability: The chance of a portrait image.
        lighting_presets: The relative weight of each lighting preset.
        color_temp_k: The range of light colour temperatures.
        intensity: The range of light intensities.
        elevation_deg: The range of main light elevations.
        environment_strength: The range of room light strengths.
        surfaces: The relative weight of each kind of table surface.
        texture_scale: The range of texture scales.
        blur_px: The range of blur radii.
        noise: The range of sensor noise levels.
        jpeg_quality: The range of JPEG qualities.
    """

    ply: tuple[int, int] = (1, 60)
    movement_bias: SceneRange = (0.0, 0.97)
    tile_gap: SceneRange = (0.0, 0.06)
    jitter_offset: float = 0.025
    jitter_rot_deg: float = 4.0
    stack_jitter_offset: float = 0.06
    loose_probability: float = 0.7
    loose_fraction: SceneRange = (0.15, 1.0)
    loose_distance: SceneRange = (0.4, 2.5)
    flipped_probability: float = 0.05
    tilt_deg: SceneRange = (0.0, 35.0)
    roll_deg: SceneRange = (-8.0, 8.0)
    focal_mm: SceneRange = (22.0, 52.0)
    fill: SceneRange = (0.35, 0.95)
    frame_offset_slack: float = 0.15
    portrait_probability: float = 0.4
    lighting_presets: dict[SceneLightingPreset, float] = field(
        default_factory=lambda: {
            "window": 3.0,
            "ceiling": 3.0,
            "lamp": 2.0,
            "flash": 1.0,
            "environment": 2.0,
        }
    )
    color_temp_k: SceneRange = (2700.0, 6500.0)
    intensity: SceneRange = (0.5, 1.6)
    elevation_deg: SceneRange = (15.0, 75.0)
    environment_strength: SceneRange = (0.15, 1.0)
    surfaces: dict[str, float] = field(
        default_factory=lambda: {"wood": 4.0, "fabric": 2.0, "stone": 1.5, "plain": 2.0}
    )
    texture_scale: SceneRange = (0.7, 1.5)
    blur_px: SceneRange = (0.0, 1.2)
    noise: SceneRange = (0.0, 0.025)
    jpeg_quality: tuple[int, int] = (60, 95)

    @classmethod
    def load(cls, path: Path | None) -> Self:
        """Read a config from a TOML file.

        Args:
            path: The TOML file, or `None` for the defaults.

        Returns:
            The config, with defaults for the values the file does not set.

        Raises:
            OSError: If the file cannot be read.
            ValueError: If the file is not valid TOML or sets unknown or invalid values.
        """
        if path is None:
            return cls()

        return cls.from_json(tomllib.loads(path.read_text()))

    def write_scenes(
        self, rules: Rules, out: Path, seed: int, indices: range, jobs: int
    ) -> list[Path]:
        """Sample scenes and write them as JSON files, in parallel processes.

        Scene `i` is named `f"{i:06d}"` and seeded by `derive_scene_seed(seed, i)`, so a
        batch can be extended or regenerated in parts.

        Args:
            rules: The rules the random games are played with.
            out: The directory for the scene files, created if needed.
            seed: The seed of the batch.
            indices: The scene indices to write.
            jobs: The number of worker processes; 1 writes in this process.

        Returns:
            The written files in index order.
        """
        out.mkdir(parents=True, exist_ok=True)

        if jobs <= 1:
            return [
                self.write_scene(rules=rules, out=out, seed=seed, index=index)
                for index in indices
            ]

        with ProcessPoolExecutor(
            max_workers=jobs, mp_context=multiprocessing.get_context("spawn")
        ) as executor:
            futures = [
                executor.submit(
                    self.write_scene, rules=rules, out=out, seed=seed, index=index
                )
                for index in indices
            ]

            return [future.result() for future in futures]

    def write_scene(self, rules: Rules, out: Path, seed: int, index: int) -> Path:
        """Sample one scene of a batch and write it as a JSON file.

        Args:
            rules: The rules the random game is played with.
            out: The directory for the scene file.
            seed: The seed of the batch.
            index: The index of the scene in the batch.

        Returns:
            The written file.
        """
        scene = self.sample_scene(
            rules=rules,
            scene_id=f"{index:06d}",
            seed=derive_scene_seed(seed=seed, index=index),
        )

        return scene.write(out)

    def sample_scene(self, rules: Rules, scene_id: str, seed: int) -> Scene:
        """Sample a scene from a random game.

        Args:
            rules: The rules the random game is played with.
            scene_id: The id of the scene.
            seed: The seed of the scene; equal seeds give equal scenes.

        Returns:
            The scene.
        """
        rng = random.Random(seed)
        state, moves = self.play_game(rules=rules, rng=rng)
        tile_gap = rng.uniform(*self.tile_gap)
        board = self.sample_board(state=state, tile_gap=tile_gap, rng=rng)
        radius = max(math.hypot(cell.x, cell.y) for cell in board) + 0.5 if board else 0.5
        loose_pieces = self.sample_loose_pieces(
            state=state, board=board, radius=radius, rng=rng
        )

        return Scene(
            schema_version=SCENE_SCHEMA_VERSION,
            scene_id=scene_id,
            seed=seed,
            moves=moves,
            board=board,
            loose_pieces=loose_pieces,
            tile_gap=tile_gap,
            camera=self.sample_camera(radius=radius, rng=rng),
            lighting=self.sample_lighting(rng),
            background=self.sample_background(rng),
            post=ScenePost(
                blur_px=rng.uniform(*self.blur_px),
                noise=rng.uniform(*self.noise),
                jpeg_quality=rng.randint(*self.jpeg_quality),
            ),
        )

    def play_game(
        self, rules: Rules, rng: random.Random
    ) -> tuple[GameState, list[Move | None]]:
        """Play a random game of a random length.

        Each game has its own bias towards moving tiles over placing new ones, so short
        games with large hives and long games with small hives both occur.

        Args:
            rules: The rules of the game.
            rng: The random number generator.

        Returns:
            The final state and the moves that lead to it.
        """
        length = rng.randint(*self.ply)
        movement_bias = rng.uniform(*self.movement_bias)
        state = rules.create_initial_state()
        moves: list[Move | None] = []

        while state.current_ply < length and not rules.is_finished(state):
            legal_moves = rules.legal_moves(state)
            movements = [
                move
                for move in legal_moves
                if move is not None and move.source_coord is not None
            ]
            candidates = (
                movements if movements and rng.random() < movement_bias else legal_moves
            )
            move = candidates[rng.randrange(len(candidates))]
            state.apply_move(move)
            moves.append(move)

        return state, moves

    def sample_board(
        self, state: GameState, tile_gap: float, rng: random.Random
    ) -> list[SceneCell]:
        """Lay out the board of a state with random tile orientations and jitter.

        Args:
            state: The state whose board is laid out.
            tile_gap: The space between neighbouring tiles.
            rng: The random number generator.

        Returns:
            The cells ordered by coordinate, centred on the hive centre.
        """
        spacing = 1.0 + tile_gap
        coords = sorted(state.board)
        positions = {
            coord: (
                spacing * (coord[0] + coord[1] / 2),
                -spacing * math.sqrt(3) / 2 * coord[1],
            )
            for coord in coords
        }
        centre_x = sum(x for x, _ in positions.values()) / max(len(coords), 1)
        centre_y = sum(y for _, y in positions.values()) / max(len(coords), 1)
        cells: list[SceneCell] = []

        for coord in coords:
            stack = state.board[coord]
            jitter = [
                SceneJitter(
                    dx=rng.uniform(-offset, offset),
                    dy=rng.uniform(-offset, offset),
                    rot_deg=rng.uniform(-self.jitter_rot_deg, self.jitter_rot_deg),
                )
                for level in range(len(stack))
                for offset in [
                    self.jitter_offset if level == 0 else self.stack_jitter_offset
                ]
            ]
            x, y = positions[coord]
            cells.append(
                SceneCell(
                    coord=coord,
                    x=x - centre_x,
                    y=y - centre_y,
                    stack=[
                        SceneTile(
                            piece_type=piece.type,
                            owner=piece.owner,
                            turn=rng.randrange(6),
                        )
                        for piece in stack
                    ],
                    jitter=jitter,
                )
            )

        return cells

    def sample_loose_pieces(
        self, state: GameState, board: list[SceneCell], radius: float, rng: random.Random
    ) -> list[SceneLoosePiece]:
        """Place some unplayed tiles of each player in a loose group next to the hive.

        The groups of the two players lie on opposite sides, as when the players sit
        across the table. Tiles never overlap each other or touch the hive.

        Args:
            state: The state whose hands hold the unplayed tiles.
            board: The laid out board.
            radius: The radius of the hive around its centre.
            rng: The random number generator.

        Returns:
            The loose tiles.
        """
        if rng.random() >= self.loose_probability:
            return []

        fraction = rng.uniform(*self.loose_fraction)
        side_angle = rng.uniform(0, 2 * math.pi)
        clearance = 2 * SCENE_TILE_CIRCUMRADIUS + 0.05
        placed: list[tuple[float, float]] = [(cell.x, cell.y) for cell in board]
        hive_count = len(placed)
        loose_pieces: list[SceneLoosePiece] = []

        for player in Player:
            pieces = [
                piece_type
                for piece_type, count in state.hand[player].items()
                for _ in range(count)
            ]
            pieces = [piece for piece in pieces if rng.random() < fraction]
            angle = side_angle + player * math.pi + rng.uniform(-0.6, 0.6)
            distance = radius + rng.uniform(*self.loose_distance) + clearance
            centre = (distance * math.cos(angle), distance * math.sin(angle))
            spread = 0.8 + 0.45 * math.sqrt(len(pieces))

            for piece_type in pieces:
                for _ in range(60):
                    x = centre[0] + rng.uniform(-spread, spread)
                    y = centre[1] + rng.uniform(-spread, spread)
                    near_hive = any(
                        math.dist((x, y), other) < clearance + 0.3
                        for other in placed[:hive_count]
                    )
                    overlaps = any(
                        math.dist((x, y), other) < clearance
                        for other in placed[hive_count:]
                    )

                    if not near_hive and not overlaps:
                        placed.append((x, y))
                        loose_pieces.append(
                            SceneLoosePiece(
                                piece_type=piece_type,
                                owner=player,
                                x=x,
                                y=y,
                                rot_deg=rng.uniform(0, 360),
                                flipped=rng.random() < self.flipped_probability,
                            )
                        )
                        break

        return loose_pieces

    def sample_camera(self, radius: float, rng: random.Random) -> SceneCamera:
        """Sample a camera that frames the hive with a random fill and offset.

        Args:
            radius: The radius of the hive around its centre.
            rng: The random number generator.

        Returns:
            The camera.
        """
        focal_mm = rng.uniform(*self.focal_mm)
        fill = rng.uniform(*self.fill)
        portrait = rng.random() < self.portrait_probability
        tan_half_short = SCENE_SENSOR_MM[1] / 2 / focal_mm
        distance = max(radius / (fill * tan_half_short), SCENE_MIN_CAMERA_DISTANCE)
        # The hive spans `fill` of the short half frame and less of the long one, so it
        # may move further along the long side before it leaves the frame.
        aspect = SCENE_SENSOR_MM[1] / SCENE_SENSOR_MM[0]
        long_limit = 1 - fill * aspect + self.frame_offset_slack
        short_limit = 1 - fill + self.frame_offset_slack
        x_limit, y_limit = (
            (short_limit, long_limit) if portrait else (long_limit, short_limit)
        )

        return SceneCamera(
            distance=distance,
            tilt_deg=rng.uniform(*self.tilt_deg),
            azimuth_deg=rng.uniform(0, 360),
            roll_deg=rng.uniform(*self.roll_deg),
            focal_mm=focal_mm,
            frame_offset=(rng.uniform(-x_limit, x_limit), rng.uniform(-y_limit, y_limit)),
            portrait=portrait,
        )

    def sample_lighting(self, rng: random.Random) -> SceneLighting:
        """Sample the lighting preset and its parameters.

        Args:
            rng: The random number generator.

        Returns:
            The lighting.
        """
        presets = list(self.lighting_presets)
        weights = [self.lighting_presets[preset] for preset in presets]

        return SceneLighting(
            preset=rng.choices(presets, weights=weights)[0],
            color_temp_k=rng.uniform(*self.color_temp_k),
            intensity=rng.uniform(*self.intensity),
            direction_deg=rng.uniform(0, 360),
            elevation_deg=rng.uniform(*self.elevation_deg),
            environment_strength=rng.uniform(*self.environment_strength),
        )

    def sample_background(self, rng: random.Random) -> SceneBackground:
        """Sample the table surface.

        Args:
            rng: The random number generator.

        Returns:
            The background.
        """
        surfaces = list(self.surfaces)
        weights = [self.surfaces[surface] for surface in surfaces]

        return SceneBackground(
            surface=rng.choices(surfaces, weights=weights)[0],
            variant_seed=rng.randrange(2**31),
            rotation_deg=rng.uniform(0, 360),
            scale=rng.uniform(*self.texture_scale),
        )


def derive_scene_seed(seed: int, index: int) -> int:
    """Derive the seed of one scene from the seed of a batch.

    Hashing keeps the scenes of nearby batch seeds independent.

    Args:
        seed: The seed of the batch.
        index: The index of the scene in the batch.

    Returns:
        A non-negative 63-bit seed.
    """
    digest = hashlib.sha256(f"hive-scene:{seed}:{index}".encode()).digest()

    return int.from_bytes(digest[:8]) >> 1
