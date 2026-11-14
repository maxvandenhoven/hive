from typing import ClassVar, Literal

from hive.agents.factory import register_agent
from hive.agents.search import SearchAgent


@register_agent("negamax")
class NegamaxAgent(SearchAgent):
    """Agent that selects moves using the negamax algorithm with iterative deepening.

    Negamax is a simplification of minimax that exploits the zero-sum property of the
    game: the value of a position to one player is the negation of the value to the
    opponent. Every node is scored from the perspective of the player to move, which
    removes the need for separate maximizing and minimizing branches.
    """

    ALGORITHM: ClassVar[Literal["minimax", "negamax"]] = "negamax"
