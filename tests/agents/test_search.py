from typing import TypedDict

import pytest

from hive.agents.factory import AgentSpec, build_agent
from hive.agents.minimax import MinimaxAgent
from hive.agents.negamax import NegamaxAgent
from hive.agents.search import SEARCH_WIN_SCORE, SearchAgent
from hive.agents.testing import LocalTurnContext
from hive.engine.rules import Rules
from hive.engine.state import GameState, Move, Piece, PieceType, Player

SEARCH_AGENTS: list[type[SearchAgent]] = [MinimaxAgent, NegamaxAgent]


class Weights(TypedDict, total=False):
    queen_safety: float
    mobility: float
    positioning: float
    material_on_board: float
    material_in_hand: float


ALL_TERMS: Weights = {
    "queen_safety": 1.0,
    "mobility": 1.0,
    "positioning": 1.0,
    "material_on_board": 1.0,
    "material_in_hand": 1.0,
}


@pytest.fixture(scope="function")
def winning_position(rules: Rules) -> GameState:
    """Build a position where the white ant can surround the black queen in one move.

    The black queen at `(0, 0)` has five occupied neighbours, and the white ant at
    `(2, 0)` can slide around the white grasshopper to the last free neighbour `(0, 1)`.
    """
    white, black = Player.WHITE, Player.BLACK
    board = {
        (0, 0): [Piece(type=PieceType.QUEEN, owner=black)],
        (1, 0): [Piece(type=PieceType.GRASSHOPPER, owner=white)],
        (1, -1): [Piece(type=PieceType.QUEEN, owner=white)],
        (0, -1): [Piece(type=PieceType.BEETLE, owner=white)],
        (-1, 0): [Piece(type=PieceType.GRASSHOPPER, owner=black)],
        (-1, 1): [Piece(type=PieceType.SPIDER, owner=black)],
        (-2, 1): [Piece(type=PieceType.ANT, owner=black)],
        (2, 0): [Piece(type=PieceType.ANT, owner=white)],
    }

    return rules.from_board(board=board, current_player=white)


@pytest.mark.parametrize("agent_class", SEARCH_AGENTS)
def test_stops_at_depth_limit(
    agent_class: type[SearchAgent], rules: Rules, position: GameState
) -> None:
    """Test that every depth up to the limit is reported and the last move is final."""
    turn = LocalTurnContext()
    agent_class(rules=rules, seed=0, depth=2).think(state=position.copy(), turn=turn)

    assert [info["depth"] for info in turn.infos] == [1, 2]
    assert [s.final for s in turn.submissions] == [False, False, True]
    pv = turn.infos[-1]["pv"]
    assert isinstance(pv, list)
    assert turn.move is not None
    assert pv[0] == turn.move.to_json()


@pytest.mark.parametrize("depth", [1, 2])
def test_minimax_and_negamax_agree(depth: int, rules: Rules, position: GameState) -> None:
    """Test that both formulations find the same score, line and nodes without a table.

    Mobility generates moves at every leaf, which is too slow at depth 2, so it is left
    out here and covered by the evaluation tests instead.
    """
    weights: Weights = {**ALL_TERMS, "mobility": 0.0}
    infos = []

    for agent_class in SEARCH_AGENTS:
        turn = LocalTurnContext()
        agent_class(rules=rules, seed=0, depth=depth, table_megabytes=0, **weights).think(
            state=position.copy(), turn=turn
        )
        infos.append({key: turn.infos[-1][key] for key in ("score", "pv", "nodes")})

    assert infos[0] == infos[1]


@pytest.mark.parametrize("agent_class", SEARCH_AGENTS)
def test_forced_win_is_final(
    agent_class: type[SearchAgent], rules: Rules, winning_position: GameState
) -> None:
    """Test that an unbounded search closes the turn as soon as it finds a win."""
    turn = LocalTurnContext()
    turn.run(agent=agent_class(rules=rules, seed=0), state=winning_position)

    assert turn.closed
    assert turn.infos[-1]["depth"] == 1
    assert turn.infos[-1]["score"] == SEARCH_WIN_SCORE - 1
    assert turn.move == Move(
        piece_type=PieceType.ANT, source_coord=(2, 0), target_coord=(0, 1)
    )


@pytest.mark.parametrize("agent_class", SEARCH_AGENTS)
def test_exhausted_tree_is_final(agent_class: type[SearchAgent]) -> None:
    """Test that an unbounded search ends once every line reaches the turn limit draw."""
    rules = Rules(max_turns=1)
    turn = LocalTurnContext()
    turn.run(agent=agent_class(rules=rules, seed=0), state=rules.create_initial_state())

    assert turn.closed
    assert [info["depth"] for info in turn.infos] == [1, 2, 3]
    assert turn.infos[-1]["score"] == 0.0


@pytest.mark.parametrize("agent_class", SEARCH_AGENTS)
def test_single_legal_move_is_final(agent_class: type[SearchAgent], rules: Rules) -> None:
    """Test that a forced pass is submitted as final without searching."""
    state = rules.from_board(
        board={
            (0, 0): [Piece(type=PieceType.QUEEN, owner=Player.WHITE)],
            (1, 0): [Piece(type=PieceType.QUEEN, owner=Player.BLACK)],
            (-1, 0): [
                Piece(type=PieceType.ANT, owner=Player.WHITE),
                Piece(type=PieceType.BEETLE, owner=Player.BLACK),
            ],
        },
        current_player=Player.WHITE,
    )
    assert rules.legal_moves(state) == [None]

    turn = LocalTurnContext()
    turn.run(agent=agent_class(rules=rules, seed=0), state=state)

    assert [(s.move, s.final) for s in turn.submissions] == [(None, True)]
    assert not turn.infos


@pytest.mark.parametrize("term", list(ALL_TERMS))
def test_evaluation_terms_are_zero_sum(
    term: str, rules: Rules, position: GameState
) -> None:
    """Test that each term scores a position oppositely for the two players."""
    weights = {name: 1.0 if name == term else 0.0 for name in ALL_TERMS}
    agent = build_agent(
        spec=AgentSpec(kind="negamax", params=weights), rules=rules, seed=0
    )
    assert isinstance(agent, SearchAgent)

    assert agent.evaluate(state=position, player=Player.WHITE) == -agent.evaluate(
        state=position, player=Player.BLACK
    )


def test_evaluation_skips_zero_weights(rules: Rules, position: GameState) -> None:
    agent = NegamaxAgent(
        rules,
        seed=0,
        queen_safety=0.0,
        mobility=0.0,
        positioning=0.0,
        material_on_board=0.0,
        material_in_hand=0.0,
    )

    assert agent.evaluate(state=position, player=Player.WHITE) == 0.0


def test_evaluation_weighs_terms(rules: Rules, winning_position: GameState) -> None:
    """Test the weighted sum of hand-counted term values in the winning position."""
    agent = NegamaxAgent(
        rules,
        seed=0,
        queen_safety=1.0,
        positioning=10.0,
        material_on_board=100.0,
        material_in_hand=1000.0,
    )

    # Queen safety: the black queen has 5 occupied neighbours, the white queen 3.
    # Positioning: white tops 3 stacks next to the black queen, black tops 1 (its queen)
    # next to the white queen. Material on board: white 4 + 10 + 4 + 7, black 10 + 4 +
    # 3 + 7. Material in hand: white 4 + 2 * 4 + 2 * 3 + 2 * 7, black 2 * 4 + 2 * 4 + 3 +
    # 2 * 7.
    expected = 1.0 * (5 - 3) + 10.0 * (3 - 1) + 100.0 * (25 - 24) + 1000.0 * (32 - 33)
    assert agent.evaluate(state=winning_position, player=Player.WHITE) == expected


def test_passing_player_has_no_mobility(rules: Rules) -> None:
    """Test that moves are counted exactly and a forced pass counts as zero moves."""
    state = rules.from_board(
        board={
            (0, 0): [Piece(type=PieceType.QUEEN, owner=Player.WHITE)],
            (1, 0): [Piece(type=PieceType.QUEEN, owner=Player.BLACK)],
            (-1, 0): [
                Piece(type=PieceType.ANT, owner=Player.WHITE),
                Piece(type=PieceType.BEETLE, owner=Player.BLACK),
            ],
        },
        current_player=Player.WHITE,
    )
    state.current_player = Player.BLACK
    black_move_count = len(rules.legal_moves(state))
    state.current_player = Player.WHITE

    agent = NegamaxAgent(rules=rules, seed=0, queen_safety=0.0, mobility=1.0)

    assert rules.legal_moves(state) == [None]
    assert agent.evaluate(state=state, player=Player.WHITE) == -black_move_count
    assert state.current_player is Player.WHITE
