from typing import ClassVar, Literal

from hive.agents.factory import register_agent
from hive.agents.search import SearchAgent


@register_agent("minimax")
class MinimaxAgent(SearchAgent):
    """Agent that selects moves using the minimax algorithm with iterative deepening.

    Positions are scored from the perspective of the root player. The search maximizes
    the score at nodes where the root player is to move, and minimizes it at nodes where
    the opponent is to move.
    """

    ALGORITHM: ClassVar[Literal["minimax", "negamax"]] = "minimax"
