import dataclasses
import json
import logging
import pstats
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from typer.testing import CliRunner

from hive import __version__, bench
from hive.agents.factory import AgentSpec
from hive.bench import PerftBenchCase
from hive.cli import app, describe_match_result, log_decision
from hive.engine.rules import Rules
from hive.engine.state import Player
from hive.match.gauntlet import GauntletConfig, GauntletReport
from hive.match.records import DecisionRecord, MatchOutcome, MatchResult, TurnCloseReason
from hive.match.runner import MatchRunner
from hive.match.worker import AgentWorkerError

SUITE = Path(__file__).parent / "data" / "perft" / "base.json"


def write_suite(path: Path, counts: dict[str, int]) -> Path:
    """Write a perft suite with default rules, the start position and the given counts."""
    position = {"name": "start", "moves": [], "counts": counts}
    path.write_text(json.dumps({"rules": {}, "positions": [position]}))

    return path


def error_text(stderr: str) -> str:
    """Strip colours and the Rich error box from an error message, joining its lines."""
    return " ".join(re.sub(r"\x1b\[[0-9;]*m|[│╭╮╰╯─]", " ", stderr).split())


def test_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"hive {__version__}\n"


class TestBenchPerft:
    def test_prints_nodes_and_speed(self) -> None:
        result = CliRunner().invoke(
            app, ["bench", "perft", "--depth", "2", "--suite", str(SUITE)]
        )

        assert result.exit_code == 0
        assert result.stdout.startswith("position start depth 2: 96 nodes in ")
        assert result.stdout.rstrip().endswith("nodes/s)")

    def test_divide(self) -> None:
        result = CliRunner().invoke(
            app,
            [
                "bench",
                "perft",
                "--depth",
                "2",
                "--position",
                "beetle_gate",
                "--divide",
                "--suite",
                str(SUITE),
            ],
        )

        lines = result.stdout.splitlines()
        assert result.exit_code == 0
        assert len(lines) == 5
        assert lines[0].startswith("beetle (0, 0) -> ")
        assert "202 nodes" in lines[-1]

    @pytest.mark.parametrize(
        ("counts", "exit_code"), [({"1": 5}, 0), ({"1": 4}, 1), ({}, 0)]
    )
    def test_checks_reference_count(
        self, tmp_path: Path, counts: dict[str, int], exit_code: int
    ) -> None:
        suite = write_suite(path=tmp_path / "suite.json", counts=counts)

        result = CliRunner().invoke(
            app, ["bench", "perft", "--depth", "1", "--divide", "--suite", str(suite)]
        )

        assert result.exit_code == exit_code
        assert ("mismatch" in result.stderr) == (exit_code == 1)

    def test_unknown_position(self) -> None:
        result = CliRunner().invoke(
            app,
            [
                "bench",
                "perft",
                "--depth",
                "1",
                "--position",
                "nope",
                "--suite",
                str(SUITE),
            ],
        )

        assert result.exit_code == 2
        assert "Unknown perft position `nope`" in result.stderr


class TestBenchEngine:
    @pytest.fixture(scope="function", autouse=True)
    def small_cases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Replace the benchmark cases with two quick ones."""
        monkeypatch.setattr(
            bench,
            "ENGINE_BENCH_CASES",
            [
                PerftBenchCase(name="start-1", position="start", depth=1, nodes=4),
                PerftBenchCase(name="start-2", position="start", depth=2, nodes=96),
            ],
        )

    def test_prints_every_case(self) -> None:
        result = CliRunner().invoke(app, ["bench", "engine", "--repeat", "2"])

        lines = result.stdout.splitlines()
        assert result.exit_code == 0
        assert lines[0].split() == ["case", "nodes", "median", "s", "spread", "nodes/s"]
        assert [line.split()[:2] for line in lines[1:3]] == [
            ["start-1", "4"],
            ["start-2", "96"],
        ]
        assert lines[3].startswith("geometric mean ")
        assert lines[3].endswith("nodes/s over 2 runs per case")

    def test_selects_cases(self) -> None:
        result = CliRunner().invoke(
            app, ["bench", "engine", "--repeat", "1", "--case", "start-2"]
        )

        assert result.exit_code == 0
        assert [line.split()[0] for line in result.stdout.splitlines()[1:-1]] == [
            "start-2"
        ]

    def test_profile(self, tmp_path: Path) -> None:
        out = tmp_path / "bench.prof"

        result = CliRunner().invoke(
            app, ["bench", "engine", "--repeat", "1", "--profile", str(out)]
        )

        assert result.exit_code == 0
        assert pstats.Stats(str(out)).get_stats_profile().func_profiles

    def test_unknown_case(self) -> None:
        result = CliRunner().invoke(app, ["bench", "engine", "--case", "nope"])

        assert result.exit_code == 2
        assert "Unknown benchmark case `nope`" in error_text(result.stderr)

    def test_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            bench,
            "ENGINE_BENCH_CASES",
            [PerftBenchCase(name="start-1", position="start", depth=1, nodes=5)],
        )

        result = CliRunner().invoke(app, ["bench", "engine", "--repeat", "1"])

        assert result.exit_code == 1
        assert "mismatch: Benchmark case `start-1` visited `4` nodes" in result.stderr


class TestPlay:
    def test_plays_match(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        spec = tmp_path / "nm1.yaml"
        spec.write_text("kind: negamax\nlabel: nm1\nparams:\n  depth: 1\n")
        out = tmp_path / "result.json"
        caplog.set_level(logging.INFO)

        result = CliRunner().invoke(
            app,
            [
                "play",
                "--white",
                str(spec),
                "--black",
                "random",
                "--budget",
                "0.5",
                "--max-turns",
                "3",
                "--out",
                str(out),
            ],
        )

        assert result.exit_code == 0, result.output
        match_result = MatchResult.from_json(json.loads(out.read_text()))
        assert len(match_result.decisions) == 6
        assert match_result.white_spec.label == "nm1"
        messages = [record.getMessage() for record in caplog.records]
        assert messages[0].startswith("  0 white nm1: ")
        assert "depth 1" in messages[0]
        assert messages[1].startswith("  1 black random: ")
        assert messages[6].startswith("Stopped at the turn cap after 6 plies")

    def test_invalid_spec(self) -> None:
        result = CliRunner().invoke(
            app,
            ["play", "--white", "{kind: negamax, params: {depth: 0}}", "--black", "x"],
        )

        # CI forces colours, so Rich styles the option name inside the message.
        stderr = re.sub(r"\x1b\[[0-9;]*m", "", result.stderr)
        assert result.exit_code == 2
        assert "Invalid value for --white" in stderr
        assert "params.depth" in stderr

    def test_worker_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail(self: MatchRunner, **kwargs: object) -> MatchResult:
            msg = "The worker of `random` failed to start: boom"
            raise AgentWorkerError(msg)

        monkeypatch.setattr(MatchRunner, "run", fail)

        result = CliRunner().invoke(
            app, ["play", "--white", "random", "--black", "random"]
        )

        assert result.exit_code == 1

    def test_logs_failures(self, caplog: pytest.LogCaptureFixture) -> None:
        decision = DecisionRecord(
            ply=4,
            player=Player.BLACK,
            agent_label="nm",
            seed=0,
            budget_s=1.0,
            elapsed_s=1.0,
            overrun_s=1.0,
            close_reason=TurnCloseReason.DEADLINE,
            candidates=1,
            illegal_submissions=2,
            move=None,
            worker_restarted=True,
            failure="slow",
        )
        caplog.set_level(logging.INFO)

        log_decision(decision)

        assert caplog.records[0].getMessage() == (
            "  4 black nm: pass (deadline, 1.00 s, 2 illegal, worker restarted, failure: "
            "slow)"
        )

    @pytest.mark.parametrize(
        ("outcome", "winner", "start"),
        [
            (MatchOutcome.WIN, Player.BLACK, "black (random) wins after 0 plies"),
            (MatchOutcome.DRAW, None, "Draw after 0 plies"),
            (MatchOutcome.TURN_CAP, None, "Stopped at the turn cap after 0 plies"),
        ],
    )
    def test_describes_result(
        self, outcome: MatchOutcome, winner: Player | None, start: str
    ) -> None:
        result = MatchResult(
            rules=Rules(),
            white_spec=AgentSpec("random"),
            black_spec=AgentSpec("random"),
            seed=0,
            budget_s=1.0,
            outcome=outcome,
            winner=winner,
        )

        assert describe_match_result(result).startswith(start)


@pytest.fixture(scope="module")
def gauntlet_report() -> GauntletReport:
    """Play a short gauntlet between two random agents, keeping the replays."""
    config = GauntletConfig(
        participants=(AgentSpec("random"), AgentSpec(kind="random", label="r2")),
        games_per_pair=2,
        budget_s=0.5,
        max_turns=3,
        seed=0,
        replays=True,
    )
    return config.run()


class TestGauntlet:
    def test_writes_report(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        out = tmp_path / "report.json"
        caplog.set_level(logging.INFO)

        result = CliRunner().invoke(
            app,
            [
                "gauntlet",
                "--agent",
                "random",
                "--agent",
                "{kind: negamax, label: nm1, params: {depth: 1}}",
                "--games-per-pair",
                "2",
                "--budget",
                "0.5",
                "--max-turns",
                "3",
                "--jobs",
                "1",
                "--seed",
                "4",
                "--replays",
                "--out",
                str(out),
            ],
        )

        assert result.exit_code == 0, result.output
        report = GauntletReport.from_json(json.loads(out.read_text()))
        assert report.config.labels == ["random", "nm1"]
        assert report.config.seed == 4
        assert report.replays is not None
        messages = [record.getMessage() for record in caplog.records]
        assert messages[0] == "Playing 2 matches between random, nm1, 1 at a time."
        assert messages[1].startswith("[1/2] match 0, random vs nm1: Stopped at the turn")
        assert "win rate" in messages[3]
        assert messages[-1].endswith(f"Wrote the gauntlet report to `{out}`.")

    def test_default_out(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        gauntlet_report: GauntletReport,
    ) -> None:
        monkeypatch.setattr(GauntletConfig, "run", lambda self, **kwargs: gauntlet_report)
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(
            app, ["gauntlet", "--agent", "random", "--agent", "{kind: random, label: r2}"]
        )

        assert result.exit_code == 0, result.output
        assert len(list((tmp_path / "reports").glob("gauntlet-*.json"))) == 1

    def test_warns_about_flagged_agents(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        gauntlet_report: GauntletReport,
    ) -> None:
        flagged = dataclasses.replace(
            gauntlet_report.participants[1],
            decision_stats=dataclasses.replace(
                gauntlet_report.participants[1].decision_stats, failures=1
            ),
        )
        report = dataclasses.replace(
            gauntlet_report, participants=[gauntlet_report.participants[0], flagged]
        )
        monkeypatch.setattr(GauntletConfig, "run", lambda self, **kwargs: report)

        result = CliRunner().invoke(
            app,
            [
                "gauntlet",
                "--agent",
                "random",
                "--agent",
                "{kind: random, label: r2}",
                "--out",
                str(tmp_path / "report.json"),
            ],
        )

        assert result.exit_code == 0, result.output
        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert warnings == [
            "Flagged for failures, overruns, restarts or missing moves: r2."
        ]

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            (["--agent", "random"], "at least two agents"),
            (["--agent", "random", "--agent", "random"], "random appear more than once"),
            (
                ["--agent", "random", "--agent", "nm2", "--games-per-pair", "3"],
                "positive even number",
            ),
            (["--agent", "random", "--agent", "{kind: nope}"], "Unknown agent kind"),
            (["--agent", "random", "--agent", "nm2", "--jobs", "1000"], "oversubscribe"),
        ],
    )
    def test_rejects_invalid(self, arguments: list[str], message: str) -> None:
        result = CliRunner().invoke(app, ["gauntlet", *arguments])

        assert result.exit_code == 2
        assert message in error_text(result.stderr)

    def test_allows_oversubscription(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        gauntlet_report: GauntletReport,
    ) -> None:
        configs = []

        def run(self: GauntletConfig, **kwargs: object) -> GauntletReport:
            configs.append(self)
            return gauntlet_report

        monkeypatch.setattr(GauntletConfig, "run", run)

        result = CliRunner().invoke(
            app,
            [
                "gauntlet",
                "--agent",
                "random",
                "--agent",
                "nm2",
                "--jobs",
                "1000",
                "--allow-oversubscribe",
                "--out",
                str(tmp_path / "report.json"),
            ],
        )

        assert result.exit_code == 0, result.output
        assert configs[0].jobs == 1000
        assert configs[0].participants[1].label == "nm2"

    def test_worker_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail(self: GauntletConfig, **kwargs: object) -> GauntletReport:
            msg = "The worker of `random` failed to start: boom"
            raise AgentWorkerError(msg)

        monkeypatch.setattr(GauntletConfig, "run", fail)

        result = CliRunner().invoke(
            app, ["gauntlet", "--agent", "random", "--agent", "nm2"]
        )

        assert result.exit_code == 1


class TestReplay:
    def write_report(self, path: Path, report: GauntletReport) -> Path:
        path.write_text(json.dumps(report.to_json()))
        return path

    def test_logs_match(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        gauntlet_report: GauntletReport,
    ) -> None:
        path = self.write_report(path=tmp_path / "report.json", report=gauntlet_report)
        caplog.set_level(logging.INFO)

        result = CliRunner().invoke(app, ["replay", str(path), "--match", "1"])

        assert result.exit_code == 0, result.output
        messages = [record.getMessage() for record in caplog.records]
        assert messages[0].startswith("Match 1: r2 (white) vs random (black), seed ")
        assert messages[1].startswith("  0 white r2: ")
        assert len(messages) == 8
        assert messages[-1].startswith("Stopped at the turn cap after 6 plies")

    def test_draws_boards(self, tmp_path: Path, gauntlet_report: GauntletReport) -> None:
        path = self.write_report(path=tmp_path / "report.json", report=gauntlet_report)
        boards = tmp_path / "boards"

        result = CliRunner().invoke(
            app, ["replay", str(path), "--match", "0", "--plot-dir", str(boards)]
        )

        assert result.exit_code == 0, result.output
        assert sorted(p.name for p in boards.iterdir()) == [
            f"ply-{ply:03d}.svg" for ply in range(1, 7)
        ]
        assert (boards / "ply-001.svg").read_text().startswith("<?xml")

    def test_needs_plotting_extra(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        gauntlet_report: GauntletReport,
    ) -> None:
        path = self.write_report(path=tmp_path / "report.json", report=gauntlet_report)
        monkeypatch.setitem(sys.modules, "hive.plotting.svg", None)

        result = CliRunner().invoke(
            app, ["replay", str(path), "--match", "0", "--plot-dir", str(tmp_path)]
        )

        assert result.exit_code == 2
        assert "plotting" in error_text(result.stderr)

    @pytest.mark.parametrize(
        ("replays", "match", "message"),
        [(False, 0, "has no replays"), (True, 5, "No match 5")],
    )
    def test_rejects_invalid(
        self,
        tmp_path: Path,
        gauntlet_report: GauntletReport,
        replays: bool,
        match: int,
        message: str,
    ) -> None:
        report = (
            gauntlet_report
            if replays
            else dataclasses.replace(gauntlet_report, replays=None)
        )
        path = self.write_report(path=tmp_path / "report.json", report=report)

        result = CliRunner().invoke(app, ["replay", str(path), "--match", str(match)])

        assert result.exit_code == 2
        assert message in error_text(result.stderr)

    def test_missing_report(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            app, ["replay", str(tmp_path / "missing.json"), "--match", "0"]
        )

        assert result.exit_code == 2


API_ENV = {
    "HIVE_DATABASE_URL": "postgresql+psycopg://u@db.invalid/x",
    "HIVE_S3_ENDPOINT_URL": "http://s3.invalid:3900",
    "HIVE_S3_ACCESS_KEY_ID": "key",
    "HIVE_S3_SECRET_ACCESS_KEY": "secret",
}
"""Complete API settings as environment variables."""


@pytest.fixture(scope="function")
def api_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the API settings in the environment, away from any `.env` file."""
    monkeypatch.chdir(tmp_path)

    for name, value in API_ENV.items():
        monkeypatch.setenv(name, value)


class TestServe:
    @pytest.mark.usefixtures("api_env")
    def test_runs_app_factory_with_json_logs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []
        monkeypatch.setattr(
            "uvicorn.run", lambda app, **kwargs: calls.append((app, kwargs))
        )
        monkeypatch.setenv("HIVE_LOG_LEVEL", "DEBUG")
        result = CliRunner().invoke(app, ["serve", "--port", "9000", "--reload"])

        [(target, kwargs)] = calls
        assert result.exit_code == 0
        assert target == "hive.api.app:create_app"
        assert kwargs["factory"] is True
        assert (kwargs["host"], kwargs["port"], kwargs["reload"]) == (
            "127.0.0.1",
            9000,
            True,
        )
        assert kwargs["log_config"]["root"]["level"] == "DEBUG"
        assert kwargs["timeout_graceful_shutdown"] > 0

    def test_needs_api_extra(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "fastapi", None)
        result = CliRunner().invoke(app, ["serve"])

        assert result.exit_code == 1

    def test_needs_settings(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.chdir(tmp_path)

        for name in API_ENV:
            monkeypatch.delenv(name, raising=False)

        result = CliRunner().invoke(app, ["serve"])

        assert result.exit_code == 1
        assert "database_url" in caplog.text


class TestDbUpgrade:
    @pytest.mark.usefixtures("api_env")
    def test_upgrades_database_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upgrades: list[tuple[str, str]] = []

        def upgrade(config: Config, revision: str) -> None:
            upgrades.append((config.attributes["database_url"], revision))

        monkeypatch.setattr("alembic.command.upgrade", upgrade)
        result = CliRunner().invoke(app, ["db", "upgrade", "--revision", "0001"])

        assert result.exit_code == 0
        assert upgrades == [("postgresql+psycopg://u@db.invalid/x", "0001")]

    def test_needs_only_the_database_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        for name in API_ENV:
            monkeypatch.delenv(name, raising=False)

        monkeypatch.setenv("HIVE_DATABASE_URL", "postgresql+psycopg://u@db.invalid/x")
        monkeypatch.setattr("alembic.command.upgrade", lambda config, revision: None)

        assert CliRunner().invoke(app, ["db", "upgrade"]).exit_code == 0


class TestOpenapi:
    def test_writes_schema_without_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        for name in API_ENV:
            monkeypatch.delenv(name, raising=False)

        output = tmp_path / "openapi.json"
        result = CliRunner().invoke(app, ["openapi", "--output", str(output)])
        schema = json.loads(output.read_text())

        assert result.exit_code == 0
        assert schema["info"]["title"] == "Hive"
        assert "/api/games" in schema["paths"]
        assert output.read_text().endswith("}\n")

    def test_needs_api_extra(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "fastapi", None)
        result = CliRunner().invoke(app, ["openapi", "--output", "openapi.json"])

        assert result.exit_code == 1


class TestDataScenes:
    def test_writes_scenes(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            app,
            ["data", "scenes", "--count", "3", "--start", "4", "--seed", "1"]
            + ["--out", str(tmp_path), "--jobs", "1"],
        )

        assert result.exit_code == 0
        assert sorted(path.name for path in tmp_path.iterdir()) == [
            "000004.json",
            "000005.json",
            "000006.json",
        ]

    def test_reads_config(self, tmp_path: Path) -> None:
        config = tmp_path / "scenes.toml"
        config.write_text("tilt_deg = [5.0, 5.0]\n")
        result = CliRunner().invoke(
            app,
            ["data", "scenes", "--count", "1", "--out", str(tmp_path / "out")]
            + ["--config", str(config), "--jobs", "1"],
        )
        scene = json.loads((tmp_path / "out" / "000000.json").read_text())

        assert result.exit_code == 0
        assert scene["camera"]["tilt_deg"] == 5.0

    def test_rejects_invalid_config(self, tmp_path: Path) -> None:
        config = tmp_path / "scenes.toml"
        config.write_text("unknown = 1\n")
        result = CliRunner().invoke(
            app,
            ["data", "scenes", "--count", "1", "--out", str(tmp_path)]
            + ["--config", str(config)],
        )

        assert result.exit_code == 2
        assert "unknown" in error_text(result.stderr)


def test_data_schema(tmp_path: Path) -> None:
    out = tmp_path / "scene.schema.json"
    result = CliRunner().invoke(app, ["data", "schema", "--out", str(out)])

    assert result.exit_code == 0
    assert json.loads(out.read_text())["title"] == "Scene"


class TestDataExport:
    def test_exports_renders(self, tmp_path: Path) -> None:
        from hive.data.testing import write_test_render

        write_test_render(renders=tmp_path / "renders", scene_id="000000")
        result = CliRunner().invoke(
            app,
            ["data", "export", "--renders", str(tmp_path / "renders"), "--version", "v1"]
            + ["--out", str(tmp_path), "--debug", "1", "--jobs", "1"],
        )

        assert result.exit_code == 0
        assert (tmp_path / "synth-v1" / "data.yaml").exists()
        assert (tmp_path / "synth-v1" / "debug" / "000000.jpg").exists()

    def test_rejects_unknown_task(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            app,
            ["data", "export", "--renders", str(tmp_path), "--version", "v1"]
            + ["--task", "pose"],
        )

        assert result.exit_code == 2
        assert "Unknown task" in error_text(result.stderr)

    def test_rejects_missing_renders(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            app,
            ["data", "export", "--renders", str(tmp_path / "none"), "--version", "v1"]
            + ["--out", str(tmp_path)],
        )

        assert result.exit_code == 2
        assert "No renders" in error_text(result.stderr)


class TestVisionDetect:
    def test_detects_and_writes_results(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import cv2
        import numpy as np

        from hive.engine.state import PieceType
        from hive.vision.types import TileObservation
        from hive.vision.yolo.reader import YoloReader

        class FakeReader:
            name = "fake"

            def read(self, image: np.ndarray) -> list[TileObservation]:
                return [
                    TileObservation(
                        center=(20.0, 15.0),
                        box=(10.0, 5.0, 30.0, 25.0),
                        polygon=None,
                        piece_type=PieceType.SPIDER,
                        owner=Player.BLACK,
                        score=0.9,
                    )
                ]

        monkeypatch.setattr(YoloReader, "load", lambda **_: FakeReader())
        photo = tmp_path / "photo.png"
        cv2.imwrite(str(photo), np.zeros((40, 60, 3), dtype=np.uint8))
        result = CliRunner().invoke(
            app,
            ["vision", "detect", str(photo), "--model", "model.onnx"]
            + ["--out", str(tmp_path / "out")],
        )
        detections = json.loads((tmp_path / "out" / "photo.json").read_text())

        assert result.exit_code == 0
        assert detections[0]["piece_type"] == "spider"
        assert detections[0]["owner"] == "black"
        assert (tmp_path / "out" / "photo.jpg").exists()

    def test_rejects_unreadable_images(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from hive.vision.yolo.reader import YoloReader

        monkeypatch.setattr(YoloReader, "load", lambda **_: object())
        result = CliRunner().invoke(
            app, ["vision", "detect", str(tmp_path / "missing.jpg"), "--model", "m.onnx"]
        )

        assert result.exit_code == 2
        assert "Cannot read the image" in error_text(result.stderr)


def test_data_sequences(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["data", "sequences", "--count", "1", "--plies", "3", "--takes", "2"]
        + ["--out", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert len(list(tmp_path.glob("000-00?-?.json"))) == 6
