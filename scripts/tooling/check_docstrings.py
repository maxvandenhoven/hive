"""Check that Google-style docstrings document every argument and the return value.

Ruff's `D417` only checks an `Args:` section that exists, so this checker covers what it
misses. Every function or method with a docstring must have:

- an `Args:` section if it has parameters other than `self` and `cls`, listing exactly
  those parameters (`*args` and `**kwargs` may be written with or without stars);
- a `Yields:` section if it is a generator with a return annotation, or otherwise a
  `Returns:` section if its return annotation is not `None`, `NoReturn` or `Never`.

Properties and `typing.overload` stubs are skipped. Whether public functions have a
docstring at all is checked by ruff's `D1` rules.

Usage: `python scripts/tooling/check_docstrings.py PATH [PATH ...]`, where each path is a
Python file or a directory that is searched recursively.
"""

import ast
import inspect
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

SKIPPED_PARAMETERS = frozenset({"self", "cls"})
"""Parameters that are never documented."""

SKIPPED_DECORATORS = frozenset({"property", "cached_property", "overload"})
"""Decorators whose functions are not checked, matched on their last name."""

NO_RETURN_ANNOTATIONS = frozenset({"None", "NoReturn", "Never"})
"""Return annotations that need no `Returns:` section, matched on the last name."""

SECTION_PATTERN = re.compile(r"^(\w[\w ]*):\s*$")
"""A line starting a section of a cleaned docstring, such as `Args:`."""

ARG_PATTERN = re.compile(r"^    \**(\w+)(?: \(.*\))?:")
"""A line starting an argument description in the `Args:` section of a docstring."""


@dataclass(frozen=True, slots=True)
class DocstringViolation:
    """A docstring style violation at a line in a file.

    Attributes:
        path: The file containing the violation.
        line: The 1-based line number of the function definition.
        message: A description of the violation.
    """

    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        """Format the violation as `path:line: message`.

        Returns:
            The formatted violation.
        """
        return f"{self.path}:{self.line}: {self.message}"


@dataclass(frozen=True, slots=True)
class DocstringSections:
    """The sections of a Google-style docstring that this checker reads.

    Attributes:
        names: The names of every section in the docstring, such as `Args`.
        documented_args: The argument names in the `Args:` section, without stars.
    """

    names: frozenset[str]
    documented_args: tuple[str, ...]

    @classmethod
    def from_docstring(cls, docstring: str) -> "DocstringSections":
        """Parse the sections of a docstring.

        Args:
            docstring: The raw docstring.

        Returns:
            The section names and the documented arguments.
        """
        names: set[str] = set()
        documented_args: list[str] = []
        section: str | None = None

        for line in inspect.cleandoc(docstring).splitlines():
            if match := SECTION_PATTERN.match(line):
                section = match.group(1)
                names.add(section)
            elif section == "Args" and (match := ARG_PATTERN.match(line)):
                documented_args.append(match.group(1))

        return cls(names=frozenset(names), documented_args=tuple(documented_args))


type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
"""A function or method definition."""


@dataclass(frozen=True, slots=True)
class DocumentedFunction:
    """A function or method definition with a docstring.

    Attributes:
        node: The definition.
        sections: The parsed sections of its docstring.
    """

    node: FunctionNode
    sections: DocstringSections

    @classmethod
    def from_source(cls, source: str) -> list["DocumentedFunction"]:
        """Find the checked functions in some source code.

        Args:
            source: Python source code.

        Returns:
            Every function and method with a docstring, nested ones included, in source
            order, except properties and overload stubs.

        Raises:
            SyntaxError: If the source cannot be parsed.
        """
        functions = []

        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue

            docstring = ast.get_docstring(node, clean=False)

            if docstring is None or SKIPPED_DECORATORS & {
                last_name(decorator) for decorator in node.decorator_list
            }:
                continue

            functions.append(
                cls(node=node, sections=DocstringSections.from_docstring(docstring))
            )

        return sorted(functions, key=lambda function: function.node.lineno)

    @property
    def parameters(self) -> list[str]:
        """The names of the parameters that must be documented, in signature order."""
        arguments = self.node.args
        names = [
            argument.arg
            for argument in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            )
        ]

        for argument in (arguments.vararg, arguments.kwarg):
            if argument is not None:
                names.append(argument.arg)

        return [name for name in names if name not in SKIPPED_PARAMETERS]

    @property
    def is_generator(self) -> bool:
        """Whether the function yields, ignoring yields in nested functions."""
        return any(
            isinstance(node, ast.Yield | ast.YieldFrom) for node in own_nodes(self.node)
        )

    @property
    def returns_value(self) -> bool:
        """Whether the return annotation says the function returns or yields a value."""
        returns = self.node.returns
        return returns is not None and last_name(returns) not in NO_RETURN_ANNOTATIONS

    def violations(self, path: Path) -> list[DocstringViolation]:
        """Check the docstring against the signature.

        Args:
            path: The file containing the function, used in the reported violations.

        Returns:
            The violations found in the docstring, if any.
        """
        messages = []
        name = self.node.name
        parameters = self.parameters
        documented = self.sections.documented_args

        if parameters and "Args" not in self.sections.names:
            messages.append(f"`{name}` is missing an `Args:` section")
        else:
            messages += [
                f"`{name}` does not document argument `{parameter}`"
                for parameter in parameters
                if parameter not in documented
            ]

        messages += [
            f"`{name}` documents `{argument}`, which is not an argument"
            for argument in documented
            if argument not in parameters
        ]

        if self.returns_value:
            section = "Yields" if self.is_generator else "Returns"

            if section not in self.sections.names:
                messages.append(f"`{name}` is missing a `{section}:` section")

        return [
            DocstringViolation(path=path, line=self.node.lineno, message=message)
            for message in messages
        ]


def last_name(node: ast.expr) -> str | None:
    """Get the last name of a name, attribute, call or subscript expression.

    For example `property` for `@property`, `overload` for `@typing.overload` and
    `Generator` for `Generator[int]`.

    Args:
        node: The expression.

    Returns:
        The last name, the text of a string constant, or `None` for other expressions.
    """
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Call(func=inner) | ast.Subscript(value=inner):
            return last_name(inner)
        case ast.Constant(value=None):
            return "None"
        case ast.Constant(value=str(text)):
            return text
        case _:
            return None


def own_nodes(function: FunctionNode) -> Iterator[ast.AST]:
    """Iterate the nodes in the body of a function, skipping nested scopes.

    Args:
        function: The function.

    Yields:
        Every node in the body, except those inside nested functions, classes and
        lambdas.
    """
    stack: list[ast.AST] = list(function.body)

    while stack:
        node = stack.pop()
        yield node

        if not isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda
        ):
            stack.extend(ast.iter_child_nodes(node))


def check_file(path: Path) -> list[DocstringViolation]:
    """Check all docstrings in a Python file.

    Args:
        path: The Python file to check.

    Returns:
        The violations found in the file, or a single violation if it cannot be parsed.
    """
    try:
        functions = DocumentedFunction.from_source(path.read_text())
    except SyntaxError as error:
        return [
            DocstringViolation(path=path, line=1, message=f"could not parse: {error}")
        ]

    return [
        violation for function in functions for violation in function.violations(path)
    ]


def main(argv: list[str] | None = None) -> int:
    """Check the docstrings in the given files and directories.

    Args:
        argv: Paths to check. Defaults to the command line arguments.

    Returns:
        1 if any violations were found, otherwise 0.
    """
    paths = [Path(arg) for arg in (sys.argv[1:] if argv is None else argv)]
    files = sorted(
        file
        for path in paths
        for file in (path.rglob("*.py") if path.is_dir() else [path])
        if file.suffix == ".py"
    )
    violations = [violation for file in files for violation in check_file(file)]

    for violation in violations:
        sys.stdout.write(f"{violation}\n")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
