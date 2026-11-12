import json
from pathlib import Path
from typing import Any

import pytest

from hive.agents.factory import AgentSpec
from hive.bench import (
    ENGINE_BENCH_CASES,
    EngineBenchCase,
    EngineBenchMismatchError,
    EngineBenchReport,
    EngineBenchResult,
    EngineBenchSample,
    PerftBenchCase,
    PerftResult,
    PerftSuite,
    SearchBenchCase,
    divide,
    perft,
    timed_perft,
)
from hive.engine.grid import get_neighbors
from hive.engine.rules import Rules
from hive.engine.state import GameBoard, GameState, Move, Piece, PieceType, Player


def snapshot(state: GameState) -> tuple[Any, ...]:
    """Capture every field of a state for comparison."""
    return (
        {coord: list(stack) for coord, stack in state.board.items()},
        state.current_player,
        state.current_ply,
        {player: dict(hand) for player, hand in state.hand.items()},
        dict(state.queen_coord),
    )


SUITE = PerftSuite.load(Path(__file__).parent / "data" / "perft" / "base.json")


def write_suite(path: Path, positions: list[dict[str, Any]], **rules: Any) -> Path:
    """Write a perft suite file with the given positions and rules."""
    path.write_text(json.dumps({"rules": rules, "positions": positions}))
    return path


@pytest.fixture(scope="function")
def rules() -> Rules:
    """Build the default rules."""
    return Rules()


@pytest.fixture(scope="function")
def finished_state(rules: Rules) -> GameState:
    """Build a state where the white queen is surrounded by six black pieces."""
    black_types = [PieceType.ANT] * 3 + [PieceType.SPIDER] * 2 + [PieceType.GRASSHOPPER]
    board: GameBoard = {(0, 0): [Piece(type=PieceType.QUEEN, owner=Player.WHITE)]}

    for coord, piece_type in zip(get_neighbors((0, 0)), black_types, strict=True):
        board[coord] = [Piece(type=piece_type, owner=Player.BLACK)]

    return rules.from_board(board=board, current_player=Player.WHITE)


class TestPerft:
    def test_depth_zero(self, rules: Rules) -> None:
        assert perft(state=rules.create_initial_state(), rules=rules, depth=0) == 1

    def test_counts_leaves(self, rules: Rules) -> None:
        state = rules.create_initial_state()

        assert perft(state=state, rules=rules, depth=1) == len(rules.legal_moves(state))

    def test_restores_state(self, rules: Rules) -> None:
        state = rules.create_initial_state()
        before = snapshot(state)

        perft(state=state, rules=rules, depth=3)

        assert snapshot(state) == before

    def test_finished_game_has_no_moves(
        self, rules: Rules, finished_state: GameState
    ) -> None:
        assert perft(state=finished_state, rules=rules, depth=0) == 1
        assert perft(state=finished_state, rules=rules, depth=2) == 0


class TestDivide:
    def test_sums_to_perft(self, rules: Rules) -> None:
        state = rules.create_initial_state()
        counts = divide(state=state, rules=rules, depth=3)

        assert [move for move, _ in counts] == rules.legal_moves(state)
        assert sum(count for _, count in counts) == perft(
            state=state, rules=rules, depth=3
        )

    def test_finished_game(self, rules: Rules, finished_state: GameState) -> None:
        assert divide(state=finished_state, rules=rules, depth=1) == []

    def test_depth_below_one(self, rules: Rules) -> None:
        with pytest.raises(ValueError, match="at least `1`"):
            divide(state=rules.create_initial_state(), rules=rules, depth=0)


class TestTimedPerft:
    def test_result(self, rules: Rules) -> None:
        result = timed_perft(state=rules.create_initial_state(), rules=rules, depth=2)

        assert result.depth == 2
        assert result.nodes == perft(
            state=rules.create_initial_state(), rules=rules, depth=2
        )
        assert result.seconds > 0
        assert result.nodes_per_second == result.nodes / result.seconds

    def test_nodes_per_second_without_time(self) -> None:
        assert PerftResult(depth=1, nodes=4, seconds=0.0).nodes_per_second == 0.0


class TestPerftSuite:
    def test_load(self, tmp_path: Path) -> None:
        moves = [
            {"piece": "spider", "from": None, "to": [0, 0]},
            {"piece": "ant", "from": None, "to": [1, 0]},
        ]
        legal_moves = [None, {"piece": "beetle", "from": [0, 0], "to": [1, 0]}]
        path = write_suite(
            path=tmp_path / "suite.json",
            positions=[
                {
                    "name": "p",
                    "moves": moves,
                    "counts": {"0": 1},
                    "legal_moves": legal_moves,
                }
            ],
            starting_player="black",
            allow_queen_first_turn=False,
        )

        suite = PerftSuite.load(path)
        position = suite.position("p")

        assert suite.rules == Rules(
            starting_player=Player.BLACK, allow_queen_first_turn=False
        )
        assert position.moves == [
            Move(piece_type=PieceType.SPIDER, source_coord=None, target_coord=(0, 0)),
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0)),
        ]
        assert position.counts == {0: 1}
        assert position.legal_moves == [
            None,
            Move(piece_type=PieceType.BEETLE, source_coord=(0, 0), target_coord=(1, 0)),
        ]

    def test_position_state(self, tmp_path: Path) -> None:
        moves = [{"piece": "spider", "from": None, "to": [0, 0]}]
        path = write_suite(
            path=tmp_path / "suite.json",
            positions=[{"name": "p", "moves": moves, "counts": {}}],
        )

        state = PerftSuite.load(path).position("p").state(Rules())

        assert state.current_ply == 1
        assert state.get_top_piece((0, 0)).type is PieceType.SPIDER
        assert PerftSuite.load(path).position("p").legal_moves is None

    def test_unknown_position(self, tmp_path: Path) -> None:
        suite = PerftSuite.load(write_suite(path=tmp_path / "suite.json", positions=[]))

        with pytest.raises(KeyError, match="Unknown perft position `missing`"):
            suite.position("missing")

    def test_unknown_piece(self, tmp_path: Path) -> None:
        moves = [{"piece": "ladybug", "from": None, "to": [0, 0]}]
        path = write_suite(
            path=tmp_path / "suite.json",
            positions=[{"name": "p", "moves": moves, "counts": {}}],
        )

        with pytest.raises(ValueError, match=r"positions\.0\.moves\.0\.piece"):
            PerftSuite.load(path)

    def test_unknown_player(self, tmp_path: Path) -> None:
        path = write_suite(
            path=tmp_path / "suite.json", positions=[], starting_player="red"
        )

        with pytest.raises(ValueError, match=r"rules\.starting_player"):
            PerftSuite.load(path)


class TestPerftPosition:
    def test_expected_count_prefers_reference(self, tmp_path: Path) -> None:
        path = write_suite(
            path=tmp_path / "suite.json",
            positions=[
                {
                    "name": "p",
                    "moves": [],
                    "counts": {"1": 4},
                    "engine_counts": {"1": 5, "2": 96},
                }
            ],
        )
        position = PerftSuite.load(path).position("p")

        assert position.expected_count(1) == 4
        assert position.expected_count(2) == 96
        assert position.expected_count(3) is None


class TestEngineBenchCase:
    def test_perft_case(self) -> None:
        case = PerftBenchCase(name="p", position="start", depth=2, nodes=96)

        sample = case.sample(SUITE)

        assert sample.nodes == 96
        assert sample.seconds > 0

    def test_search_case(self) -> None:
        case = SearchBenchCase(
            name="s",
            position="beetle_moves",
            agent=AgentSpec(kind="negamax", params={"depth": 1}),
            nodes=6,
        )

        assert case.sample(SUITE).nodes == 6

    def test_mismatch(self) -> None:
        case = PerftBenchCase(name="p", position="start", depth=2, nodes=95)

        with pytest.raises(EngineBenchMismatchError, match="`96` nodes, but `95`"):
            case.sample(SUITE)

    def test_search_case_needs_search_agent(self) -> None:
        case = SearchBenchCase(
            name="s", position="start", agent=AgentSpec(kind="random"), nodes=0
        )

        with pytest.raises(ValueError, match="needs a search agent"):
            case.sample(SUITE)

    @pytest.mark.parametrize(
        "case", [pytest.param(case, id=case.name) for case in ENGINE_BENCH_CASES]
    )
    def test_cases_match_suite(self, case: EngineBenchCase) -> None:
        position = SUITE.position(case.position)

        if isinstance(case, PerftBenchCase):
            assert position.expected_count(case.depth) == case.nodes

    def test_case_names_are_unique(self) -> None:
        names = [case.name for case in ENGINE_BENCH_CASES]

        assert len(names) == len(set(names))


class TestEngineBenchResult:
    def test_statistics(self) -> None:
        case = PerftBenchCase(name="p", position="start", depth=2, nodes=96)
        result = EngineBenchResult(
            case=case,
            samples=[
                EngineBenchSample(nodes=96, seconds=seconds)
                for seconds in [3.0, 1.0, 2.0]
            ],
        )

        assert result.median_seconds == 2.0
        assert result.nodes_per_second == 48.0
        assert result.spread == 1.0


class TestEngineBenchReport:
    def test_measure(self) -> None:
        cases = [
            PerftBenchCase(name="a", position="start", depth=1, nodes=4),
            PerftBenchCase(name="b", position="start", depth=2, nodes=96),
        ]

        report = EngineBenchReport.measure(cases=cases, suite=SUITE, repeat=3)

        assert [result.case for result in report.results] == cases
        assert [len(result.samples) for result in report.results] == [3, 3]

    def test_repeat_below_one(self) -> None:
        with pytest.raises(ValueError, match="at least `1` run"):
            EngineBenchReport.measure(cases=[], suite=SUITE, repeat=0)

    def test_geometric_mean(self) -> None:
        results = [
            EngineBenchResult(
                case=PerftBenchCase(name=name, position="start", depth=1, nodes=nodes),
                samples=[EngineBenchSample(nodes=nodes, seconds=1.0)],
            )
            for name, nodes in [("a", 10), ("b", 1000)]
        ]

        assert EngineBenchReport(results=results).nodes_per_second == pytest.approx(100)
