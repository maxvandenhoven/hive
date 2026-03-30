.PHONY: sync
sync:
	@uv sync --all-groups --all-extras


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
	@uv run pytest --cov src


.PHONY: check
check: format lint type
