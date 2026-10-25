import math
from typing import override

from hive.agents.factory import register_agent
from hive.agents.search import SearchAgent
from hive.engine.state import GameState, Move


@register_agent("negamax")
class NegamaxAgent(SearchAgent):
    """Agent that selects moves using the negamax algorithm with iterative deepening.

    Negamax is a simplification of minimax that exploits the zero-sum property of the
    game: the value of a position to one player is the negation of the value to the
    opponent. Every node is scored from the perspective of the player to move, which
    removes the need for separate maximizing and minimizing branches.
    """

    @override
    def _search(self, state: GameState, depth: int) -> tuple[float, list[Move | None]]:
        """Search the game tree from the root to a fixed depth using negamax.

        Args:
            state: The root game state, which is restored before returning.
            depth: The search depth in plies.

        Returns:
            The score of the root from the perspective of the player to move, and the
            principal variation starting with the best move.
        """
        return self.negamax(state=state, depth=depth, ply=0)

    def negamax(
        self, state: GameState, depth: int, ply: int
    ) -> tuple[float, list[Move | None]]:
        """Recursively search the game tree using negamax.

        Child scores are negated on return, since a good position for the opponent is bad
        for the player to move.

        Args:
            state: The current game state, which is restored before returning.
            depth: The remaining search depth.
            ply: The number of plies from the root to this node.

        Returns:
            The score of the node from the perspective of the player to move, and the
            principal variation from this node, which is empty at leaves.
        """
        self.visit_node()
        terminal_score = self.terminal_score(
            state=state, player=state.current_player, ply=ply
        )

        if terminal_score is not None:
            return terminal_score, []

        if depth == 0:
            self.cutoff = True
            return self.evaluate(state=state, player=state.current_player), []

        best_score = -math.inf
        best_pv: list[Move | None] = []

        for move in self.rules.legal_moves(state):
            state.apply_move(move)

            try:
                child_score, pv = self.negamax(state=state, depth=depth - 1, ply=ply + 1)
            finally:
                state.undo_move(move)

            score = -child_score

            if score > best_score:
                best_score = score
                best_pv = [move, *pv]

        return best_score, best_pv
