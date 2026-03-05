.PHONY: sync
sync:
	@uv sync


.PHONY: format
format:
	@uv run ruff format


.PHONY: lint
lint:
	@uv run ruff check --fix --output-format concise


.PHONY: type
type:
	@uv run ty check


.PHONY: test
test:
	@uv run pytest


.PHONY: check
check: format lint type
