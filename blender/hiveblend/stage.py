"""The stage: table, lights, camera and tiles of one scene, rebuilt for every image.

The persistent objects (table, camera, world) are created once and changed per scene; the
tile objects are removed and recreated. Scene lengths are in tile widths and are scaled
by the across-flats width of the tileset.
"""

import math
import random
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from hiveblend.geometry import kelvin_to_rgb, offset_direction, srgb_to_linear
from hiveblend.tilesets import OWNER_NAMES, PIECE_NAMES, TileLibrary

SENSOR_MM = (34.6, 25.95)
"""The sensor of a 4:3 camera with 35 mm equivalent focal lengths, as in the scenes."""

PLAIN_SURFACE_COLORS = [
    "#F2F2EE",
    "#D9D4CB",
    "#B9B4AA",
    "#8C8780",
    "#3B3A38",
    "#1E1F22",
    "#2F4F3A",
    "#2C3E5C",
    "#7A4A32",
    "#C8B28E",
]
"""Colours of plain tables, felt mats and painted surfaces, as sRGB."""

FALLBACK_WOOD_COLORS = ["#8A5A35", "#A9744A", "#5C3A22", "#C79A68", "#3E2A1C"]
"""Colours of the procedural stand-in for wood when no wood textures are downloaded."""


@dataclass(slots=True)
class TileInstance:
    """A tile object of the scene and what its label needs.

    Attributes:
        instance_id: The id drawn into the instance map, from 1.
        obj: The Blender object.
        piece: The piece name.
        owner: The owner name.
        coord: The axial coordinate on the board, or `None` for a loose tile.
        level: The height in the stack, 0 for the bottom tile.
        labeled: Whether the tile shows its face: the top of a stack, or a loose tile
            that is not flipped.
    """

    instance_id: int
    obj: Any
    piece: str
    owner: str
    coord: tuple[int, int] | None
    level: int
    labeled: bool


@dataclass(slots=True)
class RenderAssets:
    """The downloaded surfaces and environments, by kind.

    Attributes:
        surfaces: The texture folders per surface kind.
        hdris: The environment files.
    """

    surfaces: dict[str, list[Path]]
    hdris: list[Path]

    @classmethod
    def load(cls, manifest: Path, cache: Path) -> "RenderAssets":
        """Find the assets of the manifest that are in the cache.

        Args:
            manifest: The `assets.toml` file.
            cache: The cache directory of `make render-assets`.

        Returns:
            The available assets; missing ones are left out.
        """
        config = tomllib.loads(manifest.read_text()) if manifest.exists() else {}
        surfaces = {
            kind: [
                cache / "surfaces" / asset_id
                for asset_id in asset_ids
                if (cache / "surfaces" / asset_id / "diffuse.jpg").exists()
            ]
            for kind, asset_ids in config.get("surfaces", {}).items()
        }
        hdris = [
            cache / "hdris" / f"{asset_id}.hdr"
            for asset_id in config.get("hdris", [])
            if (cache / "hdris" / f"{asset_id}.hdr").exists()
        ]

        return cls(surfaces=surfaces, hdris=hdris)


class Stage:
    """The Blender objects of a scene.

    Attributes:
        scene: The Blender scene.
        camera: The camera object.
        table: The table plane.
        assets: The downloaded surfaces and environments.
        tiles: The tile objects of the current scene.
        lights: The light objects of the current scene.
        images: Loaded images by path, kept between scenes.
    """

    def __init__(self, assets: RenderAssets) -> None:
        """Clear the default scene and create the table and the camera.

        Args:
            assets: The downloaded surfaces and environments.
        """
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj)

        self.scene = bpy.context.scene
        self.assets = assets
        self.tiles: list[TileInstance] = []
        self.lights: list[Any] = []
        self.images: dict[Path, Any] = {}

        camera_data = bpy.data.cameras.new("camera")
        camera_data.sensor_fit = "AUTO"
        camera_data.sensor_width = SENSOR_MM[0]
        camera_data.clip_start = 0.01
        camera_data.clip_end = 50.0
        self.camera = bpy.data.objects.new("camera", camera_data)
        self.scene.collection.objects.link(self.camera)
        self.scene.camera = self.camera

        table_mesh = bpy.data.meshes.new("table")
        size = 4.0
        table_mesh.from_pydata(
            [(-size, -size, 0), (size, -size, 0), (size, size, 0), (-size, size, 0)],
            [],
            [(0, 1, 2, 3)],
        )
        table_mesh.uv_layers.new(name="uv")

        for loop, uv in zip(
            table_mesh.uv_layers[0].data, [(0, 0), (1, 0), (1, 1), (0, 1)], strict=True
        ):
            loop.uv = (uv[0] * size * 2, uv[1] * size * 2)

        self.table = bpy.data.objects.new("table", table_mesh)
        self.scene.collection.objects.link(self.table)

        world = bpy.data.worlds.new("room")
        self.scene.world = world

    def clear(self) -> None:
        """Remove the tiles and lights of the previous scene."""
        for instance in self.tiles:
            bpy.data.objects.remove(instance.obj)

        for light in self.lights:
            data = light.data
            bpy.data.objects.remove(light)
            bpy.data.lights.remove(data)

        self.tiles = []
        self.lights = []

    def build_tiles(self, scene: dict[str, Any], library: TileLibrary) -> None:
        """Create the board and loose tile objects of a scene.

        Args:
            scene: The scene JSON.
            library: The tile meshes of the chosen tileset.
        """
        width = library.spec.across_flats_m
        thickness = library.spec.thickness_m

        for cell in scene["board"]:
            stack = cell["stack"]

            for level, (tile, jitter) in enumerate(
                zip(stack, cell["jitter"], strict=True)
            ):
                location = (
                    (cell["x"] + jitter["dx"]) * width,
                    (cell["y"] + jitter["dy"]) * width,
                    level * (thickness + 0.0002),
                )
                rotation = (0.0, 0.0, math.radians(60 * tile["turn"] + jitter["rot_deg"]))
                self.add_tile(
                    library=library,
                    piece=tile["piece"],
                    owner=tile["owner"],
                    location=location,
                    rotation=rotation,
                    coord=(cell["coord"][0], cell["coord"][1]),
                    level=level,
                    labeled=level == len(stack) - 1,
                )

        for loose in scene["loose_pieces"]:
            flipped = loose["flipped"]
            location = (
                loose["x"] * width,
                loose["y"] * width,
                thickness + 0.0004 if flipped else 0.0,
            )
            rotation = (math.pi if flipped else 0.0, 0.0, math.radians(loose["rot_deg"]))
            self.add_tile(
                library=library,
                piece=loose["piece"],
                owner=loose["owner"],
                location=location,
                rotation=rotation,
                coord=None,
                level=0,
                labeled=not flipped,
            )

    def add_tile(
        self,
        library: TileLibrary,
        piece: str,
        owner: str,
        location: tuple[float, float, float],
        rotation: tuple[float, float, float],
        coord: tuple[int, int] | None,
        level: int,
        labeled: bool,
    ) -> None:
        """Create one tile object.

        Args:
            library: The tile meshes of the chosen tileset.
            piece: The piece name.
            owner: The owner name.
            location: The position of the centre of the bottom face.
            rotation: The Euler rotation in radians.
            coord: The axial coordinate on the board, or `None` for a loose tile.
            level: The height in the stack.
            labeled: Whether the tile face is labeled.
        """
        assert piece in PIECE_NAMES and owner in OWNER_NAMES
        instance_id = len(self.tiles) + 1
        obj = bpy.data.objects.new(
            f"tile-{instance_id:03d}", library.mesh(owner=owner, piece=piece)
        )
        obj.location = location
        obj.rotation_euler = rotation
        obj.pass_index = instance_id
        self.scene.collection.objects.link(obj)
        self.tiles.append(
            TileInstance(
                instance_id=instance_id,
                obj=obj,
                piece=piece,
                owner=owner,
                coord=coord,
                level=level,
                labeled=labeled,
            )
        )

    def set_camera(
        self, camera: dict[str, Any], width: float, thickness: float, resolution: int
    ) -> tuple[int, int]:
        """Place the camera so the hive centre appears at the scene's frame offset.

        The camera first looks straight at the hive centre from its tilt and azimuth,
        then rolls, then turns so the centre moves to the offset, as when a phone is
        aimed slightly off the hive.

        Args:
            camera: The camera of the scene JSON.
            width: The tile width in metres.
            thickness: The tile thickness in metres.
            resolution: The long side of the image in pixels.

        Returns:
            The image size `(width, height)` in pixels.
        """
        short = round(resolution * SENSOR_MM[1] / SENSOR_MM[0])
        size = (short, resolution) if camera["portrait"] else (resolution, short)
        self.scene.render.resolution_x, self.scene.render.resolution_y = size
        self.scene.render.resolution_percentage = 100
        self.camera.data.lens = camera["focal_mm"]

        long_fov = 2 * math.atan(SENSOR_MM[0] / 2 / camera["focal_mm"])
        short_fov = 2 * math.atan(SENSOR_MM[1] / 2 / camera["focal_mm"])
        horizontal_fov, vertical_fov = (
            (short_fov, long_fov) if camera["portrait"] else (long_fov, short_fov)
        )

        target = Vector((0.0, 0.0, thickness))
        rotation = (
            Matrix.Rotation(math.radians(camera["azimuth_deg"] + 90), 4, "Z")
            @ Matrix.Rotation(math.radians(camera["tilt_deg"]), 4, "X")
            @ Matrix.Rotation(math.radians(camera["roll_deg"]), 4, "Z")
        )
        location = target + rotation.to_3x3() @ Vector((0, 0, camera["distance"] * width))
        desired = Vector(
            offset_direction(
                offset=(camera["frame_offset"][0], camera["frame_offset"][1]),
                horizontal_fov=horizontal_fov,
                vertical_fov=vertical_fov,
            )
        )
        turn: Quaternion = Vector((0.0, 0.0, -1.0)).rotation_difference(desired)
        rotation = rotation @ turn.inverted().to_matrix().to_4x4()
        self.camera.matrix_world = Matrix.Translation(location) @ rotation

        return size

    def set_surface(self, background: dict[str, Any], rng: random.Random) -> str:
        """Give the table a downloaded surface of the scene's kind, or a plain one.

        Args:
            background: The background of the scene JSON.
            rng: The random number generator of the scene.

        Returns:
            The name of the surface: the asset id, or `plain` or `procedural-wood`.
        """
        variant = random.Random(background["variant_seed"])
        candidates = self.assets.surfaces.get(background["surface"], [])
        material = bpy.data.materials.new("table")
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        bsdf = nodes["Principled BSDF"]

        if candidates:
            folder = variant.choice(candidates)
            name = folder.name
            coords = nodes.new("ShaderNodeTexCoord")
            mapping = nodes.new("ShaderNodeMapping")
            scale = 1.0 / background["scale"]
            mapping.inputs["Scale"].default_value = (scale, scale, 1.0)
            mapping.inputs["Rotation"].default_value = (
                0.0,
                0.0,
                math.radians(background["rotation_deg"]),
            )
            mapping.inputs["Location"].default_value = (
                variant.random(),
                variant.random(),
                0.0,
            )
            links.new(coords.outputs["UV"], mapping.inputs["Vector"])

            diffuse = self.texture(nodes=nodes, path=folder / "diffuse.jpg", color=True)
            links.new(mapping.outputs["Vector"], diffuse.inputs["Vector"])
            tint = nodes.new("ShaderNodeHueSaturation")
            tint.inputs["Hue"].default_value = 0.5 + variant.uniform(-0.03, 0.03)
            tint.inputs["Saturation"].default_value = variant.uniform(0.75, 1.2)
            tint.inputs["Value"].default_value = variant.uniform(0.7, 1.25)
            links.new(diffuse.outputs["Color"], tint.inputs["Color"])
            links.new(tint.outputs["Color"], bsdf.inputs["Base Color"])

            rough = self.texture(nodes=nodes, path=folder / "roughness.jpg", color=False)
            links.new(mapping.outputs["Vector"], rough.inputs["Vector"])
            links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])

            normal_map = self.texture(
                nodes=nodes, path=folder / "normal.jpg", color=False
            )
            links.new(mapping.outputs["Vector"], normal_map.inputs["Vector"])
            normal = nodes.new("ShaderNodeNormalMap")
            normal.inputs["Strength"].default_value = variant.uniform(0.4, 1.0)
            links.new(normal_map.outputs["Color"], normal.inputs["Color"])
            links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
        else:
            is_wood = background["surface"] == "wood"
            name = "procedural-wood" if is_wood else "plain"
            palette = FALLBACK_WOOD_COLORS if is_wood else PLAIN_SURFACE_COLORS
            color = variant.choice(palette).lstrip("#")
            linear = [srgb_to_linear(int(color[i : i + 2], 16) / 255) for i in (0, 2, 4)]
            noise = nodes.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = variant.uniform(5.0, 60.0)
            noise.inputs["Detail"].default_value = 6.0
            ramp = nodes.new("ShaderNodeValToRGB")
            ramp.color_ramp.elements[0].color = (*[c * 0.85 for c in linear], 1.0)
            ramp.color_ramp.elements[1].color = (
                *[min(c * 1.15, 1.0) for c in linear],
                1.0,
            )
            links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
            links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
            bsdf.inputs["Roughness"].default_value = variant.uniform(0.3, 0.9)

        old = self.table.data.materials[0] if self.table.data.materials else None
        self.table.data.materials.clear()
        self.table.data.materials.append(material)

        if old is not None:
            bpy.data.materials.remove(old)

        rng.random()

        return name

    def texture(self, nodes: Any, path: Path, color: bool) -> Any:
        """Add an image texture node, loading the image once per stage.

        Args:
            nodes: The node collection of the material.
            path: The image file.
            color: Whether the image holds colours (sRGB) rather than data.

        Returns:
            The texture node.
        """
        if path not in self.images:
            image = bpy.data.images.load(str(path))
            image.colorspace_settings.name = "sRGB" if color else "Non-Color"
            self.images[path] = image

        node = nodes.new("ShaderNodeTexImage")
        node.image = self.images[path]

        return node

    def set_lighting(
        self, lighting: dict[str, Any], width: float, rng: random.Random
    ) -> str:
        """Create the lights of the scene's preset and the room light around it.

        Args:
            lighting: The lighting of the scene JSON.
            width: The tile width in metres, to place the flash at the camera.
            rng: The random number generator of the scene.

        Returns:
            The name of the environment: an HDRI id or `plain`.
        """
        preset = lighting["preset"]
        intensity = lighting["intensity"]
        color = kelvin_to_rgb(lighting["color_temp_k"])
        direction = math.radians(lighting["direction_deg"])
        elevation = math.radians(lighting["elevation_deg"])
        environment = self.set_world(
            strength=lighting["environment_strength"]
            * (1.8 if preset == "environment" else 0.4),
            rng=rng,
        )

        def aim(obj: Any, distance: float) -> None:
            """Place a light in the preset direction and point it at the hive.

            Args:
                obj: The light object.
                distance: The distance from the hive centre in metres.
            """
            obj.location = (
                distance * math.cos(elevation) * math.cos(direction),
                distance * math.cos(elevation) * math.sin(direction),
                distance * math.sin(elevation),
            )
            obj.rotation_euler = (
                (Vector((0, 0, 0)) - obj.location).to_track_quat("-Z", "Y").to_euler()
            )

        if preset == "window":
            light = self.add_light(kind="AREA", color=color, energy=500 * intensity)
            light.data.shape = "RECTANGLE"
            light.data.size = rng.uniform(1.0, 2.0)
            light.data.size_y = rng.uniform(0.8, 1.6)
            aim(obj=light, distance=2.5)
        elif preset == "ceiling":
            count = rng.randint(1, 3)

            for _ in range(count):
                light = self.add_light(
                    kind="AREA", color=color, energy=160 * intensity / count
                )
                light.data.size = rng.uniform(0.3, 0.9)
                light.location = (rng.uniform(-1.2, 1.2), rng.uniform(-1.2, 1.2), 2.0)
                light.rotation_euler = (0.0, 0.0, 0.0)
        elif preset == "lamp":
            light = self.add_light(kind="POINT", color=color, energy=80 * intensity)
            light.data.shadow_soft_size = rng.uniform(0.01, 0.08)
            aim(obj=light, distance=rng.uniform(0.6, 1.2))
        elif preset == "flash":
            light = self.add_light(kind="POINT", color=(1.0, 0.97, 0.92), energy=1.0)
            offset = self.camera.matrix_world.to_3x3() @ Vector((0.012, 0.02, 0.0))
            light.location = self.camera.matrix_world.translation + offset
            distance = self.camera.matrix_world.translation.length
            light.data.energy = 35 * intensity * distance**2
            light.data.shadow_soft_size = 0.003

        return environment

    def add_light(
        self, kind: str, color: tuple[float, float, float], energy: float
    ) -> Any:
        """Create a light object.

        Args:
            kind: The Blender light type, for example `AREA`.
            color: The linear light colour.
            energy: The power in watts.

        Returns:
            The light object, linked to the scene.
        """
        data = bpy.data.lights.new(f"light-{len(self.lights)}", kind)
        data.color = color
        data.energy = energy
        obj = bpy.data.objects.new(data.name, data)
        self.scene.collection.objects.link(obj)
        self.lights.append(obj)

        return obj

    def set_world(self, strength: float, rng: random.Random) -> str:
        """Light the room with a downloaded environment, or a plain one.

        Args:
            strength: The brightness of the environment.
            rng: The random number generator of the scene.

        Returns:
            The HDRI id, or `plain`.
        """
        world = self.scene.world
        nodes = world.node_tree.nodes
        links = world.node_tree.links
        background = nodes["Background"]
        background.inputs["Strength"].default_value = strength

        for node in list(nodes):
            if node.type in ("TEX_ENVIRONMENT", "MAPPING", "TEX_COORD"):
                nodes.remove(node)

        if not self.assets.hdris:
            tone = rng.uniform(0.5, 0.9)
            background.inputs["Color"].default_value = (tone, tone * 0.97, tone * 0.93, 1)

            return "plain"

        path = rng.choice(self.assets.hdris)

        if path not in self.images:
            self.images[path] = bpy.data.images.load(str(path))

        coords = nodes.new("ShaderNodeTexCoord")
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Rotation"].default_value = (0.0, 0.0, rng.uniform(0, 2 * math.pi))
        environment = nodes.new("ShaderNodeTexEnvironment")
        environment.image = self.images[path]
        links.new(coords.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
        links.new(environment.outputs["Color"], background.inputs["Color"])

        return path.stem

    def project(self, point: Vector) -> tuple[float, float]:
        """Project a world point into the image.

        Args:
            point: The point in world coordinates.

        Returns:
            The pixel position `(x, y)` with the origin at the top left; it may lie
            outside the image.
        """
        from bpy_extras.object_utils import world_to_camera_view

        ndc = world_to_camera_view(self.scene, self.camera, point)
        render = self.scene.render

        return ndc.x * render.resolution_x, (1.0 - ndc.y) * render.resolution_y

    def label_polygon(
        self, instance: TileInstance, outline: list[tuple[float, float]], top: float
    ) -> list[tuple[float, float]]:
        """Project the outline of a tile's top face into the image.

        Args:
            instance: The tile.
            outline: The outline of the top face around the tile centre, in metres.
            top: The height of the top face above the tile origin.

        Returns:
            The projected outline in pixels.
        """
        matrix = instance.obj.matrix_world

        return [self.project(matrix @ Vector((x, y, top))) for x, y in outline]


def euler_degrees(rotation: Euler) -> list[float]:
    """Convert an Euler rotation to degrees for the metadata.

    Args:
        rotation: The rotation.

    Returns:
        The angles in degrees.
    """
    return [math.degrees(angle) for angle in rotation]
