from hive_engine.state import GameState, PieceType, Player
from typing_extensions import override

from hive_agents.evaluators.base import Evaluator

DEFAULT_PIECE_VALUES: dict[PieceType, float] = {
    PieceType.QUEEN: 10.0,
    PieceType.ANT: 7.0,
    PieceType.BEETLE: 4.0,
    PieceType.GRASSHOPPER: 4.0,
    PieceType.SPIDER: 3.0,
}


class MaterialOnBoardEvaluator(Evaluator):
    """Evaluator that scores a position based on material on the board.

    Compares the total piece value on the board for the given player versus the opponent.
    Only pieces that have been placed on the board contribute to the score.
    """

    def __init__(self, piece_values: dict[PieceType, float] | None = None) -> None:
        """Initialize the on-board material evaluator.

        Parameters
        ----------
        piece_values : dict[PieceType, float] | None, optional
            A mapping from each piece type to its heuristic value. Defaults to
            `DEFAULT_PIECE_VALUES` if not provided.
        """
        self.piece_values = (
            piece_values if piece_values is not None else DEFAULT_PIECE_VALUES
        )

    @override
    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate on-board material advantage for the given player.

        Parameters
        ----------
        state : GameState
            The current game state.
        player : Player
            The player from whose perspective the evaluation is performed.

        Returns
        -------
        float
            Positive if the player has more material on the board, negative otherwise.
        """
        scores: dict[Player, float] = {Player.WHITE: 0.0, Player.BLACK: 0.0}
        for coord in state.get_occupied_coords():
            for piece in state.board[coord]:
                scores[piece.owner] += self.piece_values.get(piece.type, 0.0)

        return scores[player] - scores[player.opponent]


class MaterialInHandEvaluator(Evaluator):
    """Evaluator that scores a position based on material still in hand.

    Compares the total piece value remaining in each player's hand. Having more material
    in hand means more placement options are available.
    """

    def __init__(self, piece_values: dict[PieceType, float] | None = None) -> None:
        """Initialize the in-hand material evaluator.

        Parameters
        ----------
        piece_values : dict[PieceType, float] | None, optional
            A mapping from each piece type to its heuristic value. Defaults to
            `DEFAULT_PIECE_VALUES` if not provided.
        """
        self.piece_values = (
            piece_values if piece_values is not None else DEFAULT_PIECE_VALUES
        )

    @override
    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate in-hand material advantage for the given player.

        Parameters
        ----------
        state : GameState
            The current game state.
        player : Player
            The player from whose perspective the evaluation is performed.

        Returns
        -------
        float
            Positive if the player has more material in hand, negative otherwise.
        """
        scores: dict[Player, float] = {Player.WHITE: 0.0, Player.BLACK: 0.0}

        for p in Player:
            for piece_type, count in state.hand[p].items():
                scores[p] += count * self.piece_values.get(piece_type, 0.0)

        return scores[player] - scores[player.opponent]
