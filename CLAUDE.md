# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository.

## Project context

`docs/plans/README.md` is the main context for the project: vision, decisions, target repo
structure, work packages and the session workflow. Read it first in every session, then the
topic files and code the task points to.

## Project structure

One Python package `hive` with a single `pyproject.toml` and `uv.lock` at the repo root:

- `src/hive/engine/` — core game engine (imports nothing from the rest of the package);
  `GameState`, `Rules` and `Move` are re-exported from the Rust core `hive._core`
- `src/hive/agents/` — AI agents; the search agents configure the Rust `Searcher`
- `src/hive/_core.pyi` — hand-written stub of the Rust core, kept in sync with the
  bindings by `tests/test_core_stub.py`
- `rust/` — Cargo workspace (see `docs/plans/rust-core.md`): `core/` (crate `hive-core`,
  engine and search, no Python) and `python/` (crate `hive-python`, the PyO3 bindings that
  maturin builds into `hive._core`)
- `src/hive/plotting/` — matplotlib and SVG board plotting (extra `plotting`)
- `src/hive/assets/` — insect SVG/PNG assets
- `src/hive/cli.py` — `hive` command line entry point (Typer)
- `frontend/` — React app (Vite, TypeScript, Tailwind, shadcn/ui, TanStack Query), see
  `docs/plans/frontend.md`; built files are served by FastAPI at `/`
- `tests/` — mirrors `src/hive/`, for example `tests/engine/` for `src/hive/engine/`;
  `tests/oracle/` is the frozen Python engine the differential tests compare with
- `scripts/tooling/` — development tooling such as the comment and docstring checkers
  (tests in `tests/tooling/`)

Heavy dependencies live behind extras: `plotting`, `api`, `vision`, `train`.

## Setup and commands

Dependency management uses `uv`. Python 3.13.x is required (no other minor versions).
The Rust core needs `rustup`, which installs the toolchain pinned in `rust-toolchain.toml`;
`uv sync` and `uv run` rebuild the extension after a Rust change.

```
make sync           # uv sync --all-groups --all-extras, npm ci in frontend/
make format         # ruff format and import sorting; prettier; cargo fmt
make lint           # ruff, comment and docstring checkers; eslint --fix; clippy, rustdoc
make type           # ty check; tsc
make check          # format + lint + type (no tests)
make test           # pytest with coverage, excluding `slow` tests; vitest; cargo test
make test-slow      # pytest -m slow; the ignored (large perft) cargo tests
make perft          # perft speed benchmark (start position, depth 6)
make api-client     # regenerate frontend/src/api/schema.ts after API changes
make rules-diagrams # regenerate the engine-checked rule diagrams of the help
make dev            # .env, Postgres + Garage, migrate, API on :8000, vite on :5173
make dev-services   # only the compose services and the migration
make install-hooks  # install pre-commit hooks (including commit-msg)
```

`format`, `lint`, `type` and `test` cover Python and the frontend, and `format`, `lint`
and `test` also Rust; append `-python`, `-frontend` or `-rust` (for example
`make test-frontend`) to run one part. Run a single test with:

```
uv run pytest tests/path/to/test_file.py::test_name
cd frontend && npx vitest run src/path/to/file.test.tsx
cd rust && cargo test -p hive-core --test perft
```

The frontend uses npm (lockfile committed). After changing API models or routes, run
`make api-client` and commit `frontend/src/api/schema.ts`; CI fails if it is stale.

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
  `SEARCH_WIN_SCORE`) instead of a bare generic word (`Outcome`, `Info`, `Worker`).
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
- `uv.lock` and `rust/Cargo.lock` are committed; do not delete or gitignore them.

## Rust code style

See `docs/plans/tooling.md` §Rust. The same level of quality as the Python code, with the
standard Rust tools:

- `rustfmt` (90 characters) and `clippy::pedantic` with warnings as errors; prefer
  `#[expect(lint, reason = "...")]` over `#[allow]`. Lines, comments included, stay within
  90 characters (`make lint-rust` checks; rustfmt does not wrap comments).
- Every item has a doc comment, private ones included. Core crate docs follow rustdoc
  conventions (`# Errors`, `# Panics`, intra-doc links). Binding doc comments are the
  Python docstrings in Google style; change them together with `src/hive/_core.pyi`, and
  keep a summary that ends on its first line within 76 characters.
- `unsafe_code` is forbidden. No `println!`; the core does not log.
- The Python style rules apply by review: comment style, blank lines around blocks and
  before a function's tail expression, domain-prefixed names shared with Python,
  behaviour as methods on the owning type, config structs instead of long parameter lists.
- Unit tests live in `#[cfg(test)] mod tests`, integration tests in `rust/core/tests/`.
- Correctness gates: perft parity, the differential tests against `tests/oracle/`, and
  the same node counts and scores as before for search changes that must not change
  results (`docs/plans/rust-core.md` §Correctness gates).

## Type checking

Uses `ty` (Astral) — not mypy. Run via `make type`.

## Claude Code hooks

- PostToolUse on `Edit|Write|MultiEdit` runs `.claude/hooks/format-file.sh`, which formats
  the edited `.py` or `.pyi` file with `ruff format` and `ruff check --fix`, then runs the
  comment checker, formats edited `rust/**/*.rs` files with `rustfmt` and checks their line
  length, and formats edited `frontend/src/**/*.{ts,tsx,css}` files with Prettier.
  Remaining errors are reported back on stderr; fix them.
- Stop runs `make check`.

## Git workflow

- Branch naming: `feature/`, `fix/`, `chore/` prefixes.
- Commit messages follow conventional commits (enforced by the commitizen pre-commit hook).
- The pre-commit hook also runs `make check`. Install hooks once with `make install-hooks`.
- PRs reference their issue with `Closes #N`. CI runs the Python and frontend checks and
  tests in separate jobs.
