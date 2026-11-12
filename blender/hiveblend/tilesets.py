"""Tilesets: discovery from `tileset.toml` manifests, and the tile meshes and materials.

A tileset is a folder under `blender/tilesets/` with a `tileset.toml`. Two kinds exist:

- `procedural`: the tiles are built here from the measured sizes in the manifest, as
  bakelite slabs with rounded corners and soft edges, and the insect artwork of
  `src/hive/assets/svg/` debossed into the top face.
- `blend`: every tile is an object in its own `.blend` file, as listed under `[tiles]`.
  The object has its origin at the centre of the bottom face and is scaled in metres.
"""

import math
import random
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bmesh
import bpy

from hiveblend.geometry import hex_to_linear_rgb, rounded_hexagon, shift_color

PIECE_NAMES = ("queen", "beetle", "grasshopper", "spider", "ant")
"""The piece names in class order, matching the engine `PieceType` values."""

OWNER_NAMES = ("white", "black")
"""The owner names in class order, matching the engine `Player` values."""

INSECT_SVG_COLORS = {
    "queen": "#FECB4D",
    "beetle": "#BCB0EB",
    "grasshopper": "#6FCF57",
    "spider": "#A8695A",
    "ant": "#70B6D7",
}
"""The fill colours of the insect artwork, used when a manifest does not set them."""


@dataclass(slots=True)
class TilesetSpec:
    """The manifest of a tileset, read from its `tileset.toml`.

    Attributes:
        id: The unique tileset id, also its folder name.
        name: A readable name.
        kind: `procedural` or `blend`.
        weight: The relative sampling weight of the tileset.
        across_flats_mm: The width of a tile between two opposite sides.
        thickness_mm: The height of a tile.
        corner_radius_mm: The radius of the rounded vertical corners.
        edge_radius_mm: The radius of the soft top and bottom edges.
        deboss_mm: How deep the insect artwork is cut into the top face.
        insect_size: The height of the insect artwork as a fraction of `across_flats_mm`.
        body_colors: The sRGB body colour per owner name as `#rrggbb`.
        insect_colors: The sRGB paint colour per piece name as `#rrggbb`.
        materials: The randomisation ranges of the materials, such as `roughness`.
        tiles: For `blend` tilesets, the file and object name per `owner-piece` key.
        path: The folder of the tileset.
    """

    id: str
    name: str
    kind: str
    weight: float
    across_flats_mm: float
    thickness_mm: float
    corner_radius_mm: float
    edge_radius_mm: float
    deboss_mm: float
    insect_size: float
    body_colors: dict[str, str]
    insect_colors: dict[str, str]
    materials: dict[str, list[float]]
    tiles: dict[str, dict[str, str]]
    path: Path

    @classmethod
    def load(cls, path: Path) -> "TilesetSpec":
        """Read a tileset manifest.

        Args:
            path: The path of the `tileset.toml` file.

        Returns:
            The manifest, with defaults for optional keys.

        Raises:
            ValueError: If the kind is unknown or a `blend` tileset misses a tile.
        """
        data: dict[str, Any] = tomllib.loads(path.read_text())
        spec = cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            kind=data.get("kind", "blend"),
            weight=float(data.get("weight", 1.0)),
            across_flats_mm=float(data["across_flats_mm"]),
            thickness_mm=float(data["thickness_mm"]),
            corner_radius_mm=float(data.get("corner_radius_mm", 2.0)),
            edge_radius_mm=float(data.get("edge_radius_mm", 1.0)),
            deboss_mm=float(data.get("deboss_mm", 0.5)),
            insect_size=float(data.get("insect_size", 0.6)),
            body_colors=dict(data.get("body_colors", {})),
            insect_colors={**INSECT_SVG_COLORS, **data.get("insect_colors", {})},
            materials=dict(data.get("materials", {})),
            tiles=dict(data.get("tiles", {})),
            path=path.parent,
        )

        if spec.kind not in ("procedural", "blend"):
            msg = f"Tileset `{spec.id}` has unknown kind `{spec.kind}`."
            raise ValueError(msg)

        # A `blend` tileset with weight 0 is a template whose files are not modelled yet.
        if spec.kind == "blend" and spec.weight > 0:
            missing = [
                f"{owner}-{piece}"
                for owner in OWNER_NAMES
                for piece in PIECE_NAMES
                if f"{owner}-{piece}" not in spec.tiles
            ]

            if missing:
                msg = f"Tileset `{spec.id}` misses tiles: {', '.join(missing)}."
                raise ValueError(msg)

        return spec

    @property
    def across_flats_m(self) -> float:
        """The width of a tile between two opposite sides in metres."""
        return self.across_flats_mm / 1000

    @property
    def thickness_m(self) -> float:
        """The height of a tile in metres."""
        return self.thickness_mm / 1000

    def top_outline(self, corner_segments: int) -> list[tuple[float, float]]:
        """Get the outline of the flat top face, inside the soft edge, in metres.

        Args:
            corner_segments: The number of segments per rounded corner.

        Returns:
            The outline points around the tile centre, anti-clockwise.
        """
        return rounded_hexagon(
            apothem=self.across_flats_m / 2,
            corner_radius=self.corner_radius_mm / 1000,
            corner_segments=corner_segments,
        )

    def sample_range(self, key: str, default: list[float], rng: random.Random) -> float:
        """Sample a value uniformly from a randomisation range of the manifest.

        Args:
            key: The key in the `[materials]` table, for example `roughness`.
            default: The range `[low, high]` used when the manifest does not set it.
            rng: The random number generator.

        Returns:
            The sampled value.
        """
        low, high = self.materials.get(key, default)

        return rng.uniform(low, high)


def discover_tilesets(root: Path, only: list[str] | None) -> list[TilesetSpec]:
    """Find the tilesets in the subfolders of a directory.

    Args:
        root: The directory holding one folder per tileset.
        only: The tileset ids to keep, or `None` for all of them.

    Returns:
        The tilesets ordered by id.

    Raises:
        ValueError: If no tileset is found, or a requested id does not exist.
    """
    specs = [TilesetSpec.load(path) for path in sorted(root.glob("*/tileset.toml"))]
    specs = [spec for spec in specs if spec.weight > 0]

    if only is not None:
        unknown = sorted(set(only) - {spec.id for spec in specs})

        if unknown:
            msg = f"Unknown or disabled tilesets: {', '.join(unknown)}."
            raise ValueError(msg)

        specs = [spec for spec in specs if spec.id in only]

    if not specs:
        msg = f"No tilesets found under `{root}`."
        raise ValueError(msg)

    return specs


@dataclass(slots=True)
class TileLibrary:
    """The tile meshes and materials of one tileset, built once and shared by all tiles.

    Attributes:
        spec: The tileset manifest.
        svg_dir: The folder with the insect artwork.
        meshes: The tile mesh per `(owner, piece)` name pair.
        body_materials: The body material per owner name.
        paint_materials: The insect paint material per piece name.
    """

    spec: TilesetSpec
    svg_dir: Path
    meshes: dict[tuple[str, str], Any] = field(default_factory=dict)
    body_materials: dict[str, Any] = field(default_factory=dict)
    paint_materials: dict[str, Any] = field(default_factory=dict)

    def mesh(self, owner: str, piece: str) -> Any:
        """Get the mesh of a tile, building or loading it on first use.

        Args:
            owner: The owner name, `white` or `black`.
            piece: The piece name, for example `ant`.

        Returns:
            The mesh, shared by every tile object of this owner and piece.
        """
        key = (owner, piece)

        if key not in self.meshes:
            if self.spec.kind == "procedural":
                self.meshes[key] = self.build_procedural_mesh(owner=owner, piece=piece)
            else:
                self.meshes[key] = self.load_blend_mesh(owner=owner, piece=piece)

        return self.meshes[key]

    def vary_materials(self, rng: random.Random) -> None:
        """Randomise the material parameters for the next image.

        Only procedural materials are varied; a `blend` tileset keeps the materials of
        its files. Besides the finish, the body and paint colours shift slightly, as
        between sets, prints and white balances; the hue shift of the paint stays small
        enough that no insect takes the colour of another.

        Args:
            rng: The random number generator of the scene.
        """
        if self.spec.kind != "procedural":
            return

        roughness = self.spec.sample_range(key="roughness", default=[0.22, 0.5], rng=rng)
        coat = self.spec.sample_range(key="coat", default=[0.0, 0.5], rng=rng)
        bump = self.spec.sample_range(key="bump_strength", default=[0.02, 0.12], rng=rng)
        scuff = self.spec.sample_range(key="scuff_strength", default=[0.0, 0.35], rng=rng)
        paint_roughness = self.spec.sample_range(
            key="paint_roughness", default=[0.35, 0.65], rng=rng
        )

        for owner in OWNER_NAMES:
            nodes = self.body_material(owner).node_tree.nodes
            color = shift_color(
                color=self.body_hex(owner),
                hue_shift=rng.uniform(-0.02, 0.02),
                saturation_scale=rng.uniform(0.6, 1.5),
                value_scale=rng.uniform(0.9, 1.08),
            )
            nodes["Principled BSDF"].inputs["Base Color"].default_value = (*color, 1.0)
            nodes["roughness"].outputs[0].default_value = roughness
            nodes["scuff"].outputs[0].default_value = scuff
            nodes["Principled BSDF"].inputs["Coat Weight"].default_value = coat
            nodes["Bump"].inputs["Strength"].default_value = bump

        for piece in PIECE_NAMES:
            bsdf = self.paint_material(piece).node_tree.nodes["Principled BSDF"]
            color = shift_color(
                color=self.spec.insect_colors[piece],
                hue_shift=rng.uniform(-0.035, 0.035),
                saturation_scale=rng.uniform(0.8, 1.3),
                value_scale=rng.uniform(0.75, 1.15),
            )
            bsdf.inputs["Base Color"].default_value = (*color, 1.0)
            bsdf.inputs["Roughness"].default_value = paint_roughness

    def body_hex(self, owner: str) -> str:
        """Get the sRGB body colour of an owner from the manifest or the default.

        Args:
            owner: The owner name.

        Returns:
            The colour as `#rrggbb`.
        """
        default = "#EFE8D6" if owner == "white" else "#1C1C1E"

        return self.spec.body_colors.get(owner, default)

    def body_material(self, owner: str) -> Any:
        """Get the bakelite material of an owner, building it on first use.

        Args:
            owner: The owner name.

        Returns:
            The material.
        """
        if owner not in self.body_materials:
            color = hex_to_linear_rgb(self.body_hex(owner))
            self.body_materials[owner] = build_bakelite_material(
                name=f"{self.spec.id}-{owner}-body", color=color
            )

        return self.body_materials[owner]

    def paint_material(self, piece: str) -> Any:
        """Get the insect paint material of a piece, building it on first use.

        Args:
            piece: The piece name.

        Returns:
            The material.
        """
        if piece not in self.paint_materials:
            color = hex_to_linear_rgb(self.spec.insect_colors[piece])
            self.paint_materials[piece] = build_paint_material(
                name=f"{self.spec.id}-{piece}-paint", color=color
            )

        return self.paint_materials[piece]

    def build_procedural_mesh(self, owner: str, piece: str) -> Any:
        """Build a bakelite tile with rounded corners, soft edges and a debossed insect.

        The origin is the centre of the bottom face and the top face is at the tile
        thickness. The insect is cut `deboss_mm` deep into the top face with a boolean
        difference, and the recess is painted.

        Args:
            owner: The owner name, which picks the body material.
            piece: The piece name, which picks the artwork and the paint material.

        Returns:
            The mesh, with the body as material 0 and the painted recess as material 1.
        """
        spec = self.spec
        bm = bmesh.new()
        build_slab(
            bm=bm,
            apothem=spec.across_flats_m / 2,
            corner_radius=spec.corner_radius_mm / 1000,
            edge_radius=spec.edge_radius_mm / 1000,
            thickness=spec.thickness_m,
        )
        slab_mesh = bpy.data.meshes.new("slab")
        bm.to_mesh(slab_mesh)
        bm.free()
        slab_mesh.materials.append(self.body_material(owner))
        cutter_mesh = build_insect_cutter(
            svg_path=self.svg_dir / f"{piece}.svg",
            height=spec.insect_size * spec.across_flats_m,
            top=spec.thickness_m,
            depth=spec.deboss_mm / 1000,
        )
        cutter_mesh.materials.append(self.paint_material(piece))

        slab = bpy.data.objects.new("slab", slab_mesh)
        cutter = bpy.data.objects.new("cutter", cutter_mesh)
        collection = bpy.context.scene.collection
        collection.objects.link(slab)
        collection.objects.link(cutter)
        boolean = slab.modifiers.new("deboss", "BOOLEAN")
        boolean.operation = "DIFFERENCE"
        boolean.solver = "EXACT"
        boolean.material_mode = "TRANSFER"
        boolean.object = cutter
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        mesh = bpy.data.meshes.new_from_object(slab.evaluated_get(depsgraph))
        mesh.name = f"{spec.id}-{owner}-{piece}"

        bpy.data.objects.remove(slab)
        bpy.data.objects.remove(cutter)
        bpy.data.meshes.remove(slab_mesh)
        bpy.data.meshes.remove(cutter_mesh)

        return mesh

    def load_blend_mesh(self, owner: str, piece: str) -> Any:
        """Load the mesh of a tile from the `.blend` file listed in the manifest.

        Args:
            owner: The owner name.
            piece: The piece name.

        Returns:
            The mesh of the listed object, with the materials of the file.

        Raises:
            ValueError: If the file does not hold the listed object or it has no mesh.
        """
        entry = self.spec.tiles[f"{owner}-{piece}"]
        object_name = entry.get("object", "tile")

        with bpy.data.libraries.load(str(self.spec.path / entry["file"])) as (src, dst):
            if object_name not in src.objects:
                msg = f"`{entry['file']}` has no object `{object_name}`."
                raise ValueError(msg)

            dst.objects = [object_name]

        loaded = dst.objects[0]

        if loaded is None or loaded.type != "MESH":
            msg = f"`{entry['file']}` object `{object_name}` is not a mesh."
            raise ValueError(msg)

        mesh = loaded.data
        bpy.data.objects.remove(loaded)

        return mesh


def build_slab(
    bm: Any, apothem: float, corner_radius: float, edge_radius: float, thickness: float
) -> None:
    """Add a hexagonal slab with rounded corners and quarter-round top and bottom edges.

    The slab is built from rings of the rounded outline: each ring along a soft edge is
    the outline shrunk by the edge profile, so the edge is a quarter circle everywhere.

    Args:
        bm: The bmesh to add the slab to, with material index 0.
        apothem: Half the across-flats width.
        corner_radius: The radius of the rounded vertical corners.
        edge_radius: The radius of the soft top and bottom edges, at most the corner
            radius and half the thickness.
        thickness: The height of the slab.
    """
    edge_radius = min(edge_radius, corner_radius, thickness / 2)
    edge_steps = 5
    corner_segments = 6
    # Each ring is an inset and a height: the bottom edge from the bottom face up, then
    # the top edge up to the top face.
    profile: list[tuple[float, float]] = []

    for step in range(edge_steps + 1):
        angle = math.pi / 2 * step / edge_steps
        profile.append(
            (edge_radius * (1 - math.sin(angle)), edge_radius * (1 - math.cos(angle)))
        )

    for step in range(edge_steps + 1):
        angle = math.pi / 2 * step / edge_steps
        profile.append(
            (
                edge_radius * (1 - math.cos(angle)),
                thickness - edge_radius + edge_radius * math.sin(angle),
            )
        )

    rings = []

    for inset, height in profile:
        outline = rounded_hexagon(
            apothem=apothem - inset,
            corner_radius=corner_radius - inset,
            corner_segments=corner_segments,
        )
        rings.append([bm.verts.new((x, y, height)) for x, y in outline])

    for lower, upper in zip(rings, rings[1:], strict=False):
        count = len(lower)

        for index in range(count):
            face = bm.faces.new(
                (
                    lower[index],
                    lower[(index + 1) % count],
                    upper[(index + 1) % count],
                    upper[index],
                )
            )
            face.smooth = True

    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])


def load_insect_mesh(svg_path: Path) -> Any:
    """Import insect artwork as a flat, filled mesh.

    Args:
        svg_path: The SVG file of the insect.

    Returns:
        A mesh in the xy plane in the units of the SVG importer, with holes kept.
    """
    before = set(bpy.data.objects)
    bpy.ops.import_curve.svg(filepath=str(svg_path))
    imported = [obj for obj in bpy.data.objects if obj not in before]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()

    for obj in imported:
        obj.data.dimensions = "2D"
        obj.data.fill_mode = "BOTH"
        obj.data.resolution_u = 8

    depsgraph.update()

    for obj in imported:
        evaluated = obj.evaluated_get(depsgraph)
        flat = bpy.data.meshes.new_from_object(evaluated)
        flat.transform(obj.matrix_world)
        bm.from_mesh(flat)
        bpy.data.meshes.remove(flat)
        curve = obj.data
        bpy.data.objects.remove(obj)
        bpy.data.curves.remove(curve)

    # The importer adds a material per fill colour, which the tile does not use.
    for material in list(bpy.data.materials):
        if material.name.startswith("SVGMat") and material.users == 0:
            bpy.data.materials.remove(material)

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
    mesh = bpy.data.meshes.new(f"insect-{svg_path.stem}")
    bm.to_mesh(mesh)
    bm.free()

    return mesh


def build_insect_cutter(svg_path: Path, height: float, top: float, depth: float) -> Any:
    """Build the solid insect shape that is cut out of the top face of a tile.

    The flat artwork is centred, scaled to `height` along y, and extruded from `depth`
    below the top face to above it, so the boolean difference leaves a recess of that
    depth.

    Args:
        svg_path: The SVG file of the insect.
        height: The height of the artwork along y in metres.
        top: The height of the top face of the tile.
        depth: The depth of the recess.

    Returns:
        A closed mesh with outward normals.
    """
    flat = load_insect_mesh(svg_path)
    bm = bmesh.new()
    bm.from_mesh(flat)
    bpy.data.meshes.remove(flat)
    xs = [vert.co.x for vert in bm.verts]
    ys = [vert.co.y for vert in bm.verts]
    centre_x = (min(xs) + max(xs)) / 2
    centre_y = (min(ys) + max(ys)) / 2
    scale = height / (max(ys) - min(ys))

    for vert in bm.verts:
        vert.co.x = (vert.co.x - centre_x) * scale
        vert.co.y = (vert.co.y - centre_y) * scale
        vert.co.z = top - depth

    extruded = bmesh.ops.extrude_face_region(bm, geom=list(bm.faces))

    for elem in extruded["geom"]:
        if isinstance(elem, bmesh.types.BMVert):
            elem.co.z = top + 0.001

    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    mesh = bpy.data.meshes.new(f"cutter-{svg_path.stem}")
    bm.to_mesh(mesh)
    bm.free()

    return mesh


def build_bakelite_material(name: str, color: tuple[float, float, float]) -> Any:
    """Build a polished phenolic resin material with fine surface texture and scuffs.

    Texture coordinates are offset per object, so tiles sharing a mesh still differ.

    Args:
        name: The material name.
        color: The linear base colour.

    Returns:
        The material, with value nodes `roughness` and `scuff` and a `Bump` node that
        `TileLibrary.vary_materials` changes per image.
    """
    material = bpy.data.materials.new(name)
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Coat Roughness"].default_value = 0.08
    bsdf.inputs["Specular IOR Level"].default_value = 0.5

    coords = nodes.new("ShaderNodeTexCoord")
    info = nodes.new("ShaderNodeObjectInfo")
    offset = nodes.new("ShaderNodeVectorMath")
    offset.operation = "MULTIPLY_ADD"
    offset.inputs[1].default_value = (100.0, 100.0, 100.0)
    links.new(info.outputs["Random"], offset.inputs[0])
    links.new(coords.outputs["Object"], offset.inputs[2])

    # A fine noise gives the moulded surface its slightly uneven sheen.
    fine = nodes.new("ShaderNodeTexNoise")
    fine.inputs["Scale"].default_value = 900.0
    fine.inputs["Detail"].default_value = 4.0
    links.new(offset.outputs[0], fine.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.name = "Bump"
    bump.inputs["Distance"].default_value = 0.00005
    links.new(fine.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Coarse noise thresholded into patches makes scuffs rougher than the polish.
    coarse = nodes.new("ShaderNodeTexNoise")
    coarse.inputs["Scale"].default_value = 60.0
    coarse.inputs["Detail"].default_value = 8.0
    links.new(offset.outputs[0], coarse.inputs["Vector"])
    ramp = nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = 0.55
    ramp.inputs["From Max"].default_value = 0.75
    links.new(coarse.outputs["Fac"], ramp.inputs["Value"])

    roughness = nodes.new("ShaderNodeValue")
    roughness.name = "roughness"
    roughness.outputs[0].default_value = 0.3
    scuff = nodes.new("ShaderNodeValue")
    scuff.name = "scuff"
    scuff.outputs[0].default_value = 0.2
    scuffed = nodes.new("ShaderNodeMath")
    scuffed.operation = "MULTIPLY_ADD"
    links.new(ramp.outputs["Result"], scuffed.inputs[0])
    links.new(scuff.outputs[0], scuffed.inputs[1])
    links.new(roughness.outputs[0], scuffed.inputs[2])
    links.new(scuffed.outputs[0], bsdf.inputs["Roughness"])

    return material


def build_paint_material(name: str, color: tuple[float, float, float]) -> Any:
    """Build the satin paint of the insect relief.

    Args:
        name: The material name.
        color: The linear paint colour.

    Returns:
        The material.
    """
    material = bpy.data.materials.new(name)
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.5

    return material
