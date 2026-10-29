# Performance: engine speed (M6) and agent strength (M7)

Correctness comes first (M1, perft parity). Only then does a separate round make the engine
faster (M6), and after that the agents stronger (M7). Each speed stage happens only if the
previous one is not enough. Agent strength is measured by gauntlets between agents, and
the goal of M7 is an agent that beats an experienced human player.

## Stage 1: profiling and targeted speedups (WP 27)

- Baseline: `hive bench perft` nodes/s at a fixed depth and position set, plus a fixed
  gauntlet's average search depth per turn. Record numbers below.
- Profile with `cProfile` + `snakeviz` and `py-spy` (sampling, flame graphs) on perft and on
  a timed negamax decision.
- Likely hot spots (verify with the profiler, do not assume): articulation points
  recomputed per call, slide checks, ant flood fill, list allocations in move generation,
  dataclass `Move` construction.
- Candidate optimisations: incremental or cached articulation points per position, Zobrist
  hashing (also needed for transposition tables), cheaper move representation internally,
  avoiding repeated neighbor tuple construction.
- Gate: perft parity and all tests stay green; nodes/s improves measurably.
- Outcome: `hive bench engine` is the protocol, and six profile-driven speedups make the
  engine about 2.5 times faster (geometric mean of the benchmark cases). Slide checks
  were the hot spot, not articulation points, so neither incremental articulation points
  nor Zobrist hashing were needed. See "Engine benchmark (WP 27)" below.

## Stage 2: autoresearch (WP 29)

An agent-driven optimisation loop on the engine:

- Objective: perft nodes/s on the benchmark positions (median of several runs).
- Hard gates: perft parity at all reference depths, full test suite green, type check green.
- Each iteration proposes one change on a branch, runs the gates and benchmark, and keeps
  the change only if it passes and improves the objective beyond noise. Results are logged
  (change summary, before/after, kept or reverted).
- WP 29 builds the harness (benchmark runner with noise control, gate script, results log,
  prompt/instructions for the agent) and runs a first session.

## Stage 3: Rust core (only if needed)

If profiling and autoresearch leave the engine too slow for useful search depth, port
`GameState` and `Rules` to Rust with PyO3, keeping the Python interface identical so agents,
API and vision are unaffected. Perft parity is the acceptance test. Not planned as a work
package until the data says so.

## Agent strength (M7)

### Repetition (WP 30)

The first nm2 vs nm3 gauntlet (WP 09, seed 42, 2 s per move, 100 turns) drew all four
games at the turn cap. In one game the black agent blocked every white move and then
moved its queen back and forth for 140 plies at a constant +4, and games with the same
colours repeated move for move despite different seeds. WP 30 fixes this first, so later
gauntlets measure strength rather than stalling:

- A position key (Zobrist hash, shared with the WP 28 transposition table) and a count of
  every position in the game, kept in sync by `apply_move` / `undo_move`.
- A repetition draw in `Rules` (for example a third occurrence), reported separately from
  turn caps.
- Search scores a repeated position as a draw, so an agent that is ahead looks for progress.
- Ties between equal moves are broken with the agent's seed, so seeds give different games.

### Search and tuning (WP 28)

- Alpha-beta pruning in negamax, move ordering (moves that fill the opponent queen's
  free neighbors first, killer moves, history heuristic), transposition table keyed by Zobrist hash, iterative deepening
  with aspiration windows as an option.
- Evaluator weight tuning via gauntlets (grid or random search over weights, evaluated by
  win rate against fixed opponents at a fixed budget).
- Every change is validated by a gauntlet against the previous best at equal time budget,
  with the report committed under `reports/` or attached to the PR.

## Baseline numbers

Measured with `hive bench perft` (WP 05) on an otherwise idle machine, single process,
Python 3.13. The rules are the reference rules in `tests/data/perft/base.json`. The WP 27
rows were measured on a busier machine (see the WP 27 sections), the depth 5 row as the
mean of the two final `hive bench engine` medians.

| Date | Commit | Machine | Position | Depth | Nodes | Seconds | Nodes/s |
|---|---|---|---|---|---|---|---|
| 2026-10-24 | `18a5d3f` | AMD Ryzen 7 5800H, Linux | start | 5 | 516,240 | 0.94 | 549,000 |
| 2026-10-24 | `18a5d3f` | AMD Ryzen 7 5800H, Linux | start | 6 | 12,219,480 | 22.5 | 543,000 |
| 2026-10-24 | `18a5d3f` | AMD Ryzen 7 5800H, Linux | start | 7 | 181,641,900 | 559 | 325,000 |
| 2026-10-24 | #47 | AMD Ryzen 7 5800H, Linux | start | 5 | 516,240 | 1.07 | 483,000 |
| 2026-10-24 | #47 | AMD Ryzen 7 5800H, Linux | start | 6 | 12,219,480 | 25.6 | 478,000 |
| 2026-10-29 | WP 27 | AMD Ryzen 7 5800H, Linux | start | 5 | 516,240 | 0.72 | 718,000 |
| 2026-10-29 | WP 27 | AMD Ryzen 7 5800H, Linux | start | 6 | 12,219,480 | 17.3 | 706,000 |
| 2026-10-29 | WP 27 | AMD Ryzen 7 5800H, Linux | start | 7 | 181,641,900 | 366 | 497,000 |

Perft counts every leaf by applying and undoing the last move (no bulk counting at depth
one), so nodes/s compares apply, undo and move generation together. Nodes/s drops at depth
7 because deeper positions have more movement moves (ant flood fills, articulation
points). The depth 7 number is the `make test-slow` duration of the same walk.

The #47 rows sort `placement_moves` and `movement_moves`, so the move order depends only on
the position and seeded agents are reproducible. This costs about 12% nodes/s (median of
three runs at depth 5, one at depth 6). WP 27 generates the moves in sorted order instead,
and the WP 27 rows are well past the unsorted numbers (see the WP 27 sections below).

## Engine benchmark (WP 27)

`hive bench engine` is the benchmark protocol of the speed work. It runs a fixed set of
cases (`ENGINE_BENCH_CASES` in `src/hive/bench.py`), each about one second at the
baseline, `--repeat` times (default 5). The cases take turns, one run each per round, so a
slow phase of the machine spreads over all of them. Per case it prints the median seconds,
the spread (slowest minus fastest run over the median) and nodes/s of the median run, and
overall the geometric mean of the nodes/s of all cases, which weighs a relative speedup of
every case equally. Every run must reproduce the node count of its case, so a speedup that
changes the game tree fails the benchmark (exit code 1).

| Case | Workload | Nodes |
|---|---|---|
| `perft-start-5` | perft from the start position, depth 5: placements | 516,240 |
| `perft-ant-3` | perft from `ant_moves`, depth 3: a large hive with many ant moves | 37,589 |
| `perft-long-3` | perft from `long_hive`, depth 3: a long chain, ants along the hive | 149,512 |
| `negamax-long-3` | one `negamax` decision at depth 3 from `long_hive`, default evaluation | 153,360 |
| `mobility-ant-2` | one `negamax` decision at depth 2 from `ant_moves` with `mobility: 1.0`, which generates the moves of both players at every leaf | 946 |

The midgame positions come from the nokamute positions of the perft suite. Their depth 2
and 3 counts are `engine_counts` produced by this engine (see
`tests/data/perft/README.md`), which the perft tests also check, so a change in movement
generation fails `make test` and not only the benchmark.

Profile with `cProfile` or `py-spy` on the same cases:

```
uv run hive bench engine --repeat 1 --case perft-long-3 --profile long.prof
uv run snakeviz long.prof   # or python -m pstats long.prof
uvx py-spy record --format raw -o stacks.txt -- .venv/bin/hive bench engine --repeat 1
```

`py-spy` needs a Python process as its child (`.venv/bin/hive`, not `uv run`), and
`--format raw` writes collapsed stacks that can be summarised as text or turned into a
flame graph.

### Baseline (WP 27)

Measured on `41b8a30` (AMD Ryzen 7 5800H, Linux, Python 3.13.12, otherwise idle), median
of 5 runs per case, spread below 3% for every case:

| Case | Median s | Nodes/s |
|---|---|---|
| `perft-start-5` | 1.036 | 498,000 |
| `perft-ant-3` | 0.354 | 106,000 |
| `perft-long-3` | 1.215 | 123,000 |
| `negamax-long-3` | 1.761 | 87,100 |
| `mobility-ant-2` | 0.854 | 1,110 |
| geometric mean | | 57,500 |

`make perft` (start position, depth 6): 24.9 s, 491,000 nodes/s. A gauntlet of two
`negamax` agents without a depth limit (`--budget 1 --max-turns 30 --seed 0`, two games)
reached a mean search depth of 2.6 per decision.

Profile of the baseline (`py-spy`, share of samples including callees, `perft-long-3` and
`negamax-long-3` together):

| Function | Share |
|---|---|
| `Rules.legal_moves` | 74% |
| `Rules.ant_targets` | 60% |
| `Rules.slideable_neighbors` | 56% |
| `grid.get_flanking_coords` (twice per neighbour: `can_slide` and the contact check) | 27% |
| `GameState.can_slide` | 21% |
| `GameState.is_occupied` (self time only) | 11% |
| `SearchAgent.evaluate` | 8% |
| `Rules.winners` | 7% |
| `Rules.placement_moves` | 6% |
| `GameState.get_articulation_points` | 4% |
| `GameState.apply_move` and `undo_move` | 7% |

In the start position `placement_moves` takes 32% (including sorting the moves and
constructing `Move`s), `apply_placement` 23% (a new `Piece` per placement),
`undo_placement` 12% and `get_adjacent_players` 10% (a set per candidate coordinate).
Articulation points are not a hot spot (4%), so incremental articulation points are not
worth their complexity. Zobrist hashing only adds work to perft; it belongs to repetition
handling (WP 30) and the transposition table (WP 28).

### Speedups (WP 27)

One commit per speedup, each measured A/B: the commit and its parent ran `hive bench
engine` back to back, twice, from the same virtual environment. The machine was not idle
during WP 27 (another long-running process and an editor), so absolute numbers vary by
about 5% between sessions, but each A/B pair saw the same conditions. Geometric mean
nodes/s, both rounds:

| Commit | Change | Before | After | Gain |
|---|---|---|---|---|
| `perf(engine): look up the flanks of a slide from a cached table` | `grid.get_neighbor_flanks` caches every neighbour with its two flanking coordinates; `slideable_neighbors` checks exactly one occupied flank on the board dict | 57,485 | 109,764 | +91% |
| `perf(engine): generate moves in sorted order instead of sorting them` | sort the few coordinates, piece types and targets instead of every `Move` with a key function | 109,165 / 108,095 | 110,490 / 113,774 | +3% |
| `perf(engine): check each placement candidate once without owner sets` | `placeable_coords` checks every candidate once and stops at the first opponent neighbour | 110,440 / 110,488 | 124,605 / 125,756 | +13% |
| `perf(engine): place shared piece instances instead of new pieces` | `SHARED_PIECES` holds one immutable `Piece` per owner and type (start position +32%) | 125,209 / 123,626 | 129,840 / 131,896 | +5% |
| `perf(engine): count occupied neighbours with plain loops on the board` | `is_surrounded` stops at the first free neighbour, `count_occupied_neighbors` for the evaluation (negamax +26%) | 130,519 / 129,414 | 138,882 / 138,542 | +7% |
| `perf(engine): find articulation points with a recursive search on the board` | recursive Tarjan on the board dict, about 27% faster per call | 135,102 / 135,225 | 140,713 / 141,167 | +4% |

The first row compares with the quiet baseline above instead of an A/B pair.

### Result (WP 27)

Baseline (`59454d2`, the benchmark on the WP 27 baseline engine) and the final engine, A/B
back to back, median of 5 runs per case, nodes/s of both rounds:

| Case | Baseline | Final | Speedup |
|---|---|---|---|
| `perft-start-5` | 465,388 / 473,704 | 703,126 / 732,044 | 1.5x |
| `perft-ant-3` | 100,702 / 100,177 | 252,115 / 286,841 | 2.7x |
| `perft-long-3` | 113,358 / 114,933 | 336,426 / 364,606 | 3.1x |
| `negamax-long-3` | 81,297 / 83,643 | 183,930 / 197,476 | 2.3x |
| `mobility-ant-2` | 1,043 / 1,056 | 3,654 / 3,669 | 3.5x |
| geometric mean | 53,798 / 54,526 | 132,003 / 140,871 | 2.5x |

`make perft` (start position, depth 6): 24.9 s and 491,000 nodes/s before, 17.3 s and
706,000 nodes/s after. Depth 7 takes 366 s instead of 559 s. The gauntlet of the baseline
section reached a mean search depth of 2.8 instead of 2.6 (decisions at depth 2, 3, 4: 23,
20, 5 before and 17, 25, 6 after), and the agents reported 174,000 instead of 104,000
nodes/s. Without pruning a ply costs a factor of 30 to 100 in the midgame, so speed alone
adds little depth; alpha-beta (WP 28) is what turns it into depth. The perft parity tests,
the engine counts and the property tests pass at every commit.

Measured but not done:

- Inlining the slide check into the ant flood fill: +7% on `perft-long-3` and
  `perft-ant-3`, but it repeats the slide rule of `slideable_neighbors`. A candidate for
  WP 29, where the gates check such changes mechanically.
- Reusing the popped stack in `apply_*` and `undo_*` instead of looking it up again: no
  difference beyond noise.
- A class instead of `@contextmanager` for `piece_lifted`: 0.5 µs less per call, but at
  about 15,000 calls per `perft-long-3` run, about 2%.
- Disabling the garbage collector: at most 1%, before and after shared pieces.

Profile of the final engine (`py-spy`, `perft-long-3` and `perft-ant-3`, share of samples
including callees): `movement_moves` 43% (8% self, mostly `Move` construction),
`ant_targets` 25%, `slideable_neighbors` 17%, `apply_move` and `undo_move` 17%,
`placeable_coords` 7%, `get_articulation_points` 7%. In the start position:
`placement_moves` 26% (half of it `Move` construction), `apply_move` and `undo_move` 40%,
`placeable_coords` 11%. What is left is spread over plain Python loops, dict lookups and
object construction; further large gains need a different representation (for example
integer coordinates or bitboards), which is the work of WP 29 or a Rust core.
