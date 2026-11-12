# Perft reference data

`base.json` holds reference perft counts for the base game (queen, beetle, grasshopper,
spider, ant), together with the `Rules` settings that reproduce the reference engines.
`tests/engine/test_perft.py` checks the engine against it, and `hive bench perft` reads it
for named positions. No reference engine is a dependency; the numbers are copied data.

## File format

```json
{
  "rules": {"allow_queen_first_turn": false, "...": "..."},
  "positions": [
    {
      "name": "start",
      "source": "mzinga",
      "moves": [{"piece": "ant", "from": null, "to": [0, 0]}],
      "counts": {"0": 1, "1": 4},
      "legal_moves": [{"piece": "beetle", "from": [0, 0], "to": [1, 0]}]
    }
  ]
}
```

- `rules` holds `Rules` fields (`starting_player` as a lower case name). `piece_counts`
  keeps its base game default.
- `moves` lead from the initial state to the position. A move is `null` (a pass) or
  `{"piece", "from", "to"}` with axial coordinates `[q, r]` and `from` set to `null` for
  a placement.
- `counts` maps a depth to the reference perft count at that depth.
- `engine_counts` (optional) maps a depth to the perft count of this engine where no
  reference count is known (see below).
- `legal_moves` (optional) is the complete reference list of legal moves, so the test
  compares exact move sets and not just their number.
- `uhp` (nokamute positions only) is the original UHP game string, for traceability.

## Sources

### Start position: Mzinga

- Engine: Mzinga by Jon Thysell, counts computed with `MzingaPerft v0.12.9`.
- URL: <https://github.com/jonthysell/Mzinga/wiki/Perft> (table "Perft Results (Initial
  Position)", column "Base").
- Retrieved: 2026-10-24, copied by hand from the wiki page.
- Counts: depth 0 to 9. The wiki marks depths 3 and higher as not independently
  verified; this engine reproduces them independently up to depth 7.

### Other positions: nokamute UHP test suite

- Engine: nokamute by Eric Roshan-Eisner (MIT license), file `data/uhp_tests.txt`.
- URL: <https://github.com/edre/nokamute/blob/2d478d8f0d02e071623a983094d10dbda43e2fe9/data/uhp_tests.txt>
  (commit `2d478d8f0d02e071623a983094d10dbda43e2fe9`, 2026-10-21; the base game cases
  date from commits `bdf53e9` and `d8a968d`, May 2023).
- Retrieved: 2026-10-24.
- Each case is a UHP game string plus the complete list of valid moves in the final
  position, which nokamute compares against a UHP engine's `validmoves`. That gives the
  depth 1 count and the exact move set. A case whose game string ends in a won or drawn
  game has no moves, which gives the depth 1 count of 0.
- Converted: every case with game type `Base` except "Draw by threefold repetition"
  (see below). The UHP game strings were replayed into engine moves with a one-off script,
  using the UHP direction markers for pointy-top hexes: `X-` east `(1, 0)`, `-X` west
  `(-1, 0)`, `X/` north-east `(1, -1)`, `/X` south-west `(-1, 1)`, `X\` south-east
  `(0, 1)`, `\X` north-west `(0, -1)`, a bare `X` on top of `X`, and the first piece at
  `(0, 0)`. Perft counts and move sets do not depend on this orientation.

| Name | nokamute case | Exercises |
|---|---|---|
| `queen_moves` | Queen moves | queen slides, hive contact while sliding |
| `grasshopper_moves` | Grasshopper moves | grasshopper jumps, placements |
| `ant_moves` | Ant moves | ant reach around a large hive |
| `spider_moves` | Spider moves | spider paths, hive contact while sliding |
| `spider_moves_2` | Spider moves 2 | spider paths |
| `beetle_moves` | Beetle moves | beetle on the hive |
| `tournament_opening` | Tournament rules | no queen on the first turn |
| `white_wins` | White wins | game end, no moves after a win |
| `black_suicide` | Black suicide | game end when a player surrounds its own queen |
| `draw` | Draw | game end when both queens are surrounded |
| `pass` | Pass | pass when there is no legal move |
| `long_hive` | Super long hive axis-1 | long chain, ant along the whole hive |
| `beetle_gate` | Beetle gate | gates between stacks for a beetle on the hive |

Only depth 0 and 1 are known for these positions. Deeper counts need running a reference
engine, for example `nokamute perft "<uhp game string>"` from a local build, and adding
the numbers here with the engine commit.

### Engine counts: this engine

`engine_counts` holds the depth 2 and 3 counts of the nokamute positions that are not
finished games, produced by this engine at commit `41b8a30` (2026-10-29), before the WP 27
speedups. They are not reference counts: they match the references only as far as the
depth 1 move sets do. They guard the speed work instead, since a faster engine has to keep
producing the same trees. `tests/engine/test_perft.py` checks them like the reference
counts, and `hive bench perft` and `hive bench engine` report a mismatch. Replace them by
reference counts when a reference engine has been run on these positions.

The depth 4 counts of `ant_moves` (2,729,747) and `long_hive` (11,797,660) were added with
the Rust core (WP 43) for the native benchmark cases. Both the Rust core and the frozen
Python engine (`tests/oracle/`) produced them on 2026-11-12.

## Rule settings

Both references use the same rules, which `base.json` sets as:

| Reference rule | `Rules` setting |
|---|---|
| The queen cannot be placed on a player's first turn (tournament opening). | `allow_queen_first_turn=False` |
| The queen must be placed by a player's fourth turn. | `queen_by_turn=4` |
| Pieces cannot move before their owner's queen is placed. | `move_before_queen=False` |
| One placement per piece type and target, whichever copy is placed. | always true in this engine |
| Symmetric positions are counted separately. | always true in this engine |
| A pass is allowed only without other legal moves and counts as one move. | always true in this engine |
| A finished game (one or both queens surrounded) has no moves. | applied by `hive.bench.perft` |
| No turn limit. | `max_turns=None` |

Differences that `Rules` cannot express:

- Draw by threefold repetition: nokamute (following UHP) ends the game in a draw when a
  position repeats three times. This engine has no repetition rule, so the nokamute case
  "Draw by threefold repetition" is not included. The stored counts are not affected:
  movement starts at ply 4 at the earliest, and a position needs at least 8 more plies to
  occur a third time, which is deeper than any stored depth.
- `Rules.legal_moves` keeps returning moves after the game has ended; the perft functions
  stop at a finished game instead, matching the references.
