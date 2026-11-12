#!/usr/bin/env bash
# PostToolUse hook: format the Python, Rust or frontend file Claude just edited and report
# remaining lint and comment style errors. Exit code 2 feeds stderr back to Claude; exit
# code 0 means nothing to report.
set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
    echo "format-file.sh: jq not found, skipping formatting" >&2
    exit 0
fi

file_path="$(jq -r '.tool_input.file_path // empty')"
repo_root="$(realpath "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}")"

# Only format existing files inside the repository.
[[ -f "$file_path" ]] || exit 0
file_path="$(realpath "$file_path")"
[[ "$file_path" == "$repo_root"/* ]] || exit 0

# Frontend sources are formatted with Prettier once the dependencies are installed. It
# runs from `frontend/` so `.prettierignore` skips the generated API types.
if [[ "$file_path" == "$repo_root"/frontend/src/* && "$file_path" =~ \.(ts|tsx|css)$ ]]; then
    prettier="$repo_root/frontend/node_modules/.bin/prettier"
    [[ -x "$prettier" ]] || exit 0

    if ! output="$(cd "$repo_root/frontend" && "$prettier" --write --log-level warn "$file_path" 2>&1)"; then
        echo "$output" >&2
        exit 2
    fi
    exit 0
fi

# Rust sources are formatted with rustfmt (the pinned toolchain of `rust-toolchain.toml`).
# Clippy needs the whole crate, so it runs in the Stop hook (`make check`).
if [[ "$file_path" == "$repo_root"/rust/* && "$file_path" == *.rs ]]; then
    rustfmt="${CARGO_HOME:-$HOME/.cargo}/bin/rustfmt"
    [[ -x "$rustfmt" ]] || rustfmt="$(command -v rustfmt)" || exit 0

    if ! output="$(cd "$repo_root" && "$rustfmt" --edition 2024 "$file_path" 2>&1)"; then
        echo "$output" >&2
        exit 2
    fi
    if output="$(grep -nE '^.{91,}$' "$file_path")"; then
        echo "$file_path: lines over 90 characters:" >&2
        echo "$output" >&2
        exit 2
    fi
    exit 0
fi

[[ "$file_path" == *.py || "$file_path" == *.pyi ]] || exit 0

cd "$repo_root" || exit 0

if ! output="$(uv run --quiet ruff format --quiet "$file_path" 2>&1)"; then
    echo "$output" >&2
    exit 2
fi
if ! output="$(uv run --quiet ruff check --fix --quiet --output-format concise "$file_path" 2>&1)"; then
    echo "$output" >&2
    exit 2
fi
if ! output="$(uv run --quiet python scripts/tooling/check_comments.py "$file_path" 2>&1)"; then
    echo "$output" >&2
    exit 2
fi
# Docstring sections are only enforced in the package, not in tests or scripts.
if [[ "$file_path" == "$repo_root"/src/* ]] &&
    ! output="$(uv run --quiet python scripts/tooling/check_docstrings.py "$file_path" 2>&1)"; then
    echo "$output" >&2
    exit 2
fi
