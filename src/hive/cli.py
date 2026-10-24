"""Command line interface for the `hive` package."""

from typing import Annotated

import typer

from hive import __version__

app = typer.Typer(name="hive", no_args_is_help=True)


def _print_version(value: bool) -> None:
    """Print the package version and exit when `--version` is passed."""
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
