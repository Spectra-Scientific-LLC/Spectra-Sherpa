# Installation (OSS User)

SpectraSherpa is a local-first Python application. You can install it on your machine just like any other Python package.

## Prerequisites

- **Python 3.11 or 3.12.** 3.13 may work, but the scientific stack SpectraSherpa depends on (numpy, scipy, scikit-learn, SpectroChemPy) does not yet ship full pre-built wheels for 3.13+ on every platform, so installs can fall back to a from-source compile that fails or takes a very long time. Python 3.14 is not currently recommended.
- **macOS, Linux, or Windows.** Apple Silicon (arm64) is supported.
- A working `pip`. On Homebrew Python the command is sometimes `pip3` rather than `pip`; or use `python3 -m pip`.

If you have multiple Python versions installed, the cleanest path is to create a dedicated virtual environment so the SpectraSherpa install does not interfere with system packages:

```bash
python3.11 -m venv ~/.venvs/spectra-sherpa
source ~/.venvs/spectra-sherpa/bin/activate     # Linux/macOS
# or:  ~\.venvs\spectra-sherpa\Scripts\activate  # Windows PowerShell
```

## Quick Install

```bash
pip install spectra-sherpa
```

To enable the SpectroChemPy-backed example datasets and ~11 spectral-analysis nodes, install the `scp` extra as well:

```bash
pip install "spectra-sherpa[scp]"
```

## Install From Source

If you want to track the development branch, file a contribution, or work from a checkout instead of a published release:

```bash
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa

pip install poetry                                # Poetry 2.x manages dependencies
poetry env use python3.11                         # pin the venv to a supported Python
poetry install --with dev --extras "scp"          # full dev install + SpectroChemPy
poetry run spectra-sherpa                         # launches from the checkout
```

If `poetry install` reports `pyproject.toml changed significantly since poetry.lock was last generated`, run `poetry lock` (the bare command — Poetry 2.x removed the `--no-update` flag because that is now the default behavior) and try the install again.

## Launching the Application

Once installed, start the application from your terminal:

```bash
spectra-sherpa
```

This will:
1.  Start the local server on `http://localhost:8000`.
2.  Automatically open your default web browser.
3.  Initialize a local database in `~/.spectra_sherpa/`.

**No login is required.** In default "Local Mode", the application runs as a single-user desktop tool, similar to Jupyter Notebook.

### What you should see in the terminal

A successful first launch prints (in order):

```
Starting SpectraSherpa v0.4.1
  Mode:   local
  URL:    http://127.0.0.1:8000
  Press Ctrl+C to stop.

Loading SpectroChemPy API...
INFO:     Started server process
INFO:     Waiting for application startup.
INFO spectra_sherpa.app.main: Phase 1 complete
INFO spectra_sherpa.app.main: Phase 2: leader one-time startup tasks ...
INFO spectra_sherpa.app.main:   → ensure_database_ready
INFO alembic.runtime.migration: Will assume non-transactional DDL.
INFO spectra_sherpa.app.db.init_db: Alembic migrations applied successfully
... (Phase 2/3 logs) ...
INFO spectra_sherpa.app.main: Application startup complete
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

The browser should not be opened until you see the final `Uvicorn running on http://127.0.0.1:8000` line. Earlier output (font installation, alembic migrations, Phase 1/2/3 logs) is normal startup activity, not "ready."

The first launch can take **30–90 seconds** because SpectroChemPy populates its font and stylesheet cache and matplotlib rebuilds its font index. Subsequent launches start in a few seconds.

## Command Line Options

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--port` | Server port | `8000` |
| `--host` | Bind address | `127.0.0.1` |
| `--no-browser` | Prevent browser from opening | `False` |
| `--data-dir` | Location for database and files | `~/.spectra_sherpa/` |
| `--reload` | Auto-reload on source changes (dev only) | `False` |
| `--version` | Print version and exit | — |

Example:

```bash
spectra-sherpa --port 9000 --no-browser
```

## Troubleshooting

### `ValueError: the greenlet library is required to use this function. No module named 'greenlet'`

`greenlet` is a base dependency of `spectra-sherpa` (SQLAlchemy 2.x async needs it on every platform, regardless of driver). A clean `pip install spectra-sherpa` or `poetry install` pulls it automatically. If you see this in an existing virtual environment that pre-dates v0.4.1, recreate the venv or install greenlet directly:

```bash
pip install greenlet
# or, for a poetry checkout:
poetry env remove --all && poetry install --with dev --extras "scp"
```

### `pyproject.toml changed significantly since poetry.lock was last generated`

You're on a checkout where the lock is stale relative to `pyproject.toml`. Regenerate the lock without changing pinned versions:

```bash
poetry lock
poetry install --with dev --extras "scp"
```

(Note: Poetry 2.x removed the `--no-update` flag — `poetry lock` alone now does the right thing.)

### `ERR_CONNECTION_REFUSED` opening `http://127.0.0.1:8000`

The server is still in startup. Wait for the `Uvicorn running on http://127.0.0.1:8000` log line in the terminal before opening the browser. First launch can take 30–90 seconds.

### Banner shows an old version after upgrading

Stale virtual environment. `pip install --upgrade --force-reinstall spectra-sherpa` (or `poetry env remove --all && poetry install`) rebuilds against the new package metadata. The runtime banner is read live from installed-package metadata, so once the upgrade succeeds the banner reflects the actual version.

### Port 8000 already in use

```bash
spectra-sherpa --port 9000
```

Or, in `.env`, set `KILL_PORT_ON_START=true` to free the port automatically on launch.

### `command not found: pip` on Homebrew Python

Homebrew Python doesn't expose `pip` as a bare command — use `pip3` or `python3 -m pip` instead.

```bash
python3 -m pip install spectra-sherpa
```
