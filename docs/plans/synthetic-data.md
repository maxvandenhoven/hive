# Synthetic data

Synthetic images train the YOLO detector. The engine generates valid boards; Blender
renders them with randomised cameras, lighting, surfaces and tilesets; the output is a
YOLO dataset with metadata. Everything runs locally on the workstation GPU (Cycles with
CUDA/OptiX, Ultralytics on CUDA); artifacts are stored in Garage.

```
hive data scenes --count 20000 --seed 1 --out scenes/   (Python 3.13, uses the engine)
        │  scene JSON files
        ▼
blender -b -P blender/render.py -- --scenes scenes/ --out renders/ [--tilesets a,b] [--samples 64]
        │  images + YOLO labels + meta.jsonl
        ▼
hive data export --renders renders/ --name synth --version v001 [--upload]
        │  dataset manifest in Garage: datasets/synth/v001/
        ▼
uv run --extra train python scripts/train/train_yolo.py --dataset ... --export-onnx
```

## Scene generation (WP 21)

`src/hive/data/scenes.py`, CLI `hive data scenes`. Python-only, no Blender. Each scene is a
JSON file:

```json
{
  "schema_version": 1,
  "scene_id": "000123",
  "seed": 123,
  "board": [{"q": 0, "r": 0, "stack": [{"piece": "beetle", "owner": "white"}],
             "jitter": {"dx": 0.02, "dy": -0.01, "rot_deg": 3.5}}],
  "loose_pieces": [{"piece": "ant", "owner": "black", "x": 0.31, "y": -0.12, "rot_deg": 40,
                    "flipped": false}],
  "camera": {"height_m": 0.55, "tilt_deg": 18, "azimuth_deg": 210, "focal_mm": 26,
             "frame_offset": [0.2, -0.1]},
  "lighting": {"preset": "window", "color_temp_k": 4300, "intensity": 0.8,
               "direction_deg": 120},
  "background": {"surface": "wood", "variant_seed": 77},
  "post": {"blur_px": 0.6, "noise": 0.01, "jpeg_quality": 85}
}
```

- Boards come from random games played with `Rules` (random or weak agents, random length)
  so every board is reachable and legal, including beetle stacks. Sample game lengths so
  small, medium and large hives are all common.
- Jitter positions and rotations slightly: real tiles are never perfectly aligned.
- `loose_pieces`: unplayed pieces placed near but not touching the hive (the hand), which
  the detector should detect and the grid fit should reject.
- Camera: tilt 0–35°, any azimuth, focal length range of phone cameras, height range, and
  `frame_offset` placing the hive anywhere in the frame including near the edges. Rendering
  off-centre hives matters because CNN translation equivariance is imperfect near borders
  and lens and perspective effects differ off-centre; 2D augmentation alone is not enough.
- Tileset choice is left to the renderer (recorded in metadata), so scenes are reusable
  across tilesets.
- Scene generation is deterministic given the seed.

## Tilesets (WP 22)

```
blender/tilesets/
├─ placeholder-procedural-001/      # built in WP 22: plain hex bodies + insect SVG textures
│  └─ tileset.toml
└─ pocket-edition-normal-001/       # modeled by the project owner
   ├─ tileset.toml
   ├─ white-queen.blend  white-beetle.blend  white-grasshopper.blend
   ├─ white-spider.blend white-ant.blend
   ├─ black-queen.blend  black-beetle.blend  black-grasshopper.blend
   ├─ black-spider.blend black-ant.blend
   └─ textures/
```

`tileset.toml`:

```toml
id = "pocket-edition-normal-001"
name = "Hive Pocket (standard colours)"
weight = 1.0                       # relative sampling weight
across_flats_mm = 0.0              # measured, placeholder value
thickness_mm = 0.0                 # measured, placeholder value

[tiles]                            # piece-owner → file and object name
white-queen = { file = "white-queen.blend", object = "tile" }
# ... one entry per piece and colour

[materials]                        # randomisation ranges applied at render time
roughness = [0.2, 0.5]
scuff_strength = [0.0, 0.3]
```

- The renderer discovers tilesets by scanning `blender/tilesets/*/tileset.toml`, samples one
  per image by weight (or restricted with `--tilesets`), and appends tile objects from the
  per-tile files.
- Adding a physical set (for example `carbon-monochrome-001`) means adding a folder; no
  code changes.
- The placeholder tileset uses procedural hexagonal prisms with the insect SVGs from
  `src/hive/assets/svg/` as textures. It lets the full pipeline be built and tested before
  real tiles are modeled.
- Note: Hive Pocket includes mosquito and ladybug tiles, which are out of scope; they are
  not modeled.

### Git LFS

`.blend` files and textures are tracked with Git LFS (`.gitattributes`:
`blender/tilesets/**/*.blend filter=lfs diff=lfs merge=lfs -text`, same for `*.png`,
`*.jpg`, `*.exr` under `blender/`). Rendered images, datasets and model weights are never
committed; they live in Garage.

## Renderer (WP 22)

`blender/render.py` runs under Blender's bundled Python (pin the Blender LTS version in
`blender/README.md`). It must not import `hive`. Per scene:

1. Pick a tileset (seeded), build the board: place tile objects at hex centres (from the
   tileset's measured size), stack heights, jitter; add loose pieces.
2. Set background surface (a small library of PBR textures under `blender/surfaces/`, also
   LFS), lighting preset and parameters, camera.
3. Render with Cycles (GPU), denoised, at phone-like resolution; apply post effects (blur,
   noise, JPEG compression).
4. Labels: for each visible top tile (top of each stack, plus loose pieces), project the
   tile's top-face vertices to image space with `bpy_extras.object_utils.world_to_camera_view`,
   compute the 2D bounding box, compute visible fraction (truncation by frame), drop tiles
   ≤ 50% visible, write YOLO lines `class cx cy w h` (normalised).
5. Metadata line in `meta.jsonl`: scene id, tileset id, image size, camera, true board in
   axial coordinates, per-label hex coordinate.

A `--debug` flag writes images with drawn labels for visual inspection.

## Dataset export (WP 23)

`src/hive/data/datasets.py`, CLI `hive data export`:

- Assemble images, labels and metadata into the Ultralytics layout with
  `train`/`val` splits (synthetic val is for training curves; the real test set is
  separate), a `data.yaml` with the 10 class names, and a `manifest.json` (name, version,
  scene seed range, tilesets and counts, Blender version, renderer git commit, created at).
- `--upload` pushes to Garage at `datasets/<name>/<version>/`. `hive data pull` downloads.
- Versions are immutable once uploaded.

## Training (WP 24)

`scripts/train/train_yolo.py` (extra `train`: ultralytics, torch with CUDA):

- Start from a pretrained small YOLO detection model; train on the synthetic dataset with
  Ultralytics augmentations (translate, scale, mosaic, HSV) on top of rendered variation.
- Export to ONNX with a fixed input size; write `model.onnx`, `metrics.json`, and
  `model.json` (dataset version, training config, class map, input size) and upload to
  `models/<name>/<version>/` in Garage.
- Verify Python 3.13 support for the pinned torch and Ultralytics versions before pinning.
- Evaluate with `hive vision eval --reader yolo` on the real test set and compare with the
  classical reader report.
