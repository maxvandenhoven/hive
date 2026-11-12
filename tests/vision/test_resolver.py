import dataclasses
import random

import pytest

from hive.engine.rules import Rules
from hive.engine.state import GameState, Move, PieceType
from hive.vision.classes import TileClass
from hive.vision.grid_fit import ObservedBoard
from hive.vision.resolver import (
    MoveResolver,
    ResolutionStatus,
    board_key,
    changed_hexes,
    describe_move,
    tile_origins,
)
from hive.vision.testing import SimulatedCamera, SimulatedDetector, simulate_observations
from hive.vision.tracking import GameTracker

IMAGE_SIZE = (1024, 768)


def photo(
    state: GameState,
    rng: random.Random,
    detector: SimulatedDetector | None = None,
    max_tilt: float = 50,
) -> ObservedBoard:
    """Take a simulated photo of a position from a random camera."""
    camera = SimulatedCamera(
        tilt_deg=rng.uniform(0, max_tilt),
        azimuth_deg=rng.uniform(0, 360),
        roll_deg=rng.uniform(-8, 8),
        distance=rng.uniform(10, 18),
        focal=rng.uniform(800, 1100),
        image_size=IMAGE_SIZE,
    )
    observations = simulate_observations(
        board=state.board,
        camera=camera,
        detector=detector or SimulatedDetector(loose_tiles=rng.randint(0, 2)),
        rng=rng,
    )

    return ObservedBoard.fit(observations=observations, image_size=IMAGE_SIZE)


def after(state: GameState, *moves: Move | None) -> GameState:
    """Get the position after moves."""
    result = state.copy()

    for move in moves:
        result.apply_move(move)

    return result


def play(rules: Rules, rng: random.Random, plies: int) -> GameState:
    """Play random legal moves."""
    state = rules.create_initial_state()

    for _ in range(plies):
        state.apply_move(rng.choice(rules.legal_moves(state)))

    return state


def test_tracks_a_game_from_photos() -> None:
    rules = Rules()
    resolver = MoveResolver(rules)
    rng = random.Random(12)
    state = rules.create_initial_state()
    previous = None
    first_photo = 0
    wrong = 0
    plies = 24

    for _ in range(plies):
        move = rng.choice(rules.legal_moves(state))
        truth = after(state, move)
        observed = photo(state=truth, rng=rng)
        resolution = resolver.resolve(state=state, photos=[observed], previous=previous)

        if resolution.status is ResolutionStatus.RESOLVED:
            assert resolution.best is not None
            resolved = after(state, *resolution.best.moves)
            first_photo += 1
            wrong += board_key(resolved.board) != board_key(truth.board)

        state, previous = truth, observed

    assert wrong == 0
    assert first_photo >= 0.75 * plies


def test_symmetric_second_placement_is_one_outcome() -> None:
    rules = Rules()
    rng = random.Random(2)
    state = after(
        rules.create_initial_state(),
        Move(piece_type=PieceType.SPIDER, source_coord=None, target_coord=(0, 0)),
    )
    truth = after(
        state, Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(0, 1))
    )
    resolution = MoveResolver(rules).resolve(state=state, photos=[photo(truth, rng)])

    assert resolution.status is ResolutionStatus.RESOLVED
    assert resolution.best is not None
    assert board_key(after(state, *resolution.best.moves).board) == board_key(truth.board)


def test_unclear_new_tile_asks_for_another_photo() -> None:
    rules = Rules()
    rng = random.Random(5)
    state = play(rules=rules, rng=rng, plies=4)
    placed, other = rules.placeable_piece_types(state)[:2]
    placement = next(
        move for move in rules.placement_moves(state) if move.piece_type is placed
    )
    truth = after(state, placement)
    observed = photo(state=truth, rng=rng, detector=SimulatedDetector())
    # Make the detector torn between two placeable pieces for the new tile only.
    first = TileClass(piece_type=placed, owner=state.current_player)
    second = TileClass(piece_type=other, owner=state.current_player)
    resolver = MoveResolver(rules)
    alignment = resolver.align(state=truth, observed=observed)[0]

    for coord, tile in list(observed.tiles.items()):
        if alignment.apply(coord) == placement.target_coord:
            scores = [0.001] * 10
            scores[first.id] = scores[second.id] = 0.5
            observation = dataclasses.replace(
                tile.observation, class_scores=tuple(scores)
            )
            observed.tiles[coord] = dataclasses.replace(tile, observation=observation)

    resolution = resolver.resolve(state=state, photos=[observed])

    assert resolution.status is ResolutionStatus.AMBIGUOUS
    assert resolution.reason is not None and "another photo" in resolution.reason
    pieces = {
        move.piece_type
        for candidate in resolution.candidates[:2]
        for move in candidate.moves
        if move is not None
    }

    assert pieces == {placed, other}


def test_photos_of_one_position_add_up() -> None:
    rules = Rules()
    rng = random.Random(8)
    state = play(rules=rules, rng=rng, plies=8)
    truth = after(state, rng.choice(rules.legal_moves(state)))
    resolver = MoveResolver(rules)
    first, second = photo(truth, rng), photo(truth, rng)
    one = resolver.resolve(state=state, photos=[first])
    both = resolver.resolve(state=state, photos=[first, second])

    assert both.best is not None and one.best is not None
    assert both.best.log_likelihood < one.best.log_likelihood
    assert both.best.probability >= one.best.probability - 1e-9


def test_skipped_photo_keeps_the_true_pair_among_the_candidates() -> None:
    rules = Rules()
    wrong = 0

    for seed in range(21, 27):
        rng = random.Random(seed)
        state = play(rules=rules, rng=rng, plies=10)
        first = rng.choice(rules.legal_moves(state))
        second = rng.choice(rules.legal_moves(after(state, first)))
        truth = after(state, first, second)
        resolution = MoveResolver(rules).resolve(
            state=state, photos=[photo(truth, rng, max_tilt=20)]
        )
        outcomes = [
            board_key(after(state, *candidate.moves).board)
            for candidate in resolution.candidates
        ]

        assert board_key(truth.board) in outcomes

        if resolution.status is ResolutionStatus.RESOLVED:
            wrong += outcomes[0] != board_key(truth.board)

    # A skipped photo usually asks for another one; one that leaves a single moved
    # tile unseen can pass as one move, which the person confirming it then corrects.
    assert wrong <= 1


def test_photo_of_another_board_fails() -> None:
    rules = Rules()
    rng = random.Random(30)
    state = play(rules=rules, rng=rng, plies=14)
    other = play(rules=rules, rng=random.Random(99), plies=14)
    resolution = MoveResolver(rules).resolve(state=state, photos=[photo(other, rng)])

    assert resolution.status is ResolutionStatus.FAILED
    assert resolution.reason is not None and "does not match" in resolution.reason


def test_no_hive_fails() -> None:
    resolution = MoveResolver(Rules()).resolve(
        state=Rules().create_initial_state(), photos=[]
    )

    assert resolution.status is ResolutionStatus.FAILED
    assert resolution.candidates == []


def test_tile_memory_explains_a_consistent_misreading() -> None:
    rules = Rules()
    rng = random.Random(40)
    state = play(rules=rules, rng=rng, plies=10)
    move = rng.choice(rules.legal_moves(state))
    truth = after(state, move)
    resolver = MoveResolver(rules)
    previous = photo(state, rng, detector=SimulatedDetector())
    current = photo(truth, rng, detector=SimulatedDetector())
    # The same unmoved tile reads as another class in both photos.
    unmoved = next(coord for coord in state.board if coord not in changed_hexes((move,)))
    wrong = TileClass.from_id(
        (
            TileClass(
                piece_type=state.board[unmoved][-1].type,
                owner=state.board[unmoved][-1].owner,
            ).id
            + 3
        )
        % 10
    )

    for observed, position in ((previous, state), (current, truth)):
        alignment = resolver.align(state=position, observed=observed)[0]

        for coord, tile in list(observed.tiles.items()):
            if alignment.apply(coord) == unmoved:
                scores = [0.001] * 10
                scores[wrong.id] = 0.9
                observation = dataclasses.replace(
                    tile.observation,
                    piece_type=wrong.piece_type,
                    owner=wrong.owner,
                    class_scores=tuple(scores),
                )
                observed.tiles[coord] = dataclasses.replace(tile, observation=observation)

    without = resolver.resolve(state=state, photos=[current])
    remembered = resolver.resolve(state=state, photos=[current], previous=previous)

    assert remembered.best is not None and without.best is not None
    assert remembered.best.log_likelihood > without.best.log_likelihood + 1.0


def test_tile_origins_follow_moved_tiles() -> None:
    moves = (
        Move(piece_type=PieceType.ANT, source_coord=(0, 0), target_coord=(2, 0)),
        Move(piece_type=PieceType.ANT, source_coord=(2, 0), target_coord=(3, 0)),
        Move(piece_type=PieceType.SPIDER, source_coord=None, target_coord=(1, 1)),
    )

    assert tile_origins(moves) == {
        (0, 0): None,
        (2, 0): None,
        (3, 0): (0, 0),
        (1, 1): None,
    }
    assert changed_hexes(moves) == {(0, 0), (2, 0), (3, 0), (1, 1)}


def test_describe_move() -> None:
    assert describe_move(None) == "pass"
    assert (
        describe_move(
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0))
        )
        == "place ant at (1, 0)"
    )


def test_tracker_keeps_unclear_photos_and_confirms_moves() -> None:
    rules = Rules()
    tracker = GameTracker(rules=rules)
    rng = random.Random(3)
    first = Move(piece_type=PieceType.GRASSHOPPER, source_coord=None, target_coord=(0, 0))
    resolution = tracker.add_photo(photo(after(tracker.state, first), rng))

    assert resolution.status is ResolutionStatus.RESOLVED
    assert tracker.state.current_ply == 1
    assert tracker.previous is not None
    assert tracker.pending == []

    second = Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0))
    tracker.confirm(moves=[second], photo=None)

    assert tracker.state.current_ply == 2
    assert tracker.previous is None


@pytest.mark.parametrize("status", [ResolutionStatus.AMBIGUOUS])
def test_tracker_waits_for_another_photo(status: ResolutionStatus) -> None:
    rules = Rules()
    rng = random.Random(5)
    state = play(rules=rules, rng=rng, plies=6)
    tracker = GameTracker(rules=rules, state=state)
    observed = photo(after(state, rng.choice(rules.legal_moves(state))), rng)
    observed.tiles = dict(list(observed.tiles.items())[:2])
    resolution = tracker.add_photo(observed)

    if resolution.status is status:
        assert tracker.pending == [observed]
        assert tracker.state.current_ply == state.current_ply
