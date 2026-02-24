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

This enables SpectroChemPy-powered algorithms (PCA, PLS, MCR-ALS, EFA, SIMPLISMA), SCP file format readers (JCAMP-DX, SPC, SPA, OPUS), and coordinate-aware preprocessing (rubberband baseline, etc.).

## Features

- **Workflow Builder** — Visually design reproducible analysis pipelines (DAGs) with 100+ nodes for preprocessing, modeling, classification, diagnostics, and DOE
- **Model Artifacts** — Train, persist, and reload models (PCA, PLS, MCR, PLSDA, KNN, SIMCA) with a generic Load & Apply node
- **Type System** — URI-based port typing with registry-driven connection validation
- **Python & Notebook Export** — Generate standalone `.py` scripts or Jupyter notebooks from any workflow
- **Project Management** — Organize experiments, workflows, scripts, and models with versioned snapshots
- **Experiment Tracking** — DOE support with 96-well plate layouts, samples, mixtures, and factor definitions
- **Deploy** — Batch prediction, folder watching, execution run tracking with model provenance
- **LLM Chat** — Bring-your-own-key AI assistant for spectral analysis and workflow questions
- **Plugin System** — Extend the node library and tool registry via Python entry points or drop-in modules
- **Data Privacy Controls** — Fine-grained egress permissions for LLM context and exports

## Core Concepts

### Projects, Workflows, and Models

SpectraSherpa organizes work into **Projects** — containers that group related experiments, workflows, scripts, and trained models:

```
Project
├── Experiments        — Raw spectral data files with version history
│   └── Files          — .csv, .jdx, .spc, .spa, .spg, .opus, .mat, ...
├── Workflows          — DAG-based analysis pipelines
│   ├── Nodes + Edges  — Processing graph definition
│   ├── Versions       — Immutable snapshots on each save
│   └── Execution Runs — Saved results with diagnostics
│       └── Batch Predictions — Per-file results for deploy
├── Scripts            — Python exports (auto-generated or manual)
└── Models             — Trained model artifacts (PCA, PLS, MCR, ...)
    ├── manifest.json  — Metadata, metrics, feature axis
    └── arrays.npz     — Numpy arrays (loadings, scores, etc.)
```

- **Experiments** hold your raw spectral data. Upload files or import SpectroChemPy example datasets.
- **Workflows** define processing pipelines as directed acyclic graphs. Each workflow tracks its version history and execution runs.
- **Models** are trained model artifacts produced by modeling nodes (PCA, PLS, MCR, etc.). They persist to disk and can be reloaded in new workflows via the **Load & Apply Model** node.
- **Scripts** are Python exports generated from workflows for standalone reproducibility.

### Workflow Execution

Workflows execute as a topological sort of nodes. Data flows through typed ports:

```
Data Source → Preprocessing → Modeling → Diagnostics
                                ↓
                          Model Artifact (saved)
                                ↓
                    Load & Apply Model (new data)
```

Training nodes emit model artifacts that are automatically persisted. The **Load & Apply Model** node loads any saved model and applies `transform()` (decomposition) or `predict()` (classification) to new data.

### Deployment Modes

| Mode | Auth | Use Case |
|------|------|----------|
| `local` | None (single-user) | Desktop analysis, privacy-first |
| `hybrid` | JWT + API key | Local processing, optional cloud offload |
| `enterprise` | Full multi-user auth | Shared lab environments |

## Installation

### Requirements

- Python 3.11+
- Node.js 22+ (for frontend development only)

### From source (minimal)

This installs the core platform without optional scientific extras — enough to run the app and work on the backend or frontend:

```bash
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa
poetry install --with dev
spectra-sherpa
```

### Optional extras

Extras are opt-in packages that enable additional capabilities. You can add them to either the minimal install above or the full development setup below.

| Extra | Install | Description |
|-------|---------|-------------|
| `scp` | `pip install spectra-sherpa[scp]` | [SpectroChemPy](https://www.spectrochempy.fr/) algorithms and file readers (see [Third-Party Notices](#third-party-notices)) |

## Development Setup

For full-stack development with all scientific features enabled, install with extras:

```bash
# Backend (includes SpectroChemPy + Sherpa AI extras)
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa
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
- [Architecture](docs/dev/architecture.md)
- [Node Reference](docs/user/reference/nodes.md)

## Third-Party Notices

### SpectroChemPy

SpectraSherpa optionally integrates with [SpectroChemPy](https://www.spectrochempy.fr/), a Python library for advanced spectroscopic data analysis developed by **Arnaud Travert and Christian Fernandez** at the [Laboratoire Catalyse et Spectrochimie (LCS)](https://www.lcs.ensicaen.fr/), ENSICAEN / Universit&eacute; de Caen / CNRS.

SpectroChemPy is licensed under the [CeCILL-B](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html) free software license, which is compatible with BSD-style licenses. Because CeCILL-B is not compatible with AGPL-3.0, SpectroChemPy is distributed as an **opt-in extra** (`pip install spectra-sherpa[scp]`) and is never bundled into the core package.

When installed, SpectroChemPy powers the following SpectraSherpa nodes:

| Node | Algorithm | SpectroChemPy Docs |
|------|-----------|-------------------|
| PCA | Principal Component Analysis | [spectrochempy.PCA](https://www.spectrochempy.fr/reference/generated/spectrochempy.PCA.html) |
| PLS | Partial Least Squares Regression | [spectrochempy.PLSRegression](https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html) |
| MCR-ALS | Multivariate Curve Resolution | [spectrochempy.MCRALS](https://www.spectrochempy.fr/reference/generated/spectrochempy.MCRALS.html) |
| EFA | Evolving Factor Analysis | [spectrochempy.EFA](https://www.spectrochempy.fr/reference/generated/spectrochempy.EFA.html) |
| SIMPLISMA | Pure variable resolution | [spectrochempy.SIMPLISMA](https://www.spectrochempy.fr/reference/generated/spectrochempy.SIMPLISMA.html) |
| PLS-DA | Discriminant Analysis (via PLS) | [spectrochempy.PLSRegression](https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html) |
| SIMCA | Class-specific PCA models | [spectrochempy.PCA](https://www.spectrochempy.fr/reference/generated/spectrochempy.PCA.html) |
| Baseline (Rubberband) | Convex hull baseline | [spectrochempy.basc](https://www.spectrochempy.fr/reference/generated/spectrochempy.basc.html) |
| OSC Filter | Orthogonal Signal Correction | [spectrochempy.PLSRegression](https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html) |
| File Readers | JCAMP-DX, SPC, SPA, OPUS | [spectrochempy.NDDataset](https://www.spectrochempy.fr/reference/generated/spectrochempy.NDDataset.html) |

All other nodes (40+ preprocessing, clustering, regression, diagnostics, and visualization nodes) run on **NumPy, SciPy, and scikit-learn** with no SpectroChemPy dependency.

### Other Dependencies

SpectraSherpa also builds on these open-source projects:

- [scikit-learn](https://scikit-learn.org/) — Machine learning (BSD-3-Clause)
- [NumPy](https://numpy.org/) / [SciPy](https://scipy.org/) — Numerical computing (BSD-3-Clause)
- [FastAPI](https://fastapi.tiangolo.com/) — Web framework (MIT)
- [SQLAlchemy](https://www.sqlalchemy.org/) — Database ORM (MIT)
- [Plotly](https://plotly.com/python/) — Visualization (MIT)

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

Enterprise features and commercial licensing are available from Spectra Scientific LLC.
