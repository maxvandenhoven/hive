# Engine

The engine is the foundation everything else builds on: agents search it, the API replays
games with it, the vision matcher enumerates legal moves with it, and the synthetic data
generator plays random valid games with it. It lives in `src/hive/engine/` and imports
nothing from the rest of the package.

## Rust core (WP 43, WP 44)

From WP 44 the engine is implemented in Rust (D30, `rust-core.md`), and this file stays
the contract the Rust core keeps: the `Rules` API, the validated entry points, the
invariants, the move order and the JSON forms. What changes for callers:

- `GameState.board`, `hand` and `queen_coord` return new dicts on every access, so
  changing them does not change the state; tests that edited them build their states
  with `Rules.from_board` or `apply_placement` instead.
- `Move` is frozen and hashable.
- Helpers that only served the Python implementation (`piece_lifted`, `can_slide`,
  `slideable_neighbors`, the per-piece `*_targets`, `PIECE_TARGET_COORDS`, ...) are gone,
  see `rust-core.md` §Python API contract.
- Invariant 6 (the grid bound) is new.

The Python engine stays in `tests/oracle/` as a frozen reference for differential tests
(D32). The sections below describe how the engine got here and still hold as its
contract.

## Current state (before M1)

Source: `packages/hive-engine/src/hive_engine/`.

- `grid.py`: axial hex coordinates `(q, r)` as tuples, `HEX_DIRECTIONS`, neighbor and
  direction helpers. Plain functions on primitives. Stays as is.
- `state.py`: `Player`, `PieceType` (base game), `Piece`, `Move` (placement when
  `source_coord is None`), `GameBoard = dict[Coordinate, list[Piece]]` (stacks bottom to
  top, empty stacks never stored), and `GameState` with `board`, `current_player`,
  `current_ply`, `hand`, `queen_coord`, board queries (`is_occupied`, `get_top_piece`,
  `get_articulation_points`, `can_slide`, ...) and in-place `apply_move` / `undo_move`
  (`None` is a pass).
- `rules/`: four ABCs (`MobilityRule`, `MovementRule`, `PlacementRule`, `TerminationRule`)
  with exactly one implementation each (`Base*`). Variation is via constructor params:
  `can_move_before_queen_placed`, `place_queen_on_turn`, `max_turns_per_player`.
- `ruleset.py`: `Ruleset` aggregates the rules plus `piece_type_count` and
  `starting_player`, and exposes `create_initial_state`, `get_legal_moves` (returns
  `[None]` when there are no moves), `get_winning_players` (both queens surrounded or turn
  cap reached means a draw) and `is_finished`.
- `plotting/` and `assets/`: matplotlib and SVG rendering plus insect images.
- Tests cover `grid.py` and `state.py` only (78 tests). Rules, ruleset and agents have no
  tests yet. Perft (WP 05) closes most of that gap.
- `GameState` holds no derived caches today (articulation points are recomputed per call),
  which keeps `from_board` simple.

The core engine stays as is during M1 apart from the `Rules` change and the validated entry
points below. Speed work happens in M6 and repetition handling in M7 (`performance.md`).

## `Rules` (WP 03)

`Ruleset` and `rules/` are replaced by one frozen dataclass in `src/hive/engine/rules.py`
that holds both config and rule behaviour:

```python
@dataclass(frozen=True, slots=True)
class Rules:
    piece_counts: Mapping[PieceType, int] = BASE_PIECE_COUNTS
    starting_player: Player = Player.WHITE
    queen_by_turn: int | None = 4
    allow_queen_first_turn: bool = True
    move_before_queen: bool = False
    max_turns: int | None = None

    def create_initial_state(self) -> GameState: ...
    def legal_moves(self, state: GameState) -> list[Move | None]: ...
    def placement_moves(self, state: GameState) -> list[Move]: ...
    def movement_moves(self, state: GameState) -> list[Move]: ...
    def movable_pieces(self, state: GameState) -> list[tuple[Coordinate, PieceType]]: ...
    def target_coords(self, state: GameState, coord: Coordinate) -> list[Coordinate]: ...
    def placeable_coords(self, state: GameState) -> list[Coordinate]: ...
    def placeable_piece_types(self, state: GameState) -> list[PieceType]: ...
    def winners(self, state: GameState) -> list[Player] | None: ...
    def is_finished(self, state: GameState) -> bool: ...
    def illegal_move_reason(self, state: GameState, move: Move | None) -> str: ...
    def immobility_reason(self, state: GameState, coord: Coordinate) -> str | None: ...
```

Notes:

- `piece_counts` must be immutable for the dataclass to be hashable. `__post_init__`
  stores any given mapping as a `types.MappingProxyType` ordered by piece type, and
  validates it (exactly one queen, every positive count has movement behaviour). A
  `MappingProxyType` is not hashable itself, so `Rules` defines `__hash__` explicitly,
  hashing `piece_counts` as a tuple of its items; the generated `__eq__` is kept. The
  default is a `default_factory`, because dataclasses reject unhashable defaults.
  A `MappingProxyType` cannot be pickled either, so `Rules.__reduce__` pickles the
  fields with `piece_counts` as a dict, which match workers need (WP 08).
- `__post_init__` also rejects `queen_by_turn=1` with `allow_queen_first_turn=False`,
  which would leave the first player without a legal placement.
- `target_coords` raises `ValueError` for an unoccupied coordinate and returns `[]` for a
  piece that is not in `movable_pieces`, so the frontend can call it for any tile.
  `movement_moves` dispatches to the per-piece methods directly, so it does not recompute
  articulation points per piece.
- Per-piece movement becomes methods (`queen_targets`, `beetle_targets`,
  `grasshopper_targets`, `spider_targets`, `ant_targets`) dispatched by piece type through
  `PIECE_TARGET_COORDS`, sharing the `slideable_neighbors` helper. Port the existing logic unchanged; correctness is proven
  by perft, not by rewriting.
- `allow_queen_first_turn` is new. Some reference engines forbid placing the queen on a
  player's first turn (tournament rule), and perft parity may depend on it.
- `max_turns` replaces `max_turns_per_player` with the same semantics.
- `movable_pieces` and `target_coords` power the frontend utilities "which tiles can move"
  and "legal targets for this tile". For placements, the frontend uses `placeable_coords`.
- Agents receive `rules: Rules` instead of a `Ruleset`.
- `illegal_move_reason` and `immobility_reason` (WP 11) explain why a move is not legal
  or a piece cannot move, for messages to the player (for example "moving the piece would
  split the hive"). They only run on error paths; `apply_checked_move` puts the reason in
  its `IllegalMoveError` message, and `Move.__str__` describes the move (`place ant at
  (1, 0)`).

## Validated entry points (WP 04)

Correctness strategy: validate at the boundary, trust inside. A `GameState` should only
come from these entry points:

| Entry point | Validates | Used by |
|---|---|---|
| `Rules.create_initial_state()` | – | everything |
| `Rules.from_board(board, current_player, current_ply=None)` | piece counts per type and owner do not exceed `piece_counts` (which also limits each player to one queen), the hive is connected, no empty stacks, and the ply is consistent (see below); copies the board and derives `hand`, `queen_coord`, and `current_ply` | board editor, synthetic data, tests |
| `Rules.apply_checked_move(state, move)` | the move is in `legal_moves(state)`; raises `IllegalMoveError` otherwise | API, match runner, photo matcher |

Ply consistency in `from_board` (decided in WP 04): `current_player` must be
`starting_player` exactly on even plies (invariant 5), and no player may have more pieces on
the board than turns taken (`(ply + 1) // 2` for the starting player, `ply // 2` for the
other). Without this, `placeable_coords` and `placeable_piece_types`, which read
`current_ply`, misbehave. The default `current_ply` is the lowest ply that satisfies both,
which is the number of pieces on the board for a game with placements only. Defaulting to
the piece count alone, as first planned, gives an invalid state when the player to move does
not match its parity (for example white to move with three pieces on the board).

Search code calls `state.apply_move` / `state.undo_move` directly with moves taken from
`legal_moves`, so it stays valid without re-checking.

Errors live in `src/hive/engine/errors.py`: `HiveError` base, `IllegalMoveError`,
`InvalidBoardError`. Error messages follow the existing `msg = ...; raise X(msg)` pattern
(`EM` rules).

Property tests guard the fast path (use `hypothesis` or seeded random games):

- Random games: after every `apply_move`, `undo_move` restores an identical state.
- Random games: replaying the move list from the initial state gives the same state.
- Random games: `from_board(state.board, ...)` reproduces `hand` and `queen_coord`.
- Every move from `legal_moves` keeps the hive connected and piece counts consistent.

These live in `tests/engine/test_properties.py`, with `assert_invariants(state, rules)`
checking invariants 1 to 5. Games are drawn with `hypothesis` (moves sampled from
`legal_moves`, so failures shrink to short games) over a few rule variants. The fast profile
(100 games of up to 100 plies) runs in `make test`; the slow profile (500 games of up to 300
plies) is marked `slow`.

## Serialization (WP 06, reworked before WP 10)

Every value that is written to a file, the database or the API is a dataclass that
pydantic converts, so each value has exactly one definition (D25). `src/hive/engine/codec.py`
holds the shared pieces: the `JsonCodec` mixin (`to_json()` / `from_json(data)`), a cached
`json_adapter(type)` for type expressions such as `Move | None`, and `NamedIntEnum`, whose
members are written as lower case names. A class declares its JSON form with annotations:
`Field(alias="from")`, and `StrictInt` / `StrictBool` where JSON must hold a real integer
or boolean. `JsonCodec` carries the shared config: unknown keys are errors and fields are
written under their aliases; classes whose JSON holds keys they do not read (computed
fields, the `source` of the perft suite) override it with `extra="ignore"`. The same annotations produce the JSON
schema the API publishes, so the frontend client gets typed engine values.

The first version had a hand-written `serialize_<value>` / `deserialize_<value>` pair per
value. It was replaced because the API needed a second, pydantic definition of every
value, and the two had to be kept in sync by hand. The values stay plain dataclasses
rather than pydantic models: pydantic only runs when a value is converted, so `Move`
construction (about 0.2 µs, millions per perft run) and memory are unchanged, `Rules`
stays hashable, and the engine can change its internal representation in the speed
rounds as long as the JSON mapping keeps working.

| Value | JSON |
|---|---|
| `Player`, `PieceType` | lower case name, for example `"white"`, `"ant"` |
| `Coordinate` | `[q, r]` |
| `Piece` | `{"piece": "ant", "owner": "white"}` |
| `Move \| None` | `{"piece": "ant", "from": [q, r] \| null, "to": [q, r]}`; pass is `null` |
| `Rules` | object with every field, `piece_counts` keyed by piece type name; missing fields take their default when reading |
| `GameBoard` | list of `BoardCell`s `{"coord": [q, r], "stack": [piece, ...]}`, ordered by coordinate (object keys cannot be coordinates) |
| `BoardSetup \| None` | `null` for the initial state, or `{"board": ..., "current_player": ..., "current_ply": int \| null}` |
| `GameRecord` | `{"rules": ..., "setup": ..., "moves": [...]}` |

- `BoardSetup(board, current_player, current_ply=None)` is a board editor position. The
  plan first said a setup is just a board, but `Rules.from_board` also needs the player to
  move (and optionally the ply), so the setup carries both.
- `GameRecord(rules, setup, moves)` has `replay()`, returning the final `GameState`, and
  `states()`, yielding an independent copy of the state per ply for replay views. Both
  start from `Rules.from_board` for editor setups and use `Rules.apply_checked_move` for
  every move, so invalid records raise `InvalidBoardError` or `IllegalMoveError`.
  `GameState.copy()` was added for `states()`.
- `GameRecord` and `BoardSetup` live in `src/hive/engine/record.py`.
- Reading checks only the shape and raises `pydantic.ValidationError` (a `ValueError`)
  with the location of every problem, for example `moves.1.from`. Legality is checked by
  `replay()`. Writing is total.
- Round-trip property tests (through JSON text) and golden format tests cover every value.

## Invariants

These hold for every `GameState` reachable through the entry points:

1. Every board key maps to a non-empty stack; stacks are ordered bottom to top.
2. The occupied coordinates form one connected component (the one-hive rule), except
   transiently inside `piece_lifted`.
3. For each player and piece type: pieces on board + pieces in hand = `piece_counts`.
4. `queen_coord[p]` is the coordinate of `p`'s queen if placed, else `None`.
5. `current_player` alternates every ply, including passes.
6. From WP 43: at most 28 pieces in total (`Rules` validates `piece_counts`), so every
   cell within two steps of a connected hive has its own index in the 32 × 32 grid of the
   Rust core (`rust-core.md` §Engine representation and optimisations).

Move order: `placement_moves` and `movement_moves` return sorted lists (by piece type, then
source and target coordinate), and `legal_moves` returns placements before movements. The
order therefore depends only on the position. The board dict's iteration order does not:
`piece_lifted` and `undo_move` delete and re-add coordinates, which moves them to the end
(#47). Seeded agents that pick moves by index rely on the sorted order. The Rust core
generates moves in its own order and sorts them at the Python boundary, so the order
of `legal_moves` stays the same.
