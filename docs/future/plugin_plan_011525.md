# Plugin Management Plan

This plan captures a comprehensive plugin management system aligned with the proposal for extensibility, cloud extensions, and LLM/community plugins. It is structured to preserve API stability for CLI consumers while enabling safe, scalable, and reproducible plugin execution.

## Plan Overview
- Establish a strict plugin contract (manifest + schemas) and a plugin registry that the DAG system can load dynamically.
- Run plugins via a single execution interface (local, remote, or LLM-generated) with JSON-safe outputs and artifact references.
- Add sandboxing/permissions, version pinning, and provenance to preserve reproducibility.
- Build plugin lifecycle tools (scan, validate, enable/disable, reload, update) with CLI and API endpoints.

## 1) Plugin Contract and Manifest
Add required fields to `plugin.yaml`:
- `manifest_version`
- `plugin_id` (immutable UUID)
- `version`
- `min_platform_version`
- `max_platform_version`
- `node_metadata` (matches NodeMetadata schema)
- `input_schema` (JSON Schema)
- `output_schema` (JSON Schema)
- `capabilities` (filesystem, network, GPU)
- `resources` (CPU, memory, timeout)
- `dependencies` (optional; see packaging)
- `artifact_policy` (by_value vs by_reference)
- `checksum` and optional `signature`

Keep your existing `node_metadata` shape; add JSON Schema for inputs/outputs to make validation automatic and CLI-friendly.

## 2) Packaging and Installation
- Folder-based plugin layout:
  - `plugin.yaml`, `plugin.py`, optional `requirements.txt`, `tests/`, `README.md`
- Two installation paths:
  1) Local folder drop into `~/.spectra-workflows/plugins/`
  2) CLI/API install from a zip or git URL (future marketplace)
- Persist installed plugins in a registry store (DB table or local `plugins.json`) with: `plugin_id`, `version`, `path`, `enabled`, `trusted`, `installed_at`, `checksum`.

## 3) Execution Model
Introduce a `PluginNode` wrapper in `app/services/plugins` that:
- Maps DAG inputs to plugin inputs
- Validates with `input_schema`
- Executes via a plugin runtime (local/remote)
- Normalizes output (JSON-safe + artifact refs) using `output_schema`

Align output for CLI use: always return JSON-safe metadata, store large arrays as artifacts.

## 4) Sandboxing and Security
- Do not rely solely on RestrictedPython for safety.
- Use process isolation for local Python plugins:
  - Run plugin code in a separate process with resource limits (CPU/memory/time)
  - Disable network by default; allow only if `capabilities.network = true`
  - Restrict filesystem access to `settings.data_dir` or explicit allowlist
- Remote plugins:
  - Use explicit API keys with scoped permissions
  - Enforce timeouts and response size limits
- Maintain an allowlist of modules for local plugins (numpy/scipy/sklearn/spectrochempy).

## 5) Data and Artifact Handling
- Standardize input data into a `DatasetRef` object:
  - `path`, `checksum`, `shape`, `dtype`, `units`, `wavenumbers`
- For remote plugins, send references or chunked data uploads; avoid huge JSON.
- Store outputs as:
  - `result`: JSON-safe metadata
  - `artifacts`: file refs (npz/parquet/csv) stored in a managed output directory
- Add provenance: plugin ID/version, input checksums, execution timestamp.

## 6) Hot Reload and Lifecycle
Plugin manager responsibilities:
- `scan_plugins()` and validate manifest/schema
- Load into NodeRegistry (or remove if disabled)
- Detect changes and reload by restarting plugin worker process

Ensure running workflows keep the old plugin version (pin by version hash). Provide explicit reload command; auto-reload should be optional and can be unsafe for reproducibility.

## 7) Versioning and Compatibility
- Every workflow execution should store:
  - `plugin_id`, `version`, `checksum`, `manifest_version`
- Refuse execution if a plugin is missing or version-incompatible, unless a force flag is used.
- Compatibility checks on load (`min_platform_version`, `max_platform_version`).

## 8) Observability and Auditing
- Capture logs per plugin execution (stdout/stderr)
- Record execution metrics: duration, memory, exit code, errors
- Expose plugin logs and status via CLI/API

## 9) API and CLI Surface
Suggested API endpoints:
- `GET /api/v1/plugins`
- `POST /api/v1/plugins/reload`
- `POST /api/v1/plugins/install`
- `POST /api/v1/plugins/{id}/enable`
- `POST /api/v1/plugins/{id}/disable`
- `POST /api/v1/plugins/{id}/test`

CLI commands:
- `spectra plugins list|install|enable|disable|reload|test|remove`

## 10) LLM-Generated Plugins
Treat as Local Python plugins plus extra metadata:
- `llm_prompt`, `llm_model`, `generated_at`, `review_status`

Require explicit user approval and a test run before install. Store prompts and render a diff on regeneration.

## 11) Marketplace (Later)
- Signed manifests, trusted publishers, version pinning
- Optional review/certification process
- One-click install via CLI/API

## Phased Rollout
1) Phase A (MVP)
   - Manifest schema + registry
   - Local plugins only, no sandbox (or basic process isolation)
   - JSON-safe output and artifact storage
2) Phase B
   - Strong sandboxing, permissions, resource limits
   - Hot reload and version pinning
3) Phase C
   - Remote API plugins + auth, artifact streaming
   - LLM plugin generation and approval flow
4) Phase D
   - Marketplace and signatures, curated community plugins

## Integration with Current Backend
- Add `app/services/plugins/` with:
  - `plugin_manager.py`, `plugin_runtime.py`, `plugin_models.py`
- Add a `PluginNode` wrapper registered into `node_registry`
- Enforce JSON-safe results at the plugin boundary so CLI consumers are stable
