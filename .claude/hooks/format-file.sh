#!/usr/bin/env bash
# PostToolUse hook: format the Python file Claude just edited and report remaining lint
# and comment style errors. Exit code 2 feeds stderr back to Claude; exit code 0 means
# nothing to report.
set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
    echo "format-file.sh: jq not found, skipping formatting" >&2
    exit 0
fi

file_path="$(jq -r '.tool_input.file_path // empty')"
repo_root="$(realpath "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}")"

# Only format existing Python files inside the repository.
[[ "$file_path" == *.py && -f "$file_path" ]] || exit 0
file_path="$(realpath "$file_path")"
[[ "$file_path" == "$repo_root"/* ]] || exit 0

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
