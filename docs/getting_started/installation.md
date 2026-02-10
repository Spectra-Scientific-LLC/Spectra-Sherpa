# Installation & Setup

## Quick Install (Recommended)

SpectraSherpa is pip-installable. The CLI starts the server and opens your browser automatically.

### Prerequisites

*   **Python 3.11+**: We recommend [Miniforge](https://github.com/conda-forge/miniforge) or Anaconda.
*   **SpectroChemPy**: The core spectroscopic library (installed as a dependency).

### Install from PyPI

```bash
pip install spectra-sherpa
```

Or install from a local checkout:

```bash
cd Refactored
pip install -e .
```

### Launch

```bash
spectra-sherpa
```

This starts the server on `http://localhost:8000` and opens your browser.
The frontend SPA is bundled inside the package — no separate Node.js step required.
No login needed — local mode runs as a single-user desktop tool (like Jupyter).

**CLI Options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--port PORT` | Server port | `8000` |
| `--host HOST` | Bind address | `127.0.0.1` |
| `--no-browser` | Don't auto-open browser | off |
| `--data-dir DIR` | Data storage directory | `~/.spectra_sherpa/` |
| `--version` | Show version and exit | |

*API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs).*

### Optional: auto-clear busy port on startup

If another process is already bound to your selected CLI port, you can opt in
to automatic port cleanup via `.env`:

```bash
# .env
KILL_PORT_ON_START=true
KILL_PORT_GRACE_SECONDS=2.0
KILL_PORT_FORCE=true
```

With this enabled, `spectra-sherpa` will attempt `SIGTERM`, wait for the grace
period, then optionally send `SIGKILL` if the port remains busy.
This feature uses `lsof`; if `lsof` is unavailable, startup continues with a warning.

---

## Choosing a Mode

SpectraSherpa runs in one of three modes. **Local mode** is the default — no configuration needed.

| Mode | Who it's for | Auth | Network |
|------|-------------|------|---------|
| **Local** (default) | Individual use on your laptop/desktop | None | Offline by default |
| **Hybrid** | Local app + cloud identity / GPU offload | Loopback bypass | LLM & NIST enabled |
| **Demo** | Cloud-hosted evaluation server | JWT login required | Full multi-user |

For detailed configuration of each mode, see [Modes & Configuration](modes.md).

---

## Data Storage

SpectraSherpa stores all data under `~/.spectra_sherpa/` (or `<repo>/data` in dev checkouts):

```
~/.spectra_sherpa/
├── spectra_platform.db    # SQLite database
├── experiments/           # Uploaded spectra and results
├── calibrations/          # Calibration models
├── nist_library/          # Downloaded NIST reference spectra
└── conversations.json     # LLM chat history
```

Override with `--data-dir` or the `DATA_DIR` environment variable.

---

## Configuring LLM Access (Optional)

AI features (workflow generation, chat assistant) require an LLM API key and network egress. All core spectroscopy features work without them.

Create a `.env` file in your working directory:

```bash
# Enable network egress (required for LLM and NIST features)
EGRESS_ENABLED=true

# Add one or more providers — only the ones you want:
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...       # Most cost-effective
GEMINI_API_KEY=AI...
```

Restart SpectraSherpa after editing `.env`. Configured providers appear in **Settings > API Keys**.

You can also add API keys in-app under **Settings > API Keys** without editing files.

| Provider | Default Model | Env Variable |
|----------|--------------|-------------|
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Anthropic | `claude-sonnet-4-5-20250929` | `ANTHROPIC_API_KEY` |
| DeepSeek | `deepseek-chat` | `DEEPSEEK_API_KEY` |
| Google | `gemini-1.5-pro` | `GEMINI_API_KEY` |

> **Security note:** In local mode, API keys are stored encrypted on your machine. They never leave your computer unless you explicitly use an LLM feature.

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

The database schema is created automatically on first startup.
No manual migration step is needed for local mode.

> **Production (hybrid/demo):** Schema migrations are applied automatically via
> Alembic on startup. If migrations fail, the app refuses to start (fail-fast
> behavior ensures you never run against an outdated schema).

---

## Docker / Cloud Deployment

For production Docker deployment, see the [DigitalOcean Deployment Guide](../deployment/DIGITAL_OCEAN.md).
