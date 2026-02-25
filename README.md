# SpectraSherpa

[![CI](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml/badge.svg)](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-spectrascientific.ai-blue)](https://docs.spectrascientific.ai)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)]()

**Open-source, local-first chemometrics platform.**

SpectraSherpa brings transparent, reproducible multivariate analysis to spectroscopists and analytical chemists. Build visual analysis pipelines, train and deploy calibration models, and extend with custom Python — all without your data leaving your machine.

## Why SpectraSherpa?

- **Transparent algorithms** — Open source means every preprocessing step, decomposition, and calibration model is auditable. No black boxes.
- **Data stays on your machine** — Built for IP-sensitive labs in pharma, semiconductor, food science, and materials. Network egress is denied by default.
- **No coding required** — Visual drag-and-drop workflow builder with 100+ nodes. Go from raw spectra to a deployed PLS model without writing Python.
- **Extensible when you need it** — Export any workflow to standalone Python or Jupyter notebooks. Add custom nodes via plugins or drop-in scripts.
- **Modern metadata management** — Versioned projects, experiments, workflows, and model artifacts with full provenance tracking and audit trails.
- **AI-assisted analysis** — Integrated LLM chat with bring-your-own-key (BYOK) support for OpenAI and Anthropic. Agentic AI features in progressive development.

## Try It

**Free online demo** — Visit [demo.spectrascientific.ai](https://demo.spectrascientific.ai) to request a free access code and explore SpectraSherpa in your browser.

**Install locally:**

```bash
pip install spectra-sherpa
spectra-sherpa
```

Opens `http://localhost:8000` in your browser. No login required.

## Supported Techniques

SpectraSherpa's chemometric toolkit applies to any technique that produces multivariate spectral or sensor data:

| Domain | Techniques |
|--------|------------|
| Vibrational Spectroscopy | NIR, FTIR (mid-IR), Raman, Terahertz (THz) |
| Optical Spectroscopy | UV-Vis, Fluorescence / EEM, LIBS |
| X-ray Methods | XRF, TXRF, XRD, HRXRD, XPS, CD-SAXS |
| Mass Spectrometry | GC-MS, LC-MS, TOF-SIMS, ICP-MS, ICP-OES |
| Magnetic Resonance | Benchtop NMR, low-field NMR |
| Imaging | Hyperspectral imaging (HSI) |
| Sensor Arrays | Electronic nose / tongue, inline process sensors |
| Semiconductor Metrology | OES (plasma etch/deposition), virtual metrology |

See the [Applications Guide](docs/user/applications.md) for detailed algorithm-to-technique mapping across analytical chemistry and semiconductor process control.

## Features

- **Workflow Builder** — Visually design reproducible analysis pipelines (DAGs) with 100+ nodes for preprocessing, modeling, classification, diagnostics, and DOE
- **Model Artifacts** — Train, persist, and reload models (PCA, PLS, MCR, PLSDA, KNN, SIMCA) with a generic Load & Apply node
- **Type System** — Typed port connections with registry-driven validation prevent incompatible node wiring
- **Python & Notebook Export** — Generate standalone `.py` scripts or Jupyter notebooks from any workflow
- **Project Management** — Organize experiments, workflows, scripts, and models with versioned snapshots
- **Experiment Tracking** — DOE support with 96-well plate layouts, samples, mixtures, and factor definitions
- **Deploy** — Batch prediction, folder watching, and execution run tracking with model provenance
- **LLM Chat** — BYOK AI assistant (OpenAI, Anthropic) for spectral analysis and workflow guidance
- **Plugin System** — Extend the node library via Python entry points or drop-in modules
- **Privacy Controls** — Fine-grained egress permissions for LLM context and data exports

### Deployment Modes

| Mode | Auth | Use Case |
|------|------|----------|
| `local` | None (single-user) | Desktop analysis, privacy-first |
| `hybrid` | JWT + API key | Local processing, optional cloud features |
| `enterprise` | Full multi-user auth | Shared lab environments |

## Algorithm Library

### SpectroChemPy Nodes (optional)

Install with `pip install spectra-sherpa[scp]` to enable [SpectroChemPy](https://www.spectrochempy.fr/)-powered algorithms:

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

### Built-in Algorithms (no SpectroChemPy required)

Ships with the core install, powered by NumPy, SciPy, and scikit-learn:

**Preprocessing**

| Category | Nodes |
|----------|-------|
| Baseline | Polynomial, ALS, Penalized LS, SNIP |
| Smoothing | Savitzky-Golay, Gaussian, Whittaker, Moving Average |
| Normalization | Min-Max, L2, Standard (z-score), Area |
| Scatter Correction | SNV, MSC, EMSC |
| Derivatives | First, Second (Savitzky-Golay) |
| Cleanup | Cosmic Ray Removal, Remove NaN, Trim Edges, Crop Spectral Region |

**Modeling & Decomposition**

| Node | Algorithm |
|------|-----------|
| NMF | Non-negative Matrix Factorization |
| Fast ICA | Independent Component Analysis |
| PCR | Principal Component Regression |
| SVR | Support Vector Regression |
| Linear Regression | Ordinary Least Squares |

**Clustering & Classification**

| Node | Algorithm |
|------|-----------|
| K-Means | K-Means clustering |
| DBSCAN | Density-based clustering |
| HCA | Hierarchical Cluster Analysis |
| KNN | K-Nearest Neighbors classifier |

**Diagnostics & Analysis**

| Node | Algorithm |
|------|-----------|
| Outlier Detection | Hotelling T² and Q residuals |
| Cross-Validation | K-fold with RMSE/R² metrics |
| Peak Finding | Automated peak detection |

**Synthesis & DOE**

| Node | Description |
|------|-------------|
| Blend | Generate synthetic mixtures with concentration profiles |
| Species | Mark spectra as blend components |
| Merge | Combine spectra into stacked datasets |
| Concentration Curve | Generate concentration profiles |
| Noise Injection | Add controlled Gaussian noise |

**Data & Deployment**

| Node | Description |
|------|-------------|
| Data Source | Load from CSV, reference datasets, or sklearn |
| NIST Library | Fetch reference spectra from NIST WebBook |
| Train/Test Split | Stratified dataset splitting |
| Load & Apply Model | Reload any saved model artifact |
| Deploy Input/Output | Headless batch prediction endpoints |

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

- **Experiments** hold raw spectral data. Upload files or import example datasets.
- **Workflows** define processing pipelines as directed acyclic graphs with version history and execution runs.
- **Models** are trained artifacts (PCA, PLS, MCR, etc.) persisted to disk. Reload in new workflows via the **Load & Apply Model** node.
- **Scripts** are Python exports for standalone reproducibility.

### Workflow Execution

```
Data Source → Preprocessing → Modeling → Diagnostics
                                ↓
                          Model Artifact (saved)
                                ↓
                    Load & Apply Model (new data)
```

Training nodes automatically persist model artifacts. The **Load & Apply Model** node loads any saved model and applies `transform()` (decomposition) or `predict()` (classification) to new data.

## Installation

### Requirements

- Python 3.11+
- Node.js 22+ (for frontend development only)

### From source (minimal)

```bash
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa
poetry install --with dev
spectra-sherpa
```

### Optional extras

| Extra | Install | Description |
|-------|---------|-------------|
| `scp` | `pip install spectra-sherpa[scp]` | [SpectroChemPy](https://www.spectrochempy.fr/) algorithms and file readers (see [Third-Party Notices](#third-party-notices)) |

## Development Setup

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

Full documentation at [docs.spectrascientific.ai](https://docs.spectrascientific.ai):

- [Installation](docs/user/installation.md)
- [Quickstart](docs/user/quickstart.md)
- [Configuration](docs/user/configuration.md)
- [Applications Guide](docs/user/applications.md)
- [Architecture](docs/dev/architecture.md)
- [Node Reference](docs/user/reference/nodes.md)

## Privacy-First Design

SpectraSherpa is built for IP-sensitive environments.

- **Local by default** — No data leaves your machine unless you explicitly configure it.
- **Egress control** — The system enforces a "deny all" network policy by default. You opt in to features that require network access (NIST library, LLM assistance).
- **Lab-grade safety** — Leader locks and database migrations ensure data integrity in shared and multi-user environments.

## Third-Party Notices

### SpectroChemPy

SpectraSherpa optionally integrates with [SpectroChemPy](https://www.spectrochempy.fr/), a Python library for advanced spectroscopic data analysis developed by **Arnaud Travert and Christian Fernandez** at the [Laboratoire Catalyse et Spectrochimie (LCS)](https://www.lcs.ensicaen.fr/), ENSICAEN / Universit&eacute; de Caen / CNRS.

SpectroChemPy is licensed under [CeCILL-B](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html) (BSD-compatible); SpectraSherpa is AGPL-3.0. The two licenses differ, so SpectroChemPy is an opt-in extra (`pip install spectra-sherpa[scp]`).

### Other Dependencies

SpectraSherpa also builds on these open-source projects:

- [scikit-learn](https://scikit-learn.org/) — Machine learning (BSD-3-Clause)
- [NumPy](https://numpy.org/) / [SciPy](https://scipy.org/) — Numerical computing (BSD-3-Clause)
- [FastAPI](https://fastapi.tiangolo.com/) — Web framework (MIT)
- [SQLAlchemy](https://www.sqlalchemy.org/) — Database ORM (MIT)

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

> [!IMPORTANT]
> This project requires contributors to sign a Contributor License Agreement (CLA).
> When you open a Pull Request, a bot will comment with instructions. You can sign by commenting:
> `I have read the CLA Document and I hereby sign the CLA`

## License

SpectraSherpa is licensed under the AGPL-3.0. See [LICENSE](./LICENSE) for details.

You are free to use, modify, and distribute SpectraSherpa. If you distribute a modified version — including as a network service — you must make your modifications available under the same license.

Enterprise features and commercial licensing are available from Spectra Scientific LLC.
