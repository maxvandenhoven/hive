# Perft

Perft ("performance test") walks the full game tree from a position to a fixed depth and
counts the leaf positions, without evaluation or pruning:

```python
def perft(state: GameState, rules: Rules, depth: int) -> int:
    if depth == 0:
        return 1
    count = 0
    for move in rules.legal_moves(state):
        state.apply_move(move)
        count += perft(state, rules, depth - 1)
        state.undo_move(move)
    return count
```

It serves two purposes:

1. **Correctness.** Counts depend only on the rules, so every correct engine produces the
   same numbers. A mismatch means a missing or illegal move somewhere, or an
   `apply_move` / `undo_move` that does not restore state. A *divide* (counts per first
   move) localises the difference: compare per-move counts with the reference and recurse
   into the branch that differs.
2. **Speed.** It only generates, applies and undoes moves, so positions per second is a
   clean measure of raw engine speed, independent of evaluators and search.

## Reference data (WP 05)

Reference counts come from established Hive engines (Mzinga and nokamute publish or can
produce perft counts for the base game). They are stored as data in the repo, never as a
dependency:

```
tests/data/perft/
├─ README.md            # citation: engine, version, commit/URL, date retrieved, how produced
└─ base.json            # rule settings + counts per depth (+ optional divide tables)
```

`base.json` shape:

```json
{
  "source": "see README.md",
  "rules": {"allow_queen_first_turn": false, "queen_by_turn": 4, "...": "..."},
  "positions": [
    {"name": "start", "setup": "initial", "moves": [], "counts": {"1": 0, "2": 0}}
  ]
}
```

(`0` above is a placeholder; real values come from the cited source.)

Things to verify, not assume, while gathering references:

- Rule settings the reference uses: tournament opening (no queen on the first turn),
  queen-by-turn-4, passes, whether the game ends at the move that surrounds a queen.
- Whether the reference counts moves by notation (symmetric placements counted separately)
  the same way our engine does. Our engine does not deduplicate symmetric positions.
- Pick 2–4 non-trivial positions as well (beetle stacks, gates, a pinned queen), since the
  start position exercises placements far more than movement.

If the reference rules differ from ours in a way `Rules` cannot express, document the
difference in `tests/data/perft/README.md` and add a `Rules` option only if it is a real
rule variant.

## Code

- `src/hive/bench.py`: `perft(state, rules, depth)`, `divide(state, rules, depth)` and a
  timed variant returning nodes and nodes per second.
- CLI: `hive bench perft --depth N [--position NAME] [--divide]`.
- Tests: `tests/engine/test_perft.py` runs all positions at shallow depths in CI (keep the
  total under about 30 seconds). Deeper depths are marked `@pytest.mark.slow` and excluded
  from `make test` by default (`make test-slow` runs them).

## Use in CI and M6

- CI runs shallow perft on every PR: any rule regression fails the build.
- `hive bench perft` output is the speed baseline for M6. Record baseline numbers (depth,
  nodes, seconds, nodes/s, machine) in `performance.md` when WP 05 lands.
- In the autoresearch loop (WP 29), perft parity is the hard correctness gate and perft
  nodes/s is the objective.
