.PHONY: sync
sync:
	@uv sync --all-groups --all-extras


.PHONY: format
format:
	@uv run ruff format
	@uv run ruff check --fix --select I --output-format concise


.PHONY: lint
lint:
	@uv run ruff check --fix --output-format concise
	@uv run python scripts/tooling/check_comments.py src tests scripts


.PHONY: type
type:
	@uv run ty check


.PHONY: test
test:
	@uv run pytest -m "not slow" --cov --cov-report term-missing


.PHONY: test-slow
test-slow:
	@uv run pytest -m slow


.PHONY: perft
perft:
	@uv run hive bench perft --depth 6


.PHONY: dev-services
dev-services:
	@docker compose -f deploy/compose.yaml up -d --wait
	@uv run hive db upgrade


.PHONY: dev
dev: dev-services
	@uv run hive serve --reload


.PHONY: dev-down
dev-down:
	@docker compose -f deploy/compose.yaml down


.PHONY: check
check: format lint type


.PHONY: install-hooks
install-hooks:
	@uv run pre-commit install
	@uv run pre-commit install --hook-type commit-msg
