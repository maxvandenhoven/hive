import math
from typing import override

from hive.agents.factory import register_agent
from hive.agents.search import SearchAgent
from hive.engine.state import GameState, Move, Player


@register_agent("minimax")
class MinimaxAgent(SearchAgent):
    """Agent that selects moves using the minimax algorithm with iterative deepening.

    Positions are scored from the perspective of the root player. The search maximizes
    the score at nodes where the root player is to move, and minimizes it at nodes where
    the opponent is to move.
    """

    @override
    def _search(self, state: GameState, depth: int) -> tuple[float, list[Move | None]]:
        """Search the game tree from the root to a fixed depth using minimax.

        Args:
            state: The root game state, which is restored before returning.
            depth: The search depth in plies.

        Returns:
            The score of the root from the perspective of the player to move, and the
            principal variation starting with the best move.
        """
        return self.minimax(state, depth, 0, state.current_player)

    def minimax(
        self, state: GameState, depth: int, ply: int, root_player: Player
    ) -> tuple[float, list[Move | None]]:
        """Recursively search the game tree using minimax.

        Args:
            state: The current game state, which is restored before returning.
            depth: The remaining search depth.
            ply: The number of plies from the root to this node.
            root_player: The player to move at the root, who maximizes the score.

        Returns:
            The score of the node from the perspective of `root_player`, and the
            principal variation from this node, which is empty at leaves.
        """
        self.visit_node()
        terminal_score = self.terminal_score(state, root_player, ply)

        if terminal_score is not None:
            return terminal_score, []

        if depth == 0:
            self.cutoff = True
            return self.evaluate(state, root_player), []

        # If the player to move at the node is the player to move at the root, maximize
        # the score of the child nodes, otherwise minimize it.
        maximizing = state.current_player == root_player
        best_score = -math.inf if maximizing else math.inf
        best_pv: list[Move | None] = []

        for move in self.rules.legal_moves(state):
            state.apply_move(move)

            try:
                score, pv = self.minimax(state, depth - 1, ply + 1, root_player)
            finally:
                state.undo_move(move)

            if (score > best_score) if maximizing else (score < best_score):
                best_score = score
                best_pv = [move, *pv]

        return best_score, best_pv
