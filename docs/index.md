# Welcome to SpectraSherpa

**SpectraSherpa** is an integrated platform for spectroscopic data analysis, synthesis, and workflow automation. It bridges the gap between experimental data management and advanced computational modeling.

## Quick Start

```bash
pip install -e .
spectra-sherpa
```

## Key Features

*   **Experiment Management**: Organize raw and processed spectra with version control.
*   **NIST Library Integration**: Search and download reference spectra directly from NIST WebBook.
*   **Design of Experiments (DOE)**: Manage 96-well plate configurations and complex mixture designs.
*   **Synthesis Builder**: Create synthetic spectral datasets by blending pure components with precise concentration profiles.
*   **Workflow Builder**: Visually design analysis pipelines (DAGs) for reproducible science (e.g., Preprocess -> PCA -> Export).

## Documentation Structure

*   [**Current**](current/index.md): Active product docs, architecture, and validation guides.
*   [**Past**](past/index.md): Closed issues, fixes, and historical summaries.
*   [**Future**](future/index.md): Roadmap items and forward-looking plans.

## Product Docs (Current)

*   [**Getting Started**](getting_started/installation.md): Installation and basic setup.
*   [**User Guide**](user_guide/experiments.md): Detailed instructions for all modules.
*   [**Reference**](reference/nodes.md): Technical details on available nodes and APIs.
