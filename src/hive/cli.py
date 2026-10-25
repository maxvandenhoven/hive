"""Command line interface for the `hive` package."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from hive import __version__, bench
from hive.agents.factory import AgentSpec, InvalidAgentSpecError
from hive.bench import PerftSuite
from hive.engine.rules import Rules
from hive.engine.state import Move
from hive.match.gauntlet import (
    GauntletConfig,
    GauntletReport,
    ScheduledMatch,
    default_gauntlet_jobs,
)
from hive.match.records import DecisionRecord, MatchOutcome, MatchResult
from hive.match.runner import MatchRunner
from hive.match.worker import DEFAULT_GRACE_S, AgentWorkerError

logger = logging.getLogger(__name__)

AGENT_OPTION_HELP = (
    "A YAML spec file, a preset name (such as `nm3`), or inline YAML such as `random` or "
    "`{kind: negamax, params: {depth: 2}}`."
)

app = typer.Typer(name="hive", no_args_is_help=True)


def print_version(value: bool) -> None:
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
            callback=print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Hive engine, agents and tools."""


@app.command("play")
def play(
    white: Annotated[str, typer.Option(help=f"The white agent: {AGENT_OPTION_HELP}")],
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
        white_spec=parse_agent_spec(value=white, option="--white"),
        black_spec=parse_agent_spec(value=black, option="--black"),
        budget_s=budget,
        max_turns=max_turns,
        seed=seed,
        grace_s=grace,
    )

    try:
        result = runner.run(decision_callback=log_decision)
    except AgentWorkerError as e:
        logger.error("%s", e)
        raise typer.Exit(code=1) from e

    logger.info("%s", describe_match_result(result))

    if out is not None:
        out.write_text(json.dumps(result.to_json(), indent=2))
        logger.info("Wrote the match result to `%s`.", out)


def parse_agent_spec(value: str, option: str) -> AgentSpec:
    """Read an agent spec from a YAML file, a preset name or inline YAML, in that order.

    Args:
        value: The path of a YAML spec file, the name of a preset, or inline YAML.
        option: The name of the command line option, for error messages.

    Returns:
        The validated spec.

    Raises:
        typer.BadParameter: If the spec is invalid.
    """
    try:
        return AgentSpec.resolve(value)
    except InvalidAgentSpecError as e:
        raise typer.BadParameter(str(e), param_hint=option) from e


def log_decision(decision: DecisionRecord) -> None:
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
        format_move(decision.move),
        ", ".join(details),
    )


def describe_match_result(result: MatchResult) -> str:
    """Describe how a match ended, for example `white (negamax) wins after 27 plies`.

    Args:
        result: The played match.

    Returns:
        The outcome, the number of plies and the duration of the match.
    """
    plies = f"after {len(result.decisions)} plies in {result.duration_s:.1f} s"

    if result.outcome is MatchOutcome.WIN and result.winner is not None:
        spec = result.spec(result.winner)
        return f"{result.winner.name.lower()} ({spec.display_label}) wins {plies}"

    if result.outcome is MatchOutcome.DRAW:
        return f"Draw {plies}"

    return f"Stopped at the turn cap {plies}"


@app.command("gauntlet")
def gauntlet(
    agents: Annotated[
        list[str],
        typer.Option(
            "--agent",
            help=f"A participant, given at least twice: {AGENT_OPTION_HELP}",
            show_default=False,
        ),
    ],
    games_per_pair: Annotated[
        int,
        typer.Option(
            min=2, help="The number of games between every pair, an even number."
        ),
    ] = 2,
    budget: Annotated[
        float, typer.Option(min=0.0, help="The time budget of every decision in seconds.")
    ] = 1.0,
    max_turns: Annotated[
        int | None,
        typer.Option(min=1, help="The number of turns per player before a match stops."),
    ] = 100,
    seed: Annotated[int, typer.Option(help="The gauntlet seed.")] = 0,
    jobs: Annotated[
        int | None,
        typer.Option(
            min=1,
            help="The number of matches played at the same time. Defaults to the "
            "number of CPUs, the most allowed without `--allow-oversubscribe`.",
            show_default=False,
        ),
    ] = None,
    allow_oversubscribe: Annotated[
        bool,
        typer.Option(
            "--allow-oversubscribe",
            help="Allow more jobs than the number of CPUs, which makes timed "
            "decisions unfair.",
        ),
    ] = False,
    grace: Annotated[
        float,
        typer.Option(
            min=0.0, help="The seconds an agent may take to return after it is stopped."
        ),
    ] = DEFAULT_GRACE_S,
    out: Annotated[
        Path | None,
        typer.Option(
            help="Write the report to this file. Defaults to "
            "`reports/gauntlet-<timestamp>.json`.",
            show_default=False,
        ),
    ] = None,
    replays: Annotated[
        bool,
        typer.Option(
            "--replays", help="Keep every move and decision of every match in the report."
        ),
    ] = False,
) -> None:
    """Play a timed round robin between agents and write a JSON report."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(agents) < 2:
        msg = "A gauntlet needs at least two agents."
        raise typer.BadParameter(msg, param_hint="--agent")

    max_jobs = default_gauntlet_jobs()

    if jobs is not None and jobs > max_jobs and not allow_oversubscribe:
        msg = (
            f"At most {max_jobs} matches fit the CPUs, which keeps timed decisions "
            "fair. Pass `--allow-oversubscribe` to run more."
        )
        raise typer.BadParameter(msg, param_hint="--jobs")

    try:
        config = GauntletConfig(
            participants=tuple(
                parse_agent_spec(value=value, option="--agent") for value in agents
            ),
            games_per_pair=games_per_pair,
            budget_s=budget,
            max_turns=max_turns,
            seed=seed,
            jobs=max_jobs if jobs is None else jobs,
            grace_s=grace,
            replays=replays,
        )
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e

    schedule_size = len(config.schedule())
    finished = 0

    def log_match(match: ScheduledMatch, result: MatchResult) -> None:
        nonlocal finished
        finished += 1
        logger.info(
            "[%d/%d] match %d, %s vs %s: %s",
            finished,
            schedule_size,
            match.index,
            result.white_spec.display_label,
            result.black_spec.display_label,
            describe_match_result(result),
        )

    logger.info(
        "Playing %d matches between %s, %d at a time.",
        schedule_size,
        ", ".join(config.labels),
        config.jobs,
    )

    try:
        report = config.run(match_callback=log_match)
    except AgentWorkerError as e:
        logger.error("%s", e)
        raise typer.Exit(code=1) from e

    if out is None:
        out = Path("reports") / f"gauntlet-{datetime.now():%Y%m%d-%H%M%S}.json"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_json(), indent=2))
    logger.info("\n%s\n", report.summary_table())

    flagged = [r.label for r in report.participants if r.decision_stats.flagged]

    if flagged:
        logger.warning(
            "Flagged for failures, overruns, restarts or missing moves: %s.",
            ", ".join(flagged),
        )

    logger.info(
        "Finished in %.1f s. Wrote the gauntlet report to `%s`.", report.duration_s, out
    )


@app.command("replay")
def replay(
    report: Annotated[
        Path, typer.Argument(help="A gauntlet report written with `--replays`.")
    ],
    match: Annotated[
        int, typer.Option(min=0, help="The index of the match in the report.")
    ],
    plot_dir: Annotated[
        Path | None,
        typer.Option(
            help="Draw the board after every move as SVG files in this directory "
            "(needs the `plotting` extra)."
        ),
    ] = None,
) -> None:
    """Log the moves and decisions of a match from a gauntlet report."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        result = GauntletReport.from_json(json.loads(report.read_text())).replay(match)
    except (OSError, ValueError) as e:
        raise typer.BadParameter(str(e), param_hint="REPORT") from e

    logger.info(
        "Match %d: %s (white) vs %s (black), seed %d, budget %.2f s",
        match,
        result.white_spec.display_label,
        result.black_spec.display_label,
        result.seed,
        result.budget_s,
    )

    for decision in result.decisions:
        log_decision(decision)

    logger.info("%s", describe_match_result(result))

    if plot_dir is not None:
        paths = write_board_svgs(result=result, directory=plot_dir)
        logger.info("Drew %d boards in `%s`.", len(paths), plot_dir)


def write_board_svgs(result: MatchResult, directory: Path) -> list[Path]:
    """Draw the board after every move of a match as SVG files.

    Args:
        result: The match to draw.
        directory: The directory for the files `ply-001.svg`, `ply-002.svg` and so on,
            created if needed.

    Returns:
        The written files, in order.

    Raises:
        typer.BadParameter: If the `plotting` extra is not installed.
    """
    try:
        from hive.plotting.svg import draw_board
    except ImportError as e:
        msg = "Drawing boards needs the `plotting` extra: `uv sync --extra plotting`."
        raise typer.BadParameter(msg, param_hint="--plot-dir") from e

    directory.mkdir(parents=True, exist_ok=True)
    paths = []

    for ply, state in enumerate(result.record.states()):
        if not state.board:
            continue

        path = directory / f"ply-{ply:03d}.svg"
        draw_board(state=state, title=f"Ply {ply}").save_svg(str(path))
        paths.append(path)

    return paths


def require_api_extra() -> None:
    """Check that the `api` extra is installed.

    Raises:
        typer.Exit: With code 1 and a hint if it is not.
    """
    try:
        import fastapi  # noqa: F401
    except ImportError as e:
        logger.error("This command needs the `api` extra: `uv sync --extra api`.")
        raise typer.Exit(code=1) from e


@app.command("serve", help="Serve the API, configured by `HIVE_` environment variables.")
def serve(
    host: Annotated[str, typer.Option(help="The address to listen on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535, help="The port.")] = 8000,
    reload: Annotated[
        bool, typer.Option("--reload", help="Restart the server when the code changes.")
    ] = False,
) -> None:
    """Serve the API, configured by `HIVE_` environment variables.

    Args:
        host: The address to listen on.
        port: The port to listen on.
        reload: Whether to restart the server when the code changes.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    require_api_extra()

    import uvicorn

    from hive.api.observability import logging_config
    from hive.api.settings import ApiSettings

    uvicorn.run(
        "hive.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_config=logging_config(ApiSettings().log_level),
        access_log=False,
    )


db_app = typer.Typer(no_args_is_help=True, help="Database schema migrations.")
app.add_typer(db_app, name="db")


@db_app.command(
    "upgrade", help="Migrate the database at `HIVE_DATABASE_URL` up to a revision."
)
def db_upgrade(
    revision: Annotated[
        str, typer.Option(help="The Alembic revision to migrate to.")
    ] = "head",
) -> None:
    """Migrate the database at `HIVE_DATABASE_URL` up to a revision.

    Args:
        revision: The Alembic revision to migrate to.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)
    require_api_extra()

    from hive.api.db.session import Database
    from hive.api.settings import ApiSettings

    database = Database.from_url(ApiSettings().database_url)

    try:
        database.upgrade(revision)
    finally:
        database.dispose()

    logger.info("Migrated the database to `%s`.", revision)


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
        counts = bench.divide(state=state, rules=rules, depth=depth)
        seconds = time.perf_counter() - start

        for move, count in counts:
            typer.echo(f"{format_move(move)}: {count}")

        result = bench.PerftResult(
            depth=depth, nodes=sum(count for _, count in counts), seconds=seconds
        )
    else:
        result = bench.timed_perft(state=state, rules=rules, depth=depth)

    typer.echo(
        f"position {position} depth {result.depth}: {result.nodes} nodes in "
        f"{result.seconds:.3f} s ({result.nodes_per_second:,.0f} nodes/s)"
    )

    expected = perft_position.counts.get(depth)

    if expected is not None and expected != result.nodes:
        typer.echo(f"mismatch: the reference count is {expected}", err=True)
        raise typer.Exit(code=1)


def format_move(move: Move | None) -> str:
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
