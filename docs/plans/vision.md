# Vision

The vision pipeline turns a photo of the physical board into the move that was played. It
is an optional speed-up: every flow works with manual move entry. Code lives in
`src/hive/vision/` (extra `vision`: numpy, opencv-python-headless, onnxruntime).

## Pipeline

```
photo ──▶ BoardReader.read(image) ──▶ list[TileObservation]           (reader-specific)
      ──▶ ObservedBoard.fit(observations) ──▶ ObservedBoard           (grid_fit.py)
      ──▶ MoveResolver.resolve(state, photos, previous) ──▶ MoveResolution   (resolver.py)
      ──▶ GameTracker: plays resolved moves, keeps unclear photos     (tracking.py)
```

### Tracking assumption

Photos are taken every turn from a known starting state (the initial position or a board
entered in the editor). Therefore the photo only needs to identify **which legal move** was
played, not reconstruct the full state:

- Pieces under beetles are known from history; the reader only needs the **top piece per
  stack**.
- Side to move, hands and ply are tracked exactly by the engine.
- Detection errors are corrected by legality: the most likely legal move wins.
- Photos may be taken from any angle; everything is compared in board coordinates, never
  in pixels.

### Capture assumptions

- Phone camera: tilt up to about 60°, any rotation around the vertical axis, the hive
  anywhere in the frame (partly outside it too), any table surface, normal indoor lighting.
- Unplayed pieces and other objects may lie next to the hive; they must be ignored.
- Tiles cut off at the frame edge: only tiles more than 50% visible are labeled; tiles
  outside the frame are unseen rather than missing.

## Interfaces

```python
@dataclass(frozen=True, slots=True)
class TileObservation:
    center: tuple[float, float]           # pixels
    box: tuple[float, float, float, float]
    polygon: list[tuple[float, float]] | None
    piece_type: PieceType
    owner: Player
    score: float                           # 0..1 confidence
    class_scores: tuple[float, ...] | None # every class, in class id order

class BoardReader(Protocol):
    name: str
    def read(self, image: np.ndarray) -> list[TileObservation]: ...
```

Detection classes are tileset-agnostic: 10 classes, `class_id = owner * 5 + piece_type`
(matching the `Player` and `PieceType` enum values, `hive.vision.classes.TileClass`).

## Grid fitting (WP 17)

`ObservedBoard.fit(observations, image_size)` places the detections of one photo on the
hex lattice, in a frame of its own (`lattice.py`: x east, y south, neighbours 1 apart, so
the plane-to-photo map keeps orientation). The top faces of tiles on the table lie in one
plane, so a homography maps the lattice plane to the photo at any angle:

1. Seeds: a face outline is a hexagon in perspective; the inverse square root of its
   covariance undoes the local foreshortening (a regular hexagon has the same spread in
   every direction). Around a tile, the offset to its nearest neighbour becomes a lattice
   step and a 60° turn gives the second step: a local affine model.
2. Growth: from each seed, detections near the centre of a hex next to the hexes found so
   far are added and the model refitted (along a line while the tiles are in a line,
   affine from three tiles, homography from six spread over the plane). The largest
   grown set wins.
3. Final fit: a RANSAC homography, refitted to every face placed at table height.
   Faces on stacks are higher than the plane and shift away from the camera in steep
   views, so the camera centre is estimated from the homography (focal length from the
   orthogonality of the plane axes, principal point at the image centre) and each
   detection is snapped at the stack level that fits best, levels above 0 only when the
   table level fits poorly. Each tile records how far one level shifts it there.
4. Collisions keep the higher score; the largest connected group of hexes is the hive
   (ties: nearest the image centre). Other detections are `off_grid`; those within half a
   hex of a hex are kept in `near` for the resolver.
5. `visibility(coord, level)` projects a hex into the photo: 1 well inside, 0.5 with its
   centre on the edge, 0 outside.

On simulated photos (`hive.vision.testing`, tilts up to 60°, noise and tiles in hand) the
fit places every tile of the board exactly in 98% of photos.

## Move matching (WP 17)

`MoveResolver.resolve(state, photos, previous)` ranks the positions after every legal move
by the likelihood of one or more photos of the result:

1. Alignment: every rotation and translation that puts an observed face on an engine tile
   gets a vote weighted by the class probability; most tiles are unchanged, so the best
   few alignments are clear before any move is considered. Before the first move every
   detection is a candidate first tile, with a prior for lone tiles near the middle of the
   photo (tiles in hand lie in groups at the side).
2. Likelihood per hex, summed over the hive and the observed hexes: a detected face scores
   `(1 - ρ) p(class) + ρ / 10` with the detector's class probabilities and a confusion
   rate ρ = 5%; an expected face that is not detected costs `log(2% + 98% (1 -
   visibility))`; a face on an empty hex costs `log(1%)`; a `near` detection can stand in
   for an expected face at a penalty; where the camera angle shows stack levels clearly, a
   face at another level costs more.
3. Tile memory: the previous photo of the known position, aligned to it, gives each top
   tile's class probabilities, and the current reading counts half by its agreement with
   that reading; moved tiles take their reading along. A tile that the detector always
   reads wrongly (like the real black queen) is then still recognised.
4. Candidates are scored incrementally (only the source and target hexes change), the
   best alignment per photo, summed over photos: further photos of the same position add
   evidence instead of replacing it.
5. Outcomes are merged up to rotation and translation (for example the six equivalent
   second placements), and turned into posteriors.
6. Two moves: when the best single move leaves any hex disagreeing, every pair of legal
   moves is scored as well, with the prior `log(2%)` (a skipped photo) shared by the
   possible second moves.
7. Decision: `resolved` when the best outcome has posterior ≥ 0.95, leads the next by 3
   nats and at most `1 + 15%` of the hexes disagree; `failed` when many hexes disagree
   (another board, or no hive found); otherwise `ambiguous` with the top candidates and a
   request for another photo.

`GameTracker` keeps ambiguous photos and resolves them together with the next photo,
plays resolved moves, and uses the photo that confirmed a position as the previous photo
of the next move. `confirm(moves)` plays moves entered by hand.

### Tracking results (WP 17)

Simulated games (`hive.vision.testing`, 12 games of 30 random moves, tilts up to 55°, up
to three photos per move, entered by hand after three):

| Detector confusion | Resolved, 1 photo | 2 photos | 3 photos | By hand | Wrong |
|---|---|---|---|---|---|
| 0% | 303 | 47 | 8 | 1 | 1 |
| 5% | 280 | 65 | 6 | 8 | 1 |
| 10% | 262 | 76 | 6 | 4 | 1 |

Single photos without retakes (12 other games, the same cameras and noise): how often
the correct move ranks first and among the first three candidates, and what the resolver
decides. The WP 17 target of 99% ranked first is not met on single photos: most misses are
photos where the changed tiles are out of view or the detector misread the new tile, which
the resolver mostly reports as ambiguous and a further photo resolves.

| Detector confusion | Correct first | Correct in top 3 | Resolved | Ambiguous | Failed | Resolved wrong |
|---|---|---|---|---|---|---|
| 0% | 95.5% | 98.0% | 84.5% | 15.3% | 0.3% | 1 of 354 |
| 5% | 90.8% | 94.2% | 77.5% | 22.2% | 0.3% | 3 of 360 |
| 10% | 92.8% | 96.7% | 74.4% | 23.6% | 1.9% | 1 of 360 |

Rendered games (`hive data sequences`, 2 games of 40 moves with placements, moves and
beetles climbing onto stacks; every photo with its own camera up to 45° tilt, lighting,
table, clutter and tiles in hand; three photos per move rendered, used only when needed),
read by `hive-yolo-seg` v001 and tracked with `hive vision track`:

| Moves | Resolved, 1 photo | 2 photos | 3 photos | By hand | Wrong |
|---|---|---|---|---|---|
| 80 | 74 | 5 | 1 | 0 | 0 |

Resolving takes about 10 ms per photo, and up to about 0.5 s when pairs of moves are
searched.

## Readers

### Classical reader (WP 18)

No training data; uses templates from photos of the physical tiles.

1. Preprocess: resize, denoise, convert to grayscale and HSV/Lab.
2. Tile outlines: edge detection, Hough lines to find the three dominant edge directions
   (hexagon sides), contour detection and hexagon fitting constrained by those directions
   and a consistent tile size.
3. Owner: tile body colour (light vs dark) from the area inside the hexagon.
4. Insect: normalise the tile patch (rotate to a canonical edge direction, scale), then
   template-match against per-piece templates at 6 rotations; pick the best with its score.
5. Templates: `src/hive/vision/classical/templates/<tileset-id>/` cut from flat photos of
   each tile face (manual task). Template extraction is a small script under `scripts/`.

### YOLO reader (WP 24)

- Model trained with Ultralytics on synthetic data (`synthetic-data.md`), exported to ONNX
  with the raw head: `(1, 4 + 10 [+ 32], anchors)` plus mask prototypes for segmentation
  models.
- `hive.vision.yolo.reader.YoloReader`: inference with `onnxruntime` (CPU), letterbox
  preprocessing, decoding, class-agnostic NMS (tiles never overlap, so two classes on one
  tile are one uncertain tile) and mask decoding in numpy and OpenCV, with no Ultralytics or
  torch at inference time. Its output matches Ultralytics' predictions on the same model.
  The reader checks the model's class names against `TileClass`; for segmentation models the
  observation centre is the mask centroid, otherwise the box centre.
- `hive vision detect PHOTO... --model model.onnx --out DIR` runs it from the command line
  and writes annotated images and the observations as JSON.
- The model file is downloaded from Garage at API startup
  (`models/<name>/<version>/model.onnx`, version from `HIVE_MODEL_VERSION`) and cached
  (not implemented yet).

### First synthetic results (WP 24)

`hive-yolo` v001: YOLO26n detection, 640 px, 80 epochs on `synth-v001` (1000 renders of
the procedural bakelite tileset, 913 train and 87 val images), trained in 9 minutes on an
RTX 3070 Laptop GPU (7 s per epoch; 207 s per epoch on the Ryzen 7 5800H CPU).

| Synthetic val (87 images, 1114 tiles) | Value |
|---|---|
| Box precision / recall | 0.996 / 0.999 |
| mAP50 / mAP50-95 | 0.995 / 0.954 (per class 0.944–0.968) |
| Labeled tiles found with the right owner and insect (score ≥ 0.35) | 1114 / 1114 |
| Extra detections | 15, of which 14 are tiles cut off at the image edge (≤ 50% visible, not labeled) |
| `YoloReader` latency on the CPU (ONNX Runtime, 16 threads) | p50 51 ms, p95 118 ms |

These numbers are on synthetic images of the same tileset, so they measure the pipeline,
not real-world accuracy; the real test set (WP 20) decides that.

`hive-yolo-seg` v001: YOLO26n segmentation with the same data and settings (22 minutes):
box mAP50-95 0.943, mask mAP50 0.995 and mask mAP50-95 0.873 on the synthetic val split.

First real photos: 9 phone photos of one board of 10 Hive Pocket tiles (two tables, tilts
from about 10° to 60°), checked by eye, score threshold 0.25:

| Model | Tiles right | False positives | Errors |
|---|---|---|---|
| `hive-yolo` v001 | 85 / 90 | 2 (0.67, 0.33), at the image edge | 4 in one steep close-up, black queen as spider (0.73) in another |
| `hive-yolo-seg` v001 | 86 / 90 | 1 (0.34), at the image edge | 4 in the steep close-up |

Correct tiles mostly score 0.9–0.98. The errors are in close-ups at about 50–60° tilt,
outside the 0–35° training range, and on the black queen, whose real artwork is an orange
bee while the SVG is yellow line art. Scene schema version 2 raised the tilt range to 60°
and added close framing, depth of field, colour variation and distractor objects for the
next dataset.

## Evaluation (WP 20)

`hive vision eval --reader classical|yolo --dataset <path-or-garage-uri> [--out report.json]`

Dataset formats:

- **Labeled images**: YOLO layout (`images/`, `labels/`) plus `meta.jsonl` with per-image
  `tileset_id`, split, and (for synthetic) the true board in axial coordinates.
- **Recorded games**: `sequences.jsonl`, one game per line: setup, rules, moves, and the
  photo for each ply. Produced from games played in the app (export) or recorded manually.

Metrics, at three levels plus speed:

| Level | Metrics |
|---|---|
| Tile | precision, recall, class accuracy, owner accuracy (IoU or center-distance matching) |
| Board | exact top-piece board match rate up to rotation/translation, per-hex accuracy |
| Game | correct move identification rate (auto only, auto + candidates top-3), two-move recovery rate |
| Speed | read latency p50/p95 per reader, measured in the API image on CPU |

Reports are versioned JSON with the dataset version, reader, model version, and per-tileset
breakdowns. A comparison command renders a markdown table of several reports.

Data policy for now: train on synthetic only; real photos are for validation and test, split
by game (never by photo, since consecutive photos are near duplicates).

## Using the pipeline

From a photo to detections, on the command line (needs the `vision` extra and a model
from `scripts/train/train_yolo.py`, see `synthetic-data.md` §Training):

```
uv run hive vision detect photo.jpg --model data/models/hive-yolo-seg/v001/model.onnx \
    --out tmp/detect [--score 0.35]
```

It logs every tile face with its class, score and centre, and writes an annotated image
and the observations as JSON per photo.

From photos of a game to moves, in code:

```python
from hive.engine.rules import Rules
from hive.vision.grid_fit import BoardFitError, ObservedBoard
from hive.vision.resolver import ResolutionStatus
from hive.vision.tracking import GameTracker
from hive.vision.yolo.reader import YoloReader

reader = YoloReader.load(model_path=Path("model.onnx"), score_threshold=0.25)
tracker = GameTracker(rules=Rules())          # or state=... for a position from the editor

for image in photos_after_every_move:          # BGR arrays, as cv2.imread gives them
    try:
        observed = ObservedBoard.fit(
            observations=reader.read(image), image_size=(image.shape[1], image.shape[0])
        )
    except BoardFitError:
        ...                                    # no tiles: ask for another photo
        continue

    resolution = tracker.add_photo(observed)

    if resolution.status is ResolutionStatus.RESOLVED:
        ...                                    # tracker.state is the new position
    elif resolution.status is ResolutionStatus.AMBIGUOUS:
        ...                                    # show resolution.reason and candidates;
                                               # the next photo is combined with this one
    else:
        ...                                    # FAILED: retake, or tracker.confirm(moves)
```

Evaluating on rendered games: `hive data sequences`, render, `hive data export`, then
`hive vision track --dataset ... --model ... --out tmp/tracking`, which writes
`report.json`, a frame per photo (`frames/<game>/<id>.jpg`: the photo with its
detections next to the tracked board and the decision) and an animated GIF per game
(Pillow, from the `plotting` extra). See `synthetic-data.md` §Game sequences.

## Status and next steps

State after the branch `feature/wp21-24-synthetic-data-yolo` (M3 and M4 started out of
order: the synthetic pipeline, the YOLO reader and the move resolver first, the app work
not yet).

### Done

| WP | Part | Where |
|---|---|---|
| 21 | Scene generation, sampling config, JSON Schema, game sequences | `src/hive/data/scenes.py`, `hive data scenes`, `hive data sequences`, `hive data schema` |
| 22 | Blender renderer, procedural bakelite tileset, template for the modelled set, CC0 assets, smoke test | `blender/`, `make render-assets`, `make render-smoke` |
| 23 | Labels from instance maps, post effects, Ultralytics layout, manifests | `src/hive/data/datasets.py`, `hive data export` |
| 24 | Training and ONNX export, ONNX reader with numpy NMS and masks, first synthetic and real-photo results | `scripts/train/train_yolo.py`, `src/hive/vision/yolo/reader.py`, `hive vision detect` |
| 17 | Grid fitting, move resolution with several photos, tile memory, two-move recovery, tracker, simulator | `src/hive/vision/{lattice,grid_fit,resolver,tracking,testing}.py` |
| 20 (part) | Tracking evaluation on rendered games | `src/hive/vision/sequences.py`, `hive vision track` |

### Still missing

- **WP 16 photo capture and storage**: no upload endpoint, no photo rows, no camera button.
- **WP 19 camera move flow**: the API does not run the reader, fit or resolver; no
  `HIVE_READER` or `HIVE_MODEL_VERSION` settings; no proposal, candidate or retake
  screens; no verification mode for agent moves (checking a photo against the expected
  move with a diff).
- **WP 18 classical reader**: not started; there is no baseline to compare YOLO with.
- **WP 20 evaluation harness**: no `hive vision eval` with tile, board and game metrics on
  labeled real photos, no `sequences.jsonl` export of recorded app games, no
  `hive vision compare`. Only the rendered-game tracking evaluation exists.
- **WP 23 and 24 storage**: no `--upload` or `hive data pull`; datasets and models live in
  the local `data/` folder, not in Garage.
- **Real data**: no hand-labeled real test set and no real game recorded move by move. The
  only real data are 9 photos of one arrangement (85 or 86 of 90 tiles right).
- **Modelled tileset**: `pocket-edition-normal-001` is a template; the renders use the
  procedural tileset with the SVG line art, not the real artwork.

### Limitations

- **Synthetic-to-real gap**: the models are trained on 1000 renders of procedural tiles
  whose insects are the app's line-art SVGs at 62% of the tile, while the real set has
  filled, detailed artwork at about 75% and an orange (not yellow) queen. Synthetic
  validation scores (mAP50 0.995) overstate real accuracy; the real misreads concentrate
  on the black queen and on steep close-ups.
- **Camera range**: the models saw tilts up to 35°; the scene config now goes to 60° with
  closer framing, depth of field and distractors, but no model is trained on that yet, so
  the rendered tracking test used tilts up to 45°.
- **First move**: before the first move every detection could be the first tile; a prior
  favours lone tiles near the middle of the photo, so a first tile at the edge next to
  tiles in hand may need two or three photos.
- **Skipped photos**: two moves without a photo usually end ambiguous; when the change of
  one move is out of view, the pair can pass as a single wrong move (1 of 6 in a stress
  test). The confirmation step of the app must stay.
- **Assumptions of the fit**: one flat table; tiles roughly on the lattice (bumped tiles
  are tolerated up to about a third of a tile); principal point at the image centre; at
  least one tile clearly detected.
- **Identical-looking states**: positions that differ only below identical top tiles, or
  by swapping identical pieces, are one outcome; stack contents come from the history.
- **Calibration**: the confusion rate (5%), miss rate (2%), extra rate (1%) and thresholds
  (0.95, 3 nats) are set from simulation and the 9 real photos, not fitted on real data.
- **Speed**: about 10 ms per resolution, up to about 0.5 s when pairs of moves are
  searched, plus 50–110 ms for the reader on the CPU; the move pair search grows with the
  number of legal moves.

### Next steps to evaluate fully

1. **Record real games**: play 3–5 games with the physical set, a photo after every move
   from varying angles and tables, with the true moves written down (or entered in the
   app). This is the decisive test; store them as `sequences.jsonl` (WP 20).
2. **Label a real test set**: 50–100 photos from those games, split by game, in Label
   Studio or CVAT with YOLO polygon export, for tile-level metrics.
3. **Build `hive vision eval`** (WP 20): tile, board and game metrics and latency per
   reader and model version, and `hive vision compare` for a markdown table. Reuse
   `SequenceTracker` for the game level on real sequences.
4. **Close the synthetic gap**: photograph each tile face flat (the WP 18 manual task), use
   those as the artwork of the procedural tileset (or model `pocket-edition-normal-001`),
   render the next dataset with scene schema 2 (tilt up to 60°, distractors, depth of
   field), train `hive-yolo-seg` v002 on the GPU, and compare with v001 on the real set.
5. **Calibrate the resolver** on the real games: fit the confusion, miss and extra rates,
   then set the acceptance thresholds for a target of at most about 1 wrong resolution in
   200 moves, and measure how often a second photo is needed.
6. **Classical baseline** (WP 18), if still wanted, to complete the comparison the plan
   asks for.

### Next steps to bring it into the app

1. **WP 16 photo capture**: upload endpoint with storage in Garage and a `photo` row per
   ply; camera button in table games.
2. **Model serving** (WP 24): upload the model to `models/<name>/<version>/`, download and
   cache it at API startup from `HIVE_MODEL_VERSION`, gate `/readyz` on it; ONNX Runtime
   only, no torch in the image.
3. **Resolver in the API** (WP 19): run reader, fit and resolver in a worker thread per
   photo; keep the previous photo's observed board per game (or recompute it from the
   stored photo) and the unclear photos of the current ply; store detections and the
   resolution with the photo.
4. **UI** (WP 19): proposed move for confirmation (never commit without it), the
   candidates sheet for ambiguous photos with "take another photo", the reason of a
   failed photo, manual entry as fallback, and a border warning when the hive is cut off.
5. **Agent moves at the table**: a verification mode that scores the expected agent move
   and reports match or mismatch with the differing hexes, as an alternative to **Done**.
6. **Observability**: metrics for resolution status, photos per move, latency and
   corrections, so real accuracy can be followed after release.
