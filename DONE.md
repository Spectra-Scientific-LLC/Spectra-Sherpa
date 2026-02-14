# DONE

This document tracks completed initiatives, architectures, and bug fixes.

## 1. Architecture Refactor (Unified Data Model)
**Source**: `ARCHITECTURE_REFACTOR_PLAN.md`
**Status**: COMPLETED

- **Phase 1**: Unified Spectral Data Layer — `app/lib/spectral` (NDDataset, Parquet, Units)
- **Phase 2**: Custom Workflow Nodes — 8 atomic nodes (Blending, Synthetic Builder)
- **Phase 3**: Native Preprocessing — all preprocessing migrated to NDDataset
- **Phase 4**: Smart Unit Handling — auto Transmittance/Absorbance conversion
- **Phase 5**: Legacy Deprecation — removed `libs/project0`, `libs/project1`, `SpectrumRecord`

## 2. Critical Chemometric Fixes
**Source**: `docs/past/CHEMOMETRIC_FIX_PLAN.md`
**Status**: COMPLETED

- MCRNode: Fixed NameError, validated matrix shapes (C/St)
- SIMCANode: Single port → 5 semantic ports
- PeakFindingNode: Single port → 3 semantic ports, fixed type mismatch

## 3. 3-Repo Split
**Source**: `docs/past/REFACTOR_3_REPO_STRATEGY.md`, `docs/past/3_REPO_SPLIT_SUMMARY.md`
**Status**: COMPLETED (Steps 1-5)

- **Repo 1** (`Refactored/`): OSS local-first core
- **Repo 2** (`spectrasherpa-server/`): Auth/admin routes via `extra_routers`
- **Repo 3** (`spectra-ops/`): Docker, compose, nginx, Caddy, deploy docs
- Contracts, mode-matrix tests, mode_policy.py, MCP tools, physical split — all done

## 4. MCP Tool System
**Source**: `docs/past/SHERPA_IMPLEMENTATION_PLAN_V2.md`
**Status**: COMPLETED

- ToolRegistry + @register_tool, ToolScope (public/admin/internal), ToolOrigin (builtin/plugin)
- 6 built-in tools: list_node_types, describe_node, suggest_preprocessing, get_workflow_summary, validate_workflow, list_workflows
- LLM integration: multi-turn function-calling (OpenAI + Anthropic)
- WS actions: tool_list (scope-filtered), tool_invoke (rate-limited)
- Plugin support: plugin_context() with trust constraints

## 5. Sherpa Engine
**Source**: `docs/past/SHERPA_IMPLEMENTATION_PLAN.md`
**Status**: COMPLETED

- Direct Anthropic Claude integration with MCP tools
- Dual-path WS routing: engine direct (SHERPA_ENGINE_API_KEY) or cloud proxy
- System prompt with spectral analysis persona + auto-injected workflow context
- Multi-turn tool loop (max 5 rounds), tool progress streaming to frontend

## 6. Navigation Redesign (7 Phases)
**Source**: `docs/past/NAVIGATION_REDESIGN.md`
**Status**: COMPLETED

- **6-page architecture**: Project -> Data -> Workflow -> Experiments -> Deploy -> Report
- Phase 1: Cleanup (deleted 8 backend + ~30 frontend files)
- Phase 2: Project page (card grid, import/export, technique/sample_type fields)
- Phase 3: Data page (3-tab: Load/Explore/Synthesis)
- Phase 4: Workflow consolidation (TemplateGallery sidebar)
- Phase 5: Experiments page (ExecutionRun model, run history, batch, compare)
- Phase 6: Deploy + Batch Predict (FolderWatch, BatchPrediction, folder monitoring)
- Phase 7: Report page (assembler, preview, HTML/MD/JSON/Python export, AI narrative)

## 7. Type System (5 Phases)
**Status**: COMPLETED

- TypeRegistry + registry.json (URI: `spectrasherpa://types/{Name}/{M.m}`)
- All 120 PortMetadata use `type_ref=` (port_type property removed)
- Connection validator with subtype + version compat
- NodeResult dataclass wrapping outputs + diagnostics
- Redundancy reduction: deleted 19 JSON schemas, graph_header.py

## 8. Python Export Refactor (Phases 0-3)
**Status**: COMPLETED

- graph_utils.py: Shared topological_sort(), build_dependency_map(), build_input_map()
- Edge NamedTuple normalizes executor + DB edge models
- Node base class: generate_python(), scp_method, scp_param_map, python_extra_imports
- 19 preprocessing nodes annotated, python_export.py rewritten as thin orchestrator

## 9. Notebook Export
**Status**: COMPLETED

- `notebook_export.py`: generate_notebook() wraps Python export as .ipynb JSON
- Splits script into 4 cells: markdown title, imports, workflow function, main block
- Backend endpoint: GET /workflows/{id}/export/notebook
- Frontend: SplitButton in WorkflowBuilder, menu item in Report page
- 20 unit tests passing

## 10. Bug Fix Batch (8 fixes, 16 regression tests)
**Status**: COMPLETED

- **Workflow provenance**: technique/sample_type persisted in create/update/list/snapshot/restore
- **Deploy prediction history**: Shows all run types (not just folder_watch)
- **Comparison ordering**: ORDER BY added to compare_runs and report-data queries
- **Rate limit coverage**: /api/v1/deploy added to RATE_LIMITED_PATHS
- **Event listener leak**: BatchRunTab cleanup on unmount
- **Path traversal**: validate_folder_path() restricts to data_dir in non-local modes
- **Folder watch dedupe**: Full path keying (str(file_path), not file_path.name)
- **Batch job progress**: JobStore connected via MainLayout watch(backendConnected)

## 11. Digital Ocean Deployment
**Status**: COMPLETED

- IP: 146.190.48.1:8000, hybrid mode, SQLite
- Fixes: Alembic logging, egress for Sherpa Engine, silent startup catch
- Repos 1+2 deployed, guest superuser created

## 12. Project Persistence
**Status**: COMPLETED (42 tests)

- DB-backed Project + ProjectVersion models (self-ref FK, cascading deletes)
- Full CRUD: create, list, get, update, delete, link/unlink workflows+experiments
- Save All: single-request bulk save of linked workflows + experiments
- Export/import: full project bundles with versioned snapshots
- Frontend: Pinia store rewrite, ProjectDetailsDrawer, card grid with search/filter

## 13. ProjectScript
**Status**: COMPLETED (23 tests)

- DB model: ProjectScript with FK to Project, User, source_workflow (SET NULL)
- CRUD + generate-from-workflow API endpoint
- Snapshot/import integration: scripts included in project bundles
- Frontend: store + types for script management
- Alembic migration: `h8c6d0e4f037` (single head)

## 14. AnalysisDataset Architecture
**Status**: COMPLETED (~60 tests)

- **AnalysisDataset** (`app/lib/analysis_dataset.py`): Canonical DAG runtime container
  - Fields: X (2D array), x_axis/y_axis (AxisInfo), target, meta, provenance, backend, title, units
  - NDDataset-compatible API: `.data`, `.x`, `.y`, `.shape`, `.ndim`, `.copy()`, `.__getitem__`, `.set_coordset()`
  - Wire-format backward compat: `to_dict()` emits `type: "NDDataset"` and `x_axis.data`
  - `from_dict()` deserialization, `from_sklearn_bunch()` adapter
- **Per-node `requires_scp`**: Replaced blanket `_SCP_CATEGORIES` gate with per-node flag
  - 11 SCP-only nodes: ALS, rubberband, MSC, PCA, PLS, MCR, EFA, SIMPLISMA, OSC, PLSDA, SIMCA
  - ~38 portable nodes: run on AnalysisDataset without SCP (SNV, Scale, PCR, SVR, KMeans, etc.)
  - Clear ImportError with install instructions when SCP-only node used without SCP
- **Node migration**: All portable nodes output AnalysisDataset instead of `scp.NDDataset()`
  - Preprocessing (18), modeling (13), classification (3), output (4), data, blend, time_series, custom
  - scipy fallback for Savitzky-Golay nodes when SCP absent
- **Executor + serialization**: Extended `serialize_for_api()` and `serialize_result()` with AnalysisDataset branches
- **SCP adapters**: `from_nddataset()`, `to_nddataset()` in scp_compat.py for round-trip conversion

## 15. SpectroChemPy Optional Dependency
**Status**: COMPLETED (6 scp-compat tests)

- `scp_compat.py`: Centralized gateway with `HAS_SCP`, `require_scp()`, stub classes
- `NDDataset`/`Coord` → stub classes when absent — `isinstance()` always safe
- `pip install spectra-sherpa[scp]` to enable SCP features
- All source files import via scp_compat (AST CI test enforces)
- No-SCP data paths: sklearn + synthetic return numpy arrays via AnalysisDataset
- `/workflows/spectrochempy-examples` returns HTTP 501 when SCP absent

## 16. Alembic Migration Chain
**Status**: COMPLETED (verified on fresh DB)

- 16 linear migrations, single root `a7f3e891bc4d` → single head `h8c6d0e4f037`
- Chain: a7f→b8f→c9e→d0f→f1a→a2b→b3c→472→e94→159→c6d→d4a→e5b→f6a→g7b→h8c
- Bootstraps 20+ tables idempotently (`_ensure_*_table()` pattern)
- SQLite FK limitation handled: `add_column` without FK constraint, ORM enforces referential integrity

## 17. passlib → bcrypt Migration
**Status**: COMPLETED

- Replaced unmaintained passlib with direct `bcrypt.hashpw()`/`bcrypt.checkpw()` calls
- Removed passlib dependency from pyproject.toml, relaxed bcrypt pin to `>=4.0.1`
- Produces standard `$2b$` hashes, backward-compatible with existing DB data

## 18. Test Suite Fixes (598 passing, 0 failures)
**Status**: COMPLETED

- **test_pcr_node**: Fixed `np.array(AnalysisDataset)` creating 0-d array — use `.shape` directly
- **test_gateway_user_api_key**: Fixed passlib crash + ASGI loopback auth exemption (monkeypatch `get_client_host`)
- **test_require_scp_raises_when_absent**: Changed `skipif(HAS_SCP)` to monkeypatch for all-environment coverage
- **test_load_reference_file[P350.SPC]**: Confirmed skip-by-design (missing local data file)
- Final: 598 passed, 1 skipped (data file), 0 failed

## Documentation
- `docs/deployment/DIGITAL_OCEAN.md`: Production deployment guide
- `docs/developer/architecture.md`: System design v1.4
- `docs/developer/setup.md`: Developer setup guide
- `DONE.md` / `CURRENT.md` / `FUTURE.md`: Project tracking
