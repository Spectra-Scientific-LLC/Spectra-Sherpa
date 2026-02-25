# Changelog

All notable changes to SpectraSherpa will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.1] - 2026-02-25

### Changed
- **Public API ("front door")** — `from spectra_sherpa import SherpaDataset, SpectralAxis, from_numpy` now works; all core types, axis classes, and NumPy adapters are re-exported from the top-level package. `io` and `preprocessing` submodules load lazily on first access.
- **Lightweight cold import** — `import spectra_sherpa` no longer triggers SpectroChemPy, scipy, or pandas. The `app.lib` package init was converted from eager to lazy submodule loading.
- **`serialize_result` moved to service layer** — Relocated from `api/v1/routes/workflows.py` to `app/services/serialization.py`, fixing a dependency inversion where service-layer code imported from the API route layer.
- **Node abstraction migration** — 12 preprocessing nodes migrated to the declarative `TransformSpecNode` base class, reducing boilerplate and standardising provenance, input coercion, and Python export across all stateless transforms.

### Added
- **Import sanity tests** — `test_top_level_front_door_exports` validates all canonical symbols are re-exported from the top-level package; `test_top_level_lazy_submodules` verifies `io`/`preprocessing` load lazily and that `scp_compat` is not imported on a plain `import spectra_sherpa`.

### Fixed
- **`black` formatting** — Resolved line-length violations in `preprocessing.py` that caused CI failures.

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
