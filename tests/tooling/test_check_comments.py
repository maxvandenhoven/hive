from pathlib import Path

import pytest
from check_comments import CommentBlock, main

PATH = Path("example.py")


def messages(source: str) -> list[str]:
    """Check a source string and return the violations as `line: message` strings."""
    return [
        f"{violation.line}: {violation.message}"
        for block in CommentBlock.from_source(source)
        for violation in block.violations(PATH)
    ]


class TestCapitalisation:
    def test_capitalised_comment_passes(self) -> None:
        assert messages("# Short note\nx = 1\n") == []

    def test_lowercase_comment_fails(self) -> None:
        assert messages("# short note\nx = 1\n") == [
            "1: comment should start with a capital letter"
        ]

    def test_non_letter_start_passes(self) -> None:
        assert messages("# `x` is the counter\nx = 1\n") == []

    def test_inline_comment_is_checked(self) -> None:
        assert messages("x = 1  # lowercase\n") == [
            "1: comment should start with a capital letter"
        ]

    def test_url_start_passes(self) -> None:
        assert messages("# https://example.com/some/long/path\nx = 1\n") == []


class TestPeriod:
    def test_short_comment_without_period_passes(self) -> None:
        assert messages("# Four words no period\nx = 1\n") == []

    def test_long_comment_without_period_fails(self) -> None:
        assert messages("# Five words and no period\nx = 1\n") == [
            "1: comment of 5 or more words should end with a period"
        ]

    def test_long_comment_with_period_passes(self) -> None:
        assert messages("# Five words and a period.\nx = 1\n") == []

    def test_long_inline_comment_without_period_fails(self) -> None:
        assert messages("x = 1  # Five words and no period\n") == [
            "1: comment of 5 or more words should end with a period"
        ]

    def test_trailing_url_passes(self) -> None:
        assert messages("# See the reference at https://example.com/x\nx = 1\n") == []


class TestBlocks:
    def test_block_is_checked_as_one_comment(self) -> None:
        source = "# This comment spans two lines and\n# continues in lowercase.\nx = 1\n"

        assert messages(source) == []

    def test_block_violation_reports_first_line(self) -> None:
        source = "# this comment spans two lines and\n# continues in lowercase.\nx = 1\n"

        assert messages(source) == ["1: comment should start with a capital letter"]

    def test_block_period_violation_reports_last_line(self) -> None:
        source = "# This comment spans two lines and\n# has no final period\nx = 1\n"

        assert messages(source) == [
            "2: comment of 5 or more words should end with a period"
        ]

    def test_empty_comment_line_separates_paragraphs(self) -> None:
        source = "# First paragraph ends here.\n#\n# second paragraph\nx = 1\n"

        assert messages(source) == ["3: comment should start with a capital letter"]

    def test_different_indentation_separates_blocks(self) -> None:
        source = "if True:\n    # Indented block\n    x = 1\n# dedented block\ny = 2\n"

        assert messages(source) == ["4: comment should start with a capital letter"]

    def test_inline_comment_is_not_joined_with_next_line(self) -> None:
        source = "x = 1  # Inline note\n# next block\ny = 2\n"

        assert messages(source) == ["2: comment should start with a capital letter"]


class TestExemptions:
    @pytest.mark.parametrize(
        "comment",
        [
            "# noqa: E501",
            "# type: ignore[assignment]",
            "# pragma: no cover",
            "# fmt: off",
            "# ruff: noqa: D100",
            "# ty: ignore[invalid-return-type]",
        ],
    )
    def test_pragma_is_skipped(self, comment: str) -> None:
        assert messages(f"x = 1  {comment}\n") == []
        assert messages(f"{comment}\nx = 1\n") == []

    def test_shebang_is_skipped(self) -> None:
        assert messages("#!/usr/bin/env python3\nx = 1\n") == []

    def test_hash_in_string_is_not_a_comment(self) -> None:
        assert messages('color = "#ffffff"\n') == []

    def test_todo_with_owner_is_checked(self) -> None:
        assert messages("# TODO(WP 03): Replace this with the new rules.\nx = 1\n") == []


class TestMain:
    @pytest.fixture(scope="function")
    def package(self, tmp_path: Path) -> Path:
        """Create a directory with one clean and one violating Python file."""
        (tmp_path / "clean.py").write_text("# Clean comment\nx = 1\n")
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "bad.py").write_text("x = 1  # bad comment\n")
        (nested / "notes.txt").write_text("# not python\n")

        return tmp_path

    def test_reports_violations_and_exits_non_zero(
        self, package: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main([str(package)])

        bad_path = package / "nested" / "bad.py"
        assert exit_code == 1
        assert capsys.readouterr().out == (
            f"{bad_path}:1: comment should start with a capital letter\n"
        )

    def test_clean_file_exits_zero(
        self, package: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main([str(package / "clean.py")])

        assert exit_code == 0
        assert capsys.readouterr().out == ""

    def test_unparsable_file_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "broken.py"
        path.write_text('x = """unterminated\n')

        exit_code = main([str(path)])

        assert exit_code == 1
        assert capsys.readouterr().out.startswith(f"{path}:1: could not tokenize:")
