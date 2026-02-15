# Developer Setup

This guide is for contributors who want to modify the SpectraSherpa codebase.

## Prerequisites
- Python 3.11+
- Node.js 18+ (for Frontend)
- Git

## Backend Setup (Python)

1.  Clone the repository:
    ```bash
    git clone https://github.com/Spectra-Scientific-LLC/spectra-sherpa.git
    cd spectra-sherpa
    ```

2.  Create a virtual environment and install in editable mode:
    ```bash
    python -m venv venv
    source venv/bin/activate
    pip install -e ".[dev]"
    ```

3.  (Optional) Install SpectroChemPy for full node support:
    ```bash
    pip install -e ".[dev,scp]"
    ```
    Without SCP, ~38 nodes run on numpy/scipy/sklearn. With SCP, 11 additional spectral analysis nodes are available.

4.  Run the server with hot-reloading:
    ```bash
    cd src/spectra_sherpa
    uvicorn app.main:app --reload --port 8000
    ```

## Frontend Setup (Vue 3 + TypeScript)

1.  Navigate to the frontend directory:
    ```bash
    cd frontend
    ```

2.  Install dependencies:
    ```bash
    npm install
    ```

3.  Start the development server:
    ```bash
    npm run dev
    ```
    The frontend will run at `http://localhost:5173` and proxy API requests to port `8000`.

## Running Tests

```bash
PYTHONPATH=src/spectra_sherpa python -m pytest tests/ --no-cov
```

The `PYTHONPATH` is required because the `app` package lives under `src/spectra_sherpa/app/`.

To run a specific test file:
```bash
PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_analysis_dataset.py -v --no-cov
```

## Building for Release

To bundle your frontend changes into the Python package:
```bash
cd frontend && npm run build
```
This builds the Vue app into `frontend/dist/`, then copy to `src/spectra_sherpa/static/`:
```bash
rm -rf src/spectra_sherpa/static/assets
cp -r frontend/dist/* src/spectra_sherpa/static/
```

## Environment Variables

Create a `.env` file in `src/spectra_sherpa/` for local configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_MODE` | `local` | `local`, `hybrid`, or `enterprise` (`demo` accepted as alias) |
| `DATABASE_URL` | `sqlite:///./spectra_sherpa.db` | Database connection string |
| `SHERPA_ENGINE_API_KEY` | (none) | Anthropic API key for Sherpa Engine |
| `SECRET_KEY` | (auto-generated) | JWT signing key (required in hybrid/enterprise) |
