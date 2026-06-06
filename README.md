# SpectraSherpa by [Spectra Scientific LLC](https://spectrascientific.ai)

[![PyPI](https://img.shields.io/pypi/v/spectra-sherpa)](https://pypi.org/project/spectra-sherpa/)
[![Python](https://img.shields.io/pypi/pyversions/spectra-sherpa)](https://pypi.org/project/spectra-sherpa/)
[![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macOS%20%7C%20windows-lightgrey)]()
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](LICENSE)
[![CI](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml/badge.svg)](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-spectrascientific.ai-blue)](https://docs.spectrascientific.ai)

**The open chemometrics workbench — visual, reproducible, and local-first.**

PCA, PLS, MCR-ALS, SIMCA, PLS-DA, variable selection, and calibration transfer in a drag-and-drop workflow builder — with full version history, provenance you can defend in an audit, and one-click export for supported workflows. Open source and free to run, entirely on your own machine.

📖 [Documentation](https://docs.spectrascientific.ai) · 🚀 [Local onboarding](docs/onboarding/local-30-minutes.md) · 🧩 [Node Library](docs/nodes/index.md) · 🔬 [For developers](docs/developers/contributing.md)

Want to try it before installing? Visit the hosted demo at **[demo.spectrascientific.ai](https://demo.spectrascientific.ai)** and register with access code `welcome_to_spectra_sherpa`.

## Why SpectraSherpa

A single open workbench for the chemometrics you actually run, built around five strengths:

- **A first-class chemometric toolkit.** Preprocessing, decomposition, calibration, classification, variable selection, and calibration transfer are core features, purpose-built for spectroscopy. (Full list below.)
- **Numbers you can defend.** PCA and PLS workflows are checked against their underlying SpectroChemPy execution paths, with sklearn parity tests for exported artifact helpers where sklearn is the reference implementation. MCR-ALS is checked against synthetic ground truth and reference workflows.
- **Reproducible by construction.** Every workflow is versioned on save and every run is an immutable, provenance-tracked record, so a result always traces back to its exact recipe and data.
- **From exploration to production.** Export supported workflows to standalone Python or a Jupyter notebook; trained models are first-class artifacts you can batch-apply and deploy.
- **Open and local-first.** AGPL-3.0, reads your instrument files directly (`.spg`, `.spa`, `.jdx`, `.opus`, `.mat`, …), and runs entirely on your machine with network egress **denied by default in local mode**.

Built to be an open foundation that labs and instrument makers can standardize on, extend, and embed. Bundled public benchmark datasets (corn, diesel NIR, NIR shootout, and [SpectroChemPy](https://www.spectrochempy.fr/) examples) let you reproduce familiar results on day one.

## Install & run

```bash
pip install "spectra-sherpa[scp,hitran]"
spectra-sherpa
```

Opens `http://localhost:8000` in your browser — **no login required**. The first launch takes 30–90 s to initialize a local database and caches; later launches are fast.

<details>
<summary>Other install options — minimal, from source, extras</summary>

```bash
# Minimal core (no SpectroChemPy examples/readers, no HITRAN downloads)
pip install spectra-sherpa && spectra-sherpa

# From source (contributors)
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa
pip install poetry
poetry env use python3.11          # supported: 3.11 or 3.12
poetry install --with dev --extras "scp hitran"
poetry run spectra-sherpa
```

| Extra | Adds |
|-------|------|
| `scp` | [SpectroChemPy](https://www.spectrochempy.fr/) algorithms + instrument file readers (`.spc`, `.spa`, `.spg`, `.jdx`, `.opus`, …) |
| `hitran` | HITRAN/HAPI clients for Data → Synthesis live line-table downloads |

Requires Python **3.11 or 3.12**. Full requirements, CLI flags, and troubleshooting are in **[30 Minutes to Local Compute](docs/onboarding/local-30-minutes.md)**.

HITRAN live downloads require your own HITRAN API key, saved in **Settings > API Keys**, plus **Settings > Integrations > HITRAN/HAPI Queries** enabled.

</details>

Hosted Demo, Pro, Hybrid, and Organization deployments are operated separately by Spectra Scientific. This README covers the local workstation install.

## The chemometric toolkit

Over 60 nodes across the workflow you actually run:

- **Preprocessing** — Savitzky-Golay smoothing/derivatives, baseline correction, MSC, SNV, OSC, normalization, scaling.
- **Exploratory** — PCA, MCR-ALS, SIMPLISMA, EFA, hierarchical clustering.
- **Calibration & classification** — PLS regression, PLS-DA, SIMCA, KNN.
- **Variable selection** — iPLS, CARS, SPA, UVE, VIP.
- **Calibration transfer** — PDS and direct standardization for instrument-to-instrument transfer.
- **Validation & deployment** — cross-validation, nested CV, selection stability, model comparison, batch prediction, deploy-readiness checks.

See the **[Node Library](docs/nodes/index.md)** for node parameters and ports, and **[Current Capabilities](docs/introduction/capabilities.md)** for the supported production scope.

## Core concepts

Everything lives inside a **Project**. Five objects make up a complete analysis — each explained in depth in the **[Projects, Datasets, and Runs](docs/workflows/projects-datasets-runs.md)** guide.

| Object | What it is |
|--------|------------|
| **Project** | The durable container grouping your datasets, workflows, runs, reports, scripts, and trained models — with versioned snapshots and provenance. |
| **Data** | The spectra or feature tables you work on. Import instrument files into *My Dataset*, pull from bundled reference datasets, or synthesize FTIR time series. |
| **Workflow** | The analysis recipe: a drag-and-drop graph (DAG) of nodes, versioned on every save so any result traces back to the exact recipe that produced it. |
| **Run** | One execution of a workflow — an immutable record of parameters, node status, diagnostics, and any model **Artifacts** (frozen PCA/PLS/MCR/PLS-DA/KNN/SIMCA models) it produced. |
| **Report** | A shareable summary assembled from a workflow and its runs. Toggle sections, then export to PDF, HTML, Markdown, or JSON for publication, hand-off, or validation packages. |

## For Python analysts & chemometricians

SpectraSherpa matches your existing methods rather than replacing them. The internal container is a thin wrapper over a `(n_samples, n_features)` NumPy array with labeled wavelength and sample axes, so your scikit-learn and pandas code works directly on `dataset.data`. Bring a working notebook function and `make node-scaffold` turns it into a toolbar node in minutes.

Start here: **[Writing a Plugin Node](docs/developers/plugin-node.md)** — notebook to node to pull request, no web development required.

Because every step is a typed, provenance-tracked artifact, SpectraSherpa is also a clean foundation for AI assistance — the commercial **Sherpa Advisor** and **Guidance** layers build LLM-assisted analysis on top of this deterministic core, which remains fully usable on its own.

## Built on the work of others

SpectraSherpa stands on established open science, and keeps citation guidance close to generated outputs:

- **[SpectroChemPy](https://www.spectrochempy.fr/)** — spectroscopic algorithms and instrument-file readers, by Arnaud Travert and Christian Fernandez at the Laboratoire Catalyse et Spectrochimie (LCS), ENSICAEN / Université de Caen / CNRS. Licensed [CeCILL-B](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html) (BSD-compatible).
- **[HITRAN](https://hitran.org/) / HAPI** — the high-resolution molecular spectroscopic database used by Data → Synthesis to build physically grounded FTIR line tables.
- **[NIST Chemistry WebBook](https://webbook.nist.gov/) (SRD 69)** and the **NIST Quantitative Infrared Database (SRD 79)** — reference IR spectra for synthesis.

These databases are not owned by Spectra Scientific. Cite NIST, HITRAN, and HAPI in any report, publication, or validation package that uses synthetic datasets — [Reference Libraries and Synthesis](docs/workflows/references-synthesis.md) and the [Attributions](docs/attributions/index.md) page list the recommended attributions.

## Documentation

Full docs at **[docs.spectrascientific.ai](https://docs.spectrascientific.ai)**.

- **Get started:** [Cloud vs Local OSS](docs/introduction/cloud-vs-local.md) · [30 Minutes to Local Compute](docs/onboarding/local-30-minutes.md) · [Import Your First Dataset](docs/onboarding/import-first-dataset.md)
- **Workflows:** [Data Import](docs/workflows/data-import.md) · [Projects, Datasets, and Runs](docs/workflows/projects-datasets-runs.md) · [Reports and Exports](docs/workflows/reports-exports.md)
- **Reference:** [Supported File Types](docs/introduction/file-types.md) · [Node Library](docs/nodes/index.md) · [Templates](docs/workflow-templates/index.md)
- **Develop:** [Architecture](docs/architecture/index.md) · [Plugins and Extension Points](docs/architecture/plugins.md) · [Developer Setup](docs/developers/setup.md)

## Contributing

We welcome contributions — see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

> [!IMPORTANT]
> This project requires a signed Contributor License Agreement (CLA). When you open a PR, a bot comments with instructions; sign by replying:
> `I have read the CLA Document and I hereby sign the CLA`

## License

Copyright (C) 2026 [Spectra Scientific LLC](https://spectrascientific.ai). Licensed under **AGPL-3.0** — see [LICENSE](./LICENSE). If you distribute a modified version (including as a network service), you must release your modifications under the same license. SpectroChemPy is CeCILL-B; see [NOTICE.md](./NOTICE.md) for full third-party terms. Enterprise features and commercial licensing are available from Spectra Scientific.

> [!WARNING]
> Provided "AS IS" without warranty of any kind. Spectra Scientific LLC disclaims all liability for damages arising from use, including reliance on analytical results. See [DISCLAIMER](./DISCLAIMER).
