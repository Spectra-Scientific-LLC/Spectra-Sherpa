# SpectraSherpa by [Spectra Scientific LLC](https://spectrascientific.ai)

[![PyPI](https://img.shields.io/pypi/v/spectra-sherpa)](https://pypi.org/project/spectra-sherpa/)
[![Python](https://img.shields.io/pypi/pyversions/spectra-sherpa)](https://pypi.org/project/spectra-sherpa/)
[![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macOS%20%7C%20windows-lightgrey)]()
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](LICENSE)
[![CI](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml/badge.svg)](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-spectrascientific.ai-blue)](https://docs.spectrascientific.ai)

**The open chemometrics workbench — visual, reproducible, and local-first.**

SpectraSherpa turns spectra and feature tables into visible, versioned analysis
workflows. Import supported scientific files, inspect their axes and metadata,
then use PCA, PLS, MCR-ALS, SIMCA, PLS-DA, variable selection, calibration
transfer, and validation without hiding the data path behind a notebook.

Install the v0.6.0 Workbench and Python SDK (Python 3.11 or 3.12):

```bash
python -m pip install "spectra-sherpa==0.6.0"
spectra-sherpa
```

Try the **[hosted Demo](https://demo.spectrascientific.ai)** by registering
with your email. Demo uses supplied or registered reference datasets; use local
OSS or Pro Cloud for your own data. Local OSS includes BYOK chat; managed
Advisor and optimization campaigns are hosted features.

📖 [Documentation](https://docs.spectrascientific.ai) · 🧭 [Choose your path](docs/onboarding/choose-your-path.md) · 🧩 [Node Library](docs/nodes/index.md)

## Why SpectraSherpa

A single open workbench for the chemometrics you actually run, built around five strengths:

- **A first-class chemometric toolkit.** Preprocessing, decomposition, calibration, classification, variable selection, and calibration transfer are core features, purpose-built for spectroscopy. (Full list below.)
- **Numbers you can defend.** Native PLS and PLS-DA share one cited Sherpa SIMPLS authority, while optional SpectroChemPy operations retain their declared upstream runtime. MCR-ALS is checked against synthetic ground truth and reference workflows.
- **Reproducible by construction.** Every workflow is versioned on save and every run is an immutable, provenance-tracked record, so a result always traces back to its exact recipe and data.
- **From exploration to production.** Export supported workflows to standalone Python or a Jupyter notebook; trained models are first-class artifacts you can batch-apply and deploy.
- **Open and local-first.** AGPL-3.0, reads CSV, JCAMP-DX, NumPy, MATLAB
  v4/v5/v7.3 and qualified Eigenvector DataSet Objects, qualified Galactic
  SPC, and one-dimensional Bruker OPUS files directly, and runs entirely on
  your machine with network egress **denied by default in local mode**.

Built to be an open foundation that labs and instrument makers can standardize
on, extend, and embed. For third-party reference data, the user obtains the
source file directly from its provider. SpectraSherpa does not retrieve, proxy,
cache, or redistribute that provider file. Local and paid users can select it
through the normal upload path; a policy-constrained deployment can instead
admit only a registered byte-identical reference. See the
[dataset and provider guide](docs/workflows/datasets-and-providers.md).

## Install & run

The command above opens the Workbench at `http://localhost:8000` in your
browser — **no login required**. The first launch initializes a local database.
The Python SDK is included in the same installation.

Choose optional capabilities when installing:

```bash
python -m pip install "spectra-sherpa[scp,hitran,nist]==0.6.0"
```

| Extra | Adds |
|-------|------|
| `scp` | SpectroChemPy runtime for EFA, MCR-ALS, and SIMPLISMA |
| `hitran` | HITRAN/HAPI clients for live line-table downloads |
| `nist` | NIST WebBook search and acquisition |

HITRAN downloads require your personal key in **Settings → API Keys** and
**Settings → Integrations → HITRAN/HAPI Queries** enabled. Network access is
optional and disabled by default locally.

<details>
<summary>Build from the public source release</summary>

Requires Git, Python 3.11 or 3.12, and Node.js 22. Use this path if the tag is
available before the PyPI upload completes:

```bash
git clone --branch spectra-sherpa-v0.6.0 https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa
python -m pip install poetry
poetry env use python3.11
poetry install --extras "scp hitran nist"
npm --prefix frontend ci
npm --prefix frontend run build
poetry run spectra-sherpa
```

For base-only installation, omit `--extras`. Keep wanted extras in subsequent
`poetry install` commands. For guided choices, run
`python scripts/install_local.py --source .` from the public checkout.

</details>

Run the canonical Python example:

```bash
python -m spectra_sherpa.examples.canonical_workflow
```

It builds and executes a typed DAG, saves and reopens its workflow, and writes
results to `spectra-sherpa-quickstart/`. With Poetry, prefix the command with
`poetry run`.

See [Local onboarding](docs/onboarding/local-30-minutes.md),
[Python workflows](docs/onboarding/python-canonical-workflows.md), and
[Migrate to 0.6](docs/onboarding/migrate-to-0.6.md).

## The chemometric toolkit

A qualified catalog of data, preprocessing, exploratory, modeling, validation,
transfer, and output nodes covers the workflow you actually run:

- **Preprocessing** — Savitzky-Golay smoothing/derivatives, baseline correction, MSC, SNV, OSC, normalization, scaling.
- **Exploratory** — PCA, MCR-ALS, SIMPLISMA, EFA, hierarchical clustering.
- **Calibration & classification** — PLS regression, PLS-DA, SIMCA, KNN.
- **Variable selection** — iPLS, CARS, SPA, MC-UVE, VIP.
- **Calibration transfer** — PDS and direct standardization for instrument-to-instrument transfer.
- **Validation & deployment** — cross-validation, nested CV, selection stability, model comparison, batch prediction, deploy-readiness checks.

See the **[Node Library](docs/nodes/index.md)** for node parameters and ports, and **[Current Capabilities](docs/introduction/capabilities.md)** for the supported production scope.

## Core concepts

Keep data, workflows, runs, model artifacts, and reports together in a **Project**. See [Projects, Datasets, and Runs](docs/workflows/projects-datasets-runs.md).

## For Python analysts & chemometricians

Use labeled arrays through `dataset.data`, compose typed workflows in Python,
or add a canonical node to the visual editor. The SDK and GUI share execution
contracts. New nodes require reviewed scientific behavior and contract tests;
see [Contributing](docs/developers/contributing.md).

## Built on the work of others

SpectraSherpa stands on established open science, and keeps citation guidance close to generated outputs:

- **[SpectroChemPy](https://www.spectrochempy.fr/)** — upstream spectroscopic algorithms, data structures, and instrument-file readers, by Arnaud Travert and Christian Fernandez at the Laboratoire Catalyse et Spectrochimie (LCS), ENSICAEN / Université de Caen / CNRS. SpectroChemPy is optional, installed separately through the `scp` extra, and governed by its upstream [CeCILL-B](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html) terms. SpectraSherpa uses a private, matrix-only adapter for exactly EFA, MCR-ALS, and SIMPLISMA; it exposes none of the upstream readers or datasets.
- **[HITRAN](https://hitran.org/) / HAPI** — the high-resolution molecular spectroscopic database used by Data → Synthesis to build physically grounded FTIR line tables.
- **[Eigenvector Research data sets](https://eigenvector.com/resources/data-sets/)** — recommended NIR/OES chemometrics teaching and validation datasets. The user obtains a file directly from Eigenvector; SpectraSherpa neither downloads it on the user's behalf nor redistributes the raw data.
- **[NIST Chemistry WebBook](https://webbook.nist.gov/) (SRD 69)** and the **NIST Quantitative Infrared Database (SRD 79)** — reference IR spectra for synthesis.

These databases are not owned by Spectra Scientific. Cite NIST, HITRAN, and HAPI in any report, publication, or validation package that uses synthetic datasets — [Reference Libraries and Synthesis](docs/workflows/references-synthesis.md) and the [Attributions](docs/attributions/index.md) page list the recommended attributions.

## Documentation

Full docs at **[docs.spectrascientific.ai](https://docs.spectrascientific.ai)**.

- **Get started:** [Cloud vs Local OSS](docs/introduction/cloud-vs-local.md) · [10 Minutes to Local Compute](docs/onboarding/local-30-minutes.md) · [Import Your First Dataset](docs/onboarding/import-first-dataset.md)
- **Workflows:** [Data Import](docs/workflows/data-import.md) · [Projects, Datasets, and Runs](docs/workflows/projects-datasets-runs.md) · [Reports and Exports](docs/workflows/reports-exports.md)
- **Reference:** [Supported File Types](docs/introduction/file-types.md) · [Node Library](docs/nodes/index.md) · [Templates](docs/workflow-templates/index.md)
- **Develop:** [Architecture](docs/architecture/index.md) · [Contributing](docs/developers/contributing.md) · [Developer Setup](docs/developers/setup.md)

## Contributing

We welcome contributions — see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

> [!IMPORTANT]
> This project requires a signed Contributor License Agreement (CLA). When you open a PR, a bot comments with instructions; sign by replying:
> `I have read the CLA Document and I hereby sign the CLA`

## License

Copyright (C) 2026 [Spectra Scientific LLC](https://spectrascientific.ai). Licensed under **AGPL-3.0** — see [LICENSE](./LICENSE). If you distribute a modified version (including as a network service), you must release your modifications under the same license. SpectroChemPy is CeCILL-B; see [NOTICE.md](./NOTICE.md) for full third-party terms. Enterprise features and commercial licensing are available from Spectra Scientific.

> [!WARNING]
> Provided "AS IS" without warranty of any kind. Spectra Scientific LLC disclaims all liability for damages arising from use, including reliance on analytical results. See [DISCLAIMER](./DISCLAIMER).
