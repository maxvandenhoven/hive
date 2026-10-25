# Tooling

Tooling is set up first (WP 01, WP 02) so every later session gets consistent formatting,
linting, typing and tests for free.

## Python style rules

| Rule | Enforced by |
|---|---|
| Line length 90 for code, docstrings and comments | `ruff format`, ruff `E501` |
| Type annotations on every function and method, including private ones and tests | ruff `ANN` (no test exemptions), `ty check` |
| Google-style docstrings on public modules' classes and functions | ruff `D` with `convention = "google"` |
| Single backticks for inline code in docstrings | review (documented in `CLAUDE.md`) |
| Docstring prose and comments filled up to 90 characters (not wrapped earlier) | manual; ruff `E501` flags overlong lines (see below) |
| Comments: start with a capital letter and end with a period, unless shorter than 5 words | `scripts/tooling/check_comments.py` |
| No `print`, use `logging` | ruff `T20` |
| No manual line splitting or trailing commas to force splits; let the formatter wrap | `skip-magic-trailing-comma = true` |
| Pytest fixtures always state `scope="function"` (or another explicit scope) | review (documented in `CLAUDE.md`) |
| Behaviour is a method on the type that owns the data; functions only for math on primitives | review (see `README.md` D3) |

Ruff rule selection carries over from the current packages (`B`, `D`, `E`, `F`, `I`, `EM`,
`T20`, `RET`, `ANN`) with these changes: add `UP` (pyupgrade) and set
`[tool.ruff.lint.pydocstyle] convention = "google"`; drop the NumPy-specific ignores that no
longer apply; remove the `ANN201` test exemption. Keep `D1xx` (missing docstrings) relaxed
for tests.

Google docstring example:

```python
def target_coords(self, state: GameState, coord: Coordinate) -> list[Coordinate]:
    """Get the coordinates the top piece at `coord` may move to.

    Args:
        state: The current game state.
        coord: The axial coordinate `(q, r)` of the piece to move.

    Returns:
        All axial coordinates the piece may legally move to.

    Raises:
        ValueError: If `coord` is not occupied.
    """
```

### Docstring and comment formatting (WP 02)

`ruff format` does not wrap docstring prose or comments. WP 02 evaluated the available
tools for reflowing Google-style docstrings to 90 characters:

- `docformatter` 1.7.8 (`--style google --wrap-summaries 90 --wrap-descriptions 90`)
  refills plain paragraphs but skips every docstring that contains a section (`Args:`,
  `Returns:`, ...) or a list. That covers most docstrings in the codebase, so their
  paragraphs and argument descriptions are never refilled. It also breaks words at hyphens
  (`anti-` / `clockwise`), splits long summary lines into two-line summaries, and removes
  blank lines that `ruff format` adds back, so the two do not agree.
- `pydocstringformatter` 1.0.0 only wraps summaries by default. With
  `--linewrap-full-docstring` it inserted a period in the middle of a long summary and left
  the body unchanged.

Neither is adopted, and writing a custom reflow tool is out of scope. Instead:

1. Docstring prose and comments are filled up to 90 characters by hand (and by Claude when
   it writes them). Do not wrap earlier.
2. Ruff `E501` flags any line longer than 90 characters, including docstrings and
   comments, so overlong lines fail `make lint` and the PostToolUse hook.
3. `scripts/tooling/check_comments.py` (tested in `tests/tooling/`) checks the comment
   rule with `tokenize`. Consecutive full-line comments at the same indentation form one
   block, and an empty `#` line starts a new one. Each block and each inline comment must
   not start with a lowercase letter and, at 5 or more words, must end with a period.
   Pragmas (`noqa`, `type:`, `pragma:`, `fmt:`, `ruff:`, `ty:`, `isort:`), shebangs and
   leading or trailing URLs are exempt. Violations are printed as `path:line: message`
   with a non-zero exit code. `make lint` and the PostToolUse hook run it.

WP 02 also converted all NumPy-style docstrings to Google style. Return types are no longer
repeated in `Returns:` because the annotations carry them.

## Makefile

One root `Makefile`; every command a session needs is a target.

| Target | Does |
|---|---|
| `make sync` | `uv sync --all-groups --all-extras` |
| `make format` | `ruff format`, `ruff check --fix --select I`; `prettier --write` in `frontend/` once it exists |
| `make lint` | `ruff check --fix`, comment checker; `eslint` in `frontend/` |
| `make type` | `ty check`; `tsc --noEmit` in `frontend/` |
| `make test` | `pytest` with coverage (excludes `slow`, `core = "sysmon"` keeps tracing cheap, `concurrency = ["multiprocessing", "thread"]` measures match worker processes); `vitest run` in `frontend/` |
| `make test-slow` | `pytest -m slow` (deep perft and similar) |
| `make check` | `format lint type` (no tests) |
| `make perft` | `hive bench perft --depth 6` on the start position: a speed baseline that also fails on a count mismatch |
| `make dev` | compose up (Postgres, Garage), uvicorn `--reload`, vite dev server |
| `make api-client` | regenerate the OpenAPI TypeScript client |
| `make install-hooks` | install pre-commit hooks (including commit-msg) |

Frontend targets are added by WP 13; dev targets by WP 10.

## Claude Code hooks

`.claude/settings.json`:

- **PostToolUse** on `Edit|Write|MultiEdit`: `.claude/hooks/format-file.sh` reads the hook
  JSON from stdin, takes `tool_input.file_path`, and for `*.py` runs `ruff format`,
  `ruff check --fix` and the comment checker on that file only; for
  `frontend/**/*.{ts,tsx,css}` runs `prettier --write` (once the frontend exists). It exits
  0 when the file is not formattable and prints remaining lint and comment errors to stderr
  with exit code 2, so Claude sees and fixes them.
- **Stop**: `make check`, so type errors surface before a session ends. (Replaces the
  current `make format lint`.)

## Pre-commit

`.pre-commit-config.yaml`: `end-of-file-fixer`, commitizen on `commit-msg` (conventional
commits), and a local hook running `make check` on commit.

## CI (`.github/workflows/ci.yaml`)

On every PR and on `main`:

- Python: `uv sync --locked`, `make check`, `make test` (includes shallow perft; API tests
  use testcontainers Postgres, available on GitHub-hosted runners), coverage floor.
- Frontend (from WP 13): `npm ci`, lint, typecheck, test, build, and a check that
  `make api-client` produces no diff.
- `uv.lock` and `package-lock.json` must be up to date (`--locked` / `npm ci`).

Release workflow (`release.yaml`) is added in WP 25, see `deployment.md`.

## Git conventions

- Branches: `feature/`, `fix/`, `chore/` prefixes.
- Conventional commits, enforced by commitizen, for example `feat(engine): ...`,
  `refactor(agents): ...`, `test(engine): ...`, `docs(plans): ...`, `build: ...`, `ci: ...`.
- PRs reference their issue with `Closes #N`.
- `uv.lock` is committed.
