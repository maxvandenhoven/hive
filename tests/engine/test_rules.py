import dataclasses

import pytest

from hive.engine.errors import IllegalMoveError, InvalidBoardError
from hive.engine.grid import Coordinate, get_neighbors
from hive.engine.rules import BASE_PIECE_COUNTS, Rules
from hive.engine.state import GameBoard, GameState, Move, Piece, PieceType, Player

type Placement = tuple[Player, PieceType, Coordinate]


def _build_state(
    rules: Rules, placements: list[Placement], current_player: Player, current_ply: int
) -> GameState:
    """Build a state by placing pieces in order, ignoring placement rules.

    Later placements on the same coordinate stack on top of earlier ones.
    """
    state = rules.create_initial_state()
    for owner, piece_type, coord in placements:
        state.current_player = owner
        state.apply_placement(
            Move(piece_type=piece_type, source_coord=None, target_coord=coord)
        )
    state.current_player = current_player
    state.current_ply = current_ply
    return state


def _targets(rules: Rules, state: GameState, coord: Coordinate) -> set[Coordinate]:
    """Get the target coordinates of the piece at `coord` as a set."""
    return set(rules.target_coords(state, coord))


@pytest.fixture(scope="function")
def rules() -> Rules:
    """Build the default rules."""
    return Rules()


@pytest.fixture(scope="function")
def free_rules() -> Rules:
    """Build rules that allow moving before the queen is placed."""
    return Rules(move_before_queen=True)


@pytest.fixture(scope="function")
def gate_ring_placements() -> list[Placement]:
    r"""Build a ring of five black ants around the hole `(1, 0)`, with `(0, 0)` empty.

    Layout:
    ```text
        (1, -1) --- (2, -1)
        /                 \
    (0, 0)     (1, 0)     (2, 0)
        \                 /
        (0, 1) --- (1, 1)
    ```

    A piece added at `(0, 0)` closes the ring. The hole `(1, 0)` is then surrounded, and
    sliding into it from `(0, 0)` is blocked by the gate `(1, -1)` and `(0, 1)`.
    """
    return [
        (Player.BLACK, PieceType.ANT, (1, -1)),
        (Player.BLACK, PieceType.ANT, (2, -1)),
        (Player.BLACK, PieceType.ANT, (2, 0)),
        (Player.BLACK, PieceType.ANT, (1, 1)),
        (Player.BLACK, PieceType.ANT, (0, 1)),
    ]


class TestConfiguration:
    """Test construction, validation, equality and hashing of `Rules`."""

    def test_defaults(self, rules: Rules) -> None:
        """Test that the defaults match the base game."""
        assert dict(rules.piece_counts) == dict(BASE_PIECE_COUNTS)
        assert rules.starting_player is Player.WHITE
        assert rules.queen_by_turn == 4
        assert rules.allow_queen_first_turn is True
        assert rules.move_before_queen is False
        assert rules.max_turns is None

    def test_equal_and_hashable(self) -> None:
        """Test that rules with equal fields are equal and hash equally."""
        reversed_counts = dict(reversed(list(BASE_PIECE_COUNTS.items())))

        assert Rules() == Rules(piece_counts=reversed_counts)
        assert hash(Rules()) == hash(Rules(piece_counts=reversed_counts))
        assert len({Rules(), Rules(), Rules(piece_counts=reversed_counts)}) == 1

    @pytest.mark.parametrize(
        "changes",
        [
            {"piece_counts": {PieceType.QUEEN: 1}},
            {"starting_player": Player.BLACK},
            {"queen_by_turn": None},
            {"allow_queen_first_turn": False},
            {"move_before_queen": True},
            {"max_turns": 10},
        ],
    )
    def test_unequal_for_different_fields(self, changes: dict[str, object]) -> None:
        """Test that changing any field gives unequal rules."""
        assert Rules(**changes) != Rules()  # ty: ignore[invalid-argument-type]

    def test_frozen(self, rules: Rules) -> None:
        """Test that fields cannot be reassigned."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            rules.max_turns = 10  # ty: ignore[invalid-assignment]

    def test_piece_counts_immutable(self) -> None:
        """Test that `piece_counts` is copied and cannot be modified."""
        counts = {PieceType.QUEEN: 1, PieceType.ANT: 3}
        rules = Rules(piece_counts=counts)
        counts[PieceType.ANT] = 5

        assert rules.piece_counts[PieceType.ANT] == 3
        with pytest.raises(TypeError):
            rules.piece_counts[PieceType.ANT] = 5  # ty: ignore[invalid-assignment]

    @pytest.mark.parametrize("queen_count", [0, 2])
    def test_invalid_queen_count(self, queen_count: int) -> None:
        """Test that a queen count other than one is rejected."""
        with pytest.raises(ValueError, match="exactly one queen"):
            Rules(piece_counts={PieceType.QUEEN: queen_count, PieceType.ANT: 3})

    def test_missing_queen(self) -> None:
        """Test that piece counts without a queen are rejected."""
        with pytest.raises(ValueError, match="exactly one queen"):
            Rules(piece_counts={PieceType.ANT: 3})

    def test_queen_required_but_forbidden_on_first_turn(self) -> None:
        """Test that a queen deadline of turn one conflicts with forbidding it then."""
        with pytest.raises(ValueError, match="allow_queen_first_turn"):
            Rules(queen_by_turn=1, allow_queen_first_turn=False)

    def test_create_initial_state(self) -> None:
        """Test that the initial state has full hands and the configured first player."""
        rules = Rules(starting_player=Player.BLACK)
        state = rules.create_initial_state()

        assert state.board == {}
        assert state.current_player is Player.BLACK
        assert state.current_ply == 0
        assert state.hand[Player.WHITE] == dict(BASE_PIECE_COUNTS)
        assert state.hand[Player.BLACK] == dict(BASE_PIECE_COUNTS)

    def test_initial_states_are_independent(self, rules: Rules) -> None:
        """Test that hands of separate initial states do not share storage."""
        state = rules.create_initial_state()
        state.hand[Player.WHITE][PieceType.ANT] = 0

        assert rules.create_initial_state().hand[Player.WHITE][PieceType.ANT] == 3
        assert rules.piece_counts[PieceType.ANT] == 3


class TestPlacement:
    """Test placeable coordinates, placeable piece types and placement moves."""

    def test_first_ply_at_origin(self, rules: Rules) -> None:
        """Test that the first piece is placed at the origin."""
        state = rules.create_initial_state()

        assert rules.placeable_coords(state) == [(0, 0)]
        assert set(rules.placeable_piece_types(state)) == set(PieceType)
        assert len(rules.placement_moves(state)) == len(PieceType)

    def test_second_ply_next_to_origin(self, rules: Rules) -> None:
        """Test that the second piece may be placed on any neighbor of the origin."""
        state = _build_state(
            rules, [(Player.WHITE, PieceType.ANT, (0, 0))], Player.BLACK, current_ply=1
        )

        assert set(rules.placeable_coords(state)) == set(get_neighbors((0, 0)))
        assert len(rules.placement_moves(state)) == 6 * len(PieceType)

    def test_not_adjacent_to_opponent(self, rules: Rules) -> None:
        """Test that later placements touch own pieces and no opponent pieces."""
        state = _build_state(
            rules,
            [
                (Player.WHITE, PieceType.ANT, (0, 0)),
                (Player.BLACK, PieceType.ANT, (1, 0)),
            ],
            Player.WHITE,
            current_ply=2,
        )

        assert set(rules.placeable_coords(state)) == {(0, -1), (-1, 0), (-1, 1)}

    def test_covered_piece_does_not_count(self, rules: Rules) -> None:
        """Test that only the top piece of a stack determines colour adjacency."""
        state = _build_state(
            rules,
            [
                (Player.WHITE, PieceType.QUEEN, (0, 0)),
                (Player.BLACK, PieceType.QUEEN, (1, 0)),
                (Player.WHITE, PieceType.ANT, (-1, 0)),
                (Player.BLACK, PieceType.BEETLE, (-1, 0)),
            ],
            Player.WHITE,
            current_ply=4,
        )

        assert rules.placeable_coords(state) == []
        assert rules.placement_moves(state) == []

    def test_excludes_empty_hand_types(self, rules: Rules) -> None:
        """Test that piece types no longer in hand cannot be placed."""
        state = rules.create_initial_state()
        state.hand[Player.WHITE][PieceType.SPIDER] = 0

        assert PieceType.SPIDER not in rules.placeable_piece_types(state)

    @pytest.mark.parametrize(("current_ply", "forced"), [(4, False), (6, True)])
    def test_queen_by_turn(self, rules: Rules, current_ply: int, forced: bool) -> None:
        """Test that only the queen may be placed on turn four if it is still in hand."""
        state = rules.create_initial_state()
        state.current_ply = current_ply

        placeable_piece_types = rules.placeable_piece_types(state)

        assert (placeable_piece_types == [PieceType.QUEEN]) is forced

    def test_queen_by_turn_after_queen_placed(self, rules: Rules) -> None:
        """Test that the queen deadline no longer applies once the queen is placed."""
        state = _build_state(
            rules, [(Player.WHITE, PieceType.QUEEN, (0, 0))], Player.WHITE, current_ply=6
        )

        assert set(rules.placeable_piece_types(state)) == set(PieceType) - {
            PieceType.QUEEN
        }

    def test_queen_by_turn_disabled(self) -> None:
        """Test that no piece type is forced without a queen deadline."""
        rules = Rules(queen_by_turn=None)
        state = rules.create_initial_state()
        state.current_ply = 6

        assert set(rules.placeable_piece_types(state)) == set(PieceType)

    @pytest.mark.parametrize(
        ("current_player", "current_ply", "queen_allowed"),
        [(Player.WHITE, 0, False), (Player.BLACK, 1, False), (Player.WHITE, 2, True)],
    )
    def test_allow_queen_first_turn_false(
        self, current_player: Player, current_ply: int, queen_allowed: bool
    ) -> None:
        """Test that the queen cannot be placed on either player's first turn."""
        rules = Rules(allow_queen_first_turn=False)
        state = rules.create_initial_state()
        state.current_player = current_player
        state.current_ply = current_ply

        placeable_piece_types = rules.placeable_piece_types(state)

        assert (PieceType.QUEEN in placeable_piece_types) is queen_allowed
        assert set(placeable_piece_types) - {PieceType.QUEEN} == set(PieceType) - {
            PieceType.QUEEN
        }


class TestMobility:
    """Test which pieces are allowed to move."""

    def test_queen_not_placed(self, rules: Rules) -> None:
        """Test that no piece may move before its owner's queen is placed."""
        state = _build_state(
            rules,
            [
                (Player.WHITE, PieceType.ANT, (0, 0)),
                (Player.BLACK, PieceType.QUEEN, (1, 0)),
            ],
            Player.WHITE,
            current_ply=2,
        )

        assert rules.movable_pieces(state) == []
        assert rules.movement_moves(state) == []
        assert rules.target_coords(state, (0, 0)) == []

    def test_move_before_queen(self, free_rules: Rules) -> None:
        """Test that pieces may move before the queen when configured."""
        state = _build_state(
            free_rules,
            [
                (Player.WHITE, PieceType.ANT, (0, 0)),
                (Player.BLACK, PieceType.QUEEN, (1, 0)),
            ],
            Player.WHITE,
            current_ply=2,
        )

        assert free_rules.movable_pieces(state) == [((0, 0), PieceType.ANT)]

    def test_pinned_piece(self, rules: Rules) -> None:
        """Test that a piece whose removal splits the hive cannot move."""
        state = _build_state(
            rules,
            [
                (Player.WHITE, PieceType.ANT, (-1, 0)),
                (Player.WHITE, PieceType.QUEEN, (0, 0)),
                (Player.BLACK, PieceType.QUEEN, (1, 0)),
            ],
            Player.WHITE,
            current_ply=4,
        )

        assert rules.movable_pieces(state) == [((-1, 0), PieceType.ANT)]
        assert rules.target_coords(state, (0, 0)) == []

    def test_covered_piece(self, rules: Rules) -> None:
        """Test that a covered piece cannot move and the beetle on top can."""
        placements = [
            (Player.WHITE, PieceType.QUEEN, (0, 0)),
            (Player.BLACK, PieceType.QUEEN, (-1, 0)),
            (Player.WHITE, PieceType.ANT, (1, 0)),
            (Player.BLACK, PieceType.BEETLE, (1, 0)),
        ]
        white_state = _build_state(rules, placements, Player.WHITE, current_ply=4)
        black_state = _build_state(rules, placements, Player.BLACK, current_ply=5)

        assert rules.movable_pieces(white_state) == []
        assert set(rules.movable_pieces(black_state)) == {
            ((-1, 0), PieceType.QUEEN),
            ((1, 0), PieceType.BEETLE),
        }

    def test_opponent_pieces_not_movable(self, free_rules: Rules) -> None:
        """Test that only the current player's pieces are movable."""
        state = _build_state(
            free_rules,
            [
                (Player.WHITE, PieceType.ANT, (0, 0)),
                (Player.BLACK, PieceType.ANT, (1, 0)),
            ],
            Player.BLACK,
            current_ply=3,
        )

        assert free_rules.movable_pieces(state) == [((1, 0), PieceType.ANT)]

    def test_target_coords_unoccupied(self, rules: Rules) -> None:
        """Test that target coordinates of an empty coordinate are rejected."""
        state = rules.create_initial_state()

        with pytest.raises(ValueError, match="unoccupied"):
            rules.target_coords(state, (0, 0))


class TestMovement:
    """Test the movement of each piece type."""

    def test_queen_slides_one_space(self, free_rules: Rules) -> None:
        """Test that the queen slides one space along the hive."""
        state = _build_state(
            free_rules,
            [
                (Player.WHITE, PieceType.QUEEN, (0, 0)),
                (Player.BLACK, PieceType.ANT, (1, 0)),
            ],
            Player.WHITE,
            current_ply=2,
        )

        assert _targets(free_rules, state, (0, 0)) == {(1, -1), (0, 1)}

    def test_queen_gate(
        self, free_rules: Rules, gate_ring_placements: list[Placement]
    ) -> None:
        """Test that the queen cannot slide through a gate or lose hive contact."""
        state = _build_state(
            free_rules,
            [*gate_ring_placements, (Player.WHITE, PieceType.QUEEN, (0, 0))],
            Player.WHITE,
            current_ply=6,
        )

        assert _targets(free_rules, state, (0, 0)) == {(0, -1), (-1, 1)}

    def test_beetle_slides_and_climbs(self, free_rules: Rules) -> None:
        """Test that the beetle slides one space or climbs onto a neighbor."""
        state = _build_state(
            free_rules,
            [
                (Player.WHITE, PieceType.BEETLE, (0, 0)),
                (Player.BLACK, PieceType.ANT, (1, 0)),
            ],
            Player.WHITE,
            current_ply=2,
        )

        assert _targets(free_rules, state, (0, 0)) == {(1, -1), (0, 1), (1, 0)}

    def test_beetle_gate(
        self, free_rules: Rules, gate_ring_placements: list[Placement]
    ) -> None:
        """Test that the beetle cannot slide through a gate but can climb its sides."""
        state = _build_state(
            free_rules,
            [*gate_ring_placements, (Player.WHITE, PieceType.BEETLE, (0, 0))],
            Player.WHITE,
            current_ply=6,
        )

        assert _targets(free_rules, state, (0, 0)) == {(0, -1), (-1, 1), (1, -1), (0, 1)}

    def test_beetle_on_top_of_hive(self, free_rules: Rules) -> None:
        """Test that a beetle on a stack may move to any neighbor."""
        state = _build_state(
            free_rules,
            [
                (Player.WHITE, PieceType.ANT, (0, 0)),
                (Player.BLACK, PieceType.ANT, (1, 0)),
                (Player.WHITE, PieceType.BEETLE, (0, 0)),
            ],
            Player.WHITE,
            current_ply=4,
        )

        assert _targets(free_rules, state, (0, 0)) == set(get_neighbors((0, 0)))

    def test_beetle_climbing_moves(self, free_rules: Rules) -> None:
        """Test that climbing moves are generated as movement moves."""
        state = _build_state(
            free_rules,
            [
                (Player.WHITE, PieceType.BEETLE, (0, 0)),
                (Player.BLACK, PieceType.ANT, (1, 0)),
            ],
            Player.WHITE,
            current_ply=2,
        )

        assert Move(
            piece_type=PieceType.BEETLE, source_coord=(0, 0), target_coord=(1, 0)
        ) in free_rules.movement_moves(state)

    def test_grasshopper_jumps(self, free_rules: Rules) -> None:
        """Test that the grasshopper jumps over lines of pieces to the first gap."""
        state = _build_state(
            free_rules,
            [
                (Player.WHITE, PieceType.GRASSHOPPER, (0, 0)),
                (Player.BLACK, PieceType.ANT, (1, 0)),
                (Player.BLACK, PieceType.ANT, (2, 0)),
                (Player.BLACK, PieceType.ANT, (0, 1)),
            ],
            Player.WHITE,
            current_ply=4,
        )

        assert _targets(free_rules, state, (0, 0)) == {(3, 0), (0, 2)}

    def test_grasshopper_ignores_gates(
        self, free_rules: Rules, gate_ring_placements: list[Placement]
    ) -> None:
        """Test that the grasshopper jumps over a gate it could not slide through."""
        state = _build_state(
            free_rules,
            [*gate_ring_placements, (Player.WHITE, PieceType.GRASSHOPPER, (0, 0))],
            Player.WHITE,
            current_ply=6,
        )

        assert _targets(free_rules, state, (0, 0)) == {(2, -2), (0, 2)}

    def test_spider_around_one_piece(self, free_rules: Rules) -> None:
        """Test that the spider moves exactly three spaces around a single piece."""
        state = _build_state(
            free_rules,
            [
                (Player.WHITE, PieceType.SPIDER, (0, 0)),
                (Player.BLACK, PieceType.ANT, (1, 0)),
            ],
            Player.WHITE,
            current_ply=2,
        )

        assert _targets(free_rules, state, (0, 0)) == {(2, 0)}

    def test_spider_around_two_pieces(self, free_rules: Rules) -> None:
        """Test that the spider stops after three spaces in both directions."""
        state = _build_state(
            free_rules,
            [
                (Player.WHITE, PieceType.SPIDER, (0, 0)),
                (Player.BLACK, PieceType.ANT, (1, 0)),
                (Player.BLACK, PieceType.ANT, (2, 0)),
            ],
            Player.WHITE,
            current_ply=3,
        )

        assert _targets(free_rules, state, (0, 0)) == {(3, -1), (2, 1)}

    def test_ant_around_one_piece(self, free_rules: Rules) -> None:
        """Test that the ant reaches every space around a single piece."""
        state = _build_state(
            free_rules,
            [
                (Player.WHITE, PieceType.ANT, (0, 0)),
                (Player.BLACK, PieceType.ANT, (1, 0)),
            ],
            Player.WHITE,
            current_ply=2,
        )

        assert _targets(free_rules, state, (0, 0)) == set(get_neighbors((1, 0))) - {
            (0, 0)
        }

    def test_ant_gate(
        self, free_rules: Rules, gate_ring_placements: list[Placement]
    ) -> None:
        """Test that the ant reaches all of the outside but not the gated hole."""
        state = _build_state(
            free_rules,
            [*gate_ring_placements, (Player.WHITE, PieceType.ANT, (0, 0))],
            Player.WHITE,
            current_ply=6,
        )
        outside = {
            neighbor
            for _, _, coord in gate_ring_placements
            for neighbor in get_neighbors(coord)
            if not state.is_occupied(neighbor)
        } - {(1, 0)}

        assert _targets(free_rules, state, (0, 0)) == outside


class TestTermination:
    """Test winners and game termination."""

    @pytest.fixture(scope="function")
    def surround_placements(self) -> list[Placement]:
        """Build a white queen at `(0, 0)` surrounded on all sides but `(0, 1)`."""
        return [
            (Player.WHITE, PieceType.QUEEN, (0, 0)),
            (Player.BLACK, PieceType.QUEEN, (1, 0)),
            (Player.BLACK, PieceType.ANT, (1, -1)),
            (Player.BLACK, PieceType.ANT, (0, -1)),
            (Player.BLACK, PieceType.ANT, (-1, 0)),
            (Player.BLACK, PieceType.ANT, (-1, 1)),
        ]

    def test_in_progress(
        self, rules: Rules, surround_placements: list[Placement]
    ) -> None:
        """Test that the game continues while no queen is surrounded."""
        state = _build_state(rules, surround_placements, Player.WHITE, current_ply=6)

        assert rules.winners(state) is None
        assert rules.is_finished(state) is False

    def test_empty_board(self, rules: Rules) -> None:
        """Test that the game continues before any queen is placed."""
        assert rules.winners(rules.create_initial_state()) is None

    def test_queen_surrounded(
        self, rules: Rules, surround_placements: list[Placement]
    ) -> None:
        """Test that surrounding a queen wins the game for the opponent."""
        state = _build_state(
            rules,
            [*surround_placements, (Player.WHITE, PieceType.ANT, (0, 1))],
            Player.BLACK,
            current_ply=7,
        )

        assert rules.winners(state) == [Player.BLACK]
        assert rules.is_finished(state) is True

    def test_both_queens_surrounded(self, rules: Rules) -> None:
        """Test that surrounding both queens at once is a draw."""
        placements: list[Placement] = [
            (Player.WHITE, PieceType.QUEEN, (0, 0)),
            (Player.BLACK, PieceType.QUEEN, (1, 0)),
        ]
        others = set(get_neighbors((0, 0))) | set(get_neighbors((1, 0)))
        placements += [
            (Player.WHITE, PieceType.ANT, coord) for coord in others - {(0, 0), (1, 0)}
        ]
        state = _build_state(rules, placements, Player.WHITE, current_ply=10)

        assert set(rules.winners(state) or []) == {Player.WHITE, Player.BLACK}

    @pytest.mark.parametrize(("current_ply", "finished"), [(20, False), (21, True)])
    def test_max_turns(self, current_ply: int, finished: bool) -> None:
        """Test that exceeding the turn limit is a draw."""
        rules = Rules(max_turns=10)
        state = rules.create_initial_state()
        state.current_ply = current_ply

        assert rules.is_finished(state) is finished
        if finished:
            assert rules.winners(state) == [Player.WHITE, Player.BLACK]


class TestLegalMoves:
    """Test the combined legal moves."""

    def test_combines_placements_and_movements(self, rules: Rules) -> None:
        """Test that legal moves are placement moves followed by movement moves."""
        state = _build_state(
            rules,
            [
                (Player.WHITE, PieceType.QUEEN, (0, 0)),
                (Player.BLACK, PieceType.QUEEN, (1, 0)),
            ],
            Player.WHITE,
            current_ply=2,
        )

        placement_moves = rules.placement_moves(state)
        movement_moves = rules.movement_moves(state)

        assert placement_moves
        assert movement_moves
        assert rules.legal_moves(state) == [*placement_moves, *movement_moves]

    def test_pass_when_no_moves(self, rules: Rules) -> None:
        """Test that the only legal move is a pass when nothing can be placed or moved."""
        state = _build_state(
            rules,
            [
                (Player.WHITE, PieceType.QUEEN, (0, 0)),
                (Player.BLACK, PieceType.QUEEN, (1, 0)),
                (Player.WHITE, PieceType.ANT, (-1, 0)),
                (Player.BLACK, PieceType.BEETLE, (-1, 0)),
            ],
            Player.WHITE,
            current_ply=4,
        )

        assert rules.legal_moves(state) == [None]


def _build_board(placements: list[Placement]) -> GameBoard:
    """Build a board by placing pieces in order, stacking on repeated coordinates."""
    board: GameBoard = {}
    for owner, piece_type, coord in placements:
        board.setdefault(coord, []).append(Piece(type=piece_type, owner=owner))
    return board


class TestFromBoard:
    """Test creating a validated state from a board."""

    @pytest.fixture(scope="function")
    def placements(self) -> list[Placement]:
        """Build a four-piece opening with a white beetle on top of the black queen."""
        return [
            (Player.WHITE, PieceType.QUEEN, (0, 0)),
            (Player.BLACK, PieceType.QUEEN, (1, 0)),
            (Player.WHITE, PieceType.BEETLE, (1, 0)),
            (Player.BLACK, PieceType.ANT, (2, 0)),
        ]

    def test_derives_hand_and_queen_coord(
        self, rules: Rules, placements: list[Placement]
    ) -> None:
        """Test that hands and queen coordinates are derived from the board."""
        state = rules.from_board(_build_board(placements), Player.WHITE)

        assert state.current_player is Player.WHITE
        assert state.current_ply == 4
        assert state.queen_coord == {Player.WHITE: (0, 0), Player.BLACK: (1, 0)}
        assert state.hand[Player.WHITE] == {
            **BASE_PIECE_COUNTS,
            PieceType.QUEEN: 0,
            PieceType.BEETLE: 1,
        }
        assert state.hand[Player.BLACK] == {
            **BASE_PIECE_COUNTS,
            PieceType.QUEEN: 0,
            PieceType.ANT: 2,
        }
        assert state.board == _build_board(placements)

    def test_empty_board(self, rules: Rules) -> None:
        """Test that an empty board gives the initial state."""
        state = rules.from_board({}, Player.WHITE)
        initial_state = rules.create_initial_state()

        assert state.board == {}
        assert state.current_ply == 0
        assert state.hand == initial_state.hand
        assert state.queen_coord == initial_state.queen_coord

    @pytest.mark.parametrize(
        ("current_player", "expected_ply"), [(Player.WHITE, 4), (Player.BLACK, 5)]
    )
    def test_derives_lowest_valid_ply(
        self,
        rules: Rules,
        placements: list[Placement],
        current_player: Player,
        expected_ply: int,
    ) -> None:
        """Test that the derived ply is the lowest one consistent with the board."""
        state = rules.from_board(_build_board(placements), current_player)

        assert state.current_ply == expected_ply

    def test_derives_ply_for_uneven_piece_counts(self, rules: Rules) -> None:
        """Test that the derived ply gives the player with most pieces enough turns."""
        board = _build_board(
            [
                (Player.WHITE, PieceType.QUEEN, (0, 0)),
                (Player.WHITE, PieceType.ANT, (-1, 0)),
                (Player.WHITE, PieceType.ANT, (-2, 0)),
                (Player.BLACK, PieceType.QUEEN, (1, 0)),
            ]
        )

        assert rules.from_board(board, Player.BLACK).current_ply == 5
        assert rules.from_board(board, Player.WHITE).current_ply == 6

    def test_derives_ply_for_black_starting_player(self) -> None:
        """Test that the derived ply follows a starting player other than white."""
        rules = Rules(starting_player=Player.BLACK)
        board = _build_board([(Player.BLACK, PieceType.QUEEN, (0, 0))])

        assert rules.from_board(board, Player.WHITE).current_ply == 1

    def test_explicit_ply(self, rules: Rules, placements: list[Placement]) -> None:
        """Test that a valid explicit ply is kept."""
        state = rules.from_board(_build_board(placements), Player.WHITE, current_ply=10)

        assert state.current_ply == 10

    def test_does_not_share_input(
        self, rules: Rules, placements: list[Placement]
    ) -> None:
        """Test that moves on the state do not change the stacks of the input board."""
        board = _build_board(placements)
        expected = _build_board(placements)

        state = rules.from_board(board, Player.WHITE)
        state.apply_move(
            Move(piece_type=PieceType.BEETLE, source_coord=(1, 0), target_coord=(1, -1))
        )

        assert board == expected

    def test_playable(self, rules: Rules, placements: list[Placement]) -> None:
        """Test that the state supports `legal_moves` and `apply_checked_move`."""
        state = rules.from_board(_build_board(placements), Player.WHITE)
        move = rules.legal_moves(state)[0]

        rules.apply_checked_move(state, move)

        assert state.current_player is Player.BLACK

    def test_empty_stack(self, rules: Rules) -> None:
        """Test that an empty stack is rejected."""
        board = _build_board([(Player.WHITE, PieceType.QUEEN, (0, 0))])
        board[(1, 0)] = []

        with pytest.raises(InvalidBoardError, match=r"stack at coordinate `\(1, 0\)`"):
            rules.from_board(board, Player.BLACK)

    def test_too_many_pieces(self, rules: Rules) -> None:
        """Test that more pieces of a type than `piece_counts` allows are rejected."""
        board = _build_board([(Player.BLACK, PieceType.SPIDER, (q, 0)) for q in range(3)])

        with pytest.raises(
            InvalidBoardError,
            match="`BLACK` has `3` pieces of type `SPIDER`.*at most `2`",
        ):
            rules.from_board(board, Player.WHITE, current_ply=6)

    def test_two_queens(self, rules: Rules) -> None:
        """Test that a second queen for the same player is rejected."""
        board = _build_board(
            [
                (Player.WHITE, PieceType.QUEEN, (0, 0)),
                (Player.WHITE, PieceType.QUEEN, (1, 0)),
            ]
        )

        with pytest.raises(
            InvalidBoardError, match="`WHITE` has `2` pieces of type `QUEEN`"
        ):
            rules.from_board(board, Player.WHITE, current_ply=4)

    def test_piece_type_not_in_piece_counts(self) -> None:
        """Test that a piece type with no copies in `piece_counts` is rejected."""
        rules = Rules(piece_counts={PieceType.QUEEN: 1, PieceType.ANT: 3})
        board = _build_board([(Player.WHITE, PieceType.BEETLE, (0, 0))])

        with pytest.raises(
            InvalidBoardError, match="`1` pieces of type `BEETLE`.*at most `0`"
        ):
            rules.from_board(board, Player.BLACK)

    def test_disconnected(self, rules: Rules) -> None:
        """Test that a board split into two groups is rejected."""
        board = _build_board(
            [
                (Player.WHITE, PieceType.QUEEN, (0, 0)),
                (Player.BLACK, PieceType.QUEEN, (2, 0)),
            ]
        )

        with pytest.raises(InvalidBoardError, match="connected hive"):
            rules.from_board(board, Player.WHITE)

    def test_negative_ply(self, rules: Rules) -> None:
        """Test that a negative ply is rejected."""
        with pytest.raises(InvalidBoardError, match="must not be negative"):
            rules.from_board({}, Player.WHITE, current_ply=-2)

    @pytest.mark.parametrize(
        ("current_player", "current_ply"), [(Player.WHITE, 5), (Player.BLACK, 4)]
    )
    def test_ply_parity_mismatch(
        self,
        rules: Rules,
        placements: list[Placement],
        current_player: Player,
        current_ply: int,
    ) -> None:
        """Test that a ply at which the other player would be to move is rejected."""
        with pytest.raises(InvalidBoardError, match="cannot be to move at ply"):
            rules.from_board(_build_board(placements), current_player, current_ply)

    def test_more_pieces_than_turns(
        self, rules: Rules, placements: list[Placement]
    ) -> None:
        """Test that a ply too low for the number of pieces on the board is rejected."""
        with pytest.raises(
            InvalidBoardError, match="`WHITE` has `2` pieces.*only taken `1` turns"
        ):
            rules.from_board(_build_board(placements), Player.WHITE, current_ply=2)


class TestApplyCheckedMove:
    """Test applying moves with legality checks."""

    def test_applies_legal_move(self, rules: Rules) -> None:
        """Test that a legal move is applied and advances the turn."""
        state = rules.create_initial_state()
        move = Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 0))

        rules.apply_checked_move(state, move)

        assert state.board == {(0, 0): [Piece(type=PieceType.ANT, owner=Player.WHITE)]}
        assert state.current_player is Player.BLACK
        assert state.current_ply == 1

    def test_applies_pass(self, rules: Rules) -> None:
        """Test that a pass is applied when it is the only legal move."""
        state = rules.from_board(
            _build_board(
                [
                    (Player.WHITE, PieceType.QUEEN, (0, 0)),
                    (Player.BLACK, PieceType.QUEEN, (1, 0)),
                    (Player.WHITE, PieceType.ANT, (-1, 0)),
                    (Player.BLACK, PieceType.BEETLE, (-1, 0)),
                ]
            ),
            Player.WHITE,
        )

        rules.apply_checked_move(state, None)

        assert state.current_player is Player.BLACK

    @pytest.mark.parametrize(
        "move",
        [
            pytest.param(
                Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0)),
                id="placement-off-origin",
            ),
            pytest.param(
                Move(piece_type=PieceType.ANT, source_coord=(0, 0), target_coord=(1, 0)),
                id="movement-on-empty-board",
            ),
            pytest.param(None, id="pass-with-moves"),
        ],
    )
    def test_rejects_illegal_move(self, rules: Rules, move: Move | None) -> None:
        """Test that an illegal move raises and leaves the state unchanged."""
        state = rules.create_initial_state()

        with pytest.raises(IllegalMoveError, match="not legal for player `WHITE`"):
            rules.apply_checked_move(state, move)

        assert state.board == {}
        assert state.current_ply == 0

    def test_rejects_queen_on_first_turn(self) -> None:
        """Test that a placement forbidden by the rules is rejected."""
        rules = Rules(allow_queen_first_turn=False)
        state = rules.create_initial_state()
        move = Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0))

        with pytest.raises(IllegalMoveError):
            rules.apply_checked_move(state, move)

    def test_rejects_move_of_opponent_piece(self, rules: Rules) -> None:
        """Test that moving an opponent's piece is rejected."""
        state = rules.from_board(
            _build_board(
                [
                    (Player.WHITE, PieceType.QUEEN, (0, 0)),
                    (Player.BLACK, PieceType.QUEEN, (1, 0)),
                ]
            ),
            Player.WHITE,
        )
        move = Move(piece_type=PieceType.QUEEN, source_coord=(1, 0), target_coord=(1, -1))

        with pytest.raises(IllegalMoveError):
            rules.apply_checked_move(state, move)
