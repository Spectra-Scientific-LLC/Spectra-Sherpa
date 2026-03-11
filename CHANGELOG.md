# Changelog

All notable changes to SpectraSherpa will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.6] - 2026-03-11

### Changed
- **Toolbar reorganization** — Workflow Builder toolbar expanded from 8 to 11 sections following the standard chemometrics workflow (Unscrambler/PLS_Toolbox pattern). The former "Analysis" section was split into Exploratory, Regression, Clustering, and Validation. Deployment section is now visible.
- **Preprocessing node consolidation** — 14 individual preprocessing nodes merged into 4 consolidated nodes with method dropdowns: Smooth (Savitzky-Golay/Whittaker/Gaussian), Derivative (SG/Norris-Williams), Normalize (SNV/MSC/Scale), Scale/Center (Mean Center/Autoscale/Pareto/Max).
- **Classification predict consolidation** — Three separate Apply PLS-DA / Apply KNN / Apply SIMCA nodes replaced by a single "Apply Classifier" node (`classification.predict`) that auto-detects the model type.
- **Backend category renames** — `NodeMetadata.category` updated across 20 nodes: `modeling` split into `exploratory`, `regression`, `clustering`; `analysis` items moved to `validation`.
- **Executor: named-port-only dispatch** — Removed dual-path executor and positional `input_0`/`input_1` fallbacks. All 63 nodes now declare explicit `input_ports` and receive inputs as named kwargs.
- **Frontend: canonical node types only** — Removed `NODE_TYPE_MAP`, `normalizeNodeType()`, `getLegacyNodeType()`, `MULTI_INPUT_NODES`, `PARAM_NAME_MAP`, and all UPPERCASE-to-dot-notation mapping functions. Node types are always canonical (`model.pca`, `preprocess.smooth`).
- **Provenance key standardized** — All provenance writers now use `"op_id"` (was `"operation"` in some paths). Removed the reader-side migration shim in `Provenance.from_list()`.
- **Template seeding upsert** — `ensure_workflow_templates()` now upserts by name instead of skip-if-any-exist, so new templates propagate to existing databases on startup.

### Added
- **Conditional parameter visibility** — `NodeParameter.visible_when` field hides irrelevant parameters in the Inspector based on controlling parameter values (e.g., Whittaker-specific params hidden when Savitzky-Golay method is selected). Implemented across full stack: backend dataclass, API schema, TypeScript types, Vue template filtering.
- **SIMCA model artifacts** — SIMCA added to `EXTRACT_REGISTRY` and `LoadApplyModelNode` predict/classify support.
- **Variadic port support** — `PortMetadata.variadic` flag ensures nodes like Blend, Merge, and Golden Grid Align always receive a list input, even with a single upstream edge. Exposed in API schema and executor normalization.
- **`Any` type wildcard** — Output nodes (Plot, Export, Stats, Contour, DataTable) now accept `Any/1.0` inputs, allowing direct connections from model output ports (ScoreMatrix, LoadingMatrix, etc.). Wildcard logic added to both backend `is_compatible()` and frontend `validateTypeRefs()`.
- **Python export variadic support** — `build_input_map()` now accumulates multi-edge same-port inputs into list expressions instead of silently dropping duplicates.
- **`NodeRegistry.__contains__()`** — Supports `node_type in node_registry` syntax for validation checks.
- **`variadic` on frontend `NodePortMetadata`** — TypeScript interface now includes `variadic?: boolean`, enabling frontend cardinality enforcement in `addEdge()`.

### Fixed
- **`Node.uses_named_ports()` restored** — Method was removed during dual-path cleanup but still called by the executor at validation and dispatch time, causing all DAG execution to crash with `AttributeError`.
- **`Node.validate_parameters()` aligned with executor** — Now respects `param_def.default`, matching the executor's `_validate_parameters()`. Workflows with required params that have defaults no longer crash at execution time.
- **Variadic port list accumulation** — Executor now correctly accumulates multiple inputs into a list for variadic ports (Blend, Merge, Golden Grid Align) instead of silently overwriting with the last value.
- **"default" port inference** — Executor no longer misroutes 2nd+ edges to synthetic `input_1`/`input_2` keys when the target port is literally named `"default"`.
- **Non-variadic port cardinality enforced** — Backend validation rejects multiple edges targeting the same non-variadic port; executor raises at runtime as a safety guard; frontend replaces existing edge instead of duplicating.
- **SherpaDataset compatibility in BlendNode/MergeSpectraNode** — Replaced `dataset.meta = {...}` / `set_coordset()` (NDDataset-only APIs) with `meta["key"] = value` / `feature_axis` / `sample_axis` setters.
- **Duck-typed wavenumber extraction** — `build_golden_grid()` and `interpolate_to_grid()` now handle both SherpaDataset (`feature_axis.values`) and NDDataset (`.x.data`) inputs.
- **Backend workflow templates rewritten** — 10 seed templates corrected from 14+ invalid node types to registered types with valid parameter names.
- **Frontend templates rewritten** — 12 frontend `TEMPLATES` corrected: removed non-existent `format`/`path` params from `data.source` nodes, fixed `output.export` invalid `format: "pickle"` to `format: "csv"`.
- **Frontend `WorkflowBuilderContent` defaults corrected** — `preprocess.scale` (`range` → `method`), `preprocess.clip_range` (`min_wn`/`max_wn` → `min_wavenumber`/`max_wavenumber`), `classification.simca` (`alpha` → `confidence_level`), `output.plot` (`type`/`xAxis`/`yAxis` → `plot_type`), `stats.summary` (removed non-existent `metrics` param), `output.contour` (`reverse_x` default corrected to `false`).
- **`create_workflow()` validates node types** — Endpoint now checks all non-ualgo node types against the registry and returns HTTP 400 for unknown types.
- **`instantiate_template()` validates node types** — Template instantiation now checks all node types against the registry before persisting, preventing stale or corrupted DB templates from producing invalid workflows.

### Removed
- **`resolve_legacy_input()`** — Deleted function and all `input_0`/`input_1` kwarg fallbacks across 14+ node files.
- **`kwargs` parameter from `bind_X()`/`bind_y()`** — Removed from signatures and ~31 call sites; was only used by `resolve_legacy_input`.
- **Spectral axis v1 deserialization** — Deleted `_deserialize_spectral_axis()`, `_slice_spectral_axis()`, and the `from_dict()` v1 fallback branch.
- **Builder `blend()` deprecated method** — Deleted wrapper; API route now calls `synthesize_spectra()` directly.
- **`APP_MODE=demo` config alias** — Removed deprecated mode mapping and associated tests.
- **Disabled config API endpoints** — Removed `save_spectrasherpa_config()` and `delete_spectrasherpa_config()` stubs that returned 403.
- **Frontend legacy mapping system** — `mapParamsToBackend()`, `mapParamsFromBackend()`, `migrateLegacyParams()`, and related code fully deleted.

## [0.1.4.1] - 2026-02-25

### Changed
- **Public API ("front door")** — `from spectra_sherpa import SherpaDataset, SpectralAxis, from_numpy` now works; all core types, axis classes, and NumPy adapters are re-exported from the top-level package. `io` and `preprocessing` submodules load lazily on first access.
- **Lightweight cold import** — `import spectra_sherpa` no longer triggers SpectroChemPy, scipy, or pandas. The `app.lib` package init was converted from eager to lazy submodule loading.
- **`serialize_result` moved to service layer** — Relocated from `api/v1/routes/workflows.py` to `app/services/serialization.py`, fixing a dependency inversion where service-layer code imported from the API route layer.
- **Node abstraction migration** — 12 preprocessing nodes migrated to the declarative `TransformSpecNode` base class, reducing boilerplate and standardising provenance, input coercion, and Python export across all stateless transforms.

### Added
- **Import sanity tests** — `test_top_level_front_door_exports` validates all canonical symbols are re-exported from the top-level package; `test_top_level_lazy_submodules` verifies `io`/`preprocessing` load lazily and that `scp_compat` is not imported on a plain `import spectra_sherpa`.

### Fixed
- **`black` formatting** — Resolved line-length violations in `preprocessing.py` that caused CI failures.

## [0.1.4] - 2025-02-24

Initial open-source release.

### Added
- **Workflow Builder** — Visual DAG editor with over 60 nodes for preprocessing, modeling, classification, diagnostics, and DOE
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
