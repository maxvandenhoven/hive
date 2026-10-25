import time
from abc import abstractmethod
from collections.abc import Callable
from typing import Annotated, override

from pydantic import Field

from hive.agents.base import Agent, TurnContext
from hive.engine.grid import get_neighbors
from hive.engine.rules import Rules
from hive.engine.serialization import serialize_move
from hive.engine.state import GameState, Move, PieceType, Player

WIN_SCORE = 1_000_000.0
"""The score of a won position, reduced by one per ply so faster wins score higher."""

PIECE_VALUES: dict[PieceType, float] = {
    PieceType.QUEEN: 10.0,
    PieceType.ANT: 7.0,
    PieceType.BEETLE: 4.0,
    PieceType.GRASSHOPPER: 4.0,
    PieceType.SPIDER: 3.0,
}
"""The heuristic value of each piece type for the material evaluation terms."""


class SearchStoppedError(Exception):
    """Raised inside a search when the turn context asks the agent to stop."""


class SearchAgent(Agent):
    """Base class for agents that search the game tree with iterative deepening.

    The search runs to depth 1, 2, 3, and so on, submitting the best move after each
    completed depth, until the depth limit is reached, the game tree is exhausted, the
    result is decided (a forced win or loss), or the turn context asks to stop. A depth
    that is interrupted is discarded, so the submitted move always comes from a
    completed search.

    Leaf positions are scored by a weighted sum of evaluation terms, each from the
    perspective of the given player. Terms with weight zero are skipped. Finished games
    score `WIN_SCORE` minus the plies from the root for a win, the negation for a loss,
    and zero for a draw.

    Subclasses implement `_search` for one fixed depth and call `_visit_node` at every
    node, which counts nodes and checks `should_stop` every `STOP_CHECK_INTERVAL` nodes.

    Registered subclasses take the depth limit and the evaluation weights as agent
    parameters, described in `__init__`.

    Attributes:
        depth: The maximum search depth in plies, or `None` to search until stopped.
        queen_safety: The weight of the queen safety term.
        mobility: The weight of the mobility term.
        positioning: The weight of the positioning term.
        material_on_board: The weight of the on-board material term.
        material_in_hand: The weight of the in-hand material term.
    """

    STOP_CHECK_INTERVAL = 32
    """The number of nodes visited between two calls of `TurnContext.should_stop`."""

    _turn: TurnContext

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
        """
        super().__init__(rules, seed=seed)
        self.depth = depth
        self.queen_safety = queen_safety
        self.mobility = mobility
        self.positioning = positioning
        self.material_on_board = material_on_board
        self.material_in_hand = material_in_hand

        terms: list[tuple[float, Callable[[GameState, Player], float]]] = [
            (queen_safety, self._queen_safety),
            (mobility, self._mobility),
            (positioning, self._positioning),
            (material_on_board, self._material_on_board),
            (material_in_hand, self._material_in_hand),
        ]
        self._terms = [(weight, term) for weight, term in terms if weight != 0.0]
        self._nodes = 0
        self._cutoff = False

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
            turn.submit(legal_moves[0], final=True)
            return

        turn.submit(legal_moves[self._rng.randrange(len(legal_moves))])

        self._turn = turn
        self._nodes = 0
        start = time.perf_counter()
        depth = 1
        while not turn.should_stop():
            # The search sets the cutoff flag when it stops at the depth limit, so an
            # unset flag means the whole game tree below the root was searched.
            self._cutoff = False
            try:
                score, pv = self._search(state, depth)
            except SearchStoppedError:
                return

            elapsed = time.perf_counter() - start
            turn.info(
                depth=depth,
                nodes=self._nodes,
                score=score,
                pv=[serialize_move(move) for move in pv],
                nps=round(self._nodes / elapsed) if elapsed > 0 else None,
            )
            final = (
                depth == self.depth or not self._cutoff or abs(score) >= WIN_SCORE - depth
            )
            turn.submit(pv[0], final=final)
            if final:
                return

            depth += 1

    def evaluate(self, state: GameState, player: Player) -> float:
        """Evaluate a position as the weighted sum of the evaluation terms.

        Args:
            state: The game state to evaluate.
            player: The player from whose perspective the position is evaluated.

        Returns:
            A score where positive values favour `player`.
        """
        score = 0.0
        for weight, term in self._terms:
            score += weight * term(state, player)

        return score

    @abstractmethod
    def _search(self, state: GameState, depth: int) -> tuple[float, list[Move | None]]:
        """Search the game tree from the root to a fixed depth.

        Args:
            state: The root game state, which must be restored before returning.
            depth: The search depth in plies.

        Returns:
            The score of the root from the perspective of the player to move, and the
            principal variation starting with the best move.

        Raises:
            SearchStoppedError: If the turn context asks the agent to stop.
        """

    def _visit_node(self) -> None:
        """Count a visited node and check whether to stop every few nodes.

        Raises:
            SearchStoppedError: If the turn context asks the agent to stop.
        """
        self._nodes += 1
        if self._nodes % self.STOP_CHECK_INTERVAL == 0 and self._turn.should_stop():
            raise SearchStoppedError

    def _terminal_score(self, state: GameState, player: Player, ply: int) -> float | None:
        """Score a finished game.

        Args:
            state: The game state to score.
            player: The player from whose perspective the game is scored.
            ply: The number of plies from the root to the position.

        Returns:
            The score of a finished game, or `None` if the game is still in progress.
        """
        winners = self.rules.winners(state)
        if winners is None:
            return None
        if len(winners) == len(Player):
            return 0.0
        if player in winners:
            return WIN_SCORE - ply
        return -(WIN_SCORE - ply)

    def _queen_safety(self, state: GameState, player: Player) -> float:
        """Compare how surrounded the opponent's queen is to the player's own queen.

        Args:
            state: The game state to evaluate.
            player: The player from whose perspective the position is evaluated.

        Returns:
            The occupied neighbours of the opponent's queen minus those of the player's
            queen, in the range [-6, 6].
        """
        return self._occupied_queen_neighbors(
            state, player.opponent
        ) - self._occupied_queen_neighbors(state, player)

    def _occupied_queen_neighbors(self, state: GameState, owner: Player) -> float:
        """Count the occupied neighbours of a player's queen.

        Args:
            state: The game state to inspect.
            owner: The player whose queen to inspect.

        Returns:
            The number of occupied neighbours, or 0 if the queen has not been placed.
        """
        queen_coord = state.get_queen_coord(owner)
        if queen_coord is None:
            return 0.0

        return float(sum(state.is_occupied(c) for c in get_neighbors(queen_coord)))

    def _mobility(self, state: GameState, player: Player) -> float:
        """Compare the number of legal moves of the player and of the opponent.

        Args:
            state: The game state to evaluate, whose current player is restored.
            player: The player from whose perspective the position is evaluated.

        Returns:
            The legal moves of the player minus those of the opponent, where a forced
            pass counts as zero moves.
        """
        return float(
            self._count_legal_moves(state, player)
            - self._count_legal_moves(state, player.opponent)
        )

    def _count_legal_moves(self, state: GameState, player: Player) -> int:
        """Count the legal moves of a player by temporarily making them the current one.

        Args:
            state: The game state to inspect, whose current player is restored.
            player: The player whose legal moves to count.

        Returns:
            The number of legal moves, excluding the pass move.
        """
        original_player = state.current_player
        state.current_player = player

        # Exclude the pass move (`None`), which is only returned when there are no moves.
        move_count = sum(move is not None for move in self.rules.legal_moves(state))

        state.current_player = original_player
        return move_count

    def _positioning(self, state: GameState, player: Player) -> float:
        """Compare the pressure each player puts on the opponent's queen.

        Args:
            state: The game state to evaluate.
            player: The player from whose perspective the position is evaluated.

        Returns:
            The player's pieces next to the opponent's queen minus the opponent's pieces
            next to the player's queen, counting only the top piece of each stack.
        """
        return self._queen_pressure(state, player) - self._queen_pressure(
            state, player.opponent
        )

    def _queen_pressure(self, state: GameState, attacker: Player) -> float:
        """Count the attacker's pieces next to the defender's queen.

        Args:
            state: The game state to inspect.
            attacker: The player whose top pieces next to the opponent's queen count.

        Returns:
            The number of stacks next to the defender's queen topped by the attacker, or
            0 if the defender's queen has not been placed.
        """
        queen_coord = state.get_queen_coord(attacker.opponent)
        if queen_coord is None:
            return 0.0

        return float(
            sum(
                state.is_occupied(c) and state.get_top_piece(c).owner == attacker
                for c in get_neighbors(queen_coord)
            )
        )

    def _material_on_board(self, state: GameState, player: Player) -> float:
        """Compare the value of the pieces each player has on the board.

        Args:
            state: The game state to evaluate.
            player: The player from whose perspective the position is evaluated.

        Returns:
            The value of the player's pieces on the board minus the opponent's.
        """
        scores = dict.fromkeys(Player, 0.0)
        for stack in state.board.values():
            for piece in stack:
                scores[piece.owner] += PIECE_VALUES.get(piece.type, 0.0)

        return scores[player] - scores[player.opponent]

    def _material_in_hand(self, state: GameState, player: Player) -> float:
        """Compare the value of the pieces each player still has in hand.

        Args:
            state: The game state to evaluate.
            player: The player from whose perspective the position is evaluated.

        Returns:
            The value of the player's pieces in hand minus the opponent's.
        """
        scores = dict.fromkeys(Player, 0.0)
        for owner, hand in state.hand.items():
            for piece_type, count in hand.items():
                scores[owner] += count * PIECE_VALUES.get(piece_type, 0.0)

        return scores[player] - scores[player.opponent]
