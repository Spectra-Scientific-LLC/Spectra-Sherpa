# Changelog

All notable changes to SpectraSherpa will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Extension Contract guide** — `docs/dev/extension-contract.md` documents the stable, OSS-owned integration surface (AI advisor, auth resolvers, config overlay, demo policy, LLM provider catalog, public paths) and the compatibility rules extension authors should follow.
- **Injectable LLM provider catalog** — new `spectra_sherpa.app.contracts.llm_catalog` (`LLMProviderMeta`, `get_llm_provider_catalog` / `set_llm_provider_catalog`) supersedes the previously duplicated, hard-coded provider tables. The OSS default is unchanged; a deployment can supply its own provider catalog without editing source, and `/api/v1/config` reflects it at request time.
- **`AppMode` enum** — a canonical, string-compatible identifier for `local` / `hybrid` / `enterprise`, giving deployment-mode checks a single source of truth.
- **`CONTRIBUTORS.md`** — append-only contributor credits.

### Changed
- **Documented `AIServiceProvider` exception contract** — the advisor protocol now specifies the exceptions an implementation must raise (`SherpaAdvisorUnavailable`, `SherpaAuthorizationError`, `SubscriptionRequiredError`) so error handling stays stable across implementations.
- **`/api/v1/config` provider metadata sourced from the catalog contract** — output is byte-identical for local installs.

### Removed
- **Removed an unused legacy CI workflow** — no longer part of the project.

## [0.4.2] - 2026-05-07

### Added
- **Workflow builder sheet tabs** — Projects can organize workflows as worksheet tabs with per-sheet ordering, colors, duplication, deletion guards, trial tabs, and worksheet-scoped state restoration.
- **Project data-source associations** — Project Details now tracks data sources and workflow/data-source links so sheets can inherit dataset color and provenance.
- **Worksheet advisor channels** — Workflow sheets can bind to dedicated Sherpa Advisor channels so Topics follow the active worksheet.
- **`POST /api/v1/chat/stream`** — BYO chat SSE endpoint for local mode, with active workflow context included when available.
- **Packaged Sherpa WebSocket contract** — `sherpa-ws-v1.json` is installed as package data and can be used for runtime validation with `SPECTRA_VALIDATE_WS=1`.
- **CI drift guard for `frontend/src/types/api-generated.ts`** — The frontend CI job validates generated API types against the committed OpenAPI contract.

### Changed
- **Exported-script artifact location** — `export_artifacts()` (used by generated Python scripts and notebooks) now writes timestamped output to `./exports/<workflow>_<ts>/` by default instead of directly into the current working directory. Set `SPECTRA_SHERPA_EXPORT_DIR=<path>` to override. This prevents repo-root pollution when users run exported scripts from inside a checkout.
- **BYO chat configuration moved to `CHAT_ENDPOINT_*`** — The OSS chat assistant is now configured via `CHAT_ENDPOINT_URL`, `CHAT_ENDPOINT_KEY`, and `CHAT_ENDPOINT_MODEL` environment variables (any OpenAI-compatible endpoint). Vendor-specific keys such as `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` no longer power the OSS chat path.
- **Workflow builder actions and layout** — Header actions, sheet tabs, trial detail views, Add Nodes, and Inspector interactions were refined for narrower windows and repeated sheet switching.

## [0.3.0] - 2026-03-30

### Security
- **Auto-generated local SECRET_KEY** — In local mode, if `SECRET_KEY` is not set, a cryptographically random key is generated on first startup and persisted to `~/.spectra_sherpa/.secret_key` (mode 0600). This prevents JWT tokens from being invalidated on every restart without requiring manual configuration.

### Added
- **Health endpoint degraded state** — `GET /api/v1/health` now returns `{"status": "degraded", "plugin_failure_count": N}` when one or more filesystem or entry-point plugins failed to load at startup, making operational issues visible without exposing internal exception details.
- **Shared LLM quota helper** — Added a dedicated `llm_rate_limits` service so REST and WebSocket Sherpa flows use the same per-user quota logic and superuser bypass rules.
- **Enterprise connection validation UI** — Configured enterprise and demo deployments now show a persistent **Validate Connection** action in Settings > Integrations instead of hiding connection checks after initial setup.
- **Data Story contextual prompt input** — The Data page now includes an Additional Context field so users can pass instrument or process context into Sherpa Data Story generation.
- **Config degradation signaling** — `GET /api/v1/config` now includes `configStatus` and `configError` fields so hybrid and enterprise deployments can distinguish a subscription-overlay outage from a deliberate “all premium features disabled” state.
- **OSS extension boundary hardening** — Added an explicit actor/bootstrap contract and per-app WebSocket action registry so managed auth and premium actions can be composed by the proprietary layer without implicit OSS ownership.

### Fixed
- **Hybrid mode implicit identity logging** — Rejections of credential-free requests from non-loopback hosts in hybrid mode are now logged at `WARNING` level. Grants of implicit loopback identity are logged at `DEBUG`.
- **Migration pre-drop warning** — The `a76d82a816bf` migration (remove custom_algo table) now logs a `WARNING` with the row count before dropping the table if any data is present.
- **`test_io_csv` SCP skip guard** — Skip condition now uses `HAS_SCP` from `scp_compat` instead of checking if `create_spectral_dataset is None`; the import always succeeds when the compat layer provides stubs.
- **Test files no longer import `spectrochempy` directly** — `test_modeling_nodes`, `test_core_modeling`, and `test_data_loading_golden` now import `NDDataset` from `scp_compat` per the established rule.
- **PostgreSQL FK cascade migration** — `p6q8r0s2t815` now uses direct `drop_constraint` / `create_foreign_key` on PostgreSQL instead of `batch_alter_table(recreate="always")`, which failed with `DependentObjectsStillExistError` when foreign keys referenced the primary key being rebuilt.
- **Sherpa/WebSocket completion handling** — Server-backed Sherpa chat and related SSE proxy flows now terminate on upstream `done` events instead of waiting for socket close, eliminating long-lived “Thinking” states in enterprise/demo deployments.
- **Sherpa auth and quota enforcement** — Sherpa proxy handlers now distinguish authorization failures from subscription failures, apply shared per-user LLM rate limits consistently, and consume demo Sherpa quota uniformly across chat, sync, Data Story, code, peak, and report actions.
- **Simplified paid AI quota model** — Normal hybrid and enterprise deployments now use `MAX_LLM_REQUESTS_PER_HOUR` as the main auditable paid-usage limit, with superusers bypassing the quota.
- **Workflow template edge validation on load** — The frontend workflow store now preserves explicit `"default"` ports from backend templates, preventing valid multi-input template edges from appearing red after load.
- **Data Story / Sherpa Advisor interaction lockout** — Data Story generation is now visibly disabled while Sherpa Advisor is using the shared AI channel, with explicit user-facing messaging instead of ambiguous first-run failures.
- **Plot node freeze on rendered workflow plots** — The Plotly wrapper now clones reactive payloads and avoids stacking event listeners, preventing workflow-page freezes when opening rendered plot nodes.
- **Sherpa capability defaults are now explicit** — Base app config always exposes the full Sherpa capability set as `false`, avoiding missing-key / `undefined` feature states in local mode and during server-overlay failures.
- **Subscription overlay outages are visible to the UI** — Hybrid and enterprise config responses now fail closed on premium features while also surfacing a machine-readable degraded status instead of silently appearing as an empty feature set.
- **Contract export shadowing removed** — `spectra_sherpa.app.contracts` no longer re-exports WebSocket action names that collided with Sherpa capability names such as `SHERPA_DATA_STORY` and `SHERPA_WRITE_REPORT`.
- **Mode-matrix contract tests now use shared capability constants** — Config-shape regressions are now checked against the canonical contract vocabulary instead of duplicated string literals.
- **OSS/server boundary cleanup** — Removed the OSS managed-auth fallback, made `/auth/me` ownership explicit in managed builds, and aligned server-backed chat with the public AI provider contract.

### Changed
- **Workflow node modules split by package** — The large monolithic preprocessing and output node files were broken into package-style modules, reducing file size and clarifying ownership without changing the public node catalog.
- **Frontend workflow store type extraction** — Workflow store types were moved into `frontend/src/stores/workflow-types.ts` and frontend unit coverage was expanded around stores, errors, and demo state.
- **Release documentation refresh** — Configuration, quickstart, frontend README, developer LLM contract docs, and the main README were updated to match the current Sherpa integration flow, quota model, Data Story UX, and future-domain positioning.
- **Hybrid/provider architecture cleanup** — The Sherpa advisor layer is now split into a registry/fallback plus deployment-backed transport, and the app factory exposes cleaner extension hooks for managed builds.

### Removed
- **Dead compatibility cleanup** — Removed unused auth and deployment-provider helper code left behind by the auth/provider split.

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
- **Python & Notebook Export** — Generate reproducible scripts or Jupyter notebooks from any workflow
- **Project Management** — Experiments, workflows, scripts, and models with versioned snapshots
- **Experiment Tracking** — DOE support with 96-well plate layouts, samples, and mixtures
- **Deploy** — Batch prediction, folder watching, execution run tracking with provenance
- **LLM Chat** — Bring-your-own-key AI assistant for spectral analysis
- **Plugin System** — Extend via Python entry points or drop-in modules
- **Data Privacy Controls** — Fine-grained egress permissions (deny-all default)
- **Three Deployment Modes** — Local (zero-config), Hybrid (cloud offload), Enterprise (multi-user)
- **SpectroChemPy Integration** — Optional `[scp]` extra for advanced spectral algorithms
