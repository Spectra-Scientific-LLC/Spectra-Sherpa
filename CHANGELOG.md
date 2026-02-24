# Changelog

All notable changes to SpectraSherpa will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 2025-02-24

Initial open-source release.

### Added
- **Workflow Builder** — Visual DAG editor with 100+ nodes for preprocessing, modeling, classification, diagnostics, and DOE
- **Model Artifacts** — Train, persist, and reload PCA, PLS, MCR, PLSDA, KNN, SIMCA models
- **Type System** — URI-based port typing with registry-driven connection validation
- **Python & Notebook Export** — Generate standalone scripts or Jupyter notebooks from any workflow
- **Project Management** — Experiments, workflows, scripts, and models with versioned snapshots
- **Experiment Tracking** — DOE support with 96-well plate layouts, samples, and mixtures
- **Deploy** — Batch prediction, folder watching, execution run tracking with provenance
- **LLM Chat** — Bring-your-own-key AI assistant for spectral analysis
- **Plugin System** — Extend via Python entry points or drop-in modules
- **Data Privacy Controls** — Fine-grained egress permissions (deny-all default)
- **Three Deployment Modes** — Local (zero-config), Hybrid (cloud offload), Enterprise (multi-user)
- **SpectroChemPy Integration** — Optional `[scp]` extra for advanced spectral algorithms
