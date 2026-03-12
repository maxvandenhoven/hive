from hive_engine.grid import get_neighbors
from hive_engine.state import GameState, Player
from typing_extensions import override

from hive_agents.evaluators.base import Evaluator


class QueenSafetyEvaluator(Evaluator):
    """Evaluator that scores a position based on queen surroundedness.

    Counts the number of occupied neighbors around each player's queen. The opponent's
    queen being more surrounded is favorable (positive), while the player's own queen
    being surrounded is unfavorable (negative).
    """

    def _count_queen_pressure(self, state: GameState, player: Player) -> float:
        """Count how many neighbors of a player's queen are occupied.

        Parameters
        ----------
        state : GameState
            The current game state.
        player : Player
            The player whose queen to inspect.

        Returns
        -------
        float
            The number of occupied neighbors around the queen, or 0.0 if the queen has
            not been placed.
        """
        queen_coord = state.get_queen_coord(player)
        if queen_coord is None:
            return 0.0

        occupied_count = 0.0
        for neighbor_coord in get_neighbors(queen_coord):
            if state.is_occupied(neighbor_coord):
                occupied_count += 1.0

        return occupied_count

    @override
    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate queen safety for the given player.

        Parameters
        ----------
        state : GameState
            The current game state.
        player : Player
            The player from whose perspective the evaluation is performed.

        Returns
        -------
        float
            A score in the range [-6.0, 6.0]. Positive values indicate the opponent's
            queen is more surrounded than the player's queen.
        """
        player_pressure = self._count_queen_pressure(state, player)
        opponent_pressure = self._count_queen_pressure(state, player.opponent)
        return opponent_pressure - player_pressure
