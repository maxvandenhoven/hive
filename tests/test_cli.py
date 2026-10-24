import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hive import __version__
from hive.cli import app

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
