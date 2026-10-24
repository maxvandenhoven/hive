from typing import override

from hive.agents.evaluators.base import Evaluator
from hive.engine.rules import Rules
from hive.engine.state import GameState, Player


class MobilityEvaluator(Evaluator):
    """Evaluator that scores a position based on relative mobility.

    Compares the number of legal moves available to each player. More legal moves for the
    evaluated player relative to the opponent yields a positive score.

    This evaluator requires `Rules` to generate legal moves. Note that computing legal
    moves can be expensive, so this evaluator may be slower than simpler heuristics.
    """

    def __init__(self, rules: Rules) -> None:
        """Initialize the mobility evaluator.

        Args:
            rules: The rules used to generate legal moves for each player.
        """
        self.rules = rules

    def _count_legal_moves(self, state: GameState, player: Player) -> int:
        """Count the number of legal moves available to a player.

        Temporarily sets the current player to count that player's legal moves, then
        restores the original current player.

        Args:
            state: The current game state.
            player: The player whose legal moves to count.

        Returns:
            The number of legal moves, excluding the pass move.
        """
        original_player = state.current_player
        state.current_player = player

        # Exclude the pass move (`None`), which is only returned when there are no moves.
        move_count = sum(move is not None for move in self.rules.legal_moves(state))

        state.current_player = original_player

        return move_count

    @override
    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate mobility advantage for the given player.

        Temporarily switches the current player to count legal moves for each side, then
        restores the original current player.

        Args:
            state: The current game state.
            player: The player from whose perspective the evaluation is performed.

        Returns:
            The difference in legal move counts (player minus opponent). The pass move
            (`None`) is excluded from the count.
        """
        player_moves = self._count_legal_moves(state, player)
        opponent_moves = self._count_legal_moves(state, player.opponent)

        return float(player_moves - opponent_moves)
