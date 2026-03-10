from hive_engine.ruleset import Ruleset
from hive_engine.state import GameState, Player
from typing_extensions import override

from hive_agents.evaluators.base import Evaluator


class MobilityEvaluator(Evaluator):
    """Evaluator that scores a position based on relative mobility.

    Compares the number of legal moves available to each player. More legal moves for the
    evaluated player relative to the opponent yields a positive score.

    This evaluator requires a `Ruleset` to generate legal moves. Note that computing
    legal moves can be expensive, so this evaluator may be slower than simpler heuristics.
    """

    def __init__(self, ruleset: Ruleset) -> None:
        """Initialize the mobility evaluator.

        Parameters
        ----------
        ruleset : Ruleset
            The ruleset used to generate legal moves for each player.
        """
        self.ruleset = ruleset

    def _count_legal_moves(self, state: GameState, player: Player) -> int:
        """Count the number of legal moves available to a player.

        Temporarily sets the current player to count that player's legal moves, then
        restores the original current player.

        Parameters
        ----------
        state : GameState
            The current game state.
        player : Player
            The player whose legal moves to count.

        Returns
        -------
        int
            The number of legal moves, excluding the pass move.
        """
        original_player = state.current_player
        state.current_player = player

        # Subtract 1 to exclude the pass move (None) that is always included.
        move_count = len(self.ruleset.get_legal_moves(state)) - 1

        state.current_player = original_player

        return move_count

    @override
    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate mobility advantage for the given player.

        Temporarily switches the current player to count legal moves for each side, then
        restores the original current player.

        Parameters
        ----------
        state : GameState
            The current game state.
        player : Player
            The player from whose perspective the evaluation is performed.

        Returns
        -------
        float
            The difference in legal move counts (player minus opponent). The pass move
            (`None`) is excluded from the count.
        """
        player_moves = self._count_legal_moves(state, player)
        opponent_moves = self._count_legal_moves(state, player.opponent)

        return float(player_moves - opponent_moves)
