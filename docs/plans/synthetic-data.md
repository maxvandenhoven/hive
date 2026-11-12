# Synthetic data

Synthetic images train the YOLO detector. The engine generates valid boards; Blender
renders them with randomised cameras, lighting, surfaces and tilesets; the export labels
them into a YOLO dataset with metadata. Everything runs locally on the workstation (Cycles
and EEVEE, Ultralytics on CUDA when the GPU is available, otherwise on the CPU).

```
hive data scenes --count 1000 --seed 2026 --out data/synth/scenes   (Python 3.13, engine)
        │  scene JSON files
        ▼
blender -b --factory-startup -P blender/render.py -- --scenes data/synth/scenes \
    --out data/synth/renders [--engine mixed] [--tilesets a,b] [--shard K/N]
        │  photos + tile instance maps + metadata
        ▼
hive data export --renders data/synth/renders --version v001 [--task segment|detect]
        │  data/synth/datasets/synth-v001/ (Ultralytics layout, manifest)
        ▼
uv run python scripts/train/train_yolo.py --dataset data/synth/datasets/synth-v001 --version v001
        │  data/models/hive-yolo/v001/model.onnx
        ▼
hive vision detect photo.jpg --model data/models/hive-yolo/v001/model.onnx --out tmp/detect
```

`data/` holds the generated files and is not committed. `blender/README.md` describes the
renderer in detail.

## Scene generation (WP 21)

`src/hive/data/scenes.py`, CLI `hive data scenes`. Python-only, no Blender. Each scene is a
JSON file (schema in `src/hive/data/schemas/scene.schema.json`, written by
`hive data schema`). Lengths are in **tile widths** (the across-flats width), so a scene
renders the same with every tileset; the renderer scales it by the tileset's measured
size. Shortened example:

```json
{
  "schema_version": 2,
  "scene_id": "000123",
  "seed": 4129710123448123,
  "moves": [{"piece": "ant", "from": null, "to": [0, 0]}, "..."],
  "board": [{"coord": [0, 0], "x": -0.31, "y": 0.45,
             "stack": [{"piece": "ant", "owner": "white", "turn": 4},
                       {"piece": "beetle", "owner": "black", "turn": 1}],
             "jitter": [{"dx": 0.012, "dy": -0.004, "rot_deg": 1.8},
                        {"dx": 0.041, "dy": 0.02, "rot_deg": -3.1}]}],
  "loose_pieces": [{"piece": "ant", "owner": "black", "x": 3.1, "y": -1.2,
                    "rot_deg": 40, "flipped": false}],
  "distractors": [{"kind": "box", "x": -7.5, "y": 2.0, "size": [4.2, 3.1, 0.6],
                   "rot_deg": 17, "color_seed": 912}],
  "tile_gap": 0.03,
  "camera": {"distance": 9.4, "tilt_deg": 18, "azimuth_deg": 210, "roll_deg": -3,
             "focal_mm": 26, "frame_offset": [0.2, -0.1], "portrait": false,
             "aperture_f": 8.0},
  "lighting": {"preset": "window", "color_temp_k": 4300, "intensity": 0.8,
               "direction_deg": 120, "elevation_deg": 35, "environment_strength": 0.4},
  "background": {"surface": "wood", "variant_seed": 77, "rotation_deg": 12, "scale": 1.1},
  "post": {"blur_px": 0.6, "noise": 0.01, "jpeg_quality": 85}
}
```

- Boards come from random games played with `Rules`; `moves` replays to the board, so
  every board is reachable and legal, including beetle stacks. Each game has a random
  length and a random bias towards moving over placing, which spreads hive sizes: with
  the defaults about 5% of hives have fewer than 4 tiles, 20% each have 4–7, 8–11, 12–15
  and 16–19, 15% have 20 or more, and about 27% of scenes have a stack.
- Jitter offsets and rotates every tile slightly; `turn` rotates the insect in 60° steps.
- `loose_pieces`: unplayed tiles from both hands in two groups on opposite sides of the
  hive, never touching it or each other; 5% lie upside down and are not labeled.
- `distractors`: in 60% of scenes, 1–4 everyday objects around the hive, never on a tile:
  boxes lying flat (books, phones, notebooks), standing cylinders (mugs, cans) and rods
  (pens). They are hard negatives, and they cover tiles behind them in steep views.
- Camera: tilt 0–60° (raised from 35° after real close-ups at about 50–60° failed),
  any azimuth, slight roll, 22–52 mm equivalent focal length, a distance at which the hive
  fills 35–120% of the half frame (above 100% the hive is cut off, as in close-ups), and
  `frame_offset` placing the hive anywhere in the frame, partly outside the edges
  included, because CNN translation equivariance is imperfect near borders and lens and
  perspective effects differ off-centre. 40% of images are portrait. Depth of field at
  f/5.6–16 (35 mm equivalent) focused on the hive centre blurs the far side of close and
  steep views slightly, as phone cameras do.
- Sampling ranges live in `ScenesConfig`; `--config scenes.toml` overrides any of them.
- Schema version 2 added `aperture_f` and `distractors`; the renderer still reads
  version 1 scenes, without depth of field and objects.
- Generation is deterministic: scene `i` of a batch has the seed
  `derive_scene_seed(seed, i)`. 2000 scenes take under 2 s with 16 processes.
- Tileset choice is left to the renderer (recorded in metadata), so scenes are reusable
  across tilesets.

### Game sequences

`hive data sequences --count N --plies P --takes T --out DIR [--config scenes.toml]` writes
scenes of whole games for testing the tracking of a game from photos (`vision.md` §Move
matching): one game per sequence that mostly grows the hive and lets beetles climb when
they can, a scene after every move, and `T` photos per move with their own camera,
lighting, table, clutter and tiles in hand (the extra photos stand in for a person taking
another one). Scene ids are `<game>-<move>-<photo>`; the renderer copies the moves into
its metadata, so `hive vision track` knows the true game.

## Tilesets (WP 22)

```
blender/tilesets/
├─ bakelite-procedural-001/         # built in code: bakelite slabs, debossed insects
│  └─ tileset.toml
└─ pocket-edition-normal-001/       # template (weight 0) for the modelled set
   ├─ tileset.toml
   ├─ white-queen.blend ... black-ant.blend     # to be modelled
   └─ textures/
```

`tileset.toml` (keys of the modelled kind; see the template for the requirements on the
files):

```toml
id = "pocket-edition-normal-001"
name = "Hive Pocket (standard colours)"
kind = "blend"                     # or "procedural"
weight = 1.0                       # relative sampling weight; 0 disables the tileset
across_flats_mm = 34.64            # 20 mm sides
thickness_mm = 10.0
corner_radius_mm = 3.0             # also shapes the label outline

[tiles]                            # owner-piece → file and object name
white-queen = { file = "white-queen.blend", object = "tile" }
# ... one entry per piece and colour

[materials]                        # randomisation ranges of procedural materials
roughness = [0.22, 0.5]
```

- The renderer discovers tilesets by scanning `blender/tilesets/*/tileset.toml`, samples one
  per image by weight (or restricted with `--tilesets`), and loads tile objects from the
  per-tile files.
- Adding a physical set (for example `carbon-monochrome-001`) means adding a folder; no
  code changes.
- The procedural tileset (`kind = "procedural"`) models the physical pieces: hexagonal
  bakelite slabs with 20 mm sides and 10 mm height, rounded corners and soft edges, cream
  and near-black bodies with randomised sheen, texture and scuffs, and the insect SVGs
  from `src/hive/assets/svg/` **debossed** 0.6 mm into the top face (a boolean difference)
  and painted in the insect colours. Per image the body and paint colours shift slightly
  in hue, saturation and brightness (paint hue by at most ±0.035, so the yellow queen
  covers orange without reaching the brown spider).
- Hive Pocket includes mosquito and ladybug tiles, which are out of scope and not modelled.

### Assets

The surfaces (26 wood, fabric and stone textures) and indoor environments (20 HDRIs) are
CC0 assets from Poly Haven, listed in `blender/assets.toml` and downloaded into
`blender/.cache/` by `make render-assets` (checksums verified). This replaces the planned
Git LFS copies: the assets stay out of the repository, and Git LFS is not needed until the
modelled tilesets arrive. Rendered images, datasets and model weights are never committed.

## Renderer (WP 22)

`blender/render.py` runs under Blender's bundled Python (Blender 5.3, see
`blender/README.md`). It must not import `hive`, and checks the scene `schema_version`
instead of the full JSON Schema (Blender's Python has no validator). Per scene:

1. Pick a tileset (seeded), vary its materials, build the board: tiles at hex centres
   scaled by the tileset size, stacks, jitter, loose tiles, and the distractor objects.
2. Table surface (a downloaded texture of the scene's kind with random tint and scale, or a
   plain colour), lighting preset (window, ceiling, lamp, flash or environment only) with
   an HDRI room around it, and the camera aimed so the hive centre lands at
   `frame_offset`.
3. Meter the exposure on a small EEVEE preview to a random target brightness, as a phone
   does, then render with EEVEE or Cycles (`--engine mixed` renders `--cycles-fraction` of
   the images with Cycles) at 1024 px on the long side, with a random tone mapping.
4. Render the tile instance map with Workbench: flat object colours, no anti-aliasing,
   the instance id in the red and green channels; everything else, distractors included,
   is id 0, so it still covers the tiles behind it.
5. Write `meta/<id>.json`: tileset, engine, surface, environment, camera, board, and per
   tile its class, coordinate, stack level and the top-face outline projected with
   `world_to_camera_view`.

Labels are computed by the export rather than in Blender, so they can be changed and
tested without re-rendering. The post effects (blur, noise, JPEG) are applied there too.

## Dataset export (WP 23)

`src/hive/data/datasets.py`, CLI `hive data export` (needs the `vision` extra):

- The label of a tile is the **visible part of its top face**: the projected outline,
  intersected with the tile's own pixels in the instance map, so faces covered by stacked
  tiles and faces cut off by the frame are handled the same way. Faces with 50% or less
  visible are dropped (`--min-visible`). Only the top tile of a stack and loose tiles that
  are not flipped are labeled.
- Labels are polygons (`--task segment`, the default), which Ultralytics also uses to train
  detection models, or boxes (`--task detect`). 10 classes, `class_id = owner * 5 +
  piece_type` (`hive.vision.classes.TileClass`).
- Ultralytics layout with `train`/`val` splits (assigned by hashing the scene id, so they
  are stable when scenes are added; synthetic val is for training curves, the real test set
  is separate), `data.yaml` with the class names, `meta.jsonl` with the labels, board and
  render metadata of every image, and `manifest.json` (name, version, task, scene range,
  images per split, labels per class, tilesets, engines, Blender versions, renderer
  commit, created at).
- `--debug N` draws the labels of N images into `debug/`.
- Versions are immutable: the export refuses an existing dataset folder. Uploading to and
  pulling from Garage (`--upload`, `hive data pull`) is not implemented yet.

## Training (WP 24)

`scripts/train/train_yolo.py` (extra `train`: ultralytics 8.4, torch 2.15; the CI skips
this extra):

- Starts from a pretrained small model (`yolo26n.pt` for detection, `yolo26n-seg.pt` for
  segmentation) and trains with Ultralytics augmentations (mosaic, HSV, translate, scale,
  small rotations, horizontal and vertical flips) on top of the rendered variation.
- Exports ONNX with a fixed input size and the raw head (non-maximum suppression is done by
  the reader), and writes `model.onnx`, `best.pt`, `metrics.json` (synthetic validation
  metrics, per class) and `model.json` (dataset, training settings, class map, input size)
  to `data/models/<name>/<version>/`. Uploading to Garage is not implemented yet.
- `hive.vision.yolo.reader.YoloReader` runs the ONNX model with ONNX Runtime on the CPU,
  with letterboxing, decoding and NMS in numpy (matching Ultralytics' predictions), and
  decodes masks for segmentation models. `hive vision detect` runs it on photos.
- Evaluate with `hive vision eval --reader yolo` on the real test set and compare with the
  classical reader report once WP 20 exists.
