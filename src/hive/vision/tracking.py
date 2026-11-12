"""Game tracking: follow a physical game photo by photo with the move resolver.

After every move a photo is taken. The tracker resolves it against the position it knows;
an unclear photo is kept and combined with the next photo of the same position, and the
photo that confirms a position becomes the reference that helps to recognise the tiles
in the next one. A person can always confirm moves by hand instead.
"""

from hive.engine.rules import Rules
from hive.engine.state import GameState, Move
from hive.vision.grid_fit import ObservedBoard
from hive.vision.resolver import MoveResolution, MoveResolver, ResolutionStatus


class GameTracker:
    """Follows a game from photos taken after every move.

    Attributes:
        rules: The rules of the game.
        resolver: The move resolver.
        state: The position the tracker knows.
        previous: The photo that confirmed the current position, or `None`.
        pending: The unclear photos of the next position, waiting for another one.
    """

    def __init__(
        self,
        rules: Rules,
        resolver: MoveResolver | None = None,
        state: GameState | None = None,
    ) -> None:
        """Start tracking a game.

        Args:
            rules: The rules of the game.
            resolver: The move resolver, or `None` for one with the default settings.
            state: The starting position, or `None` for the initial position.
        """
        self.rules = rules
        self.resolver = resolver or MoveResolver(rules)
        self.state = state.copy() if state is not None else rules.create_initial_state()
        self.previous: ObservedBoard | None = None
        self.pending: list[ObservedBoard] = []

    def add_photo(self, observed: ObservedBoard) -> MoveResolution:
        """Resolve a photo taken after the next move, together with unclear earlier ones.

        A resolved move is played. An ambiguous photo is kept for the next attempt; a
        photo that fits nothing is dropped.

        Args:
            observed: The observed board of the new photo.

        Returns:
            The resolution.
        """
        photos = [*self.pending, observed]
        resolution = self.resolver.resolve(
            state=self.state, photos=photos, previous=self.previous
        )

        if resolution.status is ResolutionStatus.RESOLVED:
            assert resolution.best is not None
            self.confirm(moves=resolution.best.moves, photo=observed)
        elif resolution.status is ResolutionStatus.AMBIGUOUS:
            self.pending = photos

        return resolution

    def confirm(self, moves: list[Move | None], photo: ObservedBoard | None) -> None:
        """Play moves that were resolved or entered by hand.

        Args:
            moves: The moves, each checked against the rules.
            photo: A photo of the position after the moves, which helps to recognise the
                tiles next time, or `None`.

        Raises:
            IllegalMoveError: If a move is not legal.
        """
        for move in moves:
            self.rules.apply_checked_move(state=self.state, move=move)

        self.previous = photo
        self.pending = []
