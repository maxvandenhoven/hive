"""Check that blocks of logic in Python files are separated by blank lines.

A compound statement (`if`, `for`, `while`, `with`, `try`, `match`) needs a blank line
before and after it, unless it starts or ends its enclosing block. The closing `return` of
a function with several steps (at least `MIN_STATEMENTS_FOR_RETURN_GAP` statements, not
counting the docstring) needs a blank line before it. Comments directly above a statement
belong to it, so the blank line goes above them.

Usage: `python scripts/tooling/check_blank_lines.py [--fix] PATH [PATH ...]`, where each
path is a Python file or a directory that is searched recursively. With `--fix`, missing
blank lines are inserted instead of reported.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

COMPOUND_STATEMENTS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.TryStar,
    ast.Match,
)
"""The statements that open a block of logic and need blank lines around them."""

COMPOUND_STATEMENT_KEYWORDS: dict[type[ast.stmt], str] = {
    ast.If: "if",
    ast.For: "for",
    ast.AsyncFor: "async for",
    ast.While: "while",
    ast.With: "with",
    ast.AsyncWith: "async with",
    ast.Try: "try",
    ast.TryStar: "try",
    ast.Match: "match",
}
"""The keyword of every compound statement, for violation messages."""

MIN_STATEMENTS_FOR_RETURN_GAP = 3
"""The number of statements from which the closing `return` needs a blank line above."""


@dataclass(frozen=True, slots=True)
class BlankLineViolation:
    """A missing blank line in a file.

    Attributes:
        path: The file containing the violation.
        line: The 1-based line before which a blank line is missing.
        message: A description of the violation.
    """

    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        """Format the violation as `path:line: message`."""
        return f"{self.path}:{self.line}: {self.message}"


@dataclass(frozen=True, slots=True)
class BlankLineSource:
    """A parsed Python file whose statements are checked for separating blank lines.

    Attributes:
        path: The file the source came from, used in the reported violations.
        lines: The lines of the source, without line endings.
        tree: The parsed module.
    """

    path: Path
    lines: list[str]
    tree: ast.Module

    @classmethod
    def from_source(cls, source: str, path: Path) -> "BlankLineSource":
        """Parse source code.

        Args:
            source: Python source code.
            path: The file the source came from.

        Returns:
            The parsed source.

        Raises:
            SyntaxError: If the source is not valid Python.
        """
        return cls(path=path, lines=source.splitlines(), tree=ast.parse(source))

    def violations(self) -> list[BlankLineViolation]:
        """Find every missing blank line.

        Returns:
            The violations in line order, at most one per line.
        """
        found: dict[int, BlankLineViolation] = {}

        for node in ast.walk(self.tree):
            for body in statement_lists(node):
                for violation in self.block_violations(body):
                    found.setdefault(violation.line, violation)

            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                violation = self.return_violation(node)

                if violation is not None:
                    found.setdefault(violation.line, violation)

        return [found[line] for line in sorted(found)]

    def block_violations(self, body: list[ast.stmt]) -> list[BlankLineViolation]:
        """Check the blank lines around the compound statements of one block.

        Args:
            body: The statements of the block, in order, possibly starting with a
                docstring.

        Returns:
            The missing blank lines before and after compound statements.
        """
        violations = []

        # A docstring documents the block, so the statement after it starts the block.
        if is_docstring(body[0]):
            body = body[1:]

        for index, statement in enumerate(body):
            if not isinstance(statement, COMPOUND_STATEMENTS):
                continue

            keyword = COMPOUND_STATEMENT_KEYWORDS[type(statement)]

            if index > 0 and not self.separated(
                previous=body[index - 1], following=statement
            ):
                violations.append(
                    BlankLineViolation(
                        path=self.path,
                        line=self.gap_line(statement),
                        message=f"missing blank line before `{keyword}` statement",
                    )
                )

            if index < len(body) - 1 and not self.separated(
                previous=statement, following=body[index + 1]
            ):
                violations.append(
                    BlankLineViolation(
                        path=self.path,
                        line=self.gap_line(body[index + 1]),
                        message=f"missing blank line after `{keyword}` statement",
                    )
                )

        return violations

    def return_violation(
        self, function: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> BlankLineViolation | None:
        """Check the blank line before the closing `return` of a function.

        Args:
            function: The function to check.

        Returns:
            The violation, or `None` if the function has few statements, does not end
            with a `return`, or already has the blank line.
        """
        body = function.body[1:] if is_docstring(function.body[0]) else function.body

        if (
            len(body) < MIN_STATEMENTS_FOR_RETURN_GAP
            or not isinstance(body[-1], ast.Return)
            or self.separated(previous=body[-2], following=body[-1])
        ):
            return None

        return BlankLineViolation(
            path=self.path,
            line=self.gap_line(body[-1]),
            message="missing blank line before the closing `return`",
        )

    def separated(self, previous: ast.stmt, following: ast.stmt) -> bool:
        """Check whether a blank line separates two consecutive statements.

        Args:
            previous: The earlier statement.
            following: The statement directly after it.

        Returns:
            Whether any line between the two statements is blank.
        """
        start = previous.end_lineno or previous.lineno
        return any(
            not line.strip() for line in self.lines[start : statement_line(following) - 1]
        )

    def gap_line(self, statement: ast.stmt) -> int:
        """Find the line above which a statement's blank line belongs.

        Args:
            statement: The statement that needs a blank line above it.

        Returns:
            The first line of the comments directly above the statement at its own
            indentation, or the first line of the statement itself.
        """
        line = statement_line(statement)
        indentation = " " * statement.col_offset

        while line > 1:
            above = self.lines[line - 2]

            if not above.startswith(f"{indentation}#"):
                break

            line -= 1

        return line

    def fixed(self) -> str:
        """Insert every missing blank line.

        Returns:
            The source with a blank line before every violation line, ending with a
            newline.
        """
        lines = list(self.lines)

        for violation in reversed(self.violations()):
            lines.insert(violation.line - 1, "")

        return "\n".join(lines) + "\n"


def statement_lists(node: ast.AST) -> list[list[ast.stmt]]:
    """List the blocks of statements directly inside a node.

    Args:
        node: Any node, such as a function, an `if` statement or an `except` handler.

    Returns:
        Every field of the node that is a non-empty list of statements, such as `body`,
        `orelse` and `finalbody`.
    """
    return [
        value
        for _, value in ast.iter_fields(node)
        if isinstance(value, list) and value and isinstance(value[0], ast.stmt)
    ]


def statement_line(statement: ast.stmt) -> int:
    """Find the first line of a statement, including its decorators.

    Args:
        statement: The statement.

    Returns:
        The 1-based first line.
    """
    decorators = getattr(statement, "decorator_list", [])
    return min([statement.lineno, *(decorator.lineno for decorator in decorators)])


def is_docstring(statement: ast.stmt) -> bool:
    """Check whether a statement is a docstring.

    Args:
        statement: The first statement of a body.

    Returns:
        Whether the statement is a bare string literal.
    """
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def check_file(path: Path, fix: bool) -> list[BlankLineViolation]:
    """Check, and optionally fix, the blank lines in a Python file.

    Args:
        path: The Python file to check.
        fix: Whether to insert the missing blank lines into the file.

    Returns:
        The violations left in the file, or a single violation if it cannot be parsed.
    """
    try:
        source = BlankLineSource.from_source(source=path.read_text(), path=path)
    except SyntaxError as error:
        return [
            BlankLineViolation(path=path, line=error.lineno or 1, message=f"{error.msg}")
        ]

    violations = source.violations()

    if fix and violations:
        path.write_text(source.fixed())
        return []

    return violations


def main(argv: list[str] | None = None) -> int:
    """Check the blank lines in the given files and directories.

    Args:
        argv: `--fix` and the paths to check. Defaults to the command line arguments.

    Returns:
        1 if any violations are left, otherwise 0.
    """
    arguments = sys.argv[1:] if argv is None else argv
    fix = "--fix" in arguments
    paths = [Path(argument) for argument in arguments if argument != "--fix"]
    files = sorted(
        file
        for path in paths
        for file in (path.rglob("*.py") if path.is_dir() else [path])
        if file.suffix == ".py"
    )
    violations = [violation for file in files for violation in check_file(file, fix=fix)]

    for violation in violations:
        sys.stdout.write(f"{violation}\n")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
