from hive_engine.rules.mobility import MobilityRule
from hive_engine.rules.movement import MovementRule
from hive_engine.rules.placement import PlacementRule
from hive_engine.rules.termination import TerminationRule
from hive_engine.state import GameState, Move, PieceType, Player


class Ruleset:
    """Class representing a set of rules for a Hive game.

    This class aggregates the different types of rules (movement, placement, mobility,
    termination) and provides methods to determine valid moves, placements, and check
    for game termination based on the current game state.
    """

    def __init__(
        self,
        mobility_rule: MobilityRule,
        movement_rules: dict[PieceType, MovementRule],
        placement_rule: PlacementRule,
        termination_rule: TerminationRule,
        piece_type_count: dict[PieceType, int],
        starting_player: Player = Player.WHITE,
    ) -> None:
        """Initialize a new ruleset.

        Parameters
        ----------
        mobility_rule : MobilityRule
            The rule that determines which pieces on the board are allowed to move.
        movement_rules : dict[PieceType, MovementRule]
            A mapping from each piece type to the rule that governs how that piece type
            moves on the board.
        placement_rule : PlacementRule
            The rule that determines where and which pieces are allowed to be placed.
        termination_rule : TerminationRule
            The rule that determines when the game ends and which player(s) win.
        piece_type_count : dict[PieceType, int]
            A mapping from each piece type to the number of copies each player receives
            at the start of the game.
        starting_player : Player
            The player who takes the first turn.

        Raises
        ------
        ValueError
            If the queen piece count is not exactly one, or if a piece type
            with a positive count has no corresponding movement rule.
        """
        self.mobility_rule = mobility_rule
        self.movement_rules = movement_rules
        self.placement_rule = placement_rule
        self.termination_rule = termination_rule
        self.piece_type_count = piece_type_count
        self.starting_player = starting_player

        # Validate that each player only gets one queen piece.
        if piece_type_count.get(PieceType.QUEEN, 0) != 1:
            msg = (
                "Each player must receive exactly one queen piece, but got count "
                f"`{piece_type_count.get(PieceType.QUEEN, 0)}`."
            )
            raise ValueError(msg)

        # Validate that every piece type in the config has a corresponding movement rule.
        for piece_type, count in piece_type_count.items():
            if count > 0 and piece_type not in movement_rules:
                msg = (
                    f"Missing movement rule for piece type `{piece_type.name}` with "
                    f"count `{count}`."
                )
                raise ValueError(msg)

    def create_initial_state(self) -> GameState:
        """Create the initial game state based on the ruleset configuration.

        This method initializes the game state with the starting player and the piece
        counts for each player as defined in the ruleset.

        Returns
        -------
        GameState
            The initial game state ready for play.
        """
        return GameState(
            starting_player=self.starting_player, piece_type_count=self.piece_type_count
        )

    def get_legal_placement_moves(self, state: GameState) -> list[Move]:
        """Get all legal placement moves for the current player.

        Combines each placeable coordinate with each placeable piece type to produce the
        full list of valid placement moves.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        list[Move]
            A list of all legal placement moves. Each move has `source_coord` set to
            `None`.
        """
        moves: list[Move] = []
        for coord in self.placement_rule.get_placeable_coords(state=state):
            for piece_type in self.placement_rule.get_placeable_piece_types(state=state):
                moves.append(
                    Move(piece_type=piece_type, source_coord=None, target_coord=coord)
                )
        return moves

    def get_legal_movement_moves(self, state: GameState) -> list[Move]:
        """Get all legal movement moves for the current player.

        Iterates over all movable pieces determined by the mobility rule, then queries
        each piece's movement rule for its reachable target
        coordinates.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        list[Move]
            A list of all legal movement moves.
        """
        moves: list[Move] = []
        for coord, piece_type in self.mobility_rule.get_movable_pieces(state=state):
            movement_rule = self.movement_rules[piece_type]
            for target_coord in movement_rule.get_target_coords(state=state, coord=coord):
                moves.append(
                    Move(
                        piece_type=piece_type,
                        source_coord=coord,
                        target_coord=target_coord,
                    )
                )
        return moves

    def get_legal_moves(self, state: GameState) -> list[Move | None]:
        """Get all legal moves for the current player, including a pass.

        Combines the results of `get_legal_placement_moves` and
        `get_legal_movement_moves`. If there are no legal moves, the returned list will
        contain only `None` to represent a pass.

        and always includes `None` as the first element to
        represent a pass move.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        list[Move | None]
            A list of all legal moves. May contain `None` if there are no legal moves,
            representing a pass. The remaining elements are placement and movement moves.
        """
        moves: list[Move | None] = []
        moves += self.get_legal_placement_moves(state=state)
        moves += self.get_legal_movement_moves(state=state)

        if not moves:
            return [None]

        return moves

    def get_winning_players(self, state: GameState) -> list[Player] | None:
        """Determine which players have won the game, if any.

        Delegates to the termination rule to check whether the game has ended and which
        players are the winners.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        list[Player] | None
            A list of winning players if the game has ended, or `None` if the game is
            still in progress. A list with multiple players indicates a draw.
        """
        return self.termination_rule.get_winning_players(state=state)

    def is_finished(self, state: GameState) -> bool:
        """Check whether the game has ended.

        Parameters
        ----------
        state : GameState
            The current game state.

        Returns
        -------
        bool
            `True` if the game has ended according to the termination rule, otherwise
            `False`.
        """
        return self.get_winning_players(state=state) is not None
