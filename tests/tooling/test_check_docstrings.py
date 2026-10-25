import textwrap
from pathlib import Path

import pytest
from check_docstrings import DocumentedFunction, main

PATH = Path("example.py")


def messages(source: str) -> list[str]:
    """Check a dedented source string and return the violations as `line: message`."""
    return [
        f"{violation.line}: {violation.message}"
        for function in DocumentedFunction.from_source(textwrap.dedent(source))
        for violation in function.violations(PATH)
    ]


class TestArgs:
    def test_documented_args_pass(self) -> None:
        source = '''
            def f(a: int, b: int) -> None:
                """Do it.

                Args:
                    a: The first.
                    b (int): The second, with a type.
            """
        '''

        assert messages(source) == []

    def test_missing_section_fails(self) -> None:
        source = '''
            def f(a: int) -> None:
                """Do it."""
        '''

        assert messages(source) == ["2: `f` is missing an `Args:` section"]

    def test_missing_arg_fails(self) -> None:
        source = '''
            def f(a: int, *, b: int) -> None:
                """Do it.

                Args:
                    a: The first, whose description
                        continues: here.
                """
        '''

        assert messages(source) == ["2: `f` does not document argument `b`"]

    def test_unknown_arg_fails(self) -> None:
        source = '''
            def f(a: int) -> None:
                """Do it.

                Args:
                    a: The first.
                    old: Gone.
                """
        '''

        assert messages(source) == ["2: `f` documents `old`, which is not an argument"]

    def test_star_args_with_or_without_stars(self) -> None:
        source = '''
            def f(*args: int, **kwargs: int) -> None:
                """Do it.

                Args:
                    *args: The positional values.
                    kwargs: The keyword values.
                """
        '''

        assert messages(source) == []

    def test_self_and_cls_are_skipped(self) -> None:
        source = '''
            class C:
                def f(self) -> None:
                    """Do it."""

                @classmethod
                def g(cls) -> None:
                    """Do it."""
        '''

        assert messages(source) == []

    def test_args_of_other_sections_are_ignored(self) -> None:
        source = '''
            def f(a: int) -> None:
                """Do it.

                Args:
                    a: The first.

                Raises:
                    ValueError: If `a` is negative.
                """
        '''

        assert messages(source) == []


class TestReturns:
    @pytest.mark.parametrize("annotation", ["int", "list[int]", "'Self'", "Any"])
    def test_missing_returns_fails(self, annotation: str) -> None:
        source = f'''
            def f() -> {annotation}:
                """Do it."""
        '''

        assert messages(source) == ["2: `f` is missing a `Returns:` section"]

    @pytest.mark.parametrize("annotation", ["None", "typing.NoReturn", "Never", "'None'"])
    def test_no_value_needs_no_returns(self, annotation: str) -> None:
        source = f'''
            def f() -> {annotation}:
                """Do it."""
        '''

        assert messages(source) == []

    def test_missing_annotation_needs_no_returns(self) -> None:
        assert messages('def f():\n    """Do it."""\n    return 1\n') == []

    def test_documented_returns_pass(self) -> None:
        source = '''
            async def f() -> int:
                """Do it.

                Returns:
                    One.
                """
        '''

        assert messages(source) == []

    def test_generator_needs_yields(self) -> None:
        source = '''
            def f() -> Iterator[int]:
                """Do it.

                Returns:
                    Wrong section.
                """
                yield 1

            def g() -> Iterator[int]:
                """Return an iterator without yielding."""

                def inner() -> Iterator[int]:
                    yield 1

                return inner()
        '''

        assert messages(source) == [
            "2: `f` is missing a `Yields:` section",
            "10: `g` is missing a `Returns:` section",
        ]


class TestSkipped:
    def test_functions_without_docstrings(self) -> None:
        assert messages("def f(a: int) -> int:\n    return a\n") == []

    def test_properties_and_overloads(self) -> None:
        source = '''
            class C:
                @property
                def value(self) -> int:
                    """The value."""

                @functools.cached_property
                def cached(self) -> int:
                    """The cached value."""

                @typing.overload
                def f(self, a: int) -> int:
                    """Overload."""
        '''

        assert messages(source) == []

    def test_nested_functions_are_checked(self) -> None:
        source = '''
            def f() -> None:
                """Do it."""

                def g(a: int) -> None:
                    """Do it."""
        '''

        assert messages(source) == ["5: `g` is missing an `Args:` section"]


class TestMain:
    def test_reports_violations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = tmp_path / "pkg" / "bad.py"
        bad.parent.mkdir()
        bad.write_text('def f(a: int) -> None:\n    """Do it."""\n')
        (tmp_path / "pkg" / "notes.txt").write_text("def f(a): ...")

        assert main([str(tmp_path)]) == 1
        assert capsys.readouterr().out == f"{bad}:1: `f` is missing an `Args:` section\n"

    def test_clean_file(self, tmp_path: Path) -> None:
        good = tmp_path / "good.py"
        good.write_text("def f() -> None:\n    pass\n")

        assert main([str(good)]) == 0

    def test_syntax_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        broken = tmp_path / "broken.py"
        broken.write_text("def f(:\n")

        assert main([str(broken)]) == 1
        assert "could not parse" in capsys.readouterr().out
