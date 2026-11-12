# Blender renderer

Renders the scene JSON files of `hive data scenes` into photos, tile instance maps and
label metadata, for the synthetic YOLO datasets (see `docs/plans/synthetic-data.md`).

The code runs under Blender's bundled Python and does not import `hive`:

- `render.py`: the command line entry point and the per-scene render loop.
- `hiveblend/stage.py`: table, lights, camera and tiles of a scene.
- `hiveblend/tilesets.py`: tileset manifests, and the procedural bakelite tiles.
- `hiveblend/geometry.py`: geometry and colour math without `bpy`, tested in
  `tests/blender/`.
- `tilesets/<id>/tileset.toml`: one folder per physical tileset.
- `assets.toml`: the CC0 table surfaces and room environments from Poly Haven.

## Setup

- Blender **5.3** (tested with 5.3.0). Older 4.x versions lack parts of the API used here.
- `make render-assets` downloads the surfaces and environments (about 230 MB) into
  `blender/.cache/`, which is not committed. Without them the renderer falls back to
  plain procedural tables and a plain room light.
- GPU: Cycles uses OptiX, CUDA, HIP or oneAPI when Blender finds a GPU, and otherwise
  every CPU thread. EEVEE uses the GPU through OpenGL or Vulkan, also headless with `-b`.
  On a laptop with an NVIDIA GPU, the NVIDIA kernel module must be loaded
  (`nvidia-smi` works) for Cycles to use it.

## Running

```
uv run hive data scenes --count 1000 --seed 2026 --out data/synth/scenes
blender -b --factory-startup -P blender/render.py -- \
    --scenes data/synth/scenes --out data/synth/renders \
    [--engine mixed] [--cycles-fraction 0.25] [--samples 48] [--resolution 1024] \
    [--tilesets bakelite-procedural-001] [--shard 0/2] [--limit 10]
uv run hive data export --renders data/synth/renders --version v001 --debug 20
```

- `--engine`: `eevee` (fast), `cycles` (path traced) or `mixed`, which renders
  `--cycles-fraction` of the images with Cycles for variety.
- `--shard K/N` renders every Nth scene, so N Blender processes can share a batch.
- Scenes that already have metadata are skipped, so an interrupted batch resumes.
- `make render-smoke` renders and exports three scenes into `tmp/render-smoke/`, with the
  labels drawn in `tmp/render-smoke/synth-smoke/debug/`.

On a Ryzen 7 5800H without a usable discrete GPU, a 1024 × 768 image takes about 3 s with
EEVEE and 15–30 s with Cycles; two processes with 10% Cycles render about 1000 images in
50 minutes.

## Output

Per scene, in the `--out` folder:

- `images/<id>.png`: the photo, before the post effects of the scene (blur, sensor noise,
  JPEG), which `hive data export` applies.
- `instances/<id>.png`: the tile instance map, rendered with flat colours and no
  anti-aliasing: tile pixels have blue 255 and the instance id in red (low byte) and
  green (high byte).
- `meta/<id>.json`: the tileset, engine, surface, environment, exposure, camera, the
  board, and per tile its class, board coordinate, stack level and the projected outline
  of its top face. Written last, so it marks a complete render.

Per image the renderer picks a tileset by weight, varies the materials, and meters the
exposure on a small EEVEE preview to a random target brightness, as a phone camera does.

## Tilesets

A tileset is a folder with a `tileset.toml`; adding a folder adds it to the renders
without code changes. Detection classes do not depend on the tileset.

- `bakelite-procedural-001`: built in code. Hexagonal slabs with 20 mm sides (34.6 mm
  across flats) and 10 mm high, rounded corners and soft edges, with the insect artwork
  of `src/hive/assets/svg/` debossed 0.6 mm into the top face and painted.
- `pocket-edition-normal-001`: a template (weight 0) documenting what the modelled tiles
  must contain. It is enabled by modelling the tiles and setting its weight.
