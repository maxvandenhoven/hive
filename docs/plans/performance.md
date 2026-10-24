# Performance: engine speed and agent strength (M6)

Correctness comes first (M1, perft parity). Only then does a separate round make the engine
faster and the agents stronger. Each stage happens only if the previous one is not enough.

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

## Agent strength (WP 28)

- Alpha-beta pruning in negamax, move ordering (moves that fill the opponent queen's
  free neighbors first, killer moves, history heuristic), transposition table keyed by Zobrist hash, iterative deepening
  with aspiration windows as an option.
- Evaluator weight tuning via gauntlets (grid or random search over weights, evaluated by
  win rate against fixed opponents at a fixed budget).
- Every change is validated by a gauntlet against the previous best at equal time budget,
  with the report committed under `reports/` or attached to the PR.

## Baseline numbers

To be filled in by WP 05 and WP 27.

| Date | Commit | Machine | Position | Depth | Nodes | Seconds | Nodes/s |
|---|---|---|---|---|---|---|---|
