# SpectraSherpa

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
- **LLM Chat & Agentic Workflows** — Multi-provider AI assistant (OpenAI, Anthropic, DeepSeek, Gemini) with MCP tool integration for workflow generation and spectral analysis
- **Sherpa AI Advisor** — Cloud-connected guidance with tiered data egress controls (hybrid mode)
- **Plugin System** — Extend the node library and tool registry via Python entry points or drop-in modules
- **Deploy** — Batch prediction, folder watching, execution run tracking
- **Data Privacy Controls** — Per-user fine-grained egress permissions for LLM context, NIST queries, and exports

## Deployment Modes

| Mode | Use Case |
|------|----------|
| **Local** (default) | Single user, no login, SQLite, no network required |
| **Hybrid** | Local app + cloud identity linking + managed LLM keys + Sherpa advisor |
| **Enterprise** | Multi-user server with JWT auth, PostgreSQL, rate limiting, session expiry |

> `APP_MODE=demo` is accepted as a deprecated alias for `enterprise`.
> For marketing labels (login page branding), use `SITE_PROFILE=demo`.

## Installation

### Requirements

- Python 3.11+
- Node.js 18+ (for frontend development only)

### From source

```bash
git clone https://github.com/Spectra-Scientific-LLC/spectrasherpa.git
cd spectrasherpa
poetry install --with dev
spectra-sherpa
```

### Optional extras

| Extra | Install | Description |
|-------|---------|-------------|
| `scp` | `pip install spectra-sherpa[scp]` | SpectroChemPy support (CeCILL-B, opt-in) |
| `sherpa` | `pip install spectra-sherpa[sherpa]` | Sherpa AI advisor (Anthropic Claude) |
| `cloud` | `pip install spectra-sherpa[cloud]` | PostgreSQL + Gunicorn for production |

## Development Setup

```bash
# Backend
git clone https://github.com/Spectra-Scientific-LLC/spectrasherpa.git
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
PYTHONPATH=src:src/spectra_sherpa python -m pytest tests/ -v --no-cov

# Frontend type check + build
cd frontend && npx vue-tsc --noEmit && npm run build
```

## Documentation

Full documentation is available at [docs/](docs/index.md):

- [Installation](docs/user_guide/installation.md)
- [Quickstart](docs/user_guide/quickstart.md)
- [Configuration](docs/user_guide/configuration.md)
- [Node Reference](docs/reference/nodes.md)
- [Enterprise Mode](docs/server/enterprise_mode.md)
- [Docker Deployment](docs/deployment/DIGITAL_OCEAN.md)

## Acknowledgments

SpectraSherpa builds on [SpectroChemPy](https://www.spectrochempy.fr/) by CEA/CNRS/INRIA for spectral data handling. SpectroChemPy is licensed under [CeCILL-B](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html) and is an optional dependency.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

> [!IMPORTANT]
> This project requires contributors to sign a Contributor License Agreement (CLA).
> When you open a Pull Request, a bot will comment with instructions. You can sign by commenting:
> `I have read the CLA Document and I hereby sign the CLA`

## License

SpectraSherpa is open source software licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE).

Commercial licenses for OEM integration and cloud hosting are available from Spectra Scientific LLC.

See [LICENSE](LICENSE) for the full text.
