"""Move resolution: find the legal move that a photo of the board shows.

The engine knows the position before the photo exactly, stacks included, so a photo only
has to tell which legal move was played. Every candidate position after a legal move is
scored by how well it explains the observed boards of one or more photos of it:

- Alignment: a photo has its own lattice frame (see `grid_fit`). Most tiles do not move
  between photos, so the rotations and translations that put the observed faces on the
  engine tiles of the same class are found by voting, before any move is considered.
- Likelihood per hex: a detected face is scored by the probability its class scores
  give the expected top piece; an expected face that was not detected costs the more the
  better it should have been visible; a face on an empty hex costs a fixed penalty. Where
  the camera angle shows how high a face is, its stack level counts as well.
- Tile memory: a previous photo of the position before the move shows how the detector
  reads each physical tile, and a tile that read the same way before (even if wrongly)
  is likely the same tile now. Moved tiles take their reading with them.
- Several photos of the same position add their log-likelihoods, so an unclear photo is
  completed by another rather than replaced.

Candidates that give the same board up to rotation and translation are one outcome. The
best outcome is accepted when it is clearly more likely than the others and explains the
photos well; otherwise the result asks for another photo. When no single move explains
the photos, pairs of moves (a photo that was skipped) are tried, at a prior cost.
"""

import math
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from hive.engine.codec import JsonCodec
from hive.engine.grid import Coordinate
from hive.engine.rules import Rules
from hive.engine.state import GameBoard, GameState, Move
from hive.vision.classes import TileClass
from hive.vision.grid_fit import ObservedBoard, ObservedTile, face_size
from hive.vision.lattice import LatticeTransform, canonical_board, rotate_axial

type ExpectedFace = tuple[int, int] | None
"""The class id and stack level of the top face of a hex, or `None` for an empty hex."""


class ResolutionStatus(StrEnum):
    """The outcome of a move resolution."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ResolverConfig:
    """Settings of the move resolver; likelihoods are natural logarithms.

    Attributes:
        accept_probability: The posterior an outcome needs to be accepted.
        min_margin: The log-likelihood an accepted outcome must lead the next one by.
        confusion_rate: The chance that the detector is confused about a face and reads
            any class; the rest of the time its class scores are trusted.
        miss_probability: The chance that a fully visible face is not detected.
        extra_probability: The chance of a detection on an empty hex of the hive.
        memory_weight: How much a tile's reading in the previous photo counts.
        level_weight: How much a stack level that disagrees counts where the camera
            angle shows levels clearly.
        level_mismatch: The likelihood of a face seen at another stack level.
        max_alignments: The most alignments kept per photo.
        conflict_term: A hex scoring below this disagrees with the candidate.
        conflicts_per_tile: The share of tiles that may disagree, on top of one, before
            the result is doubted.
        near_penalty: The likelihood factor of matching an expected tile to a detection
            that was too far from its hex to be placed on the grid.
        skip_probability: The chance that a photo was skipped, so two moves were played;
            a pair of moves shares it with the other second moves of its first move.
        candidates: The number of candidates reported.
    """

    accept_probability: float = 0.95
    min_margin: float = 3.0
    confusion_rate: float = 0.05
    miss_probability: float = 0.02
    extra_probability: float = 0.01
    memory_weight: float = 0.5
    level_weight: float = 1.0
    level_mismatch: float = 0.3
    max_alignments: int = 4
    conflict_term: float = math.log(0.12)
    conflicts_per_tile: float = 0.15
    near_penalty: float = 0.3
    skip_probability: float = 0.02
    candidates: int = 5


@dataclass(frozen=True, slots=True)
class MoveCandidate(JsonCodec):
    """A possible explanation of the photos.

    Attributes:
        moves: The moves played since the known position, one or two; `None` is a pass.
        probability: The posterior probability among the candidates.
        log_likelihood: The log-likelihood of the photos, with the prior.
        conflicts: The number of hexes that disagree with the candidate in the photo that
            fits it best.
    """

    moves: list[Move | None]
    probability: float
    log_likelihood: float
    conflicts: int


@dataclass(frozen=True, slots=True)
class MoveResolution(JsonCodec):
    """The result of resolving photos to a move.

    Attributes:
        status: Whether a move was found, more photos are needed, or nothing fits.
        candidates: The most likely candidates, best first.
        reason: Why no move was accepted, for the person taking the photos.
    """

    status: ResolutionStatus
    candidates: list[MoveCandidate]
    reason: str | None = None

    @property
    def best(self) -> MoveCandidate | None:
        """The most likely candidate, if any."""
        return self.candidates[0] if self.candidates else None


@dataclass(slots=True)
class PhotoEvidence:
    """One photo placed on the engine coordinates in a few likely ways.

    Each way is a hypothesis: an alignment of the observed board, or before the first
    move, one detection taken as the first tile. A hypothesis has a log prior.

    Attributes:
        observed: The observed board of the photo.
        alignments: The map from the lattice frame of the photo to the engine, per
            hypothesis.
        tiles: Per hypothesis, the observed tile on each engine hex.
        near: Per hypothesis, the detection off the grid near each engine hex.
        priors: Per hypothesis, the log prior.
    """

    observed: ObservedBoard
    alignments: list[LatticeTransform]
    tiles: list[dict[Coordinate, ObservedTile]]
    near: list[dict[Coordinate, ObservedTile]]
    priors: list[float]

    @classmethod
    def aligned(
        cls, observed: ObservedBoard, alignments: list[LatticeTransform]
    ) -> "PhotoEvidence":
        """Place a photo on the engine coordinates with likely alignments.

        Args:
            observed: The observed board of the photo.
            alignments: The likely alignments.

        Returns:
            The evidence, with equal priors.
        """
        return cls(
            observed=observed,
            alignments=alignments,
            tiles=[
                {alignment.apply(coord): tile for coord, tile in observed.tiles.items()}
                for alignment in alignments
            ],
            near=[
                {alignment.apply(coord): tile for coord, tile in observed.near.items()}
                for alignment in alignments
            ],
            priors=[0.0] * len(alignments),
        )

    @classmethod
    def first_tile(cls, observed: ObservedBoard) -> "PhotoEvidence":
        """Take every detection of a photo as a possible first tile.

        The first tile lies alone, usually near the middle of the photo, while tiles in
        hand lie in groups at the side; the prior favours central, lone detections.

        Args:
            observed: The observed board of the photo.

        Returns:
            The evidence, one hypothesis per detection.
        """
        detections = [tile.observation for tile in observed.tiles.values()]
        detections += observed.off_grid
        width, height = observed.image_size
        half_diagonal = math.hypot(width, height) / 2
        tiles, priors = [], []

        for detection in detections:
            size = face_size(detection)
            alone = all(
                other is detection
                or math.dist(other.center, detection.center) > 1.5 * size
                for other in detections
            )
            distance = math.dist(detection.center, (width / 2, height / 2))
            tiles.append(
                {
                    (0, 0): ObservedTile(
                        observation=detection, coord=(0, 0), level=0, residual=0.0
                    )
                }
            )
            priors.append(-3.0 * distance / half_diagonal - (0.0 if alone else 2.0))

        return cls(
            observed=observed,
            alignments=[LatticeTransform.identity()] * len(detections),
            tiles=tiles,
            near=[{} for _ in detections],
            priors=priors,
        )


@dataclass(slots=True)
class CandidateScore:
    """The likelihood of a candidate and how it was reached.

    Attributes:
        moves: The moves of the candidate.
        log_likelihood: The log-likelihood with the prior.
        conflicts: The disagreeing hexes in the photo that fits best.
        key: The board after the moves up to rotation and translation.
    """

    moves: list[Move | None]
    log_likelihood: float
    conflicts: int
    key: object


class MoveResolver:
    """Resolves photos of a board to the legal move that was played.

    Attributes:
        rules: The rules of the game.
        config: The settings.
    """

    def __init__(self, rules: Rules, config: ResolverConfig | None = None) -> None:
        """Create a resolver.

        Args:
            rules: The rules of the game.
            config: The settings, or `None` for the defaults.
        """
        self.rules = rules
        self.config = config or ResolverConfig()

    def resolve(
        self,
        state: GameState,
        photos: list[ObservedBoard],
        previous: ObservedBoard | None = None,
    ) -> MoveResolution:
        """Find the move played since a known position, from photos of the result.

        Args:
            state: The known position before the move; it is not changed.
            photos: One or more photos of the position after the move.
            previous: A photo of the known position, whose readings of the tiles help to
                recognise them, or `None`.

        Returns:
            The resolution with the most likely candidates.
        """
        if not photos or all(not photo.tiles for photo in photos):
            return MoveResolution(
                status=ResolutionStatus.FAILED,
                candidates=[],
                reason="No hive was found. Take a photo with all tiles in view.",
            )

        state = state.copy()
        evidence = [
            PhotoEvidence.aligned(
                observed=photo, alignments=self.align(state=state, observed=photo)
            )
            if state.board
            else PhotoEvidence.first_tile(photo)
            for photo in photos
        ]
        memory = self.tile_memory(state=state, previous=previous)
        scores = list(
            self.score_sequences(state=state, evidence=evidence, memory=memory, depth=1)
        )
        best = max(scores, key=lambda score: score.log_likelihood)

        # Any disagreement may be a skipped photo, which only a pair of moves explains.
        if best.conflicts > 0:
            scores += self.score_sequences(
                state=state, evidence=evidence, memory=memory, depth=2
            )

        return self.decide(state=state, scores=scores)

    def decide(self, state: GameState, scores: list[CandidateScore]) -> MoveResolution:
        """Turn candidate scores into a resolution.

        Args:
            state: The known position before the move.
            scores: The scores of every candidate.

        Returns:
            The resolution.
        """
        config = self.config
        outcomes: dict[object, CandidateScore] = {}

        for score in scores:
            known = outcomes.get(score.key)

            if known is None or score.log_likelihood > known.log_likelihood:
                outcomes[score.key] = score

        ranked = sorted(outcomes.values(), key=lambda score: -score.log_likelihood)
        top = ranked[0].log_likelihood
        weights = [math.exp(score.log_likelihood - top) for score in ranked]
        total = sum(weights)
        candidates = [
            MoveCandidate(
                moves=score.moves,
                probability=weight / total,
                log_likelihood=score.log_likelihood,
                conflicts=score.conflicts,
            )
            for score, weight in zip(ranked[: config.candidates], weights, strict=False)
        ]
        best = candidates[0]
        margin = best.log_likelihood - (
            ranked[1].log_likelihood if len(ranked) > 1 else -math.inf
        )
        allowed = self.allowed_conflicts(state)

        if best.conflicts > 2 * allowed + 1:
            return MoveResolution(
                status=ResolutionStatus.FAILED,
                candidates=candidates,
                reason=(
                    f"The photo does not match any legal move: {best.conflicts} tiles "
                    "disagree with the best one. Take another photo with every tile in "
                    "view, or enter the move by hand."
                ),
            )

        if (
            best.probability >= config.accept_probability
            and margin >= config.min_margin
            and best.conflicts <= allowed
        ):
            return MoveResolution(status=ResolutionStatus.RESOLVED, candidates=candidates)

        options = ", ".join(
            f"{' then '.join(describe_move(move) for move in candidate.moves)} "
            f"({candidate.probability:.0%})"
            for candidate in candidates[:3]
        )

        return MoveResolution(
            status=ResolutionStatus.AMBIGUOUS,
            candidates=candidates,
            reason=(
                f"The photo fits several moves: {options}. Take another photo from a "
                "different angle with the changed tiles in view."
            ),
        )

    def allowed_conflicts(self, state: GameState) -> int:
        """Get how many hexes may disagree with an accepted candidate.

        Args:
            state: The known position before the move.

        Returns:
            1 plus a share of the tiles.
        """
        return 1 + math.floor(self.config.conflicts_per_tile * len(state.board))

    def align(self, state: GameState, observed: ObservedBoard) -> list[LatticeTransform]:
        """Find the likely maps from the lattice frame of a photo to the engine.

        Every rotation and translation that puts an observed face on an engine tile gets
        a vote weighted by how well the face's class fits the tile; most tiles are the
        same before and after the move, so the true alignment collects the most votes.

        Args:
            state: The known position before the move.
            observed: The observed board of the photo.

        Returns:
            The best alignments, most votes first.
        """
        if not state.board:
            return [LatticeTransform.identity()]

        votes: Counter[tuple[int, Coordinate]] = Counter()
        expected = {
            coord: TileClass(piece_type=stack[-1].type, owner=stack[-1].owner).id
            for coord, stack in state.board.items()
        }

        for rotation in range(6):
            for coord, tile in observed.tiles.items():
                q, r = rotate_axial(coord=coord, steps=rotation)
                probabilities = class_probabilities(tile)

                for target, class_id in expected.items():
                    weight = probabilities[class_id]

                    if weight > 0.05:
                        votes[(rotation, (target[0] - q, target[1] - r))] += weight

        if not votes:
            return [LatticeTransform.identity()]

        ranked = votes.most_common()
        top = ranked[0][1]

        return [
            LatticeTransform(rotation=rotation, translation=translation)
            for (rotation, translation), count in ranked[: self.config.max_alignments]
            if count >= 0.5 * top
        ]

    def tile_memory(
        self, state: GameState, previous: ObservedBoard | None
    ) -> dict[Coordinate, np.ndarray]:
        """Read how the detector saw each top tile of the known position before.

        Args:
            state: The known position, which the previous photo shows.
            previous: The previous photo, or `None`.

        Returns:
            The class probabilities of each engine hex's top tile in the previous photo.
        """
        if previous is None or not previous.tiles or not state.board:
            return {}

        alignment = self.align(state=state, observed=previous)[0]

        return {
            alignment.apply(coord): class_probabilities(tile)
            for coord, tile in previous.tiles.items()
            if alignment.apply(coord) in state.board
        }

    def score_sequences(
        self,
        state: GameState,
        evidence: list[PhotoEvidence],
        memory: Mapping[Coordinate, np.ndarray],
        depth: int,
    ) -> Iterator[CandidateScore]:
        """Score every sequence of legal moves of a length.

        Args:
            state: The known position, which is changed during the search and restored.
            evidence: The aligned photos.
            memory: The previous readings of the top tiles.
            depth: The number of moves, 1 or 2.

        Yields:
            The score of every sequence.
        """
        baselines = [
            [
                self.board_terms(
                    board=state.board, photo=photo, alignment=index, memory=memory
                )
                for index in range(len(photo.alignments))
            ]
            for photo in evidence
        ]
        skip = math.log(self.config.skip_probability)

        for moves, branching in self.sequences(state=state, depth=depth):
            prior = 0.0 if depth == 1 else skip - branching
            changed = changed_hexes(moves)
            origins = tile_origins(moves)
            # The state now holds the position after the moves (see `sequences`).
            total = prior
            conflicts = len(state.board) + len(changed) + 1

            for photo, baseline in zip(evidence, baselines, strict=True):
                best_value = -math.inf
                best_conflicts = 0

                for index, terms in enumerate(baseline):
                    value = sum(terms.values()) + photo.priors[index]
                    disagreeing = sum(
                        term < self.config.conflict_term for term in terms.values()
                    )

                    for coord in changed:
                        before = terms.get(coord, 0.0)
                        source = origins.get(coord, coord)
                        after = self.hex_term(
                            photo=photo,
                            alignment=index,
                            coord=coord,
                            expected=expected_face(state.board, coord),
                            memory=memory.get(source) if source is not None else None,
                        )
                        value += after - before
                        disagreeing += (after < self.config.conflict_term) - (
                            before < self.config.conflict_term
                        )

                    if value > best_value:
                        best_value, best_conflicts = value, disagreeing

                total += best_value
                conflicts = min(conflicts, best_conflicts)

            yield CandidateScore(
                moves=list(moves),
                log_likelihood=total,
                conflicts=conflicts,
                key=board_key(state.board),
            )

    def sequences(
        self, state: GameState, depth: int, first: bool = True
    ) -> Iterator[tuple[tuple[Move | None, ...], float]]:
        """Walk every sequence of legal moves of a length, leaving each applied.

        While a sequence is yielded, `state` holds the position after it; the moves are
        undone before the next one.

        Args:
            state: The known position.
            depth: The number of moves.
            first: Whether the first move of the sequence is chosen here.

        Yields:
            The sequences of moves, each with the log of the number of choices of its
            moves after the first, which spreads the prior of a sequence.
        """
        if depth == 0:
            yield (), 0.0
            return

        if self.rules.is_finished(state):
            return

        legal_moves = self.rules.legal_moves(state)
        choices = 0.0 if first else math.log(len(legal_moves))

        for move in legal_moves:
            state.apply_move(move)

            for rest, branching in self.sequences(
                state=state, depth=depth - 1, first=False
            ):
                yield (move, *rest), choices + branching

            state.undo_move(move)

    def board_terms(
        self,
        board: GameBoard,
        photo: PhotoEvidence,
        alignment: int,
        memory: Mapping[Coordinate, np.ndarray],
    ) -> dict[Coordinate, float]:
        """Score every hex of a board and of the photo under one alignment.

        Args:
            board: The board of the known position.
            photo: The aligned photo.
            alignment: The index of the alignment.
            memory: The previous readings of the top tiles.

        Returns:
            The log-likelihood term of every occupied or observed hex.
        """
        coords = set(board) | set(photo.tiles[alignment])

        return {
            coord: self.hex_term(
                photo=photo,
                alignment=alignment,
                coord=coord,
                expected=expected_face(board, coord),
                memory=memory.get(coord),
            )
            for coord in coords
        }

    def hex_term(
        self,
        photo: PhotoEvidence,
        alignment: int,
        coord: Coordinate,
        expected: ExpectedFace,
        memory: np.ndarray | None,
    ) -> float:
        """Score how well a photo shows the expected face of one hex.

        Args:
            photo: The aligned photo.
            alignment: The index of the alignment.
            coord: The engine hex.
            expected: The expected top face, or `None` for an empty hex.
            memory: The previous reading of the tile expected on top, or `None`.

        Returns:
            The log-likelihood of the observation of the hex.
        """
        config = self.config
        tile = photo.tiles[alignment].get(coord)

        if expected is None:
            return math.log(config.extra_probability) if tile is not None else 0.0

        class_id, level = expected

        if tile is None:
            local = photo.alignments[alignment].inverse().apply(coord)
            visible = photo.observed.visibility(coord=local, level=level)
            missed = math.log(
                config.miss_probability + (1 - config.miss_probability) * (1 - visible)
            )
            near = photo.near[alignment].get(coord)

            if near is None:
                return missed

            matched = self.face_term(
                tile=near, class_id=class_id, level=level, memory=memory
            ) + math.log(config.near_penalty)

            return max(missed, matched)

        return self.face_term(tile=tile, class_id=class_id, level=level, memory=memory)

    def face_term(
        self, tile: ObservedTile, class_id: int, level: int, memory: np.ndarray | None
    ) -> float:
        """Score a detected face against the expected top tile of its hex.

        Args:
            tile: The detected face.
            class_id: The expected class id.
            level: The expected stack level.
            memory: The previous reading of the expected tile, or `None`.

        Returns:
            The log-likelihood of the detection.
        """
        config = self.config
        probabilities = class_probabilities(tile)
        probability = float(probabilities[class_id])

        if memory is not None:
            probability = (
                1 - config.memory_weight
            ) * probability + config.memory_weight * (float(probabilities @ memory))

        class_count = len(probabilities)
        term = math.log(
            (1 - config.confusion_rate) * probability
            + config.confusion_rate / class_count
        )

        if tile.level != level and tile.level_shift > 0:
            reliability = min(1.0, tile.level_shift / 0.25)
            term += config.level_weight * reliability * math.log(config.level_mismatch)

        return term


def class_probabilities(tile: ObservedTile) -> np.ndarray:
    """Turn the class scores of a detection into probabilities.

    Args:
        tile: The observed tile.

    Returns:
        The probability of every class in class id order.
    """
    observation = tile.observation
    count = len(TileClass.all())

    if observation.class_scores is not None:
        scores = np.asarray(observation.class_scores, dtype=np.float64) + 1e-3
    else:
        scores = np.full(count, (1 - observation.score) / (count - 1))
        scores[observation.tile_class.id] = observation.score

    return scores / scores.sum()


def expected_face(board: GameBoard, coord: Coordinate) -> ExpectedFace:
    """Get the top face of a hex on an engine board.

    Args:
        board: The board.
        coord: The hex.

    Returns:
        The class id and stack level of the top tile, or `None` for an empty hex.
    """
    stack = board.get(coord)

    if not stack:
        return None

    top = stack[-1]

    return TileClass(piece_type=top.type, owner=top.owner).id, len(stack) - 1


def changed_hexes(moves: tuple[Move | None, ...]) -> set[Coordinate]:
    """Get the hexes whose top face a sequence of moves may change.

    Args:
        moves: The moves.

    Returns:
        The sources and targets of the moves.
    """
    changed: set[Coordinate] = set()

    for move in moves:
        if move is None:
            continue

        changed.add(move.target_coord)

        if move.source_coord is not None:
            changed.add(move.source_coord)

    return changed


def tile_origins(moves: tuple[Move | None, ...]) -> dict[Coordinate, Coordinate | None]:
    """Find where the top tile of each changed hex was before a sequence of moves.

    Args:
        moves: The moves.

    Returns:
        For each changed hex, the hex its top tile was on top of before the moves, or
        `None` for a placed tile or a tile that was covered and is now uncovered.
    """
    origins: dict[Coordinate, Coordinate | None] = {}

    for move in moves:
        if move is None:
            continue

        if move.source_coord is None:
            origins[move.target_coord] = None
            continue

        origins[move.target_coord] = origins.get(move.source_coord, move.source_coord)
        origins[move.source_coord] = None

    return origins


def board_key(board: GameBoard) -> object:
    """Get a key that is equal for boards that are rigid motions of each other.

    Args:
        board: The engine board.

    Returns:
        The canonical form with the stacks as tuples of piece type and owner.
    """
    return canonical_board(
        {
            coord: tuple((piece.type, piece.owner) for piece in stack)
            for coord, stack in board.items()
        }
    )


def describe_move(move: Move | None) -> str:
    """Describe a move briefly for a message.

    Args:
        move: The move, or `None` for a pass.

    Returns:
        For example `ant to (1, 0)` or `pass`.
    """
    if move is None:
        return "pass"

    piece = move.piece_type.name.lower()

    if move.source_coord is None:
        return f"place {piece} at {move.target_coord}"

    return f"{piece} {move.source_coord} to {move.target_coord}"
