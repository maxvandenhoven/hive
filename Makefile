.PHONY: sync
sync:
	@uv sync --all-groups --all-extras
	@cd frontend && npm ci --silent


# Installs the frontend dependencies on first use and whenever the lockfile changes.
frontend/node_modules: frontend/package-lock.json
	@cd frontend && npm ci --silent
	@touch frontend/node_modules


.PHONY: format format-python format-frontend
format: format-python format-frontend

format-python:
	@uv run ruff format
	@uv run ruff check --fix --select I --output-format concise

format-frontend: frontend/node_modules
	@cd frontend && npm run --silent format


.PHONY: lint lint-python lint-frontend
lint: lint-python lint-frontend

lint-python:
	@uv run ruff check --fix --output-format concise
	@uv run python scripts/tooling/check_comments.py src tests scripts
	@uv run python scripts/tooling/check_docstrings.py src

lint-frontend: frontend/node_modules
	@cd frontend && npm run --silent lint:fix


.PHONY: type type-python type-frontend
type: type-python type-frontend

type-python:
	@uv run ty check

type-frontend: frontend/node_modules
	@cd frontend && npm run --silent typecheck


.PHONY: test test-python test-frontend
test: test-python test-frontend

test-python:
	@uv run pytest -m "not slow" --cov --cov-report term-missing

test-frontend: frontend/node_modules
	@cd frontend && npm run --silent test


.PHONY: test-slow
test-slow:
	@uv run pytest -m slow


.PHONY: perft
perft:
	@uv run hive bench perft --depth 6


# Exports the OpenAPI schema from the app, without a server, and generates the types.
.PHONY: api-client
api-client: frontend/node_modules
	@uv run hive openapi --output frontend/openapi.json
	@cd frontend && npm run --silent api-client
	@rm frontend/openapi.json


# Writes the rule diagrams of the help, with their targets checked against the engine.
.PHONY: rules-diagrams
rules-diagrams:
	@uv run python scripts/rules_diagrams.py


.env:
	@cp .env.example .env


.PHONY: dev-services
dev-services: .env
	@docker compose -f deploy/compose.yaml up -d --wait
	@uv run hive db upgrade


# Serves the API on port 8000 and the frontend with hot reload on port 5173, which
# forwards `/api` to the API. The vite server is stopped when the API server exits.
.PHONY: dev
dev: dev-services frontend/node_modules
	@npm --prefix frontend run --silent dev & trap "kill $$!" EXIT; \
		uv run hive serve --reload


.PHONY: dev-down
dev-down:
	@docker compose -f deploy/compose.yaml down


.PHONY: check
check: format lint type


.PHONY: install-hooks
install-hooks:
	@uv run pre-commit install
	@uv run pre-commit install --hook-type commit-msg
