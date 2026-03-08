from hive_engine.state import GameState, Player
from typing_extensions import override

from hive_agents.evaluators.base import Evaluator


class PositioningEvaluator(Evaluator):
    """Evaluator that scores a position based on piece proximity to the opponent's queen.

    Awards points for the evaluated player's pieces that are adjacent to the opponent's
    queen (applying direct pressure), and penalizes when the opponent's pieces are
    adjacent to the player's queen.
    """

    def _count_pressure(self, state: GameState, attacker: Player) -> float:
        """Count the attacker's pieces adjacent to the defender's queen.

        Parameters
        ----------
        state : GameState
            The current game state.
        attacker : Player
            The player whose pieces are checked for proximity to the opponent's queen.

        Returns
        -------
        float
            The number of the attacker's pieces adjacent to the defender's queen, or 0.0
            if the defender's queen has not been placed.
        """
        defender = attacker.opponent
        queen_coord = state.get_queen_coord(defender)
        if queen_coord is None:
            return 0.0

        pressure = 0.0
        for neighbor_coord in state.get_neighbors(queen_coord):
            if state.is_occupied(neighbor_coord):
                top_piece = state.get_top_piece(neighbor_coord)
                if top_piece.owner == attacker:
                    pressure += 1.0

        return pressure

    @override
    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate positioning advantage for the given player.

        Parameters
        ----------
        state : GameState
            The current game state.
        player : Player
            The player from whose perspective the evaluation is performed.

        Returns
        -------
        float
            Positive if the player has more pieces adjacent to the opponent's queen than
            the opponent has adjacent to the player's queen.
        """
        player_pressure = self._count_pressure(state, attacker=player)
        opponent_pressure = self._count_pressure(state, attacker=player.opponent)

        return player_pressure - opponent_pressure
