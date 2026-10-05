.DEFAULT_GOAL := help

.PHONY: help setup install dev test test-fast test-science test-node qualify-node \
	test-frontend test-all lint fmt build docs clean node-scaffold generate-types

help:            ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup:           ## One-command project bootstrap (install + env + pre-commit)
	poetry install --with dev
	cd frontend && npm ci
	@[ -f .env ] || cp .env.example .env
	@if command -v pre-commit >/dev/null 2>&1; then pre-commit install; fi
	@echo "\n  ✔ Setup complete. Run 'make dev' to start.\n"

install:         ## Install backend (Poetry) + frontend (npm) deps
	poetry install --with dev
	cd frontend && npm ci

dev:             ## Start backend (port 8000) + frontend dev server (port 5173)
	@trap 'kill 0' EXIT; \
	poetry run uvicorn spectra_sherpa.app.main:create_app --factory --reload --port 8000 & \
	cd frontend && npm run dev

test:            ## Run backend pytest suite
	poetry run pytest tests/ -v --no-cov

test-fast:       ## Run the fast dataset, SDK, node-contract, and scaffold checks
	poetry run pytest tests/test_sdk_imports.py tests/test_sherpa_dataset.py tests/test_node_parameter_bounds.py tests/test_connection_validator.py tests/test_scaffold_node.py --no-cov -q

test-science:    ## Run scientific contracts without release or deployment machinery
	poetry run pytest tests/test_c2_*_contract.py tests/test_sdk_validate.py tests/test_sherpa_dataset.py tests/test_fold_graph_executor.py tests/test_canonical_train_test_split.py --no-cov -q

test-node:       ## Run focused evidence tests; NODE must be a canonical type such as model.pca
	poetry run python scripts/contributor_node.py test --node "$(NODE)"

qualify-node:    ## Check retained authorities and focused evidence; NODE=model.pca
	poetry run python scripts/contributor_node.py qualify --node "$(NODE)"

test-frontend:   ## Run frontend unit tests and type checking
	cd frontend && npm run test:unit -- --run
	cd frontend && npx vue-tsc --noEmit

test-all:        ## Run backend, frontend, lint, production build, and strict docs
	poetry run pytest tests/ -v --no-cov
	$(MAKE) lint
	cd frontend && npm run test:unit -- --run
	$(MAKE) build
	$(MAKE) docs

lint:            ## Run all linters (backend + frontend)
	poetry run black --check src/ tests/
	poetry run ruff check src/ tests/
	cd frontend && npx eslint src/ --max-warnings 300

fmt:             ## Auto-format backend (black + ruff) and frontend (prettier)
	poetry run black src/ tests/
	poetry run ruff check --fix src/ tests/
	cd frontend && npx prettier --write "src/**/*.{ts,vue,css}"

node-scaffold:   ## Generate boilerplate for a new processing node (interactive)
	poetry run python scripts/scaffold_node.py

generate-types:  ## Generate TypeScript types from OpenAPI schema
	cd frontend && npm run generate:types

build:           ## Build frontend into src/spectra_sherpa/static/
	cd frontend && npm run build

docs:            ## Build the public documentation with strict link checking
	poetry run mkdocs build --strict

clean:           ## Remove build artifacts
	rm -rf src/spectra_sherpa/static/assets
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
