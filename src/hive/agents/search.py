"""Search agents: iterative deepening tree search, run by the Rust core.

`SearchAgent` takes the depth limit and the evaluation weights as agent params and builds
a `Searcher` of the Rust core (`hive._core`), which searches every decision and reports
to the turn context. The kinds differ only in the tree search they configure.
"""

from typing import Annotated, ClassVar, Literal, override

from pydantic import Field

from hive._core import Searcher
from hive.agents.base import Agent, TurnContext
from hive.engine.rules import Rules
from hive.engine.state import GameState, Player

__all__ = ["SEARCH_WIN_SCORE", "SearchAgent", "Searcher"]

SEARCH_WIN_SCORE = 1_000_000.0
"""The score of a won position, reduced by one per ply so faster wins score higher."""


class SearchAgent(Agent):
    """Base class for agents that search the game tree with iterative deepening.

    The search runs to depth 1, 2, 3, and so on, submitting the best move after each
    completed depth, until the depth limit is reached, the game tree is exhausted, the
    result is decided (a forced win or loss), or the turn context asks to stop. A depth
    that is interrupted is discarded, so the submitted move always comes from a
    completed search. The search itself runs in the Rust core (`Searcher`); this class
    holds the params, submits a first move and hands the decision over.

    Leaf positions are scored by a weighted sum of evaluation terms, each from the
    perspective of the given player. Terms with weight zero are skipped. Finished games
    score `SEARCH_WIN_SCORE` minus the plies from the root for a win, the negation for a
    loss, and zero for a draw.

    Registered subclasses set `ALGORITHM` and take the depth limit and the evaluation
    weights as agent parameters, described in `__init__`.

    Attributes:
        depth: The maximum search depth in plies, or `None` to search until stopped.
        queen_safety: The weight of the queen safety term.
        mobility: The weight of the mobility term.
        positioning: The weight of the positioning term.
        material_on_board: The weight of the on-board material term.
        material_in_hand: The weight of the in-hand material term.
        alpha_beta: Whether the search prunes with alpha-beta.
        table_megabytes: The size of the transposition table in MB.
        searcher: The search of the Rust core, configured with the params.
        nodes: The number of nodes the last decision visited.
    """

    ALGORITHM: ClassVar[Literal["minimax", "negamax"]] = "negamax"
    """The tree search of the agent kind."""

    STOP_CHECK_INTERVAL: ClassVar[int] = 1024
    """The number of nodes visited between two calls of `TurnContext.should_stop`."""

    def __init__(
        self,
        rules: Rules,
        *,
        seed: int,
        depth: Annotated[int | None, Field(ge=1)] = None,
        queen_safety: float = 1.0,
        mobility: float = 0.0,
        positioning: float = 0.0,
        material_on_board: float = 0.0,
        material_in_hand: float = 0.0,
        alpha_beta: bool = True,
        table_megabytes: Annotated[int, Field(ge=0)] = 32,
    ) -> None:
        """Initialize the search agent.

        Args:
            rules: The rules governing the game.
            seed: The seed for the random number generator of the agent.
            depth: The maximum search depth in plies, or `None` to search until stopped.
            queen_safety: The weight of the occupied neighbours of the opponent's queen
                minus those of the player's own queen.
            mobility: The weight of the player's legal moves minus the opponent's. This
                term generates moves at every leaf, which makes it slow.
            positioning: The weight of the player's pieces next to the opponent's queen
                minus the opponent's pieces next to the player's queen.
            material_on_board: The weight of the value of the player's pieces on the
                board minus the opponent's.
            material_in_hand: The weight of the value of the player's pieces in hand
                minus the opponent's.
            alpha_beta: Whether to prune the search with alpha-beta, searching the best
                line of the previous depth first. It finds the same scores in far fewer
                nodes, but may choose another of several equally scored moves.
            table_megabytes: The size of the transposition table in MB, zero for none.
                `negamax` with alpha-beta uses it, and orders moves by killer moves and a
                history table too; it is kept between decisions of a match.
        """
        super().__init__(rules=rules, seed=seed)
        self.depth = depth
        self.queen_safety = queen_safety
        self.mobility = mobility
        self.positioning = positioning
        self.material_on_board = material_on_board
        self.material_in_hand = material_in_hand
        self.alpha_beta = alpha_beta
        self.table_megabytes = table_megabytes
        self.searcher = Searcher(
            rules,
            algorithm=self.ALGORITHM,
            depth=depth,
            queen_safety=queen_safety,
            mobility=mobility,
            positioning=positioning,
            material_on_board=material_on_board,
            material_in_hand=material_in_hand,
            stop_check_interval=self.STOP_CHECK_INTERVAL,
            alpha_beta=alpha_beta,
            table_megabytes=table_megabytes,
        )
        self.nodes = 0

    @override
    def think(self, state: GameState, turn: TurnContext) -> None:
        """Search with iterative deepening, submitting the best move after each depth.

        A random legal move is submitted before the search starts. The state is restored
        to its original position when the search returns or is stopped.

        Args:
            state: A copy of the current game state.
            turn: The context to submit moves and report progress to.
        """
        legal_moves = self.rules.legal_moves(state)

        if len(legal_moves) == 1:
            turn.submit(move=legal_moves[0], final=True)
            return

        turn.submit(legal_moves[self.rng.randrange(len(legal_moves))])
        self.nodes = self.searcher.think(state=state, turn=turn)

    @override
    def reset(self) -> None:
        """Forget the transposition table, killer moves and history of the last match."""
        self.searcher.clear()

    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate a position as the weighted sum of the evaluation terms.

        Args:
            state: The game state to evaluate.
            player: The player from whose perspective the position is evaluated.

        Returns:
            A score where positive values favour `player`.
        """
        return self.searcher.evaluate(state=state, player=player)
