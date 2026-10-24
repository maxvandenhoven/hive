# Vision

The vision pipeline turns a photo of the physical board into the move that was played. It
is an optional speed-up: every flow works with manual move entry. Code lives in
`src/hive/vision/` (extra `vision`: numpy, opencv-python-headless, onnxruntime).

## Pipeline

```
photo ──▶ BoardReader.read(image) ──▶ list[TileObservation]        (reader-specific)
      ──▶ fit_hex_grid(observations) ──▶ ObservedBoard              (shared)
      ──▶ match_move(state, rules, observed) ──▶ MatchResult        (shared)
```

### Tracking assumption

Photos are taken every turn from a known starting state (the initial position or a board
entered in the editor). Therefore the photo only needs to identify **which legal move** was
played, not reconstruct the full state:

- Pieces under beetles are known from history; the reader only needs the **top piece per
  stack**.
- Side to move, hands and ply are tracked exactly by the engine.
- Detection errors are corrected by legality: the closest legal move wins.

### Capture assumptions

- Phone camera, roughly overhead: tilt up to about 35°, any rotation around the vertical
  axis, the hive anywhere in the frame, any table surface, normal indoor lighting.
- Unplayed pieces may lie next to the hive; they must be ignored.
- Tiles cut off at the frame edge: only tiles more than 50% visible are labeled; the app
  warns when observations touch the image border.

## Interfaces

```python
@dataclass(frozen=True, slots=True)
class TileObservation:
    center: tuple[float, float]           # pixels
    polygon: tuple[tuple[float, float], ...] | None
    piece: PieceType
    owner: Player
    score: float                           # 0..1 confidence

class BoardReader(Protocol):
    name: str
    def read(self, image: np.ndarray) -> list[TileObservation]: ...
```

Detection classes are tileset-agnostic: 10 classes, `class_id = owner * 5 + piece_type`
(matching the `Player` and `PieceType` enum values).

## Grid fitting (WP 17)

`fit_hex_grid(observations) -> ObservedBoard` maps pixel centers to axial `(q, r)`:

1. Estimate the lattice: nearest-neighbor vectors between centers cluster into three
   directions 60° apart (up to the affine distortion from tilt). Fit an affine transform
   from axial coordinates to pixels (robustly, RANSAC style), using the known neighbor
   structure.
2. Snap each center to the nearest lattice point; reject observations far from any lattice
   point.
3. Resolve collisions (two observations on one hex) by score.
4. Keep the largest connected component of hexes (the hive); everything else (pieces in
   hand next to the board, clutter) is dropped and reported as `rejected`.
5. Output: `ObservedBoard = dict[Coordinate, (PieceType, Player, score)]` in an arbitrary
   lattice frame, plus fit diagnostics (residual, rejected count, touches border).

## Move matching (WP 17)

`match_move(state, rules, observed) -> MatchResult`:

1. Align the observed frame to the current board: search the 6 hex rotations and the
   translations that map observed hexes onto known occupied hexes, scoring agreement of top
   pieces. Most tiles are unchanged between turns, so the best alignment is clear.
2. For each move in `rules.legal_moves(state)`, compute the expected top-piece board after
   the move and score it against the aligned observation: reward matches weighted by
   score, penalise mismatched classes, missing hexes and extra hexes.
3. Rank candidates. Return `auto` if the best score passes an absolute threshold and beats
   the runner-up by a margin; otherwise `candidates` (top-k) for the user to choose.
4. Recovery: if nothing passes, search two-move sequences (own move + opponent move, about
   10k candidates) and return them as candidates flagged `two_moves`.
5. Verification mode for agent turns: score only the expected move and report `match` or
   `mismatch` with a diff.

Matching is tested without images: generate states from random games, render the expected
observation directly from the engine (with noise: dropped tiles, wrong classes, extra
tiles, random rotation/translation/affine skew), and assert the right move ranks first.

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

- Model trained with Ultralytics on synthetic data (`synthetic-data.md`), exported to ONNX.
- Inference with `onnxruntime` (CPU), letterbox preprocessing and NMS implemented in numpy
  (no Ultralytics or torch at inference time).
- The model file is downloaded from Garage at API startup
  (`models/<name>/<version>/model.onnx`, version from `HIVE_MODEL_VERSION`) and cached.

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
