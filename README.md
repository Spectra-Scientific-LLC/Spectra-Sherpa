# SpectraSherpa by [Spectra Scientific LLC](https://spectrascientific.ai)

[![PyPI](https://img.shields.io/pypi/v/spectra-sherpa)](https://pypi.org/project/spectra-sherpa/)
[![Python](https://img.shields.io/pypi/pyversions/spectra-sherpa)](https://pypi.org/project/spectra-sherpa/)
[![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macOS%20%7C%20windows-lightgrey)]()
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](LICENSE)
[![CI](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml/badge.svg)](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-spectrascientific.ai-blue)](https://docs.spectrascientific.ai)

**Open-source, local-first chemometrics platform, AI-ready.**

SpectraSherpa brings transparent, reproducible multivariate analysis to spectroscopists and analytical chemists. Build visual analysis pipelines, train and deploy calibration models, and extend with custom Python — all without your data leaving your machine.

## Why SpectraSherpa?

- **Transparent algorithms** — Open source means every preprocessing step, decomposition, and calibration model is auditable. No black boxes.
- **Data stays on your machine** — Built for IP-sensitive labs in pharma, semiconductor, food science, and materials. Network egress is denied by default.
- **No coding required** — Visual drag-and-drop workflow builder with over 60 processing nodes. Go from raw spectra to a deployed PLS model without writing Python.
- **Extensible when you need it** — Export any workflow to standalone Python or Jupyter notebooks. Add custom nodes via plugins or drop-in scripts.
- **Modern metadata management** — Versioned projects, experiments, workflows, and model artifacts with full provenance tracking and audit trails.
- **AI-ready** — Built-in chat assistant connects to any OpenAI-compatible endpoint you choose (bring your own key and URL). Full AI advisor with agentic tools, peak identification, code generation, and contextual workflow analysis [available via subscription](https://spectrascientific.ai).

## For Python data analysts and chemometricians

If you already analyze spectra in Python — whether using scikit-learn, pandas, or your own scripts — SpectraSherpa is built to match your methods, not replace them.

**The math matches what you already know.**
PCA, PLS, MCR-ALS, and classification nodes produce results validated side-by-side against scikit-learn reference outputs. The [PCA reproduction study](docs/user/case_study_pca.md) shows the exact numerical comparison on a standard dataset — same parameters, same results, verified to five decimal places.

**Your NumPy arrays work without conversion.**
The internal data container is a thin wrapper over NumPy: a `(n_samples, n_features)` array with labeled wavelength and sample axes. Your existing code works directly:

```python
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis, SampleAxis

dataset = SherpaDataset(
    X=your_array,                                        # shape: (n_samples, n_features)
    feature_axis=SpectralAxis(values=wavenumbers, units="cm-1"),
    sample_axis=SampleAxis(values=sample_ids),
)
X = dataset.data      # get the NumPy array back at any time
y = dataset.target    # labels, if any
```

**Export any workflow to a Python script or Jupyter notebook.**
The visual builder is for exploration and reproducibility. The notebook is the artifact you publish, share, or hand off — it requires only `pip install spectra-sherpa` and standard scientific libraries (NumPy, SciPy, scikit-learn).

**Add your own algorithm as a processing step.**
If you have a working function in a notebook, one command generates the wrapper and registers it in the toolbar:

```bash
make node-scaffold
```

See the **[Scientist Contributor Guide](docs/contributing/scientist-guide.md)** — notebook to node to pull request, with no web development knowledge required.

---

## Try It

**Free online demo** — Register and explore SpectraSherpa at [demo.spectrascientific.ai](https://demo.spectrascientific.ai/register) with all features including the AI advisor enabled.
*(Note: For a limited time, use the access code `welcome_to_spectra_sherpa` to create an account. No upload of proprietary data to the demo server is allowed. Accounts inactive for more than a week will be automatically deleted.)*

**Install locally:**

```bash
pip install spectra-sherpa
spectra-sherpa
```

Opens `http://localhost:8000` in your browser. No login required.
Install `spectra-sherpa[scp]` as well if you want the SpectroChemPy-backed example datasets and workflows.

## Supported Techniques

SpectraSherpa's core math applies broadly to multivariate spectral and sensor data, but the template-guided onboarding path is narrower than that general claim. The table below reflects what is actually supported in the product today.

### Supported Today

| Support Level | Techniques | Notes |
|---------------|------------|-------|
| Template-guided example workflows | FTIR, NIR, Raman, OES | Shipped templates with bundled example datasets from [Eigenvector Research](https://eigenvector.com/resources/data-sets/) and SpectroChemPy, instantiated directly from Projects. Some example workflows require the optional `spectra-sherpa[scp]` install. |
| Template-guided (user-supplied data) | UV-Vis | Templates exist for PCA, MCR-ALS, clustering, and preprocessing. Users bind their own compatible data. |
| User-data workflows | FTIR, Raman, NIR, UV-Vis, OES | All techniques accepted by the node library and template contracts when the user supplies compatible data. |

### Future Plan

Many other measurement domains are good fits for SpectraSherpa's architecture and chemometric approach, including vibrational, elemental, diffraction, mass spectrometry, imaging, and broader semiconductor virtual metrology workflows. These are inspirational targets rather than finished product claims today, and we are actively looking for developers and scientist-contributors who want to help expand template coverage, validation datasets, and technique-specific UX.

See the [Applications Guide](docs/user/applications.md) for the current support split between shipped templates, partial support, and future plan.

## Features

- **Workflow Builder** — Visually design reproducible analysis pipelines by connecting processing steps (nodes) in a drag-and-drop canvas. 11 categories: Data, Synthesis, Preprocessing, Exploratory, Regression, Classification, Clustering, Validation, Custom, Output, and Deployment
- **Model Artifacts** — Train, persist, and reload models (PCA, PLS, MCR, PLSDA, KNN, SIMCA) with a generic Load & Apply node
- **Type System** — Node connections are validated automatically; incompatible connections (e.g. feeding a model into a raw-data input) are blocked before execution
- **Python & Notebook Export** — Generate standalone `.py` scripts or Jupyter notebooks from any workflow
- **Project Management** — Organize experiments, workflows, scripts, and models with versioned snapshots
- **Experiment Tracking** — DOE support with 96-well plate layouts, samples, mixtures, and factor definitions
- **Deploy** — Batch prediction, folder watching, and execution run tracking with model provenance
- **AI Chat** — Connect any OpenAI-compatible chat endpoint for AI-assisted analysis and workflow guidance. See [Configuration](docs/user/configuration.md) for setup.
- **Plugin System** — Add your own processing nodes by dropping a Python file into a folder or installing a package
- **Privacy Controls** — Fine-grained egress permissions; "deny all" network policy by default; local-first architecture for IP-sensitive labs

| Mode | Login required? | Use Case |
|------|-----------------|----------|
| `local` | No — single user, opens straight to the app | Desktop analysis, privacy-first |
| `hybrid` | Optional external service integration | Local GUI with remote services |
| `enterprise` | Extension-defined | Shared lab environments, multi-user operation |

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

**Requirements:** Python **3.11 or 3.12** (3.13 may work but the scientific stack — numpy, scipy, scikit-learn, SpectroChemPy — does not yet ship full wheels for 3.13+, so installs may try to compile from source and fail; 3.14 is not recommended). [Node.js](https://nodejs.org) is only needed if you want to modify the browser interface itself.

```bash
# Install and run (all you need as a user)
pip install spectra-sherpa
spectra-sherpa

# From source (for contributors — see CONTRIBUTING.md for a full walkthrough)
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa
pip install poetry                              # Poetry manages Python dependencies
poetry env use python3.11                       # pin the venv to a supported Python (3.11 or 3.12)
poetry install --with dev --extras "scp"
poetry run spectra-sherpa                       # launches the app from the source checkout

# Only needed to change the browser interface
cd frontend && npm install && npm run dev       # npm is the JavaScript package manager

# Run the Python test suite
poetry run pytest tests/ -v --no-cov
```

| Extra | Install | Description |
|-------|---------|-------------|
| `scp` | `pip install spectra-sherpa[scp]` | [SpectroChemPy](https://www.spectrochempy.fr/) algorithms and file readers |

### First-run notes

The very first launch initializes a local SQLite database, runs Alembic migrations, and (when the `[scp]` extra is installed) lets SpectroChemPy populate its font and stylesheet cache. Allow **30–90 seconds** the first time before opening your browser. The server is ready when you see this line in the terminal:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Subsequent launches start in a few seconds because the SCP cache is now populated.

### Troubleshooting

- **`ValueError: the greenlet library is required to use this function. No module named 'greenlet'`** — `greenlet` is a base dependency, so a clean `pip install spectra-sherpa` (or `poetry install`) pulls it. If you see this in an existing venv, re-run the install or `pip install greenlet` directly.
- **`pyproject.toml changed significantly since poetry.lock was last generated`** — run `poetry lock` (the `--no-update` flag was removed in Poetry 2.x; bare `poetry lock` is the equivalent), then re-run `poetry install`.
- **`ERR_CONNECTION_REFUSED` when opening `http://127.0.0.1:8000` immediately after launch** — the server is still in lifespan startup. Wait for the `Uvicorn running on http://127.0.0.1:8000` log line before opening the browser.
- **Banner reads an old version (e.g. `v0.3.0`) after upgrading** — caused by stale state in an existing venv. `poetry env remove --all` then re-run `poetry install` to rebuild from the new lock; the banner now reads the version live from package metadata so it cannot drift.
- **Port 8000 already in use** — relaunch with `spectra-sherpa --port 9000`, or set `KILL_PORT_ON_START=true` in `.env` to free the port automatically.

## Documentation

Full documentation at [docs.spectrascientific.ai](https://docs.spectrascientific.ai):

- [Installation](docs/user/installation.md)
- [Quickstart](docs/user/quickstart.md)
- [Configuration](docs/user/configuration.md)
- [App Data Directory](docs/user/data-directory.md)
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

Copyright (C) 2026 [Spectra Scientific LLC](https://spectrascientific.ai).

SpectraSherpa is licensed under the AGPL-3.0. See [LICENSE](./LICENSE) for details.

You are free to use, modify, and distribute SpectraSherpa. If you distribute a modified version — including as a network service — you must make your modifications available under the same license.

> [!WARNING]
> This software is provided "AS IS" without warranty of any kind. [Spectra Scientific LLC](https://spectrascientific.ai) disclaims all liability for damages arising from use of this software, including reliance on analytical results. See [DISCLAIMER](./DISCLAIMER) for full terms.

Enterprise features and commercial licensing are available from [Spectra Scientific LLC](https://spectrascientific.ai).
