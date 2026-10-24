# Engine

The engine is the foundation everything else builds on: agents search it, the API replays
games with it, the vision matcher enumerates legal moves with it, and the synthetic data
generator plays random valid games with it. It lives in `src/hive/engine/` and imports
nothing from the rest of the package.

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
points below. Speed work happens in M6 (`performance.md`).

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
```

Notes:

- `piece_counts` must be immutable for the dataclass to be hashable. Use a
  `types.MappingProxyType` or a tuple of pairs internally; validate in `__post_init__`
  (exactly one queen, every positive count has movement behaviour).
- Per-piece movement becomes private methods (`_queen_targets`, `_beetle_targets`,
  `_grasshopper_targets`, `_spider_targets`, `_ant_targets`) dispatched by piece type,
  sharing a private slide helper. Port the existing logic unchanged; correctness is proven
  by perft, not by rewriting.
- `allow_queen_first_turn` is new. Some reference engines forbid placing the queen on a
  player's first turn (tournament rule), and perft parity may depend on it.
- `max_turns` replaces `max_turns_per_player` with the same semantics.
- `movable_pieces` and `target_coords` power the frontend utilities "which tiles can move"
  and "legal targets for this tile". For placements, the frontend uses `placeable_coords`.
- Agents receive `rules: Rules` instead of a `Ruleset`.

## Validated entry points (WP 04)

Correctness strategy: validate at the boundary, trust inside. A `GameState` should only
come from these entry points:

| Entry point | Validates | Used by |
|---|---|---|
| `Rules.create_initial_state()` | – | everything |
| `Rules.from_board(board, current_player, current_ply=None)` | piece counts per type and owner do not exceed `piece_counts`, the hive is connected, at most one queen per player, no empty stacks; derives `hand`, `queen_coord`, and `current_ply` (defaults to the number of pieces on the board, matching a game with placements only) | board editor, synthetic data, tests |
| `Rules.play(state, move)` | the move is in `legal_moves(state)`; raises `IllegalMoveError` otherwise | API, match runner, photo matcher |

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

## Codec (WP 06)

`src/hive/engine/codec.py` converts engine values to and from JSON-compatible dicts. It is
used by match records, gauntlet reports, the API and the database:

- `Move` ↔ `{"piece": "ant", "from": [q, r] | null, "to": [q, r]}`; pass ↔ `null`.
- `Rules` ↔ dict of its fields, so rules can be stored per game and per gauntlet.
- `GameRecord` (setup + rules + moves) ↔ dict, with `GameRecord.replay()` returning the
  final `GameState` (using `Rules.play`, so invalid records are rejected) and
  `GameRecord.states()` iterating states per ply for replay views.
- Setup is either `"initial"` or a board produced by the board editor (validated through
  `from_board`).

Decoders validate their input and raise `ValueError` with clear messages. Encoders are
total. Round-trip property tests cover all of it.

## Invariants

These hold for every `GameState` reachable through the entry points:

1. Every board key maps to a non-empty stack; stacks are ordered bottom to top.
2. The occupied coordinates form one connected component (the one-hive rule), except
   transiently inside `piece_lifted`.
3. For each player and piece type: pieces on board + pieces in hand = `piece_counts`.
4. `queen_coord[p]` is the coordinate of `p`'s queen if placed, else `None`.
5. `current_player` alternates every ply, including passes.
