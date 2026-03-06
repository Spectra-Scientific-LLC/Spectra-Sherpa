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
- **No coding required** — Visual drag-and-drop workflow builder with over 60 processing nodes. Go from raw spectra to a deployed PLS model without writing Python.
- **Extensible when you need it** — Export any workflow to standalone Python or Jupyter notebooks. Add custom nodes via plugins or drop-in scripts.
- **Modern metadata management** — Versioned projects, experiments, workflows, and model artifacts with full provenance tracking and audit trails.
- **AI-assisted analysis** — Integrated LLM chat with bring-your-own-key (BYOK) support for OpenAI, Anthropic, Google, DeepSeek, and Qwen. Agentic AI features in progressive development.

## Try It

**Free online demo** — Register and explore SpectraSherpa as a sandbox at [demo.spectrascientific.ai](https://demo.spectrascientific.ai/register) with all features including the LLM assistant enabled.
*(Note: For a limited time, use the access code `welcome_to_spectra_sherpa` to create an account. No upload of proprietary data to the demo server is allowed. Accounts inactive for more than a week will be automatically deleted.)*

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
| Mass Spectrometry | GC-MS, LC-MS, TOF-SIMS, ICP-MS |
| Atomic Emission | ICP-OES |
| Magnetic Resonance | Benchtop NMR, low-field NMR |
| Imaging | Hyperspectral imaging (HSI) |
| Sensor Arrays | Electronic nose / tongue, inline process sensors |
| Semiconductor Metrology | OES (plasma etch/deposition), virtual metrology |

See the [Applications Guide](docs/user/applications.md) for detailed algorithm-to-technique mapping across analytical chemistry and semiconductor process control.

## Features

- **Workflow Builder** — Visually design reproducible analysis pipelines (DAGs) with 11 toolbar sections: Data, Synthesis, Preprocessing, Exploratory, Regression, Classification, Clustering, Validation, Custom, Output, and Deployment
- **Model Artifacts** — Train, persist, and reload models (PCA, PLS, MCR, PLSDA, KNN, SIMCA) with a generic Load & Apply node
- **Type System** — Typed port connections with registry-driven validation prevent incompatible node wiring
- **Python & Notebook Export** — Generate standalone `.py` scripts or Jupyter notebooks from any workflow
- **Project Management** — Organize experiments, workflows, scripts, and models with versioned snapshots
- **Experiment Tracking** — DOE support with 96-well plate layouts, samples, mixtures, and factor definitions
- **Deploy** — Batch prediction, folder watching, and execution run tracking with model provenance
- **LLM Chat** — BYOK AI assistant (OpenAI, Anthropic, Google, DeepSeek, Qwen) for spectral analysis and workflow guidance
- **Plugin System** — Extend the node library via Python entry points or drop-in modules
- **Privacy Controls** — Fine-grained egress permissions; "deny all" network policy by default; local-first architecture for IP-sensitive labs

| Mode | Auth | Use Case |
|------|------|----------|
| `local` | None (single-user) | Desktop analysis, privacy-first |
| `hybrid` | JWT + API key | Local processing, optional cloud features |
| `enterprise` | Full multi-user auth | Shared lab environments |

## Algorithm Library

Over 60 processing nodes across preprocessing, exploratory analysis, regression, classification, clustering, validation, synthesis, and deployment. Optionally install [SpectroChemPy](https://www.spectrochempy.fr/)-powered algorithms with `pip install spectra-sherpa[scp]`.

- **[Node Reference](docs/user/reference/nodes.md)** — Full catalog of every node with parameters and port definitions
- **[Applications Guide](docs/user/applications.md)** — Algorithm-to-technique mapping for analytical chemistry and semiconductor metrology
- **[Workflow Builder Guide](docs/user/workflow.md)** — How to build, connect, and execute processing pipelines

## Core Concepts

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

## Installation

**Requirements:** Python 3.11+ (Node.js 22+ for frontend development only)

```bash
# User install
pip install spectra-sherpa
spectra-sherpa

# From source (development)
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa
poetry install --with dev --extras "scp sherpa"

# Frontend development
cd frontend && npm install && npm run dev

# Run tests
poetry run pytest tests/ -v --no-cov
cd frontend && npx vue-tsc --noEmit && npm run build
```

| Extra | Install | Description |
|-------|---------|-------------|
| `scp` | `pip install spectra-sherpa[scp]` | [SpectroChemPy](https://www.spectrochempy.fr/) algorithms and file readers |

## Documentation

Full documentation at [docs.spectrascientific.ai](https://docs.spectrascientific.ai):

- [Installation](docs/user/installation.md)
- [Quickstart](docs/user/quickstart.md)
- [Configuration](docs/user/configuration.md)
- [Applications Guide](docs/user/applications.md)
- [Node Reference](docs/user/reference/nodes.md)
- [Architecture](docs/dev/architecture.md)

## Third-Party Notices

SpectraSherpa optionally integrates with [SpectroChemPy](https://www.spectrochempy.fr/), a Python library for advanced spectroscopic data analysis developed by **Arnaud Travert and Christian Fernandez** at the [Laboratoire Catalyse et Spectrochimie (LCS)](https://www.lcs.ensicaen.fr/), ENSICAEN / Universit&eacute; de Caen / CNRS. SpectroChemPy is licensed under [CeCILL-B](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html) (BSD-compatible); SpectraSherpa is AGPL-3.0.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

> [!IMPORTANT]
> This project requires contributors to sign a Contributor License Agreement (CLA).
> When you open a Pull Request, a bot will comment with instructions. You can sign by commenting:
> `I have read the CLA Document and I hereby sign the CLA`

## License

Copyright (C) 2026 Spectra Scientific LLC.

SpectraSherpa is licensed under the AGPL-3.0. See [LICENSE](./LICENSE) for details.

You are free to use, modify, and distribute SpectraSherpa. If you distribute a modified version — including as a network service — you must make your modifications available under the same license.

> [!WARNING]
> This software is provided "AS IS" without warranty of any kind. Spectra Scientific LLC disclaims all liability for damages arising from use of this software, including reliance on analytical results. See [DISCLAIMER](./DISCLAIMER) for full terms.

Enterprise features and commercial licensing are available from Spectra Scientific LLC.
