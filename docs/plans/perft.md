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
    {"name": "start", "moves": [], "counts": {"1": 0, "2": 0}}
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

## Outcome (WP 05)

What the reference search found, recorded in `tests/data/perft/README.md` in full:

- Mzinga's wiki publishes base game counts for the start position only (depth 0 to 9,
  `MzingaPerft v0.12.9`). No published perft counts exist for other base game positions.
- nokamute's UHP test suite (`data/uhp_tests.txt`) provides 13 base game positions (piece
  movement, gates, game end, pass) with the complete list of legal moves. They are stored
  with depth 0 and 1 counts plus the exact move set, which the test compares as sets.
  Deeper counts for them need a local nokamute build (`nokamute perft "<game string>"`);
  WP 05 did not run external engines.
- Reference rules: tournament opening (`allow_queen_first_turn=False`), queen by turn 4,
  no movement before the queen, one placement per piece type, symmetric positions counted
  separately, a pass only without other moves, and no moves in a finished game. The last
  rule lives in `perft` (it returns 0 below a finished position), not in
  `Rules.legal_moves`. nokamute's threefold repetition draw has no `Rules` equivalent and
  its test case is left out.
- Engine bugs found, each fixed with a regression test in `tests/engine/test_rules.py`:
  - Sliding pieces only checked that the target touched some piece, so a slide could
    "jump" to a piece across an empty gap. A slide now needs one occupied flanking
    coordinate (`grid.get_flanking_coords`), which affects queen, spider and ant, and the
    beetle on the ground.
  - The beetle ignored gates on the hive. Following nokamute and the BoardGameGeek ruling
    it cites, a beetle move at height `h = max(source height without the beetle, target
    height)` is blocked when both flanking stacks are higher than `h`. Before, climbing
    was never blocked and moving down from the hive was blocked by any two flanking
    pieces.
- Agreed depths: the start position runs depth 0 to 5 in `make test` (about 1 second) and
  depth 6 and 7 under `slow` (about 23 seconds and 9 minutes). Depth 8 and 9 are stored but
  not run (hours in Python). The nokamute positions run in `make test`.
- `hive bench perft --depth N [--position NAME] [--divide] [--suite PATH]` reads the
  positions and rules from `tests/data/perft/base.json` and exits with an error when the
  count differs from a stored reference count. `make perft` runs it at depth 6.

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
- WP 27 adds `engine_counts`: depth 2 and 3 counts of the nokamute positions produced by
  this engine before the speedups, checked by the perft tests like reference counts. The
  start position only exercises placements up to depth 7, so without them a movement bug
  introduced by a speedup would only show at depth 1. `hive bench engine` (see
  `performance.md`) is the speed objective.
- In the autoresearch loop (WP 29), perft parity is the hard correctness gate and perft
  nodes/s is the objective.
