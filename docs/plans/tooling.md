# Tooling

Tooling is set up first (WP 01, WP 02) so every later session gets consistent formatting,
linting, typing and tests for free.

## Python style rules

| Rule | Enforced by |
|---|---|
| Line length 90 for code, docstrings and comments | `ruff format`, ruff `E501` |
| Type annotations on every function and method, including private ones and tests | ruff `ANN` (no test exemptions), `ty check` |
| Google-style docstrings on public modules' classes and functions | ruff `D` with `convention = "google"` |
| Docstrings in `src/` document every argument in `Args:` (and no others) and the return value in `Returns:` (or `Yields:` for generators) unless the return annotation is `None`; properties and overloads are exempt. Tests keep one-line docstrings | `scripts/tooling/check_docstrings.py` (ruff `D417` only checks an existing `Args:` section, and the ruff `DOC` rules are preview-only and lack a missing-arguments rule) |
| Single backticks for inline code in docstrings | review (documented in `CLAUDE.md`) |
| Docstring prose and comments filled up to 90 characters (not wrapped earlier) | manual; ruff `E501` flags overlong lines (see below) |
| Comments: start with a capital letter and end with a period, unless shorter than 5 words | `scripts/tooling/check_comments.py` |
| No `print`, use `logging` | ruff `T20` |
| No manual line splitting or trailing commas to force splits; let the formatter wrap | `skip-magic-trailing-comma = true` |
| Pytest fixtures always state `scope="function"` (or another explicit scope) | review (documented in `CLAUDE.md`) |
| Behaviour is a method on the type that owns the data; functions only for math on primitives | review (see `README.md` D3) |
| Specific, consistent names: prefix types, enums and constants with their domain (`MatchOutcome`, `TurnCloseReason`, `AgentRegistration`, `INJECTED_AGENT_PARAMS`), never a bare generic word (`Outcome`, `Info`, `Worker`); related types share a naming pattern (`ThinkMessage`, `IdleMessage`, ...) | review (documented in `CLAUDE.md`) |
| Public by default: no leading underscore on functions, methods, attributes or constants unless hiding them clearly matters (for example state that must only change through methods, or hooks such as `SearchAgent._search` that subclasses implement but callers must not use); document public attributes in `Attributes:` | review (documented in `CLAUDE.md`) |
| Blank lines between distinct blocks of logic: a blank line before and after every compound statement (`if`, `for`, `while`, `with`, `try`, `match`) unless it starts or ends its enclosing block, and before the closing `return` of a function with several steps (three or more statements, not counting the docstring) | review (documented in `CLAUDE.md`) |
| Keyword arguments for calls to our own functions, methods and classes with two or more arguments (`worker.decide(state=state, budget_s=1.0)`); positional is fine for single-argument calls, the standard library, builtins, third-party APIs and `*args` parameters | review (documented in `CLAUDE.md`) |

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
4. `scripts/tooling/check_docstrings.py` (tested in `tests/tooling/`) checks with `ast`
   that every function in `src/` with a docstring, nested ones included, has an `Args:`
   section listing exactly its parameters (except `self` and `cls`) and a `Returns:` or,
   for generators, `Yields:` section unless the return annotation is `None`, `NoReturn`
   or `Never`. Properties and `overload` stubs are skipped. Public text that comes from a
   docstring elsewhere is set explicitly instead: `description=` on FastAPI routes and
   `help=` on typer commands, so the sections stay out of the OpenAPI page and `--help`.
   `make lint` runs it on `src/`, and the PostToolUse hook on edited files in `src/`.

WP 02 also converted all NumPy-style docstrings to Google style. Return types are no longer
repeated in `Returns:` because the annotations carry them.

## Rust (WP 42)

The Rust core (`rust-core.md`) keeps the quality bar of the Python code with the standard
Rust tools: `rustfmt`, `clippy`, the rustdoc lints and `cargo test`, a pinned toolchain
and a committed lockfile. Python rules carry over where Rust has a tool for them and by
review where they are style; the bindings reuse the Python checkers through the generated
stub.

| Rule | Enforced by |
|---|---|
| Pinned stable toolchain in `rust-toolchain.toml` (components `rustfmt` and `clippy`), edition 2024, `rust/Cargo.lock` committed, CI builds with `--locked` | rustup, cargo |
| Line length 90 for code: `max_width = 90` and `use_small_heuristics = "Max"`, so rustfmt fills lines up to 90 characters like `ruff format` instead of breaking calls at 60% of the width. rustfmt decides every split itself, so there is no magic trailing comma to disable | `cargo fmt` |
| Line length 90 for comments and docs, which stable rustfmt does not check | a `grep` in `make lint-rust` |
| `clippy::pedantic` at warn level, warnings as errors in `make lint` and CI. Allowed: `module_name_repetitions` (names are domain-prefixed and shared with Python, `MatchOutcome` rather than `outcome::Match`) and `must_use_candidate`. Added: `print_stdout`, `print_stderr` and `dbg_macro` (no prints, like ruff `T20`) and `allow_attributes_without_reason` (`#[expect(lint, reason = "...")]` instead of a bare `#[allow]`, like a `noqa` with a reason) | clippy, `[workspace.lints]` |
| `unsafe_code = "forbid"`; `unsafe` for speed is a decision recorded in `rust-core.md`, not a local choice | rustc |
| Every item is documented, private ones included | `missing_docs`, `clippy::missing_docs_in_private_items` |
| Core docs follow rustdoc conventions: a summary line, prose that explains arguments whose meaning the names and types do not carry, `# Errors` and `# Panics` sections, `# Examples` doc tests on the main entry points, intra-doc links such as ``[`GameState`]``, single backticks for inline code. They do not list every argument, which goes against Rust convention | `clippy::missing_errors_doc`, `missing_panics_doc`, `cargo doc` with warnings as errors (broken links) |
| Binding doc comments are the Python docstrings: Google style with `Args:`, `Returns:` and `Raises:`, as in `src/`. They are repeated with the signatures in the hand-written stub `src/hive/_core.pyi` (as pydantic-core and orjson do), where ruff `D`, `ty` and the two checkers (which read `*.pyi` too) check them like any Python file. A summary that ends on its first line stays within 76 characters, so it fits the stub | the Python checkers on the stub; `tests/test_core_stub.py` fails when the stub and the bindings differ in classes, members, parameters or docstrings |
| Python style rules that apply as they are: comments start with a capital letter and end with a period from 5 words; a blank line before and after `if`, `for`, `while`, `loop` and `match` statements unless they start or end their block, and before the tail expression of a function with three or more statements; behaviour as methods on the type that owns the data (free functions only for hex math); specific, domain-prefixed names; no long parameter lists (config structs and newtypes are Rust's answer to keyword arguments; clippy's `too_many_arguments` flags more than 7) | review (`CLAUDE.md`) |
| Visibility: public fields for plain values (`Move`, the `Rules` config), private fields behind methods where an invariant needs them (the board, its caches, the hash), `pub(crate)` for crate helpers | review |
| Errors: `thiserror` enums in the core, which the bindings map to `IllegalMoveError` and `InvalidBoardError` with the current message texts; `expect("why")` rather than `unwrap()` outside tests | review |
| Tests: unit tests inline in `#[cfg(test)] mod tests` (they may test private items, the Rust convention), integration tests in `rust/core/tests/`, doc tests on entry points; the Python suite tests the bindings | `cargo test`, pytest |

Configuration:

```toml
# rust/rustfmt.toml
edition = "2024"
max_width = 90
use_small_heuristics = "Max"

# rust/Cargo.toml (each crate sets `[lints] workspace = true`)
[workspace.lints.rust]
missing_docs = "warn"
unsafe_code = "forbid"

[workspace.lints.clippy]
pedantic = { level = "warn", priority = -1 }
module_name_repetitions = "allow"
must_use_candidate = "allow"
missing_docs_in_private_items = "warn"
print_stdout = "warn"
print_stderr = "warn"
dbg_macro = "warn"
allow_attributes_without_reason = "warn"

[profile.release]
lto = "fat"
codegen-units = 1
```

Lints warn rather than deny, so a half-finished edit still builds; `make lint-rust` and CI
pass `-D warnings`. The PyO3 macros compiled under `forbid(unsafe_code)` with PyO3 0.25 in
the spike; WP 42 confirms this for the PyO3 version it adopts, or the binding crate uses
`deny` with an `expect` and a reason where the macros need it. Panics stay `unwind` (the
default), because PyO3 turns them into Python exceptions and `abort` would kill the API
process.

Build and editable installs:

- `pyproject.toml` uses maturin as the build backend instead of `uv_build`, with
  `manifest-path = "rust/python/Cargo.toml"`, `python-source = "src"` and `module-name =
  "hive._core"`.
- `[tool.uv] cache-keys` lists `pyproject.toml`, `rust/**/*.rs`, `rust/**/Cargo.toml` and
  `rust/Cargo.lock`, so `uv sync` and `uv run` rebuild the extension after a Rust edit.
  The editable build puts `src/hive/_core*.so` next to the Python sources (gitignored),
  and cargo's incremental artifacts stay in `rust/target/` (gitignored).
- One release profile serves uv, the tests, the benchmarks and the image. In the spike a
  rebuild after an edit took 3.7 s with fat LTO and one codegen unit (0.8 s without LTO);
  if the full core rebuilds slowly, WP 29 measures what fat LTO is worth.
- Contributors and CI need `rustup`; it installs the pinned toolchain on first use.

Left out on purpose (evaluated in this plan, not adopted):

- Nightly rustfmt: comment wrapping (`wrap_comments`, `comment_width`), import grouping
  and `error_on_line_overflow` are nightly-only. A moving toolchain is not worth it; the
  line-length `grep` covers the one check that matters, and comments are filled by hand as
  in Python.
- A custom comment and blank-line checker for Rust (for example with tree-sitter): the
  rules stay review rules, as several Python rules are.
- `cargo-deny`, `cargo-llvm-cov`, `proptest` and `pyo3-log`: the core has few
  dependencies; perft parity, the differential tests and the Python suite are the coverage
  that matters; Hypothesis drives the property tests through the bindings; the hot core
  does not log, and search progress goes through the turn context.

## Makefile

One root `Makefile`; every command a session needs is a target.

| Target | Does |
|---|---|
| `make sync` | `uv sync --all-groups --all-extras` and `npm ci` in `frontend/` |
| `make format` | `ruff format`, `ruff check --fix --select I`; `prettier --write` in `frontend/` |
| `make lint` | `ruff check --fix`, comment checker, docstring checker on `src/`; `eslint --fix` in `frontend/` |
| `make type` | `ty check`; `tsc -b --noEmit` in `frontend/` |
| `make test` | `pytest` with coverage (excludes `slow`, `core = "sysmon"` keeps tracing cheap, `concurrency = ["multiprocessing", "thread"]` measures match worker processes); `vitest run` in `frontend/` |
| `make test-slow` | `pytest -m slow` (deep perft and similar) |
| `make check` | `format lint type` (no tests) |
| `make perft` | `hive bench perft --depth 6` on the start position: a speed baseline that also fails on a count mismatch |
| `make dev-services` | compose up (Postgres, Garage) and wait until healthy, then `hive db upgrade` |
| `make dev` | `make dev-services`, then `hive serve --reload` on port 8000 and the vite dev server on port 5173, which proxies `/api` to it (set `HIVE_API_URL` to proxy elsewhere) |
| `make dev-down` | compose down (volumes are kept) |
| `make api-client` | `hive openapi` writes the schema from the app without a server or settings, then `openapi-typescript` generates `frontend/src/api/schema.ts` |
| `make install-hooks` | install pre-commit hooks (including commit-msg) |

`format`, `lint`, `type` and `test` each run a `-python` and a `-frontend` target (for
example `make lint-python`), so CI runs the two halves in separate jobs. From WP 42,
`format`, `lint` and `test` also run a `-rust` target: `format-rust` is `cargo fmt`,
`lint-rust` is `cargo clippy --all-targets -- -D warnings`, `cargo doc` with warnings as
errors and the comment line-length `grep`, and `test-rust` is `cargo test`. Rust needs no
`type-rust`: clippy compiles everything, and `type-python` runs `ty` over the stub. The
frontend targets run `npm ci` first when `frontend/node_modules` is missing or older than
the lockfile. Frontend targets are added by WP 13; dev targets by WP 10.

Frontend tooling (WP 13): ESLint uses `typescript-eslint` `strictTypeChecked` with the React
hooks and React refresh rules; Prettier uses a print width of 90 and sorts Tailwind classes.
The shadcn/ui primitives in `src/components/ui/` and the generated `src/api/schema.ts` are
not linted, and the generated file is not formatted either. TypeScript is pinned to 5.9
because `openapi-typescript` 7 declares a TypeScript 5 peer dependency.

## Claude Code hooks

`.claude/settings.json`:

- **PostToolUse** on `Edit|Write|MultiEdit`: `.claude/hooks/format-file.sh` reads the hook
  JSON from stdin, takes `tool_input.file_path`, and for `*.py` runs `ruff format`,
  `ruff check --fix`, the comment checker and, under `src/`, the docstring checker on that
  file only; for
  `frontend/src/**/*.{ts,tsx,css}` runs `prettier --write` (once `npm ci` has run). It exits
  0 when the file is not formattable and prints remaining lint and comment errors to stderr
  with exit code 2, so Claude sees and fixes them. From WP 42 it also formats edited
  `rust/**/*.rs` files with `rustfmt` and reports comment lines over 90 characters; clippy
  needs the whole crate, so it runs in the Stop hook.
- **Stop**: `make check`, so type errors surface before a session ends. (Replaces the
  current `make format lint`.) With the Rust half (clippy, `cargo doc`), its timeout goes
  up from 120 to 300 seconds.

## Pre-commit

`.pre-commit-config.yaml`: `end-of-file-fixer`, commitizen on `commit-msg` (conventional
commits), and a local hook running `make check` on commit, which includes the Rust half
from WP 42.

## CI (`.github/workflows/ci.yaml`)

On every PR and on `main`:

- Python: `uv sync --locked`, `make format-python lint-python type-python`,
  `make test-python` (includes shallow perft; API tests use testcontainers Postgres,
  available on GitHub-hosted runners), coverage floor.
- Frontend (from WP 13): `npm ci`, lint, format check, typecheck, test, build, and a check
  that `make api-client` produces no diff in `frontend/src/api/schema.ts`.
- Rust (from WP 42): the toolchain from `rust-toolchain.toml` with a cargo cache
  (`Swatinem/rust-cache`), `make format-rust` as a check, `make lint-rust`,
  `make test-rust` (including perft parity), against a bare `uv venv` for PyO3. The Python
  and frontend jobs build the extension in `uv sync` with the same cache; GitHub's runners
  have rustup, which installs the pinned toolchain on first use.
- `uv.lock`, `rust/Cargo.lock` and `package-lock.json` must be up to date (`--locked` /
  `npm ci`).

Release workflow (`release.yaml`) is added in WP 25, see `deployment.md`.

## Git conventions

- Branches: `feature/`, `fix/`, `chore/` prefixes.
- Conventional commits, enforced by commitizen, for example `feat(engine): ...`,
  `refactor(agents): ...`, `test(engine): ...`, `docs(plans): ...`, `build: ...`, `ci: ...`.
- PRs reference their issue with `Closes #N`.
- `uv.lock` and `rust/Cargo.lock` are committed.
