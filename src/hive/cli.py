"""Command line interface for the `hive` package."""

import time
from pathlib import Path
from typing import Annotated

import typer

from hive import __version__, bench
from hive.bench import PerftSuite
from hive.engine.state import Move

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
