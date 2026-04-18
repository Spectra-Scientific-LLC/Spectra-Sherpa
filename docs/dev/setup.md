# Developer Setup

This guide is for contributors who want to modify the SpectraSherpa codebase.

## Prerequisites
- Python 3.11+
- Node.js 22+ (for Frontend)
- [Poetry](https://python-poetry.org/) (`pip install poetry`)
- Git

## Backend Setup (Python)

1.  Clone the repository:
    ```bash
    git clone https://github.com/Spectra-Scientific-LLC/spectra-sherpa.git
    cd spectra-sherpa
    ```

2.  Install dependencies with Poetry:
    ```bash
    poetry install --with dev
    ```

3.  (Optional) Install SpectroChemPy for full node support:
    ```bash
    poetry install --with dev -E scp
    ```
    Without SCP, ~38 nodes run on numpy/scipy/sklearn. With SCP, 11 additional spectral analysis nodes are available.

4.  Run the server with hot-reloading:
    ```bash
    poetry run uvicorn spectra_sherpa.app.main:create_app --factory --reload --port 8000
    ```

    In all modes (`local`, `hybrid`, `enterprise`), the frontend depends on a healthy config response from the backend. If config loading fails, the UI now fails closed instead of pretending the app is in local mode.

## Frontend Setup (Vue 3 + TypeScript)

1.  Navigate to the frontend directory:
    ```bash
    cd frontend
    ```

2.  Install dependencies:
    ```bash
    npm ci
    ```

3.  Start the development server:
    ```bash
    npm run dev
    ```
    The frontend will run at `http://localhost:5173` and proxy WebSocket requests to port `8000`.

## Quick Start (Both Together)

```bash
make dev    # starts backend (:8000) + frontend (:5173) — Ctrl+C stops both
```

## Running Tests

```bash
make test       # or: poetry run pytest tests/ -v --no-cov
```

To run a specific test file:
```bash
poetry run pytest tests/test_sherpa_dataset.py -v --no-cov
```

## Linting

```bash
# Frontend (enforced in CI)
cd frontend && npm run lint

# Backend (available locally, CI enforcement pending format-only PR)
poetry run ruff check src/ tests/
poetry run black --check src/ tests/
```

## Building for Release

To bundle your frontend changes into the Python package:
```bash
cd frontend && npm run build
```
Vite is configured to build directly into `src/spectra_sherpa/static/` — no manual copy step needed.

## Environment Variables

Copy `.env.example` to `.env` for local configuration. The defaults work with zero changes.
For direct Python launches, the app also loads `~/.env` as a shared base layer and then lets the repo-local `.env` override it. Docker Compose deployments are separate: they read the compose env file, not `~/.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_MODE` | `local` | `local`, `hybrid`, or `enterprise` |
| `DATA_DIR` | `./data` in source checkout, `~/.spectra_sherpa` when installed | App data root for experiments, exports, manifests, and prepared-data override sidecars |
| `DATABASE_URL` | `sqlite:///./spectra_sherpa.db` | Database connection string |
| `CHAT_ENDPOINT_URL` | (none) | Base URL of an OpenAI-compatible endpoint for the OSS BYO chat assistant |
| `CHAT_ENDPOINT_KEY` | (none) | API key for the BYO chat endpoint |
| `CHAT_ENDPOINT_MODEL` | `deepseek-chat` | Model identifier for the BYO chat endpoint |

Experiment-backed files and materialized example/template files are resolved against the active `DATA_DIR` at runtime, not at module import time. This matters when switching between local, hybrid, enterprise, test, or packaged deployments.

See `.env.example` for all available settings including hybrid/enterprise options.
