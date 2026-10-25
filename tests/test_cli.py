import json
import logging
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hive import __version__
from hive.agents.factory import AgentSpec
from hive.cli import _describe_result, _log_decision, app
from hive.engine.rules import Rules
from hive.engine.serialization import GameRecord
from hive.engine.state import Player
from hive.match.records import CloseReason, DecisionRecord, MatchResult, Outcome
from hive.match.runner import MatchRunner
from hive.match.worker import WorkerError

_SUITE = Path(__file__).parent / "data" / "perft" / "base.json"


def _write_suite(path: Path, counts: dict[str, int]) -> Path:
    """Write a perft suite with default rules, the start position and the given counts."""
    position = {"name": "start", "moves": [], "counts": counts}
    path.write_text(json.dumps({"rules": {}, "positions": [position]}))
    return path


def test_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"hive {__version__}\n"


class TestBenchPerft:
    def test_prints_nodes_and_speed(self) -> None:
        result = CliRunner().invoke(
            app, ["bench", "perft", "--depth", "2", "--suite", str(_SUITE)]
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
                str(_SUITE),
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
        suite = _write_suite(tmp_path / "suite.json", counts)

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
                str(_SUITE),
            ],
        )

        assert result.exit_code == 2
        assert "Unknown perft position `nope`" in result.stderr


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
        match_result = MatchResult.from_dict(json.loads(out.read_text()))
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
            raise WorkerError(msg)

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
            close_reason=CloseReason.DEADLINE,
            candidates=1,
            illegal_submissions=2,
            move=None,
            worker_restarted=True,
            failure="slow",
        )
        caplog.set_level(logging.INFO)

        _log_decision(decision)

        assert caplog.records[0].getMessage() == (
            "  4 black nm: pass (deadline, 1.00 s, 2 illegal, worker restarted, failure: "
            "slow)"
        )

    @pytest.mark.parametrize(
        ("outcome", "winner", "start"),
        [
            (Outcome.WIN, Player.BLACK, "black (random) wins after 0 plies"),
            (Outcome.DRAW, None, "Draw after 0 plies"),
            (Outcome.TURN_CAP, None, "Stopped at the turn cap after 0 plies"),
        ],
    )
    def test_describes_result(
        self, outcome: Outcome, winner: Player | None, start: str
    ) -> None:
        result = MatchResult(
            rules=Rules(),
            white_spec=AgentSpec("random"),
            black_spec=AgentSpec("random"),
            seed=0,
            budget_s=1.0,
            record=GameRecord(Rules()),
            outcome=outcome,
            winner=winner,
        )

        assert _describe_result(result).startswith(start)
