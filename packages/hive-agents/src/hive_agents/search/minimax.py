import math

from hive_engine.ruleset import Ruleset
from hive_engine.state import GameState, Move, Player
from typing_extensions import override

from hive_agents.base import Agent
from hive_agents.evaluators.base import Evaluator


class MinimaxAgent(Agent):
    """Agent that selects moves using the minimax algorithm.

    Searches the game tree to a fixed depth, maximizing the evaluated score when it is
    the root player's turn and minimizing when it is the opponent's turn. The search
    uses a provided evaluator to score leaf positions.
    """

    def __init__(self, ruleset: Ruleset, evaluator: Evaluator, depth: int) -> None:
        """Initialize the minimax agent.

        Parameters
        ----------
        ruleset : Ruleset
            The ruleset governing the game.
        evaluator : Evaluator
            The position evaluator used to score leaf nodes.
        depth : int
            The maximum search depth in plies.
        """
        self.ruleset = ruleset
        self.evaluator = evaluator
        self.depth = depth

    def _minimax(
        self, state: GameState, depth: int, root_player: Player,
    ) -> tuple[float, Move | None]:
        """Recursively search the game tree using minimax.

        Parameters
        ----------
        state : GameState
            The current game state.
        depth : int
            The remaining search depth.
        root_player : Player
            The player who initiated the search (maximizing player at the root).

        Returns
        -------
        tuple[float, Move | None]
            The best score and the corresponding move. The move is `None` at leaf nodes
            or when the best action is to pass.
        """
        if depth == 0 or self.ruleset.is_finished(state):
            return self.evaluator.evaluate(state, root_player), None

        best_move: Move | None = None

        # If the player whose turn it is at the node is the same as the player whose
        # turn it is at the root of the tree, maximize the score from child nodes.
        if state.current_player == root_player:
            max_score = -math.inf
            for move in self.ruleset.get_legal_moves(state):
                state.apply_move(move)
                score, _ = self._minimax(state, depth - 1, root_player)
                state.undo_move(move)
                if score > max_score:
                    max_score = score
                    best_move = move

            return max_score, best_move

        min_score = math.inf
        for move in self.ruleset.get_legal_moves(state):
            state.apply_move(move)
            score, _ = self._minimax(state, depth - 1, root_player)
            state.undo_move(move)
            if score < min_score:
                min_score = score
                best_move = move
                
        return min_score, best_move

    @override
    def choose_move(self, state: GameState) -> Move | None:
        """Choose the best move using minimax search.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        Move | None
            The move with the highest minimax value, or `None` to pass.
        """
        root_player = state.current_player
        _, best_move = self._minimax(state, self.depth, root_player)

        return best_move


class AlphaBetaMinimaxAgent(Agent):
    """Agent that selects moves using minimax with alpha-beta pruning.

    Equivalent to `MinimaxAgent` but prunes branches that cannot influence the final
    decision, significantly reducing the number of nodes evaluated.
    """

    def __init__(self, ruleset: Ruleset, evaluator: Evaluator, depth: int) -> None:
        """Initialize the alpha-beta minimax agent.

        Parameters
        ----------
        ruleset : Ruleset
            The ruleset governing the game.
        evaluator : Evaluator
            The position evaluator used to score leaf nodes.
        depth : int
            The maximum search depth in plies.
        """
        self.ruleset = ruleset
        self.evaluator = evaluator
        self.depth = depth

    def _minimax(
        self,
        state: GameState,
        depth: int,
        root_player: Player,
        alpha: float,
        beta: float,
    ) -> tuple[float, Move | None]:
        """Recursively search the game tree using minimax with alpha-beta pruning.

        Parameters
        ----------
        state : GameState
            The current game state.
        depth : int
            The remaining search depth.
        root_player : Player
            The player who initiated the search (maximizing player at the root).
        alpha : float
            The best score the maximizing player can guarantee so far.
        beta : float
            The best score the minimizing player can guarantee so far.

        Returns
        -------
        tuple[float, Move | None]
            The best score and the corresponding move. The move is `None` at leaf nodes
            or when the best action is to pass.
        """
        if depth == 0 or self.ruleset.is_finished(state):
            return self.evaluator.evaluate(state, root_player), None

        best_move: Move | None = None

        if state.current_player == root_player:
            max_score = -math.inf
            for move in self.ruleset.get_legal_moves(state):
                state.apply_move(move)
                score, _ = self._minimax(state, depth - 1, root_player, alpha, beta)
                state.undo_move(move)
                if score > max_score:
                    max_score = score
                    best_move = move

                alpha = max(alpha, score)
                if alpha >= beta:
                    break

            return max_score, best_move

        min_score = math.inf
        for move in self.ruleset.get_legal_moves(state):
            state.apply_move(move)
            score, _ = self._minimax(state, depth - 1, root_player, alpha, beta)
            state.undo_move(move)
            if score < min_score:
                min_score = score
                best_move = move

            beta = min(beta, score)
            if alpha >= beta:
                break
        
        return min_score, best_move

    @override
    def choose_move(self, state: GameState) -> Move | None:
        """Choose the best move using alpha-beta minimax search.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        Move | None
            The move with the highest minimax value, or `None` to pass.
        """
        root_player = state.current_player
        _, best_move = self._minimax(state, self.depth, root_player, -math.inf, math.inf)

        return best_move
