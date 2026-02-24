# Welcome to SpectraSherpa

**SpectraSherpa** is an integrated platform for spectroscopic data analysis, synthesis, and workflow automation. It bridges the gap between experimental data management and advanced computational modeling.

## Quick Start

```bash
pip install spectra-sherpa
spectra-sherpa
```

Your browser opens to `http://localhost:8000`. No login required — start analyzing immediately.

See the [Quickstart Guide](user/quickstart.md) for a 2-minute walkthrough.

## Key Features

*   **Experiment Management**: Organize raw and processed spectra with version control.
*   **Workflow Builder**: Visually design analysis pipelines (DAGs) for reproducible science (e.g., Preprocess -> PCA -> Export).
*   **Model Artifacts**: Train, persist, and reload models (PCA, PLS, MCR, PLSDA, KNN, SIMCA) for batch prediction.
*   **Project Management**: Group experiments, workflows, scripts, and models into versioned projects.
*   **NIST Library Integration**: Search and download reference spectra directly from NIST WebBook.
*   **Design of Experiments (DOE)**: Manage 96-well plate configurations and complex mixture designs.
*   **Synthesis Builder**: Create synthetic spectral datasets by blending pure components with precise concentration profiles.

## Documentation

*   [**Installation**](user/installation.md): Install and launch SpectraSherpa.
*   [**Quickstart**](user/quickstart.md): Load data and run your first workflow.
*   [**Configuration**](user/configuration.md): Configure SpectraSherpa for your environment.
*   [**User Guide**](user/experiments.md): Detailed instructions for all modules.
*   [**Node Reference**](user/reference/nodes.md): Complete catalog of available analysis nodes.
*   [**Architecture**](dev/architecture.md): System design, entity relationships, and model artifact pipeline.
