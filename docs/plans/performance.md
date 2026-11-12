# Performance: engine speed (M6) and agent strength (M7)

Correctness comes first (M1, perft parity). Only then does a separate round make the engine
faster (M6), and after that the agents stronger (M7). The speed round went from profiling
the Python engine (stage 1) to a Rust core for the engine and the search (stage 2, D30,
D31), with autoresearch on the Rust core for the long tail (stage 3). Agent strength is
measured by gauntlets between agents, and the goal of M7 is an agent that beats an
experienced human player.

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

## Stage 2: Rust core (WP 42 to 45)

WP 27 left the time spread over Python loops, dict lookups and object construction, and a
spike (2026-11-12) showed what a Rust core gives: perft and negamax entirely in Rust were
40 to 83 times faster than the WP 27 engine (62M nodes/s for `perft-start-5`, 14M for
`negamax-long-3`), with legal moves and perft counts identical on all suite positions. A
Python search loop over a Rust engine only reached 4.7 times on `negamax-long-3`, because
the loop itself costs about 1 µs per node, so the search moves to Rust too. The numbers,
the design and the correctness gates are in `rust-core.md`.

- WP 42: toolchain, Cargo workspace, maturin build, lints, Make targets, hooks, CI and the
  stub pipeline, with a minimal `hive._core` (`tooling.md` §Rust).
- WP 43: the engine in pure Rust (`hive-core`) with Zobrist hashing and native perft;
  parity at all reference depths in `cargo test`, native cases in `hive bench engine`.
- WP 44: the Rust `GameState`, `Rules` and `Move` replace the Python classes behind the
  same imports; the Python engine becomes the test oracle for differential tests.
- WP 45: the search kernel in Rust; `random`, `minimax` and `negamax` keep their behaviour
  and node counts, and the agents stay registered Python classes.
- Gate: perft parity, differential tests, node-count parity and `make check test`; each WP
  records `hive bench engine` before and after below.

### Result (WP 42 to 45)

The engine (WP 43, 44) and the search (WP 45) run in the Rust core. `hive bench engine`
on the WP 27 engine and on the Rust core, the same machine and session (AMD Ryzen 7 5800H),
median of 3 and 5 runs; every case visits the same nodes as before:

| Case | WP 27 nodes/s | Rust core nodes/s | Speedup |
|---|---|---|---|
| `perft-start-5` (Python loop over the bindings) | 739,644 | 5,264,569 | 7.1x |
| `perft-ant-3` (Python loop over the bindings) | 291,442 | 4,223,384 | 14.5x |
| `perft-long-3` (Python loop over the bindings) | 365,777 | 4,694,296 | 12.8x |
| `negamax-long-3` (Rust search) | 199,771 | 20,832,929 | 104x |
| `mobility-ant-2` (Rust search) | 3,761 | 577,787 | 154x |
| geometric mean of the five | 142,734 | 4,170,000 | 29x |

The new cases run entirely in Rust: `perft-start-6-native` 55.8M nodes/s (the Python
`make perft` walk of the same tree ran at 706,000), `perft-ant-4-native` 28.4M,
`perft-long-4-native` 32.7M, `negamax-long-4` 21.7M and `mobility-ant-3` 629,000. Against
the spike, the twisted torus, packed moves and allocation-free generation doubled the
midgame perft (15M before) and kept the start position (55M). The perft cases through the
bindings are bounded by the Python loop, as the spike predicted; Python code that walks
trees should call `Rules.perft` or the search instead.

The gauntlet of the WP 27 baseline (two unbounded `negamax` agents, `--budget 1
--max-turns 30 --seed 0`, two games) reached a mean search depth of 4.1 per decision
instead of 2.8. Without pruning a ply costs a factor of 30 to 100, so a hundred times
faster search buys about one ply; the depth target of 6 is for alpha-beta (WP 28).

Correctness: perft parity at every reference depth up to `start` depth 7 (181,641,900
nodes) in `cargo test`, the Python perft tests through the bindings, the differential
tests against the frozen Python engine (300 games of up to 200 plies in the slow profile,
plus random boards for `from_board`), and the node counts of the search cases. The full
Python suite passes without changes outside the engine apart from tests that wrote to the
state's internals, and the published API schema is unchanged.

## Stage 3: autoresearch on the Rust core (WP 29)

An agent-driven optimisation loop on the Rust engine and search, for what design alone
does not find (candidates in `rust-core.md` §Engine representation and optimisations):

- Objective: nodes/s of the native cases of `hive bench engine` (perft and fixed-depth
  search, median of several runs), reported per case and as a geometric mean.
- Hard gates: perft parity at all reference depths, the differential tests against the
  Python oracle, the search equivalence tests, `make check test`.
- Each iteration proposes one change on a branch, runs the gates and benchmark, and keeps
  the change only if it passes and improves the objective beyond noise. Results are logged
  (change summary, before/after, kept or reverted).
- WP 29 builds the harness (benchmark runner with noise control, gate script, results log,
  prompt/instructions for the agent) and runs a first session. It can start after WP 44,
  but gains most once the search runs in Rust (WP 45).

## Agent strength (M7)

### Repetition (WP 30)

Planned for the Rust core after WP 45: position history in `GameState`, a repetition
draw in `Rules`, and draw scoring and seeded tie-breaking in the search. The current
engine has a position hash but does not yet adjudicate repetition.

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

Implemented in the Rust search kernel (`rust-core.md` §Search kernel); repetition
awareness will be integrated through WP 30:

- Alpha-beta pruning in negamax, move ordering (moves that fill the opponent queen's
  free neighbors first, killer moves, history heuristic), transposition table keyed by Zobrist hash, iterative deepening
  with aspiration windows as an option.
- Evaluator weight tuning via gauntlets (grid or random search over weights, evaluated by
  win rate against fixed opponents at a fixed budget).
- Lazy SMP: a `threads` agent param (default 1) sharing the transposition table; gauntlet
  fairness counts threads against `cpu_count`.
- Changes that must not change results (alpha-beta itself, the transposition table, move
  ordering) give the same root score as plain negamax at the same depth; the rest is
  judged by gauntlets.
- Every change is validated by a gauntlet against the previous best at equal time budget,
  with the report committed under `reports/` or attached to the PR.

### Alpha-beta (first part of WP 28)

`alpha_beta` is an agent param of `minimax` and `negamax`, on by default. The search
prunes with alpha-beta and searches the principal variation of the previous depth first;
other moves keep their order (at the root, the documented order of legal moves). Rust
tests check that the root score equals the full search at depths 3 and 4 on several suite
positions, for both formulations, and that minimax and negamax prune alike. Among equally
scored moves another may be chosen than without pruning. The older benchmark cases turn
it off to keep their node counts.

Time to reach a depth on `long_hive` with the default evaluation, and on `ant_moves` with
the mobility term (medians of `hive bench engine` and single runs):

| Search | Full nodes | Full time | Alpha-beta nodes | Alpha-beta time | Speedup |
|---|---|---|---|---|---|
| `long_hive` depth 3 | 153,360 | 7.2 ms | 5,989 | 0.5 ms | 14x |
| `long_hive` depth 4 | 12,102,433 | 572 ms | 51,847 | 6 ms | 95x |
| `long_hive` depth 5 | – | – | 454,425 | 27 ms | |
| `long_hive` depth 6 | – | – | 1,241,120 | 341 ms | |
| `ant_moves` mobility depth 3 | 39,464 | 64 ms | 3,286 | 5.4 ms | 12x |
| `ant_moves` mobility depth 5 | – | – | 481,529 | 755 ms | |

Pruning costs nodes per second (3.6M against 21M at `long_hive`, since every visited node
generates all its moves but searches few of them), but it reaches depth 6 in a third of
the time the full search needs for depth 4. The gauntlet of the WP 27 baseline (two
unbounded `negamax` agents, `--budget 1 --max-turns 30 --seed 0`, two games) reached a
mean search depth of 5.4 per decision, against 4.1 without pruning and 2.8 for the Python
search, and both games ended in a win instead of a draw at the turn cap. Move ordering
beyond the principal variation, the transposition table and threads (the rest of WP 28)
come next.

### Search speed log (WP 28)

Every step keeps the root scores of the full search (Rust tests compare them at fixed
depths). Time to reach a depth with `negamax`, median of 3 runs on the Ryzen 7 5800H:

| Step | `long_hive` depth 4 | `long_hive` depth 6 | `long_hive` depth 7 | `ant_moves` mobility depth 5 |
|---|---|---|---|---|
| Python search (WP 27) | about 60 s (12.1M nodes) | – | – | – |
| Rust search, no pruning (WP 45) | 572 ms, 12,102,433 nodes | – | – | – |
| Alpha-beta, previous best line first | 6.0 ms, 51,847 nodes | 342 ms, 1,241,120 | 2,776 ms, 46,021,711 | 758 ms, 481,529 |
| Transposition table (key includes the ply), killer moves, history ordering | 3.2 ms, 13,614 nodes | 103 ms, 455,206 | 477 ms, 5,155,252 | 74 ms, 46,978 |

The table, killers and history apply to `negamax` (param `table_megabytes`, default 32,
zero turns them off); `minimax` keeps plain alpha-beta. The table is kept between the
decisions of a match and cleared by `reset`. The continuation below adds optional search refinements and evaluates weights.


### Search continuation and weight tuning (WP 28)

The continuation adds three independently configurable search options:

- `aspiration_window`: start each new depth near the previous score and widen failed
  windows geometrically. Only a completed search inside its window is reported.
- `principal_variation_search`: scout later moves with the smallest representable score
  window, then re-search improvements with the full window. This supports fractional
  evaluator weights without assuming integral scores.
- `threads`: lazy SMP with one reporting thread and diversified helper root orders. The
  transposition table is shared through striped locks; one-thread searches avoid locks.
  Helpers only poll a cancellation flag and never call Python. Scope exit cancels and
  joins them, including when the observer panics. Reported nodes/NPS count the main
  thread, not total work across helpers. The configured table budget is shared.

Table score cutoffs now require the same remaining depth. A deeper heuristic search is
not generally the score of a shallower search; this matters with a warm table or helpers
searching different depths. Other-depth entries still supply move ordering. Tests compare
scores with full search, re-use warm tables, replay PV moves, and check cancellation and
state restoration. Gauntlet CLI concurrency accounts for the largest thread count.

Depth measurements use `scripts/bench_search.py`, a fresh agent per position, one second
(three repetitions) and ten seconds (one observation per position). The four distinct
positions are `start`, `long_hive`, `ant_moves`, and `beetle_gate`, using the perft suite
rules (queen-first opening disabled). Gauntlets and tuning use the app default rules,
which allow a queen-first opening. An initial run included
`tournament_opening`, which is identical to `start` under the suite rules; it was replaced
by a separate serial measurement of `beetle_gate` before calculating the final summaries.
Searches run sequentially, separately from tuning. Completed depths only are counted.
These are wall-clock measurements on the Ryzen 7 5800H, not guarantees for other machines.

| Cumulative change | 1 s mean | 1 s maximum | 10 s mean | 10 s maximum |
|---|---:|---:|---:|---:|
| Alpha-beta only | 6.75 | 8 | 7.75 | 9 |
| Table + killers + history (#89) | 8.25 | 10 | 9.75 | 11 |
| + aspiration (0.5) | 8.25 | 10 | 9.75 | 11 |
| + principal-variation search | 8.25 | 10 | 9.75 | 11 |
| + 2 threads | 8.25 | 10 | 10.00 | 11 |
| 4 threads instead of 2 | 8.33 | 10 | 10.00 | 11 |

The table gives +2 maximum plies over alpha-beta at both budgets. Each subsequent change
adds **zero** to the global maximum, which is set by the opening. Two threads do add one
ply to `beetle_gate` at ten seconds (9 to 10), while four add no further depth there. Four
threads complete an extra ply on one of three one-second `beetle_gate` runs; that marginal
result should not be treated as a reliable one-ply gain. Ten-second per-position results:

| Configuration | start | long_hive | ant_moves | beetle_gate |
|---|---:|---:|---:|---:|
| Alpha-beta | 9 | 7 | 7 | 8 |
| Table | 11 | 9 | 10 | 9 |
| + aspiration | 11 | 9 | 10 | 9 |
| + PVS | 11 | 9 | 10 | 9 |
| + 2 threads | 11 | 9 | 10 | 10 |
| 4 threads | 11 | 9 | 10 | 10 |

Depth is coarse: saving time does not necessarily complete another whole ply. Median
seconds to complete the same depth in the one-second runs (`nodes / nps`, rounded):

| Configuration | start depth 10 | long_hive depth 7 | ant_moves depth 8 |
|---|---:|---:|---:|
| Table | 0.933 | 0.486 | 0.484 |
| + aspiration | 0.896 | 0.374 | 0.355 |
| + PVS | 0.817 | 0.376 | 0.340 |
| + 2 threads | 0.640 | 0.426 | 0.278 |
| 4 threads | 0.598 | 0.475 | 0.266 |

Thus aspiration saves about 23% on `long_hive` and 27% on `ant_moves`; PVS helps the opening
by another 9% but is neutral on `long_hive`. SMP helps some positions and hurts others.
All three remain options, with the existing defaults preserved (window 0, PVS false,
threads 1). Two threads are the better resource tradeoff in this sample. Raw observations
are `reports/wp28-{alpha-beta,table,aspiration,pvs,threads2,threads4}-{1,10}s.json`.

Each new option also played its predecessor for two colour-swapped games at one second
per move, seed 0, cap 30 turns (`wp28-{aspiration,pvs,threads2,threads4}-gauntlet.json`).
Every pairing finished 1–1, with white winning both games; none recorded failures,
restarts, overruns or illegal submissions. These small matches are smoke tests, not
strength significance tests. Candidate mean/maximum completed depths were:

| Change | Previous mean / maximum | Candidate mean / maximum |
|---|---:|---:|
| Aspiration | 6.72 / 9 | 6.72 / 9 |
| PVS | 6.76 / 9 | 6.76 / 9 |
| Two threads | 6.72 / 9 | 6.79 / 10 |
| Four threads | 6.79 / 10 | 6.86 / 10 |

The requested #89 self-play rerun is `reports/wp28-baseline-gauntlet.json`: two games,
one second per move, seed 0, 30 turns maximum, one concurrent match. Its participants
average 6.7 and 6.6 plies respectively, versus the earlier alpha-beta report's 5.4. Both
games finish in wins, with no worker failures, illegal submissions or recorded overruns.
Self-play depth is descriptive; the fixed suite above is the controlled speed comparison.


The tuning harness, `scripts/tune_search.py`, uses eight seeded legal opening plies,
then plays both colours from each opening against a fixed opponent. Every move is checked
by the engine. A turn cap counts as a draw, never as a heuristic win. All moves, openings,
parameters and decision depths are retained in the JSON reports. The screening round uses
seeds 0–3, eight candidates, 0.1 seconds per decision and 120 plies maximum (64 games).
Validation uses disjoint seeds 100–107 and 0.5 seconds per decision. Jobs times search
threads must fit the CPU count. The two material terms are negatives in the base game,
so only on-board material is varied; queen safety stays at 1 to fix the weight scale.

| Candidate (queen safety stays 1) | Screening, 0.1 s (8 games) | Validation, 0.5 s (16 games) |
|---|---:|---:|
| positioning 0.25 | 81.25% | 53.125% |
| positioning 0.5 | 81.25% | 40.625% |
| material_on_board 0.05 | 62.5% | 62.5% |
| material_on_board 0.1 | 56.25% | not advanced |
| positioning 0.5, material_on_board 0.1 | 43.75% | not advanced |
| mobility 0.02 | 62.5% | 56.25% |
| mobility 0.1 | 43.75% | not advanced |
| mobility 0.05, positioning 0.5, material_on_board 0.1 | 62.5% | 50% |

Percentages are points per game (win 1, draw 0.5). The initial positioning finalists did
not convincingly improve on the baseline, so three other screening candidates were also
validated on the same held-out opening set. Material 0.05 led with 6 wins, 8 draws and
2 losses. A separate confirmation on seeds 200–203, both colours, at **one second** yielded
3 wins, 2 draws and 3 losses: **50%**. Across screening, validation and confirmation this
is 152 games. There is no statistically established weight improvement, so **the default
weights are retained**. The requirement in issue #39 to establish a significant strength
increase remains open; this work must not close that issue on speed evidence alone.

The material candidate's fixed-suite maximum stays 10 at one second and 11 at ten seconds
(zero improvement); its mean stays 8.25 at one second and drops from 9.75 to 9.50 at ten
seconds (`ant_moves` drops from 10 to 9). Those observations are in `wp28-tuned-{1,10}s.json`.
Raw tuning reports are `wp28-tuning-{screen,validation,additional,confirmation}.json`.

The app's default-rule opening also reaches **11 completed plies at ten seconds**, both
with default search options and with aspiration/PVS/two threads, recorded separately in
`wp28-app-{default,smp}-10s.json`. The new `nm-smp` preset exposes the tested two-thread
configuration with the original evaluator. It is a performance option, not a claim of
statistically established playing superiority. Existing defaults stay compatible.

Validation: `make check api-client test test-slow` passes: 1,099 regular Python tests,
10 slow Python tests, 209 frontend tests, and all Rust tests including the large perft
case. The generated API client is unchanged. Search tests cover warm-table score parity,
fractional PVS/aspiration windows, 1/2/4 threads, legal variations, state restoration,
cancellation and observer panic; boundary and gauntlet CPU-accounting tests pass.


Reproduce from the repo root after `uv sync`:

```sh
uv run python scripts/bench_search.py --budget 10 --repeat 3 \
  --params '{"aspiration_window": 0.5, "principal_variation_search": true}' \
  --out reports/wp28-repeat-10s.json
uv run python scripts/tune_search.py --candidates candidates.json --budget 0.5 \
  --pairs 8 --seed 100 --jobs 4 --out reports/wp28-validation-repeat.json
```

The `candidates` mapping inside the screening/validation report is the contents to use
for `candidates.json`. Exact timed decisions can differ between runs. Screening and
validation are evidence against the tested opponents and openings, not proof of optimal
weights or experienced-human strength. Repetition handling (WP 30) remains a separate
engine/search task; these experiments use the explicit turn cap for non-finishing games.

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
