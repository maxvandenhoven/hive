"""Perft and benchmarks for the engine.

Perft walks the full game tree from a position to a fixed depth and counts the leaf
positions. The counts depend only on the rules, so they prove correctness against
reference engines, and the time taken measures raw engine speed. The engine benchmark
repeats a fixed set of perft walks and search decisions and reports the median speed of
each, the objective of the engine speed work in `docs/plans/performance.md`.
"""

import json
import math
import statistics
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, override

from pydantic import ConfigDict

from hive.agents.factory import AgentSpec, build_agent
from hive.agents.search import SearchAgent
from hive.agents.testing import LocalTurnContext
from hive.engine.codec import JsonCodec
from hive.engine.rules import Rules
from hive.engine.state import GameState, Move


def perft(state: GameState, rules: Rules, depth: int) -> int:
    """Count the leaf positions of the game tree from a state to a fixed depth.

    A finished game has no moves, so it counts as a leaf at depth zero and contributes
    nothing at greater depths. This matches the reference engines.

    Args:
        state: The game state to start from. It is modified during the walk, but
            restored before returning.
        rules: The rules that generate the moves.
        depth: The number of plies to walk.

    Returns:
        The number of positions reached after exactly `depth` plies.
    """
    if depth == 0:
        return 1

    if rules.is_finished(state):
        return 0

    count = 0

    for move in rules.legal_moves(state):
        state.apply_move(move)
        count += perft(state=state, rules=rules, depth=depth - 1)
        state.undo_move(move)

    return count


def divide(state: GameState, rules: Rules, depth: int) -> list[tuple[Move | None, int]]:
    """Count the leaf positions below each legal move of a state.

    Comparing these counts with a reference localises a perft mismatch to one move.

    Args:
        state: The game state to start from. It is modified during the walk, but
            restored before returning.
        rules: The rules that generate the moves.
        depth: The number of plies to walk, including the first move. Must be at least
            one.

    Returns:
        Each legal move with the perft count of the position after it at `depth - 1`,
        in the order of `legal_moves`. Empty if the game is finished.

    Raises:
        ValueError: If `depth` is less than one.
    """
    if depth < 1:
        msg = f"The divide depth must be at least `1`, but got `{depth}`."
        raise ValueError(msg)

    if rules.is_finished(state):
        return []

    counts: list[tuple[Move | None, int]] = []

    for move in rules.legal_moves(state):
        state.apply_move(move)
        counts.append((move, perft(state=state, rules=rules, depth=depth - 1)))
        state.undo_move(move)

    return counts


@dataclass(frozen=True, slots=True)
class PerftResult:
    """The result of a timed perft run.

    Attributes:
        depth: The number of plies walked.
        nodes: The number of leaf positions counted.
        seconds: The wall clock time the walk took.
    """

    depth: int
    nodes: int
    seconds: float

    @property
    def nodes_per_second(self) -> float:
        """Get the number of leaf positions counted per second.

        Returns:
            `nodes` divided by `seconds`, or `0.0` if no time was measured.
        """
        return self.nodes / self.seconds if self.seconds > 0 else 0.0


def timed_perft(state: GameState, rules: Rules, depth: int) -> PerftResult:
    """Run perft and measure how long it takes.

    Args:
        state: The game state to start from. It is modified during the walk, but
            restored before returning.
        rules: The rules that generate the moves.
        depth: The number of plies to walk.

    Returns:
        The depth, node count and wall clock time of the walk.
    """
    start = time.perf_counter()
    nodes = perft(state=state, rules=rules, depth=depth)
    seconds = time.perf_counter() - start

    return PerftResult(depth=depth, nodes=nodes, seconds=seconds)


@dataclass(frozen=True, slots=True)
class PerftPosition(JsonCodec):
    """A named perft position with reference counts.

    Attributes:
        name: The name of the position, for example `start`.
        moves: The moves that lead to the position from the initial state.
        counts: The reference perft count per depth.
        engine_counts: Perft counts per depth produced by this engine where no reference
            count is known. They catch changes in behaviour, not rule bugs.
        legal_moves: The reference legal moves of the position, or `None` if only the
            counts are known.
    """

    # The suite file also holds where the reference counts come from.
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str
    moves: list[Move | None]
    counts: dict[int, int]
    engine_counts: dict[int, int] = field(default_factory=dict)
    legal_moves: list[Move | None] | None = None

    def expected_count(self, depth: int) -> int | None:
        """Get the stored count at a depth, preferring a reference count.

        Args:
            depth: The perft depth.

        Returns:
            The reference count, else the count of this engine, or `None` if neither is
            stored.
        """
        return self.counts.get(depth, self.engine_counts.get(depth))

    def state(self, rules: Rules) -> GameState:
        """Create the game state of the position by replaying its moves.

        Args:
            rules: The rules the moves are checked against.

        Returns:
            The game state after all moves.

        Raises:
            IllegalMoveError: If a move is not legal under `rules`.
        """
        state = rules.create_initial_state()

        for move in self.moves:
            rules.apply_checked_move(state=state, move=move)

        return state


@dataclass(frozen=True, slots=True)
class PerftSuite(JsonCodec):
    """A set of perft positions with the rules their reference counts were made with.

    Attributes:
        rules: The rules matching the reference engine.
        positions: The positions, in file order.
    """

    # The suite file also holds where the reference counts come from.
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    rules: Rules
    positions: list[PerftPosition]

    @classmethod
    def load(cls, path: Path) -> "PerftSuite":
        """Load a perft suite from a JSON file.

        The file holds the JSON form of the suite: the `rules` (missing fields keep their
        default) and a list of `positions`, each with a `name`, a list of `moves`,
        `counts` keyed by depth and optionally `engine_counts` and `legal_moves`. Other
        keys, such as the `source` of the reference counts, are ignored.

        Args:
            path: The path of the JSON file.

        Returns:
            The suite described by the file.

        Raises:
            pydantic.ValidationError: If the file does not describe a valid suite.
        """
        return cls.from_json(json.loads(path.read_text()))

    def position(self, name: str) -> PerftPosition:
        """Get a position by name.

        Args:
            name: The name of the position.

        Returns:
            The position with the given name.

        Raises:
            KeyError: If no position has the given name.
        """
        for position in self.positions:
            if position.name == name:
                return position

        msg = f"Unknown perft position `{name}`."
        raise KeyError(msg)


@dataclass(frozen=True, slots=True)
class EngineBenchSample:
    """One timed run of an engine benchmark case.

    Attributes:
        nodes: The number of nodes the run counted or visited.
        seconds: The wall clock time of the run.
    """

    nodes: int
    seconds: float


class EngineBenchMismatchError(ValueError):
    """Raised when a benchmark run visits a different number of nodes than expected."""


@dataclass(frozen=True, slots=True)
class EngineBenchCase(ABC):
    """A fixed workload of the engine benchmark, started from a perft suite position.

    Every run of a case visits the same nodes, so the node count checks that a speedup
    did not change what the engine does, and the time measures how fast it does it.

    Attributes:
        name: The name of the case in reports.
        position: The name of the suite position the case starts from.
        nodes: The number of nodes every run must count or visit.
    """

    name: str
    position: str
    nodes: int

    @abstractmethod
    def run(self, state: GameState, rules: Rules) -> EngineBenchSample:
        """Run the workload once and time it.

        Args:
            state: The state of the position, which the run may modify.
            rules: The rules of the suite.

        Returns:
            The number of nodes and the seconds of the timed part of the run.
        """

    def sample(self, suite: PerftSuite) -> EngineBenchSample:
        """Run the workload once from a fresh state of the position and check the nodes.

        Args:
            suite: The suite with the position and the rules.

        Returns:
            The number of nodes and the seconds of the run.

        Raises:
            EngineBenchMismatchError: If the run visits a different number of nodes than
                `nodes`.
        """
        state = suite.position(self.position).state(suite.rules)
        sample = self.run(state=state, rules=suite.rules)

        if sample.nodes != self.nodes:
            msg = (
                f"Benchmark case `{self.name}` visited `{sample.nodes}` nodes, but "
                f"`{self.nodes}` are expected."
            )
            raise EngineBenchMismatchError(msg)

        return sample


@dataclass(frozen=True, slots=True)
class PerftBenchCase(EngineBenchCase):
    """A benchmark case that runs perft, which measures move generation, apply and undo.

    Attributes:
        depth: The number of plies to walk.
    """

    depth: int

    @override
    def run(self, state: GameState, rules: Rules) -> EngineBenchSample:
        """Run perft once and time it.

        Args:
            state: The state of the position, which is restored afterwards.
            rules: The rules of the suite.

        Returns:
            The number of leaf positions and the seconds of the walk.
        """
        result = timed_perft(state=state, rules=rules, depth=self.depth)
        return EngineBenchSample(nodes=result.nodes, seconds=result.seconds)


@dataclass(frozen=True, slots=True)
class NativePerftBenchCase(EngineBenchCase):
    """A benchmark case that runs perft entirely in the Rust core (`Rules.perft`).

    It applies and undoes every leaf like `PerftBenchCase`, but without the Python loop,
    so it measures the engine itself rather than the engine through the bindings.

    Attributes:
        depth: The number of plies to walk.
    """

    depth: int

    @override
    def run(self, state: GameState, rules: Rules) -> EngineBenchSample:
        """Run the native perft once and time it.

        Args:
            state: The state of the position, which is restored afterwards.
            rules: The rules of the suite.

        Returns:
            The number of leaf positions and the seconds of the walk.
        """
        start = time.perf_counter()
        nodes = rules.perft(state=state, depth=self.depth)
        seconds = time.perf_counter() - start

        return EngineBenchSample(nodes=nodes, seconds=seconds)


@dataclass(frozen=True, slots=True)
class SearchBenchCase(EngineBenchCase):
    """A benchmark case that makes one search decision, which adds evaluation to perft.

    Attributes:
        agent: The search agent, which needs a `depth` limit so every run visits the same
            nodes.
    """

    agent: AgentSpec

    @override
    def run(self, state: GameState, rules: Rules) -> EngineBenchSample:
        """Make one decision with the agent and time it, without building the agent.

        Args:
            state: The state of the position, which is restored afterwards.
            rules: The rules of the suite.

        Returns:
            The number of nodes the search visited and the seconds of the decision.

        Raises:
            ValueError: If `agent` is not a search agent.
        """
        agent = build_agent(spec=self.agent, rules=rules, seed=0)

        if not isinstance(agent, SearchAgent):
            msg = f"Benchmark case `{self.name}` needs a search agent, not `{agent}`."
            raise ValueError(msg)

        start = time.perf_counter()
        agent.think(state=state, turn=LocalTurnContext())
        seconds = time.perf_counter() - start

        return EngineBenchSample(nodes=agent.nodes, seconds=seconds)


ENGINE_BENCH_CASES: list[EngineBenchCase] = [
    PerftBenchCase(name="perft-start-5", position="start", depth=5, nodes=516_240),
    PerftBenchCase(name="perft-ant-3", position="ant_moves", depth=3, nodes=37_589),
    PerftBenchCase(name="perft-long-3", position="long_hive", depth=3, nodes=149_512),
    SearchBenchCase(
        name="negamax-long-3",
        position="long_hive",
        agent=AgentSpec(kind="negamax", params={"depth": 3}),
        nodes=153_360,
    ),
    SearchBenchCase(
        name="mobility-ant-2",
        position="ant_moves",
        agent=AgentSpec(kind="negamax", params={"depth": 2, "mobility": 1.0}),
        nodes=946,
    ),
    NativePerftBenchCase(
        name="perft-start-6-native", position="start", depth=6, nodes=12_219_480
    ),
    NativePerftBenchCase(
        name="perft-ant-4-native", position="ant_moves", depth=4, nodes=2_729_747
    ),
    NativePerftBenchCase(
        name="perft-long-4-native", position="long_hive", depth=4, nodes=11_797_660
    ),
    SearchBenchCase(
        name="negamax-long-4",
        position="long_hive",
        agent=AgentSpec(kind="negamax", params={"depth": 4}),
        nodes=12_102_433,
    ),
    SearchBenchCase(
        name="mobility-ant-3",
        position="ant_moves",
        agent=AgentSpec(kind="negamax", params={"depth": 3, "mobility": 1.0}),
        nodes=39_464,
    ),
]
"""The fixed cases of `hive bench engine`.

The first five were each about one second at the WP 27 baseline. The start position
measures placements. `ant_moves` and `long_hive` from the perft suite are large hives with
many ant, spider and beetle moves, where articulation points and slide checks dominate.
The search cases add a negamax decision with the default evaluation and one with the
mobility term, which generates the moves of both players at every leaf. Since the Rust
core (WP 44 and 45), the perft cases measure the engine through the Python bindings and
the search cases run in Rust. The native perft cases walk deeper entirely in Rust, and the
deeper search cases take long enough to time the Rust search reliably.
"""


@dataclass(frozen=True, slots=True)
class EngineBenchResult:
    """The repeated runs of one engine benchmark case.

    Attributes:
        case: The case.
        samples: The runs, in the order they were made.
    """

    case: EngineBenchCase
    samples: list[EngineBenchSample]

    @property
    def median_seconds(self) -> float:
        """Get the median wall clock time of the runs.

        Returns:
            The median of the seconds of every run.
        """
        return statistics.median(sample.seconds for sample in self.samples)

    @property
    def nodes_per_second(self) -> float:
        """Get the speed of the median run.

        Returns:
            The nodes of the case divided by the median seconds.
        """
        return self.case.nodes / self.median_seconds

    @property
    def spread(self) -> float:
        """Get the spread of the runs relative to the median, a measure of noise.

        Returns:
            The slowest minus the fastest run, divided by the median run.
        """
        seconds = [sample.seconds for sample in self.samples]
        return (max(seconds) - min(seconds)) / self.median_seconds


@dataclass(frozen=True, slots=True)
class EngineBenchReport:
    """The results of an engine benchmark over several cases.

    Attributes:
        results: The result of every case, in the order of the cases.
    """

    results: list[EngineBenchResult]

    @classmethod
    def measure(
        cls, cases: Sequence[EngineBenchCase], suite: PerftSuite, repeat: int
    ) -> "EngineBenchReport":
        """Run every case `repeat` times.

        The cases take turns, one run each per round, so a slow phase of the machine
        affects every case a little rather than one case a lot.

        Args:
            cases: The cases to run.
            suite: The suite with the positions and the rules.
            repeat: The number of runs per case, at least one.

        Returns:
            The runs of every case.

        Raises:
            ValueError: If `repeat` is less than one.
        """
        if repeat < 1:
            msg = f"The benchmark needs at least `1` run per case, but got `{repeat}`."
            raise ValueError(msg)

        samples: list[list[EngineBenchSample]] = [[] for _ in cases]

        for _ in range(repeat):
            for case, case_samples in zip(cases, samples, strict=True):
                case_samples.append(case.sample(suite))

        return cls(
            results=[
                EngineBenchResult(case=case, samples=case_samples)
                for case, case_samples in zip(cases, samples, strict=True)
            ]
        )

    @property
    def nodes_per_second(self) -> float:
        """Get the overall speed, which weighs a relative speedup of every case equally.

        Returns:
            The geometric mean of the nodes per second of every case.
        """
        return math.exp(
            statistics.mean(math.log(result.nodes_per_second) for result in self.results)
        )
