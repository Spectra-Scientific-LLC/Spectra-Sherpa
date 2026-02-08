# Installation & Setup

## Quick Install (Recommended)

SpectraSherpa is pip-installable. The CLI starts the server and opens your browser automatically.

### Prerequisites

*   **Python 3.11+**: We recommend [Miniforge](https://github.com/conda-forge/miniforge) or Anaconda.
*   **SpectroChemPy**: The core spectroscopic library (installed as a dependency).

### Install from Source

```bash
cd Refactored
pip install -e .
```

### Run

```bash
spectra-sherpa
```

This starts the server on `http://localhost:8000` and opens your browser.
The frontend SPA is bundled inside the package — no separate Node.js step required.

**Options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--port PORT` | Server port | `8000` |
| `--host HOST` | Bind address | `127.0.0.1` |
| `--no-browser` | Don't auto-open browser | off |
| `--data-dir DIR` | Data storage directory | `~/.spectra_sherpa/` |
| `--version` | Show version and exit | |

*API Documentation will be available at [http://localhost:8000/docs](http://localhost:8000/docs).*

---

## Developer Setup (Frontend + Backend)

If you want to modify the Vue frontend or work on the backend with hot-reload:

### Backend (Python)

```bash
cd Refactored
pip install -e ".[dev]"

# Start with auto-reload
cd src/spectra_sherpa
uvicorn app.main:app --reload --port 8000
```

### Frontend (Vue 3 + TypeScript)

```bash
cd Refactored/frontend
npm install
npm run dev
```

*The dev frontend runs at [http://localhost:5173](http://localhost:5173) and proxies API calls to the backend at `:8000`.*

### Build Frontend into Package

After making frontend changes, rebuild the SPA into the package:

```bash
scripts/build_frontend.sh
```

This copies the built `dist/` into `src/spectra_sherpa/static/` so the CLI serves it directly.

---

## Database

The database schema is created automatically on first startup via
`Base.metadata.create_all`.  No manual migration step is needed for local mode.

> **Production upgrades:** When migrating an existing production database to a
> newer schema version, use Alembic:
> `cd src/spectra_sherpa && alembic upgrade heads`

---

## Docker / Cloud Deployment

For production Docker deployment, see the [DigitalOcean Deployment Guide](../deployment/DIGITAL_OCEAN.md).

Docker infrastructure lives in the `deploy/` directory:

```bash
cd deploy
docker compose -f docker-compose.prod.yaml up -d --build
```
