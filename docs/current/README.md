# SpectraSherpa

SpectraSherpa (`spectra-sherpa`) is a pip-installable platform for spectroscopic data analysis, synthesis, and workflow automation.

## Quick Start

```bash
pip install -e .
spectra-sherpa
```

## Documentation

**Complete documentation is available in the `docs/` directory.**

To view the documentation as a website (recommended):

1.  Install MkDocs:
    ```bash
    pip install mkdocs
    ```
2.  Run the documentation server:
    ```bash
    mkdocs serve
    ```
3.  Open [http://127.0.0.1:8100](http://127.0.0.1:8100) in your browser.

Alternatively, you can browse the Markdown files directly in the `docs/` tree.

## Repository Layout

```
spectra-sherpa/
├── pyproject.toml                  # Package definition (pip install -e .)
├── src/spectra_sherpa/         # The pip-installable package
│   ├── __init__.py                 # Version + meta-path finder
│   ├── cli.py                      # `spectra-sherpa` CLI entry point
│   ├── app/                        # FastAPI backend (all services, routes, models)
│   ├── libs/                       # NIST scraper
│   ├── alembic/                    # Database migrations
│   └── static/                     # Pre-built Vue frontend (committed)
├── frontend/                       # Vue 3 source (dev only)
├── tests/                          # Test suite
├── scripts/                        # Build & migration scripts
├── deploy/                         # Docker / cloud infrastructure
└── docs/                           # This documentation
```

## Quick Links

*   [Installation Guide](../getting_started/installation.md)
*   [Quickstart](../getting_started/quickstart.md)
*   [User Guide](../user_guide/experiments.md)
