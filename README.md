# Spectra Sherpa by [Spectra Scientific LLC](https://spectrascientific.ai)

[![PyPI](https://img.shields.io/pypi/v/spectra-sherpa)](https://pypi.org/project/spectra-sherpa/)
[![Python](https://img.shields.io/pypi/pyversions/spectra-sherpa)](https://pypi.org/project/spectra-sherpa/)
![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macOS%20%7C%20windows-lightgrey)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](LICENSE)
[![CI](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml/badge.svg)](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-spectrascientific.ai-blue)](https://docs.spectrascientific.ai)

SpectraSherpa is an open-source workbench for building spectroscopic and
chemometric models. Inspect spectra and feature tables, assemble analysis
workflows, review validation results, and apply saved models to new data.
The browser interface and Python SDK use the same scientific operations.

**Local OSS** runs on your computer with your own data. Optional AI assistance
uses your chosen provider and API key. The
**[hosted Demo](https://demo.spectrascientific.ai)** runs in your browser with
reference datasets and AI access provided by Spectra Scientific—no installation
or API key required.

BYOK means **bring your own key**; you pay your chosen provider’s usage charges.
A configured local model is also supported. Hosted optimization campaigns are
separate from OSS.

## Why SpectraSherpa

Fitting a model is only part of the work. A lab also needs to know which spectra
were used, why observations were excluded, where preprocessing was fitted, and
whether a reported error describes calibration or genuinely held-out samples.
Moving between spreadsheets, notebooks, and instrument software can break that
record before a model ever reaches another analyst or instrument.

Pasting spectra or metrics into an AI chat does not preserve data custody: the
connection between the source, transformations, and conclusions. A convincing
explanation can omit sample identity, introduce leakage, or describe a different
analysis from the one actually run.

SpectraSherpa keeps source context, workflow versions, sample selections, and
retained results together so you can inspect how a model was built and check
whether it can be applied. Its approach to a trustworthy AI co-scientist is to
ground assistance in that recorded context while scientific code performs the
calculations. You review the suggestions and evidence. Reproduction still
requires the original inputs and a compatible runtime.

## Getting started

**Try the [Demo](https://demo.spectrascientific.ai)** to explore the workflow
with reference data. See [Demo access and limits](https://docs.spectrascientific.ai/cloud/demo-access/).

**Use local OSS for your own data.** With Python 3.11 or 3.12, install the latest
published package and open the Workbench:

```bash
python -m pip install spectra-sherpa
spectra-sherpa
```

Open `http://localhost:8000`; no hosted account is required. This repository
contains **v0.6.4** source; check [PyPI](https://pypi.org/project/spectra-sherpa/)
for availability and the [upgrade notes](docs/releases/0.6.4.md) before updating
an existing installation. See [local setup](docs/onboarding/local-30-minutes.md)
for source installation and provider configuration.

Optional extras: `scp` adds EFA, MCR-ALS, and SIMPLISMA; `hitran` and `nist` add
reference-data integrations. [Setup and data-provider guidance](docs/workflows/datasets-and-providers.md)
covers credentials and access. Obtain Eigenvector research datasets directly
from their provider before importing them. Local network access is disabled by
default; enabling an external AI provider sends permitted context to that provider.

## Chemometric toolkit

| Task | Methods and tools |
| --- | --- |
| Prepare spectra | Smoothing and derivatives, baseline correction, MSC, SNV, OSC, normalization, scaling |
| Explore mixtures and populations | PCA, MCR-ALS, SIMPLISMA, EFA, hierarchical clustering |
| Calibrate and classify | PLS regression, PLS-DA, SIMCA, KNN |
| Select variables and transfer calibration | iPLS, CARS, SPA, MC-UVE, VIP, PDS, direct standardization |
| Evaluate and apply | Cross-validation, nested CV, selection stability, model comparison, batch prediction |

A **Project** holds datasets, workflows, saved runs, models, and reports.
**Workflows** describe the analysis; **runs** retain its recorded results.
Sample labels are distinct from observation identities, and calibration,
cross-validation, and held-out evaluation have different meanings.

The included **Python SDK** lets you compose and run typed workflows in code
using the same operations as the GUI. Supported workflows can be exported to
Python or notebooks. Start with [Python workflows](docs/onboarding/python-canonical-workflows.md);
consult the [Node Library](docs/nodes/index.md) and
[capability boundaries](docs/introduction/capabilities.md) for supported methods.

## Documentation

Full docs at **[docs.spectrascientific.ai](https://docs.spectrascientific.ai)**.

- **Get started:** [Demo, Pro and local OSS](docs/introduction/cloud-vs-local.md) · [Local onboarding](docs/onboarding/local-30-minutes.md) · [Import Your First Dataset](docs/onboarding/import-first-dataset.md)
- **Workflows:** [Data Import](docs/workflows/data-import.md) · [Projects, Datasets, and Runs](docs/workflows/projects-datasets-runs.md) · [Reports and Exports](docs/workflows/reports-exports.md)
- **Reference:** [Supported File Types](docs/introduction/file-types.md) · [Node Library](docs/nodes/index.md) · [Templates](docs/workflow-templates/index.md)
- **Develop:** [Architecture](docs/architecture/index.md) · [Contributing](docs/developers/contributing.md) · [Developer Setup](docs/developers/setup.md)

## Contributing and acknowledgements

Help improve readers, scientific methods, workflow examples, documentation, and
regression tests. For a scientific issue, include the data shape, processing
steps, and expected result, using shareable data where possible. See
[Contributing](CONTRIBUTING.md); code contributions require a signed CLA.

SpectraSherpa builds on work by the wider spectroscopy community:

- **[SpectroChemPy](https://www.spectrochempy.fr/)**, by Arnaud Travert and Christian Fernandez: optional EFA, MCR-ALS, and SIMPLISMA through a matrix adapter. Upstream readers and datasets are not exposed by this integration.
- **[HITRAN / HAPI](https://hitran.org/)**: molecular line data and tools for spectral synthesis.
- **[Eigenvector Research (EVRI)](https://eigenvector.com/resources/data-sets/)**: chemometrics teaching and research datasets, obtained by users directly rather than redistributed here.
- **[NIST](https://webbook.nist.gov/)**: Chemistry WebBook (SRD 69) and Quantitative Infrared Database (SRD 79) reference spectra.

Credit the methods and data you use. See [Attributions](docs/attributions/index.md)
and [Reference Libraries and Synthesis](docs/workflows/references-synthesis.md)
for citations and provider terms.

## License and warning

Copyright © 2026 [Spectra Scientific LLC](https://spectrascientific.ai).
Licensed under [AGPL-3.0](LICENSE); commercial licensing is available.
Third-party terms, including SpectroChemPy’s CeCILL-B license, are listed in [NOTICE](NOTICE.md).

> [!WARNING]
> Provided “AS IS,” without warranty. AI suggestions and model outputs require
> scientific review; successful execution does not establish analytical validity
> or fitness for a particular use. See [DISCLAIMER](DISCLAIMER).
