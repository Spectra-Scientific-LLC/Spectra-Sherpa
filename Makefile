.DEFAULT_GOAL := help

.PHONY: help setup install dev test test-all lint fmt build clean

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

test-all:        ## Run backend tests + frontend type-check
	poetry run pytest tests/ -v --no-cov
	cd frontend && npx vue-tsc --noEmit

lint:            ## Run all linters (backend + frontend)
	poetry run black --check src/ tests/
	poetry run ruff check src/ tests/
	cd frontend && npx eslint src/ --max-warnings 300

fmt:             ## Auto-format backend (black + ruff) and frontend (prettier)
	poetry run black src/ tests/
	poetry run ruff check --fix src/ tests/
	cd frontend && npx prettier --write "src/**/*.{ts,vue,css}"

build:           ## Build frontend into src/spectra_sherpa/static/
	cd frontend && npm run build

clean:           ## Remove build artifacts
	rm -rf src/spectra_sherpa/static/assets
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
