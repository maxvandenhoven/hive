from abc import ABC, abstractmethod
from typing import override

from hive.engine.state import GameState, Player


class Evaluator(ABC):
    """Base class for position evaluators.

    An evaluator assigns a numeric score to a game state from the perspective of a given
    player. Positive scores indicate a favorable position for that player, and negative
    scores indicate an unfavorable one.

    Subclasses must implement `evaluate` to define their scoring heuristic.
    """

    @abstractmethod
    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate the game state from the perspective of the given player.

        Args:
            state: The current game state.
            player: The player from whose perspective the evaluation is performed.

        Returns:
            A score where positive values favor `player` and negative values favor the
            opponent.
        """


class WeightedCompositeEvaluator(Evaluator):
    """An evaluator that combines multiple evaluators using weighted summation.

    Each sub-evaluator contributes its score multiplied by its weight. This allows
    composing different evaluation heuristics into a single evaluator.
    """

    def __init__(self, components: list[tuple[Evaluator, float]]) -> None:
        """Initialize the composite evaluator.

        Args:
            components: A list of (evaluator, weight) pairs. Each evaluator's score is
                multiplied by its weight and the results are summed.
        """
        self.components = components

    @override
    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate the game state as a weighted sum of sub-evaluator scores.

        Args:
            state: The current game state.
            player: The player from whose perspective the evaluation is performed.

        Returns:
            The weighted sum of all sub-evaluator scores.
        """
        score = 0.0
        for evaluator, weight in self.components:
            score += weight * evaluator.evaluate(state, player)

        return score
