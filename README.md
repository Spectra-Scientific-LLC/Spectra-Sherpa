# SpectraSherpa

[![CI](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml/badge.svg)](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-spectrascientific.ai-blue)](https://docs.spectrascientific.ai)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)]()

**Local-first spectroscopy platform for chemometricians.**

SpectraSherpa is an integrated platform for spectroscopic data analysis, experiment management, and workflow automation. It bridges the gap between experimental data and advanced computational modeling with a visual DAG-based workflow builder.

## Quick Start

```bash
pip install spectra-sherpa
spectra-sherpa
```

Your browser opens to `http://localhost:8000`. No login required.

### With SpectroChemPy support

```bash
pip install spectra-sherpa[scp]
```

This enables native AnalysisDataset operations, SCP file format readers (JCAMP-DX, SPC, SPA, OPUS), and SpectroChemPy preprocessing methods.

## Features

- **Workflow Builder** — Visually design reproducible analysis pipelines (DAGs) with 100+ nodes for preprocessing, modeling, classification, diagnostics, and DOE
- **Type System** — URI-based port typing with registry-driven connection validation
- **Python & Notebook Export** — Generate standalone `.py` scripts or Jupyter notebooks from any workflow
- **Project Management** — Organize experiments, workflows, and scripts with versioned snapshots
- **Experiment Tracking** — DOE support with 96-well plate layouts, samples, mixtures, and factor definitions
- **LLM Chat** — Bring-your-own-key AI assistant for spectral analysis and workflow questions
- **Sherpa AI Advisor** — Cloud-powered domain-expert guidance with peak identification, code generation, report writing, and agentic tool use (available via [subscription](https://spectrascientific.ai))
- **Plugin System** — Extend the node library and tool registry via Python entry points or drop-in modules
- **Deploy** — Batch prediction, folder watching, execution run tracking
- **Demo Mode** — Public-facing demo profile with configurable usage limits and upgrade prompts
- **Data Privacy Controls** — Per-user fine-grained egress permissions for LLM context, cloud sync, and exports

## Installation

### Requirements

- Python 3.11+
- Node.js 22+ (for frontend development only)

### From source (minimal)

This installs the core platform without optional scientific extras — enough to run the app and work on the backend or frontend:

```bash
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd spectrasherpa
poetry install --with dev
spectra-sherpa
```

### Optional extras

Extras are opt-in packages that enable additional capabilities. You can add them to either the minimal install above or the full development setup below.

| Extra | Install | Description |
|-------|---------|-------------|
| `scp` | `pip install spectra-sherpa[scp]` | SpectroChemPy support (CeCILL-B, opt-in) |

## Development Setup

For full-stack development with all scientific features enabled, install with extras:

```bash
# Backend (includes SpectroChemPy + Sherpa AI extras)
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd spectrasherpa
poetry install --with dev --extras "scp sherpa"

# Frontend
cd frontend
npm install
npm run dev        # Dev server at http://localhost:5173
```

### Running Tests

```bash
# Backend (from repo root)
poetry run pytest tests/ -v --no-cov

# Frontend type check + build
cd frontend && npx vue-tsc --noEmit && npm run build
```

### Automated Test Triggers (GitHub Actions)

Backend/frontend/docs CI runs automatically when:

- A commit is pushed to `main`
- A pull request targets `main`
- A maintainer manually starts the workflow (`workflow_dispatch`)

## Documentation

Full documentation is available at [docs.spectrascientific.ai](https://docs.spectrascientific.ai):

- [Installation](docs/user/installation.md)
- [Quickstart](docs/user/quickstart.md)
- [Configuration](docs/user/configuration.md)
- [Node Reference](docs/user/reference/nodes.md)

## Acknowledgments

SpectraSherpa builds on [scikit-learn](https://scikit-learn.org/) and [NumPy](https://numpy.org/) for core data analysis. It optionally supports [SpectroChemPy](https://www.spectrochempy.fr/) (by CEA/CNRS/INRIA, licensed under [CeCILL-B](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html)) for advanced spectral file formats and preprocessing.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

> [!IMPORTANT]
> This project requires contributors to sign a Contributor License Agreement (CLA).
> When you open a Pull Request, a bot will comment with instructions. You can sign by commenting:
> `I have read the CLA Document and I hereby sign the CLA`

## Privacy-First Design

SpectraSherpa is built for IP-sensitive environments.

- **Local-By-Default**: No data leaves your machine unless you explicitly configure it.
- **Egress Control**: The system enforces a "Deny All" network policy by default (`ensure_egress_defaults`). You must opt-in to features that require network access (like NIST library downloads or LLM assistance).
- **Lab-Grade Safety**: Integrated features like **Leader Locks** and **Alembic Migrations** ensure data integrity even in shared or multi-user lab environments.

## License

SpectraSherpa is licensed under the AGPL-3.0. See [LICENSE](./LICENSE) for details.

Commercial licenses for OEM integration and cloud hosting are available from Spectra Scientific LLC.
