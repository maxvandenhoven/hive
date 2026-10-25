from pathlib import Path
from textwrap import dedent

import pytest
from check_blank_lines import BlankLineSource, main

PATH = Path("example.py")


def messages(source: str) -> list[str]:
    """Check a source string and return the violations as `line: message` strings."""
    checked = BlankLineSource.from_source(source=dedent(source), path=PATH)
    return [
        f"{violation.line}: {violation.message}" for violation in checked.violations()
    ]


def fixed(source: str) -> str:
    """Insert the missing blank lines into a source string."""
    return BlankLineSource.from_source(source=dedent(source), path=PATH).fixed()


class TestCompoundStatements:
    def test_separated_statements_pass(self) -> None:
        source = """
        def f(xs: list[int]) -> None:
            total = 0

            for x in xs:
                total += x

            print(total)
        """

        assert messages(source) == []

    @pytest.mark.parametrize(
        ("statement", "keyword"),
        [
            ("if x:\n    y = 1", "if"),
            ("for x in y:\n    pass", "for"),
            ("while x:\n    break", "while"),
            ("with x:\n    pass", "with"),
            ("try:\n    pass\nexcept ValueError:\n    pass", "try"),
            ("match x:\n    case 1:\n        pass", "match"),
        ],
    )
    def test_missing_lines_fail(self, statement: str, keyword: str) -> None:
        lines = len(statement.splitlines())

        assert messages(f"a = 1\n{statement}\nb = 2\n") == [
            f"2: missing blank line before `{keyword}` statement",
            f"{lines + 2}: missing blank line after `{keyword}` statement",
        ]

    def test_start_and_end_of_block_pass(self) -> None:
        source = """
        def f(x: int) -> None:
            if x:
                for y in range(x):
                    print(y)
            else:
                while x:
                    x -= 1
        """

        assert messages(source) == []

    def test_statement_after_docstring_starts_the_block(self) -> None:
        source = '''
        def f(x: int) -> None:
            """Docstring."""
            if x:
                print(x)
        '''

        assert messages(source) == []

    def test_comment_belongs_to_the_next_statement(self) -> None:
        source = """
        a = 1
        # Explain the loop.
        for x in []:
            pass
        """

        assert messages(source) == ["3: missing blank line before `for` statement"]
        assert fixed(source) == "\na = 1\n\n# Explain the loop.\nfor x in []:\n    pass\n"

    def test_blank_line_above_comment_passes(self) -> None:
        source = """
        a = 1

        # Explain the loop.
        for x in []:
            pass
        """

        assert messages(source) == []

    def test_nested_blocks_and_handlers_are_checked(self) -> None:
        source = """
        try:
            a = 1
            if a:
                pass
        except ValueError:
            b = 2
            with open("x"):
                pass
        """

        assert messages(source) == [
            "4: missing blank line before `if` statement",
            "8: missing blank line before `with` statement",
        ]


class TestClosingReturn:
    def test_several_steps_need_blank_line(self) -> None:
        source = """
        def f() -> int:
            a = 1
            b = 2
            return a + b
        """

        assert messages(source) == ["5: missing blank line before the closing `return`"]

    def test_short_function_passes(self) -> None:
        source = '''
        def f() -> int:
            """Docstring."""
            a = 1
            return a
        '''

        assert messages(source) == []

    def test_return_after_compound_is_reported_once(self) -> None:
        source = """
        def f(x: int) -> int:
            if x:
                x += 1
            return x
        """

        assert messages(source) == ["5: missing blank line after `if` statement"]

    def test_return_inside_block_is_not_checked(self) -> None:
        source = """
        def f(x: int) -> int:
            if x:
                a = 1
                b = 2
                return a + b

            return 0
        """

        assert messages(source) == []


class TestMain:
    def test_reports_violations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "bad.py"
        path.write_text("a = 1\nif a:\n    pass\n")

        assert main([str(tmp_path)]) == 1
        assert capsys.readouterr().out == (
            f"{path}:2: missing blank line before `if` statement\n"
        )

    def test_fixes_files(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.py"
        path.write_text("a = 1\nif a:\n    pass\nb = 2\n")

        assert main(["--fix", str(path)]) == 0
        assert path.read_text() == "a = 1\n\nif a:\n    pass\n\nb = 2\n"
        assert main([str(path)]) == 0

    def test_reports_syntax_errors(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.py"
        path.write_text("if:\n")

        assert main([str(path), "--fix"]) == 1
        assert path.read_text() == "if:\n"
