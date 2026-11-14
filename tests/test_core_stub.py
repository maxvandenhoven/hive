"""Check that `src/hive/_core.pyi` describes the Rust bindings it stands in for.

The stub is written by hand, so these tests catch drift: every class and public member of
`hive._core` is in the stub and the other way around, docstrings are identical, and
parameter names match. Constructor docstrings live on the `#[new]` functions of the
bindings, which Python cannot see, so they are compared with the Rust source.
"""

import ast
import inspect
from pathlib import Path

import pytest

from hive import _core

REPO = Path(__file__).parents[1]
STUB = REPO / "src" / "hive" / "_core.pyi"
BINDINGS = REPO / "rust" / "python" / "src"


def stub_classes() -> dict[str, ast.ClassDef]:
    """Parse the classes of the stub by name."""
    tree = ast.parse(STUB.read_text())
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    }


def stub_members(node: ast.ClassDef) -> dict[str, ast.FunctionDef]:
    """Get the functions of a stub class by name, without property setters."""
    return {
        member.name: member
        for member in node.body
        if isinstance(member, ast.FunctionDef)
        and not any(
            isinstance(decorator, ast.Attribute) and decorator.attr == "setter"
            for decorator in member.decorator_list
        )
    }


def parameter_names(function: ast.FunctionDef) -> list[str]:
    """Get the parameter names of a stub function, without `self` and `cls`."""
    arguments = function.args
    names = [arg.arg for arg in [*arguments.posonlyargs, *arguments.args]]
    names += [arg.arg for arg in arguments.kwonlyargs]
    return [name for name in names if name not in {"self", "cls"}]


def is_property(member: ast.FunctionDef) -> bool:
    """Check whether a stub function is a property getter."""
    return any(
        isinstance(decorator, ast.Name) and decorator.id == "property"
        for decorator in member.decorator_list
    )


def constructor_doc(class_name: str) -> str:
    """Read the doc comment of the `#[new]` function of a class from the bindings."""
    for source in BINDINGS.glob("*.rs"):
        lines = source.read_text().splitlines()

        if not any(f'#[pyclass(name = "{class_name}"' in line for line in lines):
            continue

        index = next(i for i, line in enumerate(lines) if line.strip() == "#[new]")
        doc: list[str] = []

        while lines[index - 1].strip().startswith("///"):
            index -= 1
            doc.insert(0, lines[index].strip().removeprefix("///").removeprefix(" "))

        return "\n".join(doc)

    msg = f"No binding defines the class `{class_name}`."
    raise LookupError(msg)


CLASSES = stub_classes()
MEMBERS = [
    (class_name, member_name)
    for class_name, node in CLASSES.items()
    for member_name, member in stub_members(node).items()
    if member_name != "__init__" and ast.get_docstring(member) is not None
]


def test_stub_lists_every_class() -> None:
    runtime = {name for name, value in vars(_core).items() if isinstance(value, type)}
    assert set(CLASSES) == runtime


@pytest.mark.parametrize("class_name", list(CLASSES))
def test_stub_lists_every_public_member(class_name: str) -> None:
    runtime = {
        name for name in vars(getattr(_core, class_name)) if not name.startswith("_")
    }
    stub = {
        name for name in stub_members(CLASSES[class_name]) if not name.startswith("_")
    }
    assert stub == runtime


@pytest.mark.parametrize("class_name", list(CLASSES))
def test_class_docstring_matches(class_name: str) -> None:
    runtime = inspect.cleandoc(getattr(_core, class_name).__doc__ or "")
    assert ast.get_docstring(CLASSES[class_name]) == runtime


@pytest.mark.parametrize("class_name", list(CLASSES))
def test_constructor_matches(class_name: str) -> None:
    init = stub_members(CLASSES[class_name])["__init__"]
    runtime_parameters = list(inspect.signature(getattr(_core, class_name)).parameters)

    assert parameter_names(init) == runtime_parameters
    assert ast.get_docstring(init) == constructor_doc(class_name)


@pytest.mark.parametrize(("class_name", "member_name"), MEMBERS)
def test_member_matches(class_name: str, member_name: str) -> None:
    member = stub_members(CLASSES[class_name])[member_name]
    runtime = getattr(getattr(_core, class_name), member_name)

    assert ast.get_docstring(member) == inspect.cleandoc(runtime.__doc__ or "")

    if not is_property(member):
        runtime_parameters = [
            name for name in inspect.signature(runtime).parameters if name != "self"
        ]
        assert parameter_names(member) == runtime_parameters
