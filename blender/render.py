"""Render scene JSON files into images, instance maps and label metadata with Blender.

Runs under Blender's bundled Python and does not import `hive` (see `blender/README.md`):

    blender -b -P blender/render.py -- --scenes SCENES --out RENDERS [--engine mixed]

Per scene it writes into `RENDERS`:

- `images/<id>.png`: the rendered photo, before post effects (blur, noise, JPEG), which
  `hive data export` applies.
- `instances/<id>.png`: the tile instance map, with the instance id of every tile pixel
  in the red (low byte) and green (high byte) channels, and 0 elsewhere.
- `meta/<id>.json`: the tileset, camera, surface and lighting used, and per tile its
  class, board coordinate, stack level, and the projected outline of its top face.

Scenes with metadata are skipped, so an interrupted batch resumes where it stopped, and
`--shard K/N` splits a batch over several Blender processes.
"""

import argparse
import json
import logging
import math
import os
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hiveblend.stage import RenderAssets, Stage  # noqa: E402
from hiveblend.tilesets import TileLibrary, TilesetSpec, discover_tilesets  # noqa: E402

BLENDER_DIR = Path(__file__).resolve().parent
REPO_DIR = BLENDER_DIR.parent
SCENE_SCHEMA_VERSIONS = (1, 2)
"""The scene schema versions this renderer reads (`hive.data.scenes`); version 1 scenes
have no aperture and no distractors."""

logger = logging.getLogger("render")

VIEW_TRANSFORMS = [("AgX", "None"), ("AgX", "AgX - Punchy"), ("Standard", "None")]
"""Tone mappings sampled per image, as `(view transform, look)`, for camera variety."""


class SceneRenderer:
    """Renders scenes with randomly chosen tilesets and render engines.

    Attributes:
        out: The output directory.
        tilesets: The tilesets to sample from.
        libraries: The tile library per tileset id, built on first use.
        stage: The Blender objects of the current scene.
        engine: `eevee`, `cycles` or `mixed`.
        cycles_fraction: The fraction of images rendered with Cycles when mixed.
        samples: The render samples per pixel.
        resolution: The long side of the image in pixels.
    """

    def __init__(
        self,
        out: Path,
        tilesets: list[TilesetSpec],
        assets: RenderAssets,
        engine: str,
        cycles_fraction: float,
        samples: int,
        resolution: int,
    ) -> None:
        """Set up the stage and the output folders.

        Args:
            out: The output directory.
            tilesets: The tilesets to sample from.
            assets: The downloaded surfaces and environments.
            engine: `eevee`, `cycles` or `mixed`.
            cycles_fraction: The fraction of images rendered with Cycles when mixed.
            samples: The render samples per pixel.
            resolution: The long side of the image in pixels.
        """
        self.out = out
        self.tilesets = tilesets
        self.libraries: dict[str, TileLibrary] = {}
        self.stage = Stage(assets=assets)
        self.engine = engine
        self.cycles_fraction = cycles_fraction
        self.samples = samples
        self.resolution = resolution

        for folder in ("images", "instances", "meta"):
            (out / folder).mkdir(parents=True, exist_ok=True)

        configure_cycles()

    def library(self, spec: TilesetSpec) -> TileLibrary:
        """Get the tile library of a tileset, creating it on first use.

        Args:
            spec: The tileset.

        Returns:
            The library.
        """
        if spec.id not in self.libraries:
            svg_dir = REPO_DIR / "src" / "hive" / "assets" / "svg"
            self.libraries[spec.id] = TileLibrary(spec=spec, svg_dir=svg_dir)

        return self.libraries[spec.id]

    def render(self, path: Path) -> dict[str, Any] | None:
        """Render one scene file unless its metadata already exists.

        Args:
            path: The scene JSON file.

        Returns:
            The metadata written, or `None` if the scene was already rendered.

        Raises:
            ValueError: If the scene has an unsupported schema version.
        """
        scene = json.loads(path.read_text())

        if scene.get("schema_version") not in SCENE_SCHEMA_VERSIONS:
            msg = f"`{path}` has schema version {scene.get('schema_version')}."
            raise ValueError(msg)

        scene_id = scene["scene_id"]
        meta_path = self.out / "meta" / f"{scene_id}.json"

        if meta_path.exists():
            return None

        begin = time.perf_counter()
        rng = random.Random(scene["seed"])
        spec = rng.choices(self.tilesets, weights=[s.weight for s in self.tilesets])[0]
        library = self.library(spec)
        library.vary_materials(rng)
        engine = self.pick_engine(rng)
        stage = self.stage
        stage.clear()
        stage.build_tiles(scene=scene, library=library)
        stage.build_distractors(scene=scene, width=spec.across_flats_m)
        width, height = stage.set_camera(
            camera=scene["camera"],
            width=spec.across_flats_m,
            thickness=spec.thickness_m,
            resolution=self.resolution,
        )
        surface = stage.set_surface(background=scene["background"], rng=rng)
        environment = stage.set_lighting(
            lighting=scene["lighting"], width=spec.across_flats_m, rng=rng
        )
        view_transform, look = rng.choice(VIEW_TRANSFORMS)
        exposure = self.meter(
            view_transform=view_transform, look=look, target=rng.uniform(0.32, 0.55)
        )

        image_path = self.out / "images" / f"{scene_id}.png"
        instance_path = self.out / "instances" / f"{scene_id}.png"
        self.render_photo(
            path=image_path,
            engine=engine,
            view_transform=view_transform,
            look=look,
            exposure=exposure,
        )
        self.render_instances(instance_path)

        outline = spec.top_outline(corner_segments=3)
        instances = []

        for instance in stage.tiles:
            entry: dict[str, Any] = {
                "instance_id": instance.instance_id,
                "piece": instance.piece,
                "owner": instance.owner,
                "coord": None if instance.coord is None else list(instance.coord),
                "level": instance.level,
                "labeled": instance.labeled,
            }

            if instance.labeled:
                polygon = stage.label_polygon(
                    instance=instance, outline=outline, top=spec.thickness_m
                )
                entry["polygon"] = [[round(x, 2), round(y, 2)] for x, y in polygon]

            instances.append(entry)

        meta = {
            "scene_id": scene_id,
            "seed": scene["seed"],
            "tileset_id": spec.id,
            "engine": engine,
            "samples": self.samples,
            "blender_version": bpy.app.version_string,
            "image": f"images/{scene_id}.png",
            "instance_map": f"instances/{scene_id}.png",
            "width": width,
            "height": height,
            "surface": surface,
            "environment": environment,
            "view_transform": view_transform,
            "look": look,
            "exposure": exposure,
            "camera": scene["camera"],
            "distractors": scene.get("distractors", []),
            "lighting": scene["lighting"],
            "post": scene["post"],
            "board": [
                {"coord": cell["coord"], "stack": cell["stack"]}
                for cell in scene["board"]
            ],
            "instances": instances,
            "render_s": round(time.perf_counter() - begin, 2),
        }
        # The metadata is written last, so its presence marks a complete render.
        meta_path.write_text(json.dumps(meta, indent=1))

        return meta

    def pick_engine(self, rng: random.Random) -> str:
        """Pick the render engine of an image.

        Args:
            rng: The random number generator of the scene.

        Returns:
            The Blender engine id.
        """
        if self.engine == "mixed":
            return "CYCLES" if rng.random() < self.cycles_fraction else "BLENDER_EEVEE"

        return "CYCLES" if self.engine == "cycles" else "BLENDER_EEVEE"

    def meter(self, view_transform: str, look: str, target: float) -> float:
        """Find the exposure at which the image has a target brightness, like a phone.

        A small, quick EEVEE render is measured, and the exposure is corrected assuming
        displayed values scale with the linear light to the power 1/2.2.

        Args:
            view_transform: The colour management view transform.
            look: The look of the view transform.
            target: The mean displayed brightness to reach, between 0 and 1.

        Returns:
            The exposure in stops, between -4 and 4.
        """
        scene = self.stage.scene
        path = Path(tempfile.gettempdir()) / f"hive-meter-{os.getpid()}.png"
        samples = self.samples
        self.samples = 4
        scene.render.resolution_percentage = 15
        self.render_photo(
            path=path,
            engine="BLENDER_EEVEE",
            view_transform=view_transform,
            look=look,
            exposure=0.0,
        )
        self.samples = samples
        scene.render.resolution_percentage = 100
        image = bpy.data.images.load(str(path))
        pixels = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(pixels)
        bpy.data.images.remove(image)
        path.unlink()
        mean = float(pixels.reshape(-1, 4)[:, :3].mean())

        return min(max(2.2 * math.log2(target / max(mean, 1e-3)), -4.0), 4.0)

    def render_photo(
        self, path: Path, engine: str, view_transform: str, look: str, exposure: float
    ) -> None:
        """Render the photo of the current scene.

        Args:
            path: The PNG file to write.
            engine: The Blender engine id.
            view_transform: The colour management view transform.
            look: The look of the view transform.
            exposure: The exposure in stops.
        """
        scene = self.stage.scene
        scene.render.engine = engine
        scene.render.film_transparent = False
        scene.render.dither_intensity = 1.0
        scene.view_settings.view_transform = view_transform

        try:
            scene.view_settings.look = look
        except TypeError:
            scene.view_settings.look = "None"

        scene.view_settings.exposure = exposure

        if engine == "CYCLES":
            scene.cycles.samples = self.samples
            scene.cycles.use_denoising = True
            scene.cycles.max_bounces = 6
        else:
            scene.eevee.taa_render_samples = self.samples
            scene.eevee.use_raytracing = True
            scene.eevee.use_shadows = True

        settings = scene.render.image_settings
        settings.file_format = "PNG"
        settings.color_mode = "RGB"
        settings.color_depth = "8"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)

    def render_instances(self, path: Path) -> None:
        """Render the tile instance map with flat object colours and no anti-aliasing.

        Args:
            path: The PNG file to write.
        """
        scene = self.stage.scene
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.film_transparent = True
        scene.render.dither_intensity = 0.0
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
        scene.display.render_aa = "OFF"
        shading = scene.display.shading
        shading.light = "FLAT"
        shading.color_type = "OBJECT"
        shading.show_shadows = False
        shading.show_cavity = False
        shading.show_object_outline = False
        shading.show_specular_highlight = False
        # Everything but tiles is id 0, so other objects still cover the tiles behind.
        self.stage.table.color = (0.0, 0.0, 0.0, 1.0)

        for prop in self.stage.props:
            prop.color = (0.0, 0.0, 0.0, 1.0)

        for instance in self.stage.tiles:
            instance.obj.color = instance_color(instance.instance_id)

        settings = scene.render.image_settings
        settings.file_format = "PNG"
        settings.color_mode = "RGBA"
        settings.color_depth = "8"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)


def instance_color(instance_id: int) -> tuple[float, float, float, float]:
    """Encode an instance id as an object colour of the instance map.

    The Standard view transform encodes linear values as sRGB, so the channels are
    chosen as the linear values whose sRGB encoding is the id bytes.

    Args:
        instance_id: The instance id between 1 and 65535.

    Returns:
        The linear RGBA object colour.
    """

    def linear(byte: int) -> float:
        """Get the linear value that the sRGB transfer function maps to a byte.

        Args:
            byte: The 8-bit value.

        Returns:
            The linear value between 0 and 1.
        """
        value = byte / 255

        if value <= 0.04045:
            return value / 12.92

        return ((value + 0.055) / 1.055) ** 2.4

    return (linear(instance_id % 256), linear(instance_id // 256), 1.0, 1.0)


def configure_cycles() -> None:
    """Use the GPU for Cycles when one is available, otherwise every CPU thread."""
    scene = bpy.context.scene
    scene.cycles.device = "CPU"
    preferences = bpy.context.preferences.addons["cycles"].preferences

    for device_type in ("OPTIX", "CUDA", "HIP", "ONEAPI"):
        try:
            preferences.compute_device_type = device_type
        except TypeError:
            continue

        preferences.get_devices()
        gpus = [device for device in preferences.devices if device.type != "CPU"]

        if gpus:
            for device in preferences.devices:
                device.use = device.type != "CPU"

            scene.cycles.device = "GPU"
            logger.info(
                "Cycles renders on %s: %s.", device_type, ", ".join(d.name for d in gpus)
            )

            return

    logger.info("Cycles renders on the CPU.")


def parse_args() -> argparse.Namespace:
    """Parse the arguments after `--` on the Blender command line.

    Returns:
        The parsed arguments.
    """
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="render.py", description=__doc__)
    parser.add_argument("--scenes", type=Path, required=True, help="Scene JSON folder.")
    parser.add_argument("--out", type=Path, required=True, help="Output folder.")
    parser.add_argument("--tilesets", help="Comma-separated tileset ids to sample from.")
    parser.add_argument("--engine", choices=["eevee", "cycles", "mixed"], default="mixed")
    parser.add_argument(
        "--cycles-fraction",
        type=float,
        default=0.25,
        help="With `--engine mixed`, the fraction of images rendered with Cycles.",
    )
    parser.add_argument("--samples", type=int, default=48)
    parser.add_argument("--resolution", type=int, default=1024)
    parser.add_argument("--shard", default="0/1", help="Render every Nth scene: K/N.")
    parser.add_argument("--limit", type=int, help="Render at most this many scenes.")

    return parser.parse_args(argv)


def main() -> None:
    """Render the scenes of the command line."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = parse_args()
    shard, shards = (int(part) for part in args.shard.split("/"))
    tilesets = discover_tilesets(
        root=BLENDER_DIR / "tilesets",
        only=args.tilesets.split(",") if args.tilesets else None,
    )
    assets = RenderAssets.load(
        manifest=BLENDER_DIR / "assets.toml", cache=BLENDER_DIR / ".cache"
    )
    renderer = SceneRenderer(
        out=args.out,
        tilesets=tilesets,
        assets=assets,
        engine=args.engine,
        cycles_fraction=args.cycles_fraction,
        samples=args.samples,
        resolution=args.resolution,
    )
    paths = sorted(args.scenes.glob("*.json"))[shard::shards]

    if args.limit is not None:
        paths = paths[: args.limit]

    begin = time.perf_counter()
    rendered = 0

    for index, path in enumerate(paths):
        meta = renderer.render(path)

        if meta is None:
            continue

        rendered += 1
        elapsed = time.perf_counter() - begin
        logger.info(
            "[%d/%d] %s %s %s %s %.1f s (mean %.1f s)",
            index + 1,
            len(paths),
            meta["scene_id"],
            meta["engine"],
            meta["tileset_id"],
            meta["surface"],
            meta["render_s"],
            elapsed / rendered,
        )

    logger.info(
        "Rendered %d scenes in %d s.", rendered, math.ceil(time.perf_counter() - begin)
    )


if __name__ == "__main__":
    main()
