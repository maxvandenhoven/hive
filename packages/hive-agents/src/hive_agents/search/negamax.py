import math

from hive_engine.ruleset import Ruleset
from hive_engine.state import GameState, Move
from typing_extensions import override

from hive_agents.base import Agent
from hive_agents.evaluators.base import Evaluator


class NegamaxAgent(Agent):
    """Agent that selects moves using the negamax algorithm.

    Negamax is a simplification of minimax that exploits the zero-sum property of the
    game: the value of a position to one player is the negation of the value to the
    opponent. This eliminates the need for separate maximizing and minimizing branches.
    """

    def __init__(self, ruleset: Ruleset, evaluator: Evaluator, depth: int) -> None:
        """Initialize the negamax agent.

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

    def _negamax(
        self,
        state: GameState,
        depth: int,
    ) -> tuple[float, Move | None]:
        """Recursively search the game tree using negamax.

        The evaluator is always called from the perspective of the current player at the
        node. Child scores are negated on return, since a good position for the opponent
        is bad for the current player.

        Parameters
        ----------
        state : GameState
            The current game state.
        depth : int
            The remaining search depth.

        Returns
        -------
        tuple[float, Move | None]
            The best score and the corresponding move. The move is `None` at leaf nodes
            or when the best action is to pass.
        """
        if depth == 0 or self.ruleset.is_finished(state):
            return self.evaluator.evaluate(state, state.current_player), None

        max_score = -math.inf
        best_move: Move | None = None
        for move in self.ruleset.get_legal_moves(state):
            state.apply_move(move)
            score, _ = self._negamax(state, depth - 1)
            score = -score
            state.undo_move(move)
            if score > max_score:
                max_score = score
                best_move = move

        return max_score, best_move

    @override
    def choose_move(self, state: GameState) -> Move | None:
        """Choose the best move using negamax search.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        Move | None
            The move with the highest negamax value, or `None` to pass.
        """
        _, best_move = self._negamax(state, self.depth)

        return best_move


class AlphaBetaNegamaxAgent(Agent):
    """Agent that selects moves using negamax with alpha-beta pruning.

    Equivalent to `NegamaxAgent` but prunes branches that cannot influence the final
    decision, significantly reducing the number of nodes evaluated.
    """

    def __init__(self, ruleset: Ruleset, evaluator: Evaluator, depth: int) -> None:
        """Initialize the alpha-beta negamax agent.

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

    def _negamax(
        self,
        state: GameState,
        depth: int,
        alpha: float,
        beta: float,
    ) -> tuple[float, Move | None]:
        """Recursively search the game tree using negamax with alpha-beta pruning.

        Parameters
        ----------
        state : GameState
            The current game state.
        depth : int
            The remaining search depth.
        alpha : float
            The best score the current player can guarantee so far.
        beta : float
            The best score the opponent can guarantee so far.

        Returns
        -------
        tuple[float, Move | None]
            The best score and the corresponding move. The move is `None` at leaf nodes
            or when the best action is to pass.
        """
        if depth == 0 or self.ruleset.is_finished(state):
            return self.evaluator.evaluate(state, state.current_player), None

        max_score = -math.inf
        best_move: Move | None = None
        for move in self.ruleset.get_legal_moves(state):
            state.apply_move(move)
            score, _ = self._negamax(state, depth - 1, -beta, -alpha)
            score = -score
            state.undo_move(move)
            if score > max_score:
                max_score = score
                best_move = move

            alpha = max(alpha, score)
            if alpha >= beta:
                break

        return max_score, best_move

    @override
    def choose_move(self, state: GameState) -> Move | None:
        """Choose the best move using alpha-beta negamax search.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        Move | None
            The move with the highest negamax value, or `None` to pass.
        """
        _, best_move = self._negamax(state, self.depth, -math.inf, math.inf)

        return best_move
