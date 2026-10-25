"""Command line interface for the `hive` package."""

import json
import logging
import time
from pathlib import Path
from typing import Annotated

import typer

from hive import __version__, bench
from hive.agents.factory import AgentSpec, InvalidAgentSpecError
from hive.bench import PerftSuite
from hive.engine.rules import Rules
from hive.engine.state import Move
from hive.match.records import DecisionRecord, MatchResult, Outcome
from hive.match.runner import MatchRunner
from hive.match.worker import DEFAULT_GRACE_S, WorkerError

logger = logging.getLogger(__name__)

app = typer.Typer(name="hive", no_args_is_help=True)


def _print_version(value: bool) -> None:
    """Print the package version and exit when `--version` is passed.

    Args:
        value: Whether `--version` was passed.

    Raises:
        typer.Exit: After printing the version.
    """
    if value:
        typer.echo(f"hive {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Hive engine, agents and tools."""


@app.command("play")
def play(
    white: Annotated[
        str,
        typer.Option(
            help="The white agent: a YAML spec file, or inline YAML such as `random` or "
            "`{kind: negamax, params: {depth: 2}}`."
        ),
    ],
    black: Annotated[
        str, typer.Option(help="The black agent, in the same form as `--white`.")
    ],
    budget: Annotated[
        float, typer.Option(min=0.0, help="The time budget of every decision in seconds.")
    ] = 1.0,
    max_turns: Annotated[
        int | None,
        typer.Option(
            min=1, help="The number of turns per player before the match stops."
        ),
    ] = 100,
    seed: Annotated[int, typer.Option(help="The match seed.")] = 0,
    grace: Annotated[
        float,
        typer.Option(
            min=0.0, help="The seconds an agent may take to return after it is stopped."
        ),
    ] = DEFAULT_GRACE_S,
    out: Annotated[
        Path | None, typer.Option(help="Write the match result as JSON to this file.")
    ] = None,
) -> None:
    """Play one timed match between two agents and log every decision and the result."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    runner = MatchRunner(
        rules=Rules(),
        white_spec=_parse_spec(white, "--white"),
        black_spec=_parse_spec(black, "--black"),
        budget_s=budget,
        max_turns=max_turns,
        seed=seed,
        grace_s=grace,
    )
    try:
        result = runner.run(on_decision=_log_decision)
    except WorkerError as e:
        logger.error("%s", e)
        raise typer.Exit(code=1) from e

    logger.info("%s", _describe_result(result))
    if out is not None:
        out.write_text(json.dumps(result.to_dict(), indent=2))
        logger.info("Wrote the match result to `%s`.", out)


def _parse_spec(value: str, option: str) -> AgentSpec:
    """Read an agent spec from a YAML file, or from inline YAML if no such file exists.

    Args:
        value: The path of a YAML spec file, or inline YAML.
        option: The name of the command line option, for error messages.

    Returns:
        The validated spec.

    Raises:
        typer.BadParameter: If the spec is invalid.
    """
    try:
        path = Path(value)
        if path.is_file():
            return AgentSpec.load(path)
        return AgentSpec.from_yaml(value)
    except InvalidAgentSpecError as e:
        raise typer.BadParameter(str(e), param_hint=option) from e


def _log_decision(decision: DecisionRecord) -> None:
    """Log a one line summary of a decision.

    Args:
        decision: The decision to summarise.
    """
    details = [decision.close_reason.value, f"{decision.elapsed_s:.2f} s"]
    info = decision.last_info or {}
    details += [
        f"{key} {info[key]}" for key in ("depth", "nodes", "score") if key in info
    ]
    if decision.illegal_submissions:
        details.append(f"{decision.illegal_submissions} illegal")
    if decision.worker_restarted:
        details.append("worker restarted")
    if decision.failure is not None:
        details.append(f"failure: {decision.failure}")
    logger.info(
        "%3d %-5s %s: %s (%s)",
        decision.ply,
        decision.player.name.lower(),
        decision.agent_label,
        _format_move(decision.move),
        ", ".join(details),
    )


def _describe_result(result: MatchResult) -> str:
    """Describe how a match ended, for example `white (negamax) wins after 27 plies`.

    Args:
        result: The played match.

    Returns:
        The outcome, the number of plies and the duration of the match.
    """
    plies = f"after {len(result.decisions)} plies in {result.duration_s:.1f} s"
    if result.outcome is Outcome.WIN and result.winner is not None:
        spec = result.spec(result.winner)
        return f"{result.winner.name.lower()} ({spec.label or spec.kind}) wins {plies}"
    if result.outcome is Outcome.DRAW:
        return f"Draw {plies}"
    return f"Stopped at the turn cap {plies}"


bench_app = typer.Typer(no_args_is_help=True, help="Benchmarks and correctness checks.")
app.add_typer(bench_app, name="bench")

DEFAULT_PERFT_SUITE = Path("tests/data/perft/base.json")


@bench_app.command("perft")
def bench_perft(
    depth: Annotated[int, typer.Option(min=0, help="The number of plies to walk.")],
    position: Annotated[
        str, typer.Option(help="The name of the position in the suite.")
    ] = "start",
    divide: Annotated[
        bool, typer.Option("--divide", help="Print the count below each first move.")
    ] = False,
    suite: Annotated[
        Path, typer.Option(help="The perft suite with the positions and rules.")
    ] = DEFAULT_PERFT_SUITE,
) -> None:
    """Run perft on a position and print nodes, seconds and nodes per second."""
    perft_suite = PerftSuite.load(suite)
    try:
        perft_position = perft_suite.position(position)
    except KeyError as e:
        raise typer.BadParameter(str(e.args[0]), param_hint="--position") from e

    rules = perft_suite.rules
    state = perft_position.state(rules)

    if divide and depth > 0:
        start = time.perf_counter()
        counts = bench.divide(state, rules, depth)
        seconds = time.perf_counter() - start
        for move, count in counts:
            typer.echo(f"{_format_move(move)}: {count}")
        result = bench.PerftResult(
            depth=depth, nodes=sum(count for _, count in counts), seconds=seconds
        )
    else:
        result = bench.timed_perft(state, rules, depth)
    typer.echo(
        f"position {position} depth {result.depth}: {result.nodes} nodes in "
        f"{result.seconds:.3f} s ({result.nodes_per_second:,.0f} nodes/s)"
    )

    expected = perft_position.counts.get(depth)
    if expected is not None and expected != result.nodes:
        typer.echo(f"mismatch: the reference count is {expected}", err=True)
        raise typer.Exit(code=1)


def _format_move(move: Move | None) -> str:
    """Format a move for the divide output, for example `ant (0, 0) -> (1, 0)`.

    Args:
        move: The move to format, or `None` for a pass.

    Returns:
        The piece type, the source coordinate for a movement and the target coordinate,
        or `pass` for a pass.
    """
    if move is None:
        return "pass"

    piece = move.piece_type.name.lower()
    if move.source_coord is None:
        return f"{piece} -> {move.target_coord}"

    return f"{piece} {move.source_coord} -> {move.target_coord}"
