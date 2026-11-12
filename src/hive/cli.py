"""Command line interface for the `hive` package."""

import cProfile
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from pydantic import ValidationError

from hive import __version__, bench
from hive.agents.factory import AgentSpec, InvalidAgentSpecError
from hive.bench import PerftSuite
from hive.data.scenes import SCENE_SCHEMA_PATH, Scene, ScenesConfig
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

if TYPE_CHECKING:
    from hive.api.settings import DatabaseSettings

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


@app.callback(help="Hive engine, agents and tools.")
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
    """Hive engine, agents and tools.

    Args:
        version: Whether `--version` was passed, handled eagerly by `print_version`.
    """


@app.command(
    "play",
    help="Play one timed match between two agents and log every decision and the result.",
)
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
    """Play one timed match between two agents and log every decision and the result.

    Args:
        white: The white agent as a spec file, a preset name or inline YAML.
        black: The black agent, in the same form as `white`.
        budget: The time budget of every decision in seconds.
        max_turns: The number of turns per player before the match stops, or `None`
            for no cap.
        seed: The match seed.
        grace: The seconds an agent may take to return after it is stopped.
        out: The file to write the match result to as JSON, or `None` to not write it.

    Raises:
        typer.BadParameter: If an agent spec is invalid.
        typer.Exit: With code 1 if an agent worker fails.
    """
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


@app.command(
    "gauntlet", help="Play a timed round robin between agents and write a JSON report."
)
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
    """Play a timed round robin between agents and write a JSON report.

    Args:
        agents: The participants, at least two, each as a spec file, a preset name or
            inline YAML.
        games_per_pair: The number of games between every pair, an even number.
        budget: The time budget of every decision in seconds.
        max_turns: The number of turns per player before a match stops, or `None` for
            no cap.
        seed: The gauntlet seed.
        jobs: The number of matches played at the same time, or `None` for the number
            of CPUs.
        allow_oversubscribe: Whether to allow more jobs than the number of CPUs.
        grace: The seconds an agent may take to return after it is stopped.
        out: The report file, or `None` for `reports/gauntlet-<timestamp>.json`.
        replays: Whether to keep every move and decision of every match in the report.

    Raises:
        typer.BadParameter: If there are fewer than two agents, a spec is invalid, too
            many jobs are asked for, or the configuration is invalid.
        typer.Exit: With code 1 if an agent worker fails.
    """
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


@app.command(
    "replay", help="Log the moves and decisions of a match from a gauntlet report."
)
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
    """Log the moves and decisions of a match from a gauntlet report.

    Args:
        report: A gauntlet report written with `--replays`.
        match: The index of the match in the report.
        plot_dir: The directory to draw the board after every move in as SVG files, or
            `None` to not draw them.

    Raises:
        typer.BadParameter: If the report cannot be read or has no such match, or the
            `plotting` extra is missing when drawing boards.
    """
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


def load_settings[S: DatabaseSettings](kind: type[S]) -> S:
    """Read settings from `HIVE_` environment variables and `.env`.

    Args:
        kind: The settings class, `ApiSettings` or the smaller `DatabaseSettings`.

    Returns:
        The settings.

    Raises:
        typer.Exit: With code 1 and the missing or invalid settings if they do not
            validate.
    """
    try:
        return kind()
    except ValidationError as e:
        logger.error(
            "Invalid settings; set `HIVE_` environment variables or create `.env` "
            "from `.env.example`.\n%s",
            e,
        )
        raise typer.Exit(code=1) from e


SERVE_GRACEFUL_SHUTDOWN_S = 5
"""The seconds `hive serve` waits for open requests, such as thinking streams, before it
closes them on shutdown or reload."""


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

    settings = load_settings(ApiSettings)

    uvicorn.run(
        "hive.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_config=logging_config(settings.log_level),
        timeout_graceful_shutdown=SERVE_GRACEFUL_SHUTDOWN_S,
    )


@app.command(
    "openapi", help="Write the OpenAPI schema of the API as JSON, without serving it."
)
def openapi(
    output: Annotated[Path, typer.Option(help="The JSON file to write.")],
) -> None:
    """Write the OpenAPI schema of the API as JSON, without serving it.

    The frontend generates its API types from the file (`make api-client`).

    Args:
        output: The JSON file to write.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)
    require_api_extra()

    from hive.api.app import create_app
    from hive.api.settings import ApiSettings

    # The schema does not depend on the settings, so none are read from the environment.
    settings = ApiSettings.model_construct(frontend_dir=None)
    schema = create_app(settings=settings).openapi()
    output.write_text(json.dumps(schema, indent=2) + "\n")
    logger.info("Wrote the OpenAPI schema to `%s`.", output)


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

    from alembic import command

    from hive.api.settings import DatabaseSettings

    command.upgrade(load_settings(DatabaseSettings).alembic_config(), revision)
    logger.info("Migrated the database to `%s`.", revision)


bench_app = typer.Typer(no_args_is_help=True, help="Benchmarks and correctness checks.")
app.add_typer(bench_app, name="bench")

DEFAULT_PERFT_SUITE = Path("tests/data/perft/base.json")


@bench_app.command(
    "perft", help="Run perft on a position and print nodes, seconds and nodes per second."
)
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
    """Run perft on a position and print nodes, seconds and nodes per second.

    Args:
        depth: The number of plies to walk.
        position: The name of the position in the suite.
        divide: Whether to print the count below each first move.
        suite: The perft suite with the positions and rules.

    Raises:
        typer.BadParameter: If the suite has no position with the name.
        typer.Exit: With code 1 if the count differs from the reference count.
    """
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

    expected = perft_position.expected_count(depth)

    if expected is not None and expected != result.nodes:
        typer.echo(f"mismatch: the stored count is {expected}", err=True)
        raise typer.Exit(code=1)


@bench_app.command(
    "engine",
    help=(
        "Run the fixed engine benchmark cases several times and print the median speed "
        "of each and their geometric mean."
    ),
)
def bench_engine(
    repeat: Annotated[
        int, typer.Option(min=1, help="The number of runs of every case.")
    ] = 5,
    case: Annotated[
        list[str] | None,
        typer.Option(help="Run only the case with this name, given once per case."),
    ] = None,
    suite: Annotated[
        Path, typer.Option(help="The perft suite with the positions and rules.")
    ] = DEFAULT_PERFT_SUITE,
    profile: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Write `cProfile` statistics of the runs to this file, for `pstats` or "
                "`snakeviz`. Profiling slows the runs down."
            )
        ),
    ] = None,
) -> None:
    """Run the fixed engine benchmark cases and print the median speed of each.

    Args:
        repeat: The number of runs of every case.
        case: The names of the cases to run, or `None` for all of them.
        suite: The perft suite with the positions and rules.
        profile: The file to write `cProfile` statistics of the runs to, or `None` to
            run without profiling.

    Raises:
        typer.BadParameter: If a case name is unknown.
        typer.Exit: With code 1 if a run visits a different number of nodes than its case
            expects.
    """
    cases = bench.ENGINE_BENCH_CASES

    if case:
        known = {bench_case.name: bench_case for bench_case in cases}
        unknown = [name for name in case if name not in known]

        if unknown:
            msg = f"Unknown benchmark case `{unknown[0]}`, choose from {list(known)}."
            raise typer.BadParameter(msg, param_hint="--case")

        cases = [known[name] for name in case]

    perft_suite = PerftSuite.load(suite)
    profiler = cProfile.Profile()

    try:
        if profile is not None:
            profiler.enable()

        report = bench.EngineBenchReport.measure(
            cases=cases, suite=perft_suite, repeat=repeat
        )
    except bench.EngineBenchMismatchError as e:
        typer.echo(f"mismatch: {e}", err=True)
        raise typer.Exit(code=1) from e
    finally:
        if profile is not None:
            profiler.disable()
            profiler.dump_stats(profile)

    typer.echo(f"{'case':<16} {'nodes':>9} {'median s':>9} {'spread':>7} {'nodes/s':>9}")

    for result in report.results:
        typer.echo(
            f"{result.case.name:<16} {result.case.nodes:>9,} "
            f"{result.median_seconds:>9.3f} {result.spread:>7.1%} "
            f"{result.nodes_per_second:>9,.0f}"
        )

    typer.echo(
        f"geometric mean {report.nodes_per_second:,.0f} nodes/s over {repeat} runs per "
        "case"
    )


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


data_app = typer.Typer(
    no_args_is_help=True, help="Synthetic scenes and datasets for the vision models."
)
app.add_typer(data_app, name="data")


@data_app.command(
    "scenes", help="Generate scene JSON files from random games for the Blender renderer."
)
def data_scenes(
    count: Annotated[int, typer.Option(min=1, help="The number of scenes.")],
    out: Annotated[Path, typer.Option(help="The directory for the scene files.")],
    seed: Annotated[int, typer.Option(help="The seed of the batch.")] = 0,
    start: Annotated[
        int, typer.Option(min=0, help="The index of the first scene, to extend a batch.")
    ] = 0,
    config: Annotated[
        Path | None,
        typer.Option(help="A TOML file with sampling ranges that replace the defaults."),
    ] = None,
    jobs: Annotated[
        int | None,
        typer.Option(min=1, help="The number of worker processes; defaults to the CPUs."),
    ] = None,
) -> None:
    """Generate scene JSON files from random games for the Blender renderer.

    Args:
        count: The number of scenes.
        out: The directory for the scene files.
        seed: The seed of the batch.
        start: The index of the first scene.
        config: A TOML file with sampling ranges, or `None` for the defaults.
        jobs: The number of worker processes, or `None` for one per CPU.

    Raises:
        typer.BadParameter: If the config file cannot be read or is invalid.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        scenes_config = ScenesConfig.load(config)
    except (OSError, ValueError) as e:
        raise typer.BadParameter(str(e), param_hint="--config") from e

    begin = time.perf_counter()
    paths = scenes_config.write_scenes(
        rules=Rules(),
        out=out,
        seed=seed,
        indices=range(start, start + count),
        jobs=jobs or os.cpu_count() or 1,
    )
    logger.info(
        "Wrote %d scenes to `%s` in %.1f s.", len(paths), out, time.perf_counter() - begin
    )


@data_app.command(
    "sequences",
    help="Generate scenes of games after every move, with several photos per move, to "
    "test tracking games from photos.",
)
def data_sequences(
    count: Annotated[int, typer.Option(min=1, help="The number of games.")],
    out: Annotated[Path, typer.Option(help="The directory for the scene files.")],
    plies: Annotated[int, typer.Option(min=1, help="The number of moves per game.")] = 40,
    takes: Annotated[int, typer.Option(min=1, help="The number of photos per move.")] = 3,
    seed: Annotated[int, typer.Option(help="The seed of the batch.")] = 0,
    config: Annotated[
        Path | None,
        typer.Option(help="A TOML file with sampling ranges that replace the defaults."),
    ] = None,
) -> None:
    """Generate scenes of games after every move, with several photos per move.

    Args:
        count: The number of games.
        out: The directory for the scene files.
        plies: The number of moves per game.
        takes: The number of photos per move.
        seed: The seed of the batch.
        config: A TOML file with sampling ranges, or `None` for the defaults.

    Raises:
        typer.BadParameter: If the config file cannot be read or is invalid.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        scenes_config = ScenesConfig.load(config)
    except (OSError, ValueError) as e:
        raise typer.BadParameter(str(e), param_hint="--config") from e

    paths = scenes_config.write_sequences(
        rules=Rules(), out=out, seed=seed, count=count, plies=plies, takes=takes
    )
    logger.info("Wrote %d scenes of %d games to `%s`.", len(paths), count, out)


@data_app.command("schema", help="Write the JSON Schema of the scene files.")
def data_schema(
    out: Annotated[
        Path, typer.Option(help="The file to write the schema to.")
    ] = SCENE_SCHEMA_PATH,
) -> None:
    """Write the JSON Schema of the scene files.

    Args:
        out: The file to write the schema to.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(Scene.json_schema(), indent=2) + "\n")
    logger.info("Wrote the scene schema to `%s`.", out)


def require_vision_extra() -> None:
    """Check that the `vision` extra is installed.

    Raises:
        typer.Exit: With code 1 and a hint if it is not.
    """
    try:
        import cv2  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError as e:
        logger.error("This command needs the `vision` extra: `uv sync --extra vision`.")
        raise typer.Exit(code=1) from e


@data_app.command(
    "export", help="Label Blender renders and write them as a versioned YOLO dataset."
)
def data_export(
    renders: Annotated[
        Path, typer.Option(help="The render folder written by `blender/render.py`.")
    ],
    version: Annotated[str, typer.Option(help="The dataset version, for example v001.")],
    name: Annotated[str, typer.Option(help="The dataset name.")] = "synth",
    out: Annotated[
        Path, typer.Option(help="The folder the dataset folder is created in.")
    ] = Path("data/synth/datasets"),
    task: Annotated[
        str,
        typer.Option(
            help="`segment` writes face polygons (which also train detection models), "
            "`detect` writes boxes."
        ),
    ] = "segment",
    val_fraction: Annotated[
        float, typer.Option(min=0.0, max=1.0, help="The fraction of validation images.")
    ] = 0.1,
    min_visible: Annotated[
        float,
        typer.Option(
            min=0.0,
            max=1.0,
            help="Faces with this visible fraction or less are not labeled.",
        ),
    ] = 0.5,
    debug: Annotated[
        int,
        typer.Option(min=0, help="Draw the labels of this many images into `debug/`."),
    ] = 0,
    jobs: Annotated[
        int | None,
        typer.Option(min=1, help="The number of worker processes; defaults to the CPUs."),
    ] = None,
) -> None:
    """Label Blender renders and write them as a versioned YOLO dataset.

    Args:
        renders: The render folder written by `blender/render.py`.
        version: The dataset version.
        name: The dataset name.
        out: The folder the dataset folder `<name>-<version>` is created in.
        task: `segment` or `detect`.
        val_fraction: The fraction of validation images.
        min_visible: The visible fraction of a face at or below which it is not labeled.
        debug: The number of images to draw the labels of into `debug/`.
        jobs: The number of worker processes, or `None` for one per CPU.

    Raises:
        typer.BadParameter: If the task is unknown, the dataset exists or there are no
            renders.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    require_vision_extra()

    import cv2

    from hive.data.datasets import DatasetExport, DatasetImage, draw_labels, read_image

    if task not in ("segment", "detect"):
        msg = f"Unknown task `{task}`; use `segment` or `detect`."
        raise typer.BadParameter(msg, param_hint="--task")

    export = DatasetExport(
        renders=renders,
        out=out / f"{name}-{version}",
        name=name,
        version=version,
        task=task,
        val_fraction=val_fraction,
        min_visible=min_visible,
    )
    begin = time.perf_counter()

    try:
        manifest = export.run(jobs=jobs or os.cpu_count() or 1)
    except (FileExistsError, FileNotFoundError) as e:
        raise typer.BadParameter(str(e)) from e

    logger.info(
        "Exported %s images with %d labels to `%s` in %.1f s.",
        sum(manifest.images.values()),
        manifest.labels,
        export.out,
        time.perf_counter() - begin,
    )

    if debug > 0:
        (export.out / "debug").mkdir()

        with (export.out / "meta.jsonl").open() as file:
            for _, line in zip(range(debug), file, strict=False):
                image = DatasetImage.from_json(json.loads(line))
                photo = read_image(path=export.out / image.image, flags=cv2.IMREAD_COLOR)
                cv2.imwrite(
                    str(export.out / "debug" / f"{image.scene_id}.jpg"),
                    draw_labels(image=photo, labels=image.labels),
                )

        logger.info(
            "Drew the labels of %d images into `%s`.", debug, export.out / "debug"
        )


vision_app = typer.Typer(no_args_is_help=True, help="Read boards from photos.")
app.add_typer(vision_app, name="vision")


@vision_app.command(
    "detect", help="Detect the tile faces in photos with a YOLO model in ONNX format."
)
def vision_detect(
    images: Annotated[list[Path], typer.Argument(help="The photos to read.")],
    model: Annotated[Path, typer.Option(help="The `model.onnx` file.")],
    out: Annotated[
        Path | None,
        typer.Option(help="Write annotated images and detections as JSON here."),
    ] = None,
    score: Annotated[
        float, typer.Option(min=0.0, max=1.0, help="The lowest score that counts.")
    ] = 0.35,
    iou: Annotated[
        float,
        typer.Option(
            min=0.0,
            max=1.0,
            help="The overlap above which the weaker detection is dropped.",
        ),
    ] = 0.5,
) -> None:
    """Detect the tile faces in photos with a YOLO model in ONNX format.

    Args:
        images: The photos to read.
        model: The ONNX model file.
        out: The folder for annotated images and detections as JSON, or `None` to only
            log the detections.
        score: The lowest class score that counts as a detection.
        iou: The overlap above which the weaker of two detections is dropped.

    Raises:
        typer.BadParameter: If a photo cannot be read.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    require_vision_extra()

    import cv2

    from hive.vision.yolo.reader import YoloReader

    reader = YoloReader.load(model_path=model, score_threshold=score, iou_threshold=iou)

    if out is not None:
        out.mkdir(parents=True, exist_ok=True)

    for path in images:
        photo = cv2.imread(str(path), cv2.IMREAD_COLOR)

        if photo is None:
            msg = f"Cannot read the image `{path}`."
            raise typer.BadParameter(msg, param_hint="IMAGES")

        begin = time.perf_counter()
        observations = reader.read(photo)
        elapsed_ms = (time.perf_counter() - begin) * 1000
        logger.info("%s: %d tiles in %.0f ms", path, len(observations), elapsed_ms)

        for observation in sorted(observations, key=lambda o: (o.center[1], o.center[0])):
            logger.info(
                "  %-18s %.2f at (%.0f, %.0f)",
                observation.tile_class.name,
                observation.score,
                *observation.center,
            )

        if out is not None:
            canvas = photo.copy()

            for observation in observations:
                observation.draw(canvas)

            cv2.imwrite(str(out / f"{path.stem}.jpg"), canvas)
            detections = [observation.to_json() for observation in observations]
            (out / f"{path.stem}.json").write_text(json.dumps(detections, indent=1))


@vision_app.command(
    "track",
    help="Track rendered games photo by photo and check every resolved move; write a "
    "report, a frame per photo and an animation per game.",
)
def vision_track(
    dataset: Annotated[
        Path, typer.Option(help="The dataset exported from rendered `data sequences`.")
    ],
    model: Annotated[Path, typer.Option(help="The `model.onnx` file.")],
    out: Annotated[
        Path, typer.Option(help="The folder for the report, frames and animations.")
    ],
    score: Annotated[
        float, typer.Option(min=0.0, max=1.0, help="The lowest score that counts.")
    ] = 0.25,
) -> None:
    """Track rendered games photo by photo and check every resolved move.

    Args:
        dataset: The dataset exported from rendered `data sequences`.
        model: The ONNX model file.
        out: The folder for the report, frames and animations.
        score: The lowest class score that counts as a detection.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    require_vision_extra()

    from hive.vision.sequences import SequenceTracker
    from hive.vision.yolo.reader import YoloReader

    reader = YoloReader.load(model_path=model, score_threshold=score)
    tracker = SequenceTracker(
        dataset=dataset, reader=reader, rules=Rules(), frames=out / "frames"
    )
    report = tracker.run()
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report.to_json(), indent=1))

    for ply in report.plies:
        statuses = ", ".join(
            f"{photo.status} ({photo.probability:.2f})"
            if photo.probability is not None
            else photo.status
            for photo in ply.photos
        )
        logger.info(
            "game %s move %2d: %-8s %-40s photos: %s",
            ply.sequence,
            ply.ply,
            ply.outcome,
            format_move(ply.true_move),
            statuses,
        )

    logger.info("Summary: %s", report.summary)
    write_animations(frames=out / "frames", out=out)
    logger.info("Wrote the report, frames and animations to `%s`.", out)


def write_animations(frames: Path, out: Path) -> None:
    """Join the frames of every game into an animated GIF, if Pillow is installed.

    Args:
        frames: The folder with one subfolder of frames per game.
        out: The folder for the animations.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.info("Install the `plotting` extra for animations of the frames.")
        return

    for folder in sorted(path for path in frames.iterdir() if path.is_dir()):
        images = [Image.open(path) for path in sorted(folder.glob("*.jpg"))]

        if not images:
            continue

        width = 1200
        resized = [
            image.resize((width, round(image.height * width / image.width)))
            for image in images
        ]
        resized[0].save(
            out / f"game-{folder.name}.gif",
            save_all=True,
            append_images=resized[1:],
            duration=900,
            loop=0,
        )
