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
        queen_danger: Nonlinear queen crowding: squared occupied-neighbour counts.
        queen_escape: Legal queen escapes, excluding covered or pinned queens.
        pinned_material: Opponent minus own covered or articulation-pinned material.
        free_ants: Own minus opponent uncovered, unpinned ants after queen placement.
        beetle_control: Elevated beetle balance, doubled over an enemy queen.
        tempo: A bonus for the player to move.
        mobile_queen: Own minus opponent queens that can take a first step.
        mobile_beetle: Own minus opponent beetles that can move.
        mobile_grasshopper: Own minus opponent grasshoppers that can move.
        mobile_spider: Own minus opponent spiders that can take a first step.
        mobile_ant: Own minus opponent ants that can take a first step.
        placement_cells: Own minus opponent free cells to place a piece on.
        queen_locked_neighbors: Queen neighbours its owner cannot move away.
        alpha_beta: Whether the search prunes with alpha-beta.
        table_megabytes: The size of the transposition table in MB.
        aspiration_window: Initial score half-window, zero to disable aspiration.
        threads: Total negamax search threads sharing one table.
        principal_variation_search: Whether to scout later moves with a narrow window.
        table_deeper_hits: Reuse table entries searched deeper than needed.
        late_move_reductions: Moves searched at full depth before later ones are
            scouted a ply shallower, zero for none. Needs principal variation search.
        null_move_reduction: Extra depth reduction of a null move at scout nodes,
            zero for none.
        queen_attack_ordering: Order moves next to the enemy queen after killers.
        queen_threat_extension: Search a ply deeper once a queen has five neighbours.
        repetition_draws: Score a repeat of an earlier position as a draw.
        forced_move_extension: Search a forced move without using up depth.
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
        queen_danger: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        queen_escape: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        pinned_material: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        free_ants: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        beetle_control: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        tempo: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        mobile_queen: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        mobile_beetle: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        mobile_grasshopper: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        mobile_spider: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        mobile_ant: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        placement_cells: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        queen_locked_neighbors: Annotated[float, Field(allow_inf_nan=False)] = 0.0,
        alpha_beta: bool = True,
        table_megabytes: Annotated[int, Field(ge=0)] = 32,
        aspiration_window: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.0,
        threads: Annotated[int, Field(ge=1, le=256)] = 1,
        principal_variation_search: bool = False,
        table_deeper_hits: bool = False,
        late_move_reductions: Annotated[int, Field(ge=0, le=255)] = 0,
        null_move_reduction: Annotated[int, Field(ge=0, le=8)] = 0,
        queen_attack_ordering: bool = False,
        queen_threat_extension: bool = False,
        repetition_draws: bool = False,
        forced_move_extension: bool = False,
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
            queen_danger: Nonlinear queen crowding: squared occupied-neighbour counts.
            queen_escape: Legal queen escapes, excluding covered or pinned queens.
            pinned_material: Opponent minus own covered or articulation-pinned material.
            free_ants: Own minus opponent uncovered, unpinned ants after queen placement.
            beetle_control: Elevated beetle balance, doubled over an enemy queen.
            tempo: A bonus for the player to move.
            mobile_queen: Own minus opponent queens that can take a first step.
            mobile_beetle: Own minus opponent beetles that can move.
            mobile_grasshopper: Own minus opponent grasshoppers that can move.
            mobile_spider: Own minus opponent spiders that can take a first step.
            mobile_ant: Own minus opponent ants that can take a first step.
            placement_cells: Own minus opponent free cells to place a piece on.
            queen_locked_neighbors: Queen neighbours its owner cannot move away.
            alpha_beta: Whether to prune the search with alpha-beta, searching the best
                line of the previous depth first. It finds the same scores in far fewer
                nodes, but may choose another of several equally scored moves.
            table_megabytes: The size of the transposition table in MB, zero for none.
                `negamax` with alpha-beta uses it, and orders moves by killer moves and a
                history table too; it is kept between decisions of a match.
            aspiration_window: Initial score half-window, zero to disable aspiration.
            threads: Total negamax search threads sharing one table, at least one.
            principal_variation_search: Scout later moves before a full-window search.
            table_deeper_hits: Reuse table entries searched deeper than needed.
            late_move_reductions: Moves searched at full depth before later ones are
                scouted a ply shallower, zero for none. Needs principal variation search.
            null_move_reduction: Extra depth reduction of a null move at scout nodes,
                zero for none.
            queen_attack_ordering: Order moves next to the enemy queen after killers.
            queen_threat_extension: Search a ply deeper once a queen has five neighbours.
            repetition_draws: Score a repeat of an earlier position as a draw.
            forced_move_extension: Search a forced move without using up depth.
        """
        super().__init__(rules=rules, seed=seed)
        self.depth = depth
        self.queen_safety = queen_safety
        self.mobility = mobility
        self.positioning = positioning
        self.material_on_board = material_on_board
        self.material_in_hand = material_in_hand
        self.queen_danger = queen_danger
        self.queen_escape = queen_escape
        self.pinned_material = pinned_material
        self.free_ants = free_ants
        self.beetle_control = beetle_control
        self.tempo = tempo
        self.mobile_queen = mobile_queen
        self.mobile_beetle = mobile_beetle
        self.mobile_grasshopper = mobile_grasshopper
        self.mobile_spider = mobile_spider
        self.mobile_ant = mobile_ant
        self.placement_cells = placement_cells
        self.queen_locked_neighbors = queen_locked_neighbors
        self.alpha_beta = alpha_beta
        self.table_megabytes = table_megabytes
        self.aspiration_window = aspiration_window
        self.threads = threads
        self.principal_variation_search = principal_variation_search
        self.table_deeper_hits = table_deeper_hits
        self.late_move_reductions = late_move_reductions
        self.null_move_reduction = null_move_reduction
        self.queen_attack_ordering = queen_attack_ordering
        self.queen_threat_extension = queen_threat_extension
        self.repetition_draws = repetition_draws
        self.forced_move_extension = forced_move_extension
        self.searcher = Searcher(
            rules,
            algorithm=self.ALGORITHM,
            depth=depth,
            queen_safety=queen_safety,
            mobility=mobility,
            positioning=positioning,
            material_on_board=material_on_board,
            material_in_hand=material_in_hand,
            queen_danger=queen_danger,
            queen_escape=queen_escape,
            pinned_material=pinned_material,
            free_ants=free_ants,
            beetle_control=beetle_control,
            tempo=tempo,
            mobile_queen=mobile_queen,
            mobile_beetle=mobile_beetle,
            mobile_grasshopper=mobile_grasshopper,
            mobile_spider=mobile_spider,
            mobile_ant=mobile_ant,
            placement_cells=placement_cells,
            queen_locked_neighbors=queen_locked_neighbors,
            stop_check_interval=self.STOP_CHECK_INTERVAL,
            alpha_beta=alpha_beta,
            table_megabytes=table_megabytes,
            aspiration_window=aspiration_window,
            threads=threads,
            principal_variation_search=principal_variation_search,
            table_deeper_hits=table_deeper_hits,
            late_move_reductions=late_move_reductions,
            null_move_reduction=null_move_reduction,
            queen_attack_ordering=queen_attack_ordering,
            queen_threat_extension=queen_threat_extension,
            repetition_draws=repetition_draws,
            forced_move_extension=forced_move_extension,
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
