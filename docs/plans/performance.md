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
Python 3.13. The rules are the reference rules in `tests/data/perft/base.json`.

| Date | Commit | Machine | Position | Depth | Nodes | Seconds | Nodes/s |
|---|---|---|---|---|---|---|---|
| 2026-10-24 | `18a5d3f` | AMD Ryzen 7 5800H, Linux | start | 5 | 516,240 | 0.94 | 549,000 |
| 2026-10-24 | `18a5d3f` | AMD Ryzen 7 5800H, Linux | start | 6 | 12,219,480 | 22.5 | 543,000 |
| 2026-10-24 | `18a5d3f` | AMD Ryzen 7 5800H, Linux | start | 7 | 181,641,900 | 559 | 325,000 |
| 2026-10-24 | #47 | AMD Ryzen 7 5800H, Linux | start | 5 | 516,240 | 1.07 | 483,000 |
| 2026-10-24 | #47 | AMD Ryzen 7 5800H, Linux | start | 6 | 12,219,480 | 25.6 | 478,000 |

Perft counts every leaf by applying and undoing the last move (no bulk counting at depth
one), so nodes/s compares apply, undo and move generation together. Nodes/s drops at depth
7 because deeper positions have more movement moves (ant flood fills, articulation
points). The depth 7 number is the `make test-slow` duration of the same walk.

The #47 rows sort `placement_moves` and `movement_moves`, so the move order depends only on
the position and seeded agents are reproducible. This costs about 12% nodes/s (median of
three runs at depth 5, one at depth 6). Win it back in WP 27, for example with a move or
board representation whose order is deterministic by construction.
