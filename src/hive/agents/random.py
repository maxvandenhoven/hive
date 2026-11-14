from typing import override

from hive.agents.base import Agent, TurnContext
from hive.agents.factory import register_agent
from hive.agents.params import AgentParams
from hive.engine.state import GameState


@register_agent("random")
class RandomAgent(Agent[AgentParams]):
    """Agent that selects moves uniformly at random from the set of legal moves."""

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Submit a move chosen uniformly at random from the legal moves as final.

        Args:
            state: A copy of the current game state.
            turn: The context to submit the move to.
        """
        legal_moves = self.rules.legal_moves(state)
        turn.submit(move=legal_moves[self.rng.randrange(len(legal_moves))], final=True)
