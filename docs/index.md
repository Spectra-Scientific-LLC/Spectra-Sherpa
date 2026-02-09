# Welcome to SpectraSherpa

**SpectraSherpa** is an integrated platform for spectroscopic data analysis, synthesis, and workflow automation. It bridges the gap between experimental data management and advanced computational modeling.

## Quick Start

```bash
pip install spectra-sherpa
spectra-sherpa
```

Your browser opens to `http://localhost:8000`. No login required — start analyzing immediately.

See the [Quickstart Guide](getting_started/quickstart.md) for a 2-minute walkthrough.

## Key Features

*   **Experiment Management**: Organize raw and processed spectra with version control.
*   **NIST Library Integration**: Search and download reference spectra directly from NIST WebBook.
*   **Design of Experiments (DOE)**: Manage 96-well plate configurations and complex mixture designs.
*   **Synthesis Builder**: Create synthetic spectral datasets by blending pure components with precise concentration profiles.
*   **Workflow Builder**: Visually design analysis pipelines (DAGs) for reproducible science (e.g., Preprocess -> PCA -> Export).

## Deployment Modes

SpectraSherpa runs in three modes to fit different use cases:

| Mode | Use Case |
|------|----------|
| **Local** (default) | Single user on your laptop — no login, no network |
| **Hybrid** | Local app with cloud identity linking and GPU offload |
| **Demo** | Cloud-hosted multi-user server with JWT auth and rate limiting |

See [Modes & Configuration](getting_started/modes.md) for details.

## Documentation

*   [**Installation**](getting_started/installation.md): Install and launch SpectraSherpa.
*   [**Quickstart**](getting_started/quickstart.md): Load data and run your first workflow.
*   [**Modes & Configuration**](getting_started/modes.md): Configure local, hybrid, or demo mode.
*   [**User Guide**](user_guide/experiments.md): Detailed instructions for all modules.
*   [**Node Reference**](reference/nodes.md): Complete catalog of available analysis nodes.
*   [**Deployment**](deployment/DIGITAL_OCEAN.md): Deploy to DigitalOcean with Docker.

## Documentation Structure

*   [**Current**](current/index.md): Active product docs, architecture, and validation guides.
*   [**Past**](past/index.md): Closed issues, fixes, and historical summaries.
*   [**Future**](future/index.md): Roadmap items and forward-looking plans.
