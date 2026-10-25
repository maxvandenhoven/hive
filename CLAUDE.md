# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository.

## Project context

`docs/plans/README.md` is the main context for the project: vision, decisions, target repo
structure, work packages and the session workflow. Read it first in every session, then the
topic files and code the task points to.

## Project structure

One Python package `hive` with a single `pyproject.toml` and `uv.lock` at the repo root:

- `src/hive/engine/` — core game engine (imports nothing from the rest of the package)
- `src/hive/agents/` — AI agents, search algorithms and evaluators
- `src/hive/plotting/` — matplotlib and SVG board plotting (extra `plotting`)
- `src/hive/assets/` — insect SVG/PNG assets
- `src/hive/cli.py` — `hive` command line entry point (Typer)
- `tests/` — mirrors `src/hive/`, for example `tests/engine/` for `src/hive/engine/`
- `scripts/tooling/` — development tooling such as the comment and docstring checkers
  (tests in `tests/tooling/`)

Heavy dependencies live behind extras: `plotting`, `api`, `vision`, `train`.

## Setup and commands

Dependency management uses `uv`. Python 3.13.x is required (no other minor versions).

```
make sync           # uv sync --all-groups --all-extras
make format         # ruff format and import sorting
make lint           # ruff check --fix, the comment checker and the docstring checker
make type           # ty check
make check          # format + lint + type (no tests)
make test           # pytest with coverage, excluding `slow` tests
make test-slow      # pytest -m slow
make perft          # perft speed benchmark (start position, depth 6)
make dev            # local Postgres + Garage (compose), migrate, `hive serve --reload`
make dev-services   # only the compose services and the migration
make install-hooks  # install pre-commit hooks (including commit-msg)
```

Run a single test with:

```
uv run pytest tests/path/to/test_file.py::test_name
```

## Code style

See `docs/plans/tooling.md` for the full rules and how each one is enforced.

- Line length: 90 characters for code, docstrings and comments.
- Type annotations on every function and method, including private ones and tests (ruff
  `ANN`, no test exemptions). Test functions return `-> None`.
- Google-style docstrings on public classes and functions (ruff `D`, `convention =
  "google"`). Do not repeat types in `Args:` or `Returns:`; the annotations carry them.
- In `src/`, every docstring documents all arguments in `Args:` and the return value in
  `Returns:` (`Yields:` for generators) unless the annotation is `None`. Checked by
  `scripts/tooling/check_docstrings.py` (part of `make lint`). FastAPI routes and typer
  commands set their public text with `description=` and `help=`.
- Use single backticks (`` `code` ``) for inline code in docstrings, not double backticks.
- Fill docstring prose and comments up to the 90-character limit by hand; do not wrap
  earlier. No tool reflows them, and ruff `E501` flags lines past 90 characters.
- Comments start with a capital letter and end with a period, unless shorter than 5 words.
  Checked by `scripts/tooling/check_comments.py` (part of `make lint`).
- No `print` statements (ruff `T20`); use `logging` instead.
- Do not split lines manually or add trailing commas to force splits; let `ruff format`
  wrap (`skip-magic-trailing-comma = true`).
- Pytest fixtures always state their scope explicitly, for example `scope="function"`.
- Behaviour is a method on the type that owns the data it reads. Plain functions only for
  math on primitives without an owning type (for example `engine/grid.py`).
- Use specific, descriptive names, consistent across the package. Prefix types, enums and
  constants with their domain (`MatchOutcome`, `TurnCloseReason`, `AgentRegistration`,
  `INJECTED_AGENT_PARAMS`) instead of a bare generic word (`Outcome`, `Info`, `Worker`).
  Related types share a pattern, for example the worker messages `ThinkMessage`,
  `SubmissionMessage`, `IdleMessage`.
- Prefer public over private. Do not prefix functions, methods, attributes or constants
  with `_` unless hiding them clearly matters (state that must only change through
  methods, or a subclass hook that callers must not use). Document public attributes in
  the class `Attributes:` section. This applies to tests as well.
- Separate distinct blocks of logic with a blank line: before and after every compound
  statement (`if`, `for`, `while`, `with`, `try`, `match`) unless it starts or ends its
  enclosing block, and before the closing `return` of a function with several steps
  (three or more statements, not counting the docstring).
- Pass arguments by keyword in calls to our own functions, methods and classes with two
  or more arguments, for example `worker.decide(state=state, budget_s=1.0)` and
  `Move(piece_type=..., source_coord=None, target_coord=(0, 0))`. Positional is fine for
  single-argument calls, the standard library, builtins, third-party APIs (`isinstance`,
  logging format arguments, `pytest.mark.parametrize`) and `*args` parameters. Apply it
  consistently.
- `uv.lock` is committed; do not delete or gitignore it.

## Type checking

Uses `ty` (Astral) — not mypy. Run via `make type`.

## Claude Code hooks

- PostToolUse on `Edit|Write|MultiEdit` runs `.claude/hooks/format-file.sh`, which formats
  the edited `.py` file with `ruff format` and `ruff check --fix`, then runs the comment
  checker. Remaining errors are reported back on stderr; fix them.
- Stop runs `make check`.

## Git workflow

- Branch naming: `feature/`, `fix/`, `chore/` prefixes.
- Commit messages follow conventional commits (enforced by the commitizen pre-commit hook).
- The pre-commit hook also runs `make check`. Install hooks once with `make install-hooks`.
- PRs reference their issue with `Closes #N`. CI runs `make check` and `make test`.
