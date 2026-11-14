# Rust core

The engine and the search of the agents run in a Rust core with Python bindings (D30,
D31). This file covers the crates, the Python API contract, the representation and its
optimisations, the search kernel and the correctness gates. Tooling is in `tooling.md`
§Rust, measurements in `performance.md`, and the work packages (WP 42 to 45, then 29, 30
and 28) in `README.md`.

## Why: the spike (2026-11-12)

WP 27 made the Python engine 2.5 times faster, and its final profile had no single hot
spot left: the time is spread over Python loops, dict lookups and object construction. A
spike ported move generation, apply and undo, winners, perft and the default negamax to
Rust (about 600 lines: a 32 × 32 wrapping grid, coordinates as integer pairs, no
bitboards) and exposed them with PyO3 as classes shaped like `Rules`, `GameState` and
`Move`, so the real `hive.bench.perft` and `NegamaxAgent` ran on them unchanged. The legal
moves, in order, matched the Python engine on all 14 suite positions, and every perft
count matched up to `start` depth 7 (181,641,900 nodes).

Median of 3 runs on the AMD Ryzen 7 5800H, in the same session as a Python baseline that
matched the WP 27 result:

| Case | Python nodes/s | Python loop, Rust engine | Same, dataclass `Move` | All in Rust |
|---|---|---|---|---|
| `perft-start-5` | 743,000 | 7.5x | 1.9x | 83x (62M nodes/s) |
| `perft-ant-3` | 297,000 | 14.8x | 4.5x | 49x |
| `perft-long-3` | 392,000 | 11.8x | 3.3x | 40x |
| `negamax-long-3` | 202,000 | 4.7x | 3.1x | 70x (14M nodes/s) |
| `mobility-ant-2` | 3,740 | 23x | 9.4x | – |

"Python loop, Rust engine" runs `hive.bench.perft` and `NegamaxAgent` on Rust classes that
return Rust `Move` objects; "dataclass `Move`" makes the same classes build the current
Python `Move` dataclass instead. Perft entirely in Rust from the start position takes
0.22 s at depth 6 (17.3 s in Python) and 4.8 s at depth 7 (366 s).

What shapes the design:

1. A Python search loop costs about 1 µs per node by itself (`visit_node`,
   `terminal_score`, `evaluate`, list building, recursion), so Python agents top out near
   1M nodes/s however fast the engine is. The search must run in Rust (D31).
2. What crosses the boundary matters. Building Python dataclass moves costs 3 to 4 times
   more than Rust `Move` objects, and a thin Python class that delegates to the Rust
   classes costs another 20 to 30% on a Python perft loop. The Rust classes are the public
   classes, without a Python layer in between.
3. Python `IntEnum` members returned by Rust keep identity checks such as
   `move.piece_type is PieceType.QUEEN` working, so the enums can stay Python.
4. A midgame ply costs a factor of 30 to 100 without pruning, so 70 times faster is about
   one more ply at the same budget; with alpha-beta (effective branching around 6 to 10)
   about two.

## Scope

Rust holds everything that runs per node: `GameState`, `Rules` (move generation,
validation, winners), `Move`, Zobrist hashing and the position history, perft, the search
and the evaluation.

Python keeps what is not per node, unchanged or as a thin layer over the core: `Player`,
`PieceType`, `Piece` and `SHARED_PIECES`, `codec.py`, `record.py` (`GameRecord`,
`BoardSetup`), `errors.py`, `grid.py` (hex helpers for vision, plotting and the API),
agent registration, params and presets (D23), and everything outside the engine and
agents: the match layer, API, vision, data, plotting and benchmarks. They use the same
imports as today.

## Layout

```
rust-toolchain.toml        # pinned stable toolchain (rustup reads it from the repo root)
rust/
├─ Cargo.toml              # workspace: members, [workspace.lints], dependency versions
├─ Cargo.lock              # committed
├─ rustfmt.toml
├─ core/                   # crate `hive-core`: pure Rust, no PyO3
│  ├─ src/lib.rs
│  ├─ src/engine/          # grid, board, state, moves, rules, zobrist, perft
│  ├─ src/agents/          # search, evaluation, transposition table, time control
│  └─ tests/               # perft parity (reads tests/data/perft/base.json), integration
└─ python/                 # crate `hive-python`: PyO3 bindings only, builds `hive._core`
   └─ src/                 # lib.rs, moves.rs, state.rs, rules.rs, search.rs, json.rs
src/hive/
├─ _core.pyi               # the stub of the bindings, kept in sync by a test
├─ _core.*.so              # built by uv and maturin, gitignored
├─ py.typed
├─ engine/                 # state.py and rules.py re-export the Rust classes
└─ agents/                 # registered agent classes configure the Rust search
```

- The `engine` modules of `hive-core` import nothing from `agents`, the same direction as
  in the package (`engine ← agents`), checked in review.
- `hive-core` has no Python dependency, so `cargo test` runs without an interpreter and
  the hot code never touches PyO3. `hive-python` depends on `hive-core` and PyO3.
- `_core` is the one private module of the package: its names are re-exported from
  `hive.engine.state`, `hive.engine.rules` and `hive.agents`, so no import outside the
  engine changes.

## Python API contract

The core must stay pleasant to use from Python, and cheap at the boundary.

- **Same names and signatures.** `Rules(piece_counts=..., starting_player=..., ...)` with
  the same keyword arguments and defaults, `rules.legal_moves(state)`,
  `rules.apply_checked_move(state=state, move=move)`, `state.apply_move(move)`,
  `Move(piece_type=..., source_coord=None, target_coord=(0, 0))`. Every argument can be
  passed by keyword, which the call style in `CLAUDE.md` relies on.
- **Values behave like the dataclasses they replace.** `==`, a dataclass-style `repr`,
  `__match_args__`, `str(move)` (`place ant at (1, 0)`), `to_json` and `from_json`, and
  `__get_pydantic_core_schema__` (delegating to a helper in `codec.py`), so `Move` and
  `Rules` keep working inside `GameRecord`, the API schemas and
  `json_adapter(list[Move | None])`. Pickling uses `__reduce__`, since workers receive
  rules and state copies.
  `Rules` stays frozen and hashable. `Move` becomes frozen and hashable (nothing mutates
  moves today), so moves can be set members and dict keys.
- **Enums and pieces stay Python.** The core returns the cached `Player` and `PieceType`
  members and the shared `Piece` instances, so identity checks and the JSON forms are
  unchanged.
- **`GameState` internals are snapshots.** `board`, `hand` and `queen_coord` return new
  dicts on every access (typed as before, so a board still passes as a `GameBoard`), and
  changing them does not change the state; production code only reads them, and the
  tests that wrote to them build states with `Rules.from_board` instead. `current_player` and
  `current_ply` keep their unchecked setters for tests and tools. A board snapshot costs a
  few microseconds, so code that reads the board in a loop uses the query methods
  (`is_occupied`, `get_top_piece`, `get_stack_height`, ...) or gets a batch method in the
  core. `copy()` stays, and `==` compares positions.
- **Errors keep their classes and texts.** `IllegalMoveError` and `InvalidBoardError` come
  from `errors.py` and carry the current messages. A Rust panic becomes a Python exception
  (`panic = "unwind"`, which PyO3 needs to catch it), so a bug in the core cannot kill the
  API process.
- **Docs and types.** The hand-written `_core.pyi` holds the Google-style docstrings and
  full annotations, so hover, `ty` and the docstring checkers see the same API as before.
  `help()` shows the same text at runtime, and `inspect.signature` works.
  `tests/test_core_stub.py` checks that the stub and the bindings have the same classes,
  members, parameters and docstrings (constructor docstrings against the Rust source).
- **What stays and what goes.** Everything the rest of the package uses stays: the `Rules`
  methods of `engine.md` (`legal_moves`, `placement_moves`, `movement_moves`,
  `movable_pieces`, `target_coords`, `placeable_coords`, `placeable_piece_types`,
  `winners`, `is_finished`, `from_board`, `apply_checked_move`, `illegal_move_reason`,
  `immobility_reason`, `create_initial_state`), and on `GameState` the queries,
  `apply_move` and `undo_move` with their placement and movement variants,
  `get_articulation_points` and `is_connected`. Helpers that only exist for the Python
  implementation go, and their tests move to Rust unit tests: `piece_lifted`, `can_slide`,
  `slideable_neighbors`, the per-piece `*_targets`, `PIECE_TARGET_COORDS`,
  `get_adjacent_players` and `calculate_boundary_coords`; `is_connected_after_removing`
  stays.
  `grid.py` stays as it is: the package uses its hex helpers, and the oracle its flank
  helpers.
- **Cross the boundary rarely.** Python code uses the Rust classes directly, never through
  wrappers. Work that loops over many nodes crosses the boundary once (perft, search,
  counting moves), and long calls release the GIL so other Python threads, such as the API
  event loop, keep running.

## Engine representation and optimisations

The engine is designed for speed from the start (WP 43); the long tail is left to
measurement (WP 29). Every item must keep perft parity and the differential tests green.

- **Grid.** A 32 × 32 twisted torus: cell index `(q + 32 r) mod 1024` as a `u16`, so the
  six neighbours of every cell are at the constant offsets `+1, −31, −32, −1, +31, +32`
  (mod 1024). A neighbour is one add and one mask, with no tables and no row wrapping. Two
  coordinates share an index only if their `q` or their `r` differ by 32 or more. Move
  generation reads cells up to two steps from the hive (the flanks of a slide, the
  neighbours of a placement candidate), and with `n` connected pieces those cells span at
  most `n + 3` in `q` and in `r`. With at most 28 pieces that is 31, so no two cells the
  engine reads share an index. `Rules` rejects piece counts above 28 in total (the base
  game has 22 pieces, all three expansions together 28), and debug builds assert the
  bound.
- **Cells.** A height and a small fixed stack per cell (at most 7 pieces with the
  expansions), plus per-player top-piece and occupancy sets kept by apply and undo, so
  ownership and occupancy checks are single lookups. Each occupied cell keeps its real
  `(q, r)`, so conversions at the Python boundary stay exact while the hive drifts across
  the torus.
- **Moves.** Packed into a `u32` (piece type, source cell, target cell) and generated into
  fixed-capacity buffers on the stack, so there is no heap allocation per node. Real
  coordinates and `Move` objects only exist at the boundary, and so does sorting into the
  documented order (placements first, then by piece type, source and target); the search
  uses its own move order.
- **Zobrist hash.** A 64-bit key per cell, height and piece, plus one for the side to
  move, updated by apply and undo. Hands follow from the board. The transposition table
  and repetition use it.
- **Articulation points.** Tarjan over the occupied cells (at most 28), only when
  movements are possible (own queen placed).
- **Counting without generating.** `count_moves` for perft leaves (bulk counting, reported
  separately from the apply-and-undo protocol of `hive bench engine`) and for the mobility
  evaluation.
- **Build.** One release profile with fat LTO and one codegen unit for uv, the tests,
  the benchmarks and the image (`tooling.md` §Rust).
- **Candidates to measure (WP 29),** kept only with a measured gain: 1024-bit occupancy
  bitboards (16 × `u64`) for placement candidates and the ant flood fill (the constant
  offsets make neighbour sets bit rotations, but long thin hives may still favour the
  scalar flood fill), per-player piece lists, caching articulation points by hash,
  profile-guided optimisation, and the CPU level of the image (WP 25 decides with the
  homelab hardware).

## Search kernel

Agents stay registered Python classes (D23): the constructor signature is still the params
schema, presets still work, and the match runner still calls `think(state, turn)`. A
search agent builds a Rust `Searcher` from its params once, and `think` hands it the state
and the turn context.

- **Control.** The search runs in Rust with the GIL released and calls back into Python
  rarely: `turn.submit` for the first legal move and after each completed depth,
  `turn.info` after each completed depth, and `turn.should_stop` before each depth and
  every `STOP_CHECK_INTERVAL` (1024) nodes: a fixed count rather than a time, so a seeded
  agent is reproducible under a fake clock, and at 20M nodes/s a stop is noticed within
  about 0.1 ms. The `TurnContext` protocol, the `info` fields (`depth`,
  `nodes`, `score`, `pv`, `nps`) and the runner are unchanged.
- **Port first (WP 45).** `negamax` and `minimax` keep their iterative deepening,
  finishing rules and evaluation terms, and visit the same number of nodes as the Python
  agents at a fixed depth (153,360 for `negamax-long-3`, 946 for `mobility-ant-2`).
  The `random` agent stays Python, so its seeded games stay the same.
- **Then strength (M7).** Repetition and seeded tie-breaking (WP 30); then principal
  variation search with alpha-beta, a transposition table (fixed size in MB, lockless
  entries holding the best move, depth-preferred replacement), move ordering (table move,
  killers, history, moves that crowd the opponent's queen), aspiration windows and lazy
  SMP threads (WP 28). `threads` is an agent param (default 1, so gauntlets stay
  reproducible), and gauntlet fairness counts threads against `cpu_count`. Pruning and
  reductions (null move, late move reductions) come only with gauntlet evidence.
- **Seeds.** The core has its own seeded RNG, so a seed reproduces a Rust agent's games
  but not the games the Python agents played with it.

## Correctness gates

"Correct" means the same game as the current Python engine, proven mechanically:

1. **Perft parity** at every reference depth in `tests/data/perft/base.json`, natively in
   `cargo test` and through the bindings in pytest. Native speed makes `start` depth 8
   (2,657,392,800 nodes) feasible as a slow test.
2. **Differential tests.** The current Python engine moves to `tests/oracle/` as a frozen,
   test-only reference. Hypothesis games compare the two engines at every ply: legal moves
   in order, winners, articulation points, `from_board` results and errors,
   `illegal_move_reason` texts and JSON forms. This catches what perft counts cannot (move
   order, messages, validation). Removing the oracle is a later decision, once the core
   has been stable for a while.
3. **Debug invariants** (`debug_assert!`, checked by `cargo test`): the incremental hash
   equals a fresh computation, apply then undo restores the state exactly, the occupancy
   and owner sets match the stacks, and the grid bound holds.
4. **Search equivalence.** A change that must not change results (alpha-beta without
   reductions, the transposition table, move ordering, stop handling, one thread) gives
   the same root score as plain negamax at the same depth on a fixed set of positions. A
   change that may change results (reductions, pruning, evaluation) needs a gauntlet win
   (M7).
5. **The Python suite is the API contract.** Imports, behaviour and JSON stay the same,
   and `make api-client` produces no diff.

## Benchmarks and targets

`hive bench engine` stays the protocol (`performance.md`). It gains native cases, where
perft and the search run entirely in Rust, and keeps the current cases, which then measure
the engine through the bindings. Targets on the Ryzen 7 5800H, recorded per work package:

| WP | Target | Result |
|---|---|---|
| 43 | Native perft at least as fast as the spike (62M nodes/s for `start` depth 5, 15M in the midgame cases), parity at all reference depths | 55.8M at `start` depth 6, 28.4M and 32.7M in the midgame; parity up to `start` depth 7 |
| 44 | The current benchmark cases at least 5 times faster through the bindings (geometric mean), the Python suite green without changes to code outside the engine | 10.2x before the search moved (29x after); green |
| 45 | `negamax-long-3` and `mobility-ant-2` at least 50 times faster than WP 27, with the same node counts | 104x and 154x, same node counts |
| 28 | A mean search depth of at least 6 at a 1 s budget (2.8 after WP 27) | 4.1 after WP 45; open (M7) |

The targets are lower bounds taken from the spike, not estimates of the final speed. The
results are from `performance.md` §Result (WP 42 to 45).
