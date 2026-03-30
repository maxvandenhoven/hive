import pytest

from hive_engine.state import GameState, Move, PieceType, Player


def _apply_placements(
    state: GameState,
    placements: list[tuple[PieceType, tuple[int, int]]],
) -> None:
    """Apply a sequence of placement moves to the game state."""
    for piece_type, coord in placements:
        state.apply_placement(
            Move(piece_type=piece_type, source_coord=None, target_coord=coord)
        )


@pytest.fixture(scope="function")
def default_piece_type_count() -> dict[PieceType, int]:
    """Build standard piece counts for each piece type."""
    return {
        PieceType.QUEEN: 1,
        PieceType.BEETLE: 2,
        PieceType.GRASSHOPPER: 3,
        PieceType.SPIDER: 2,
        PieceType.ANT: 3,
    }


@pytest.fixture(scope="function")
def default_state(default_piece_type_count: dict[PieceType, int]) -> GameState:
    """Build a default GameState with an empty board and standard piece counts."""
    return GameState(
        piece_type_count=default_piece_type_count, starting_player=Player.WHITE
    )


@pytest.fixture(scope="function")
def line_3_state(default_state: GameState) -> GameState:
    """Build an east-west line layout.

    Layout:
    ```text
    (-1, 0) --- (0, 0) --- (1, 0)
    ```

    The middle coordinate `(0, 0)` is an articulation point.
    """
    _apply_placements(
        default_state,
        [(PieceType.ANT, (-1, 0)), (PieceType.ANT, (0, 0)), (PieceType.ANT, (1, 0))],
    )
    return default_state


@pytest.fixture(scope="function")
def ring_6_state(default_state: GameState) -> GameState:
    r"""Build a six-piece ring layout.
    
    Layout:
    ```text
        (0, -1) --- (1, -1)
        /                 \
    (-1, 0)             (1, 0)
        \                 /
        (-1, 1) --- (0, 1)
    ```
    
    There are no articulation points.
    """
    _apply_placements(
        default_state,
        [
            (PieceType.ANT, (1, 0)),
            (PieceType.ANT, (1, -1)),
            (PieceType.ANT, (0, -1)),
            (PieceType.BEETLE, (-1, 0)),
            (PieceType.BEETLE, (-1, 1)),
            (PieceType.SPIDER, (0, 1)),
        ],
    )
    return default_state


@pytest.fixture(scope="function")
def t_shape_state(default_state: GameState) -> GameState:
    r"""Build a T-shaped layout.

    Layout:
    ```text
          (0, -1)
          /     \
    (-1, 0) --- (0, 0) --- (1, 0)
    ```

    The middle coordinate `(0, 0)` is an articulation point.
    """
    _apply_placements(
        default_state,
        [
            (PieceType.ANT, (-1, 0)),
            (PieceType.ANT, (0, 0)),
            (PieceType.ANT, (1, 0)),
            (PieceType.BEETLE, (0, -1)),
        ],
    )
    return default_state


@pytest.fixture(scope="function")
def l_shape_state(default_state: GameState) -> GameState:
    r"""Build an L-shaped layout.

    Layout:
    ```text
    (-1, 0) --- (0, 0) --- (1, 0)
                                 \
                                  (1, 1)
    ``` 

    The middle coordinates `(0, 0)` and `(1, 0)` are articulation points.
    """
    _apply_placements(
        default_state,
        [
            (PieceType.ANT, (-1, 0)),
            (PieceType.ANT, (0, 0)),
            (PieceType.ANT, (1, 0)),
            (PieceType.BEETLE, (1, 1)),
        ],
    )
    return default_state


@pytest.fixture(scope="function")
def long_chain_state(default_state: GameState) -> GameState:
    """Build a long chain layout.

    Layout:
    ```text
    (-2,0) --- (-1,0) --- (0,0) --- (1,0) --- (2,0)
    ```

    The middle coordinates `(-1, 0)`, `(0, 0)`, and `(1, 0)` are articulation points.
    """
    _apply_placements(
        default_state,
        [
            (PieceType.ANT, (-2, 0)),
            (PieceType.ANT, (-1, 0)),
            (PieceType.ANT, (0, 0)),
            (PieceType.BEETLE, (1, 0)),
            (PieceType.BEETLE, (2, 0)),
        ],
    )
    return default_state


@pytest.fixture(scope="function")
def east_gate_state(default_state: GameState) -> GameState:
    r"""Build a gate blocking an east slide.
    
    Layout:
    ```text
           (1, -1)  
          /
    (0, 0) 
          \
           (0, 1) 

    The gate prevents sliding from `(0, 0)` to `(1, 0)`.
    """
    _apply_placements(
        default_state,
        [
            (PieceType.ANT, (0, 0)),
            (PieceType.ANT, (1, -1)),
            (PieceType.ANT, (0, 1)),
        ],
    )
    return default_state
