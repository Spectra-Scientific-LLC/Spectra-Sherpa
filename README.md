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

This enables native NDDataset operations, SCP file format readers (JCAMP-DX, SPC, SPA, OPUS), and SpectroChemPy preprocessing methods.

## Features

- **Workflow Builder** -- Visually design reproducible analysis pipelines (DAGs) with 30+ nodes for preprocessing, modeling, classification, and diagnostics
- **Type System** -- 120 typed ports with registry-based connection validation
- **Python & Notebook Export** -- Generate standalone `.py` scripts or Jupyter notebooks from any workflow
- **Project Management** -- Organize experiments, workflows, and scripts with versioned snapshots
- **Experiment Tracking** -- DOE support with 96-well plate layouts, samples, mixtures, and factor definitions
- **LLM Chat** -- Bring-your-own-key integration with OpenAI, Anthropic, DeepSeek, and more
- **Deploy** -- Execution runs, folder watch, batch prediction

## Deployment Modes

| Mode | Use Case |
|------|----------|
| **Local** (default) | Single user, no login, no network required |
| **Hybrid** | Local app + cloud auth + Sherpa AI advisor |
| **Demo** | Multi-user server with JWT auth and rate limiting |

## Installation

### Requirements

- Python 3.11+
- Node.js 18+ (for frontend development only)

### From source

```bash
git clone https://github.com/Spectra-Scientific-LLC/spectrasherpa.git
cd spectrasherpa
pip install -e ".[scp,sherpa]"
spectra-sherpa
```

### Optional extras

| Extra | Install | Description |
|-------|---------|-------------|
| `scp` | `pip install spectra-sherpa[scp]` | SpectroChemPy NDDataset support |
| `sherpa` | `pip install spectra-sherpa[sherpa]` | Sherpa AI advisor (Anthropic Claude) |
| `cloud` | `pip install spectra-sherpa[cloud]` | PostgreSQL + Gunicorn for production |

## Documentation

Full documentation is available at [docs/](docs/index.md):

- [Installation](docs/user_guide/installation.md)
- [Quickstart](docs/user_guide/quickstart.md)
- [Configuration](docs/user_guide/configuration.md)
- [Node Reference](docs/reference/nodes.md)

## Acknowledgments

SpectraSherpa builds on [SpectroChemPy](https://www.spectrochempy.fr/) by CEA/CNRS/INRIA for spectral data handling. SpectroChemPy is licensed under [CeCILL-B](https://cecill.info/licences/Licence_CeCILL-B_V1-en.html) and is an optional dependency.

## License

Copyright 2024-2026 Spectra Scientific LLC.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

See [LICENSE](LICENSE) for the full text.
