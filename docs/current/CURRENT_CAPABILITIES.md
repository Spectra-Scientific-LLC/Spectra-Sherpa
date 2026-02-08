# Current Capabilities — SpectraSherpa Lite v1.3

What ships today. Every item here is implemented across the three deployment
modes (local, hybrid, demo). Test coverage is concentrated on local-mode
paths; hybrid and demo modes have minimal automated test coverage (see
Testing Status below).

---

## Feature Matrix (Current Release)

| Capability | Local | Hybrid | Demo | Status |
|-----------|-------|--------|------|--------|
| DAG Workflow Builder | Full | Full | Full | Ready |
| SpectroChemPy Algorithms (50+ nodes) | All | All | All | Ready |
| Plugin Ecosystem | Full | Full | Full | Ready |
| Basic LLM Chat (user's own keys) | Yes | Yes | Yes | Ready |
| Workflow Templates | All 10 | All 10 | All 10 | Ready (no tier gating) |
| Model Diagnostics | Full | Full | Full | Ready (no tier gating) |
| Sherpa AI Advisor (cloud) | No | Available | Available | Ready (protocol + client) |
| Data Sharing Control | Local only | Tiered egress + remote audit | Tiered egress (local audit only) | Ready |
| Offline Mode | Always | Graceful degradation | Rate-limited cloud (no auto-fallback) | Ready |
| Export Controls | Full | Permission-gated | Permission-gated | Ready |

---

## Backend Infrastructure

### Plugin SDK (`spectrasherpa_lite.sdk`)
- Stable public API for third-party node developers
- Re-exports: `Node`, `NodeMetadata`, `NodeParameter`, `PortMetadata`,
  `register_node`, `node_registry`
- Provenance helpers: `add_processing_step`, `safe_get_coord`,
  `get_processing_history`
- Sample management: `exclude_samples`, `include_samples`,
  `get_included_data`, `set_class`, `filter_by_class`
- Spectral detection: `detect_spectral_technique`, `detect_x_axis_type`
- Version policy: semver (minor = additive, major = may remove deprecated)
- File: `src/spectrasherpa_lite/sdk.py`

### Plugin Discovery (`plugin_loader.py`)
- Scans `~/.spectrasherpa/plugins/` for package and single-file plugins
- Scans `<data_dir>/plugins/` as secondary location
- Loads Python packages with `spectrasherpa.plugins` entry-point group
- Best-effort loading: individual failures logged, never crash the app
- Runs at startup before network health monitoring
- File: `src/spectrasherpa_lite/app/services/plugin_loader.py`

### Sherpa Protocol (`schemas/sherpa.py`)
- `EgressTier` enum: `STRUCTURE`, `SUMMARIES`, `FULL`
- `WorkflowStateSync`: local-to-cloud workflow context message
- `SherpaRecommendation`: cloud-to-local suggestion with `WorkflowPatch`
- `UserDecision`: accept/reject with optional feedback
- `ExplorationResult`: autonomous exploration results
- `SherpaWSMessage`: WebSocket envelope
- File: `src/spectrasherpa_lite/app/schemas/sherpa.py`

### Sherpa Advisor Service (`sherpa_advisor.py`)
- Async httpx client talking to `spectrasherpa-server`
- `filter_workflow_for_tier()`: strips data beyond user's selected tier
  **before** anything leaves the machine
- `sync_workflow()`: sends context, receives recommendations
- `send_decision()`: notifies cloud of accept/reject
- `request_exploration()`: opt-in autonomous parameter exploration
- Local recommendation cache with expiration on new sync
- Graceful degradation: returns empty list on connection failure
- File: `src/spectrasherpa_lite/app/services/sherpa_advisor.py`

### WebSocket Actions (in `main.py`)
- `sherpa_sync`: forwards workflow state to cloud, checks
  `allow_spectrasherpa_sync` egress permission, returns recommendations
- `sherpa_decide`: forwards user decision, returns delivery ack
- Existing: `subscribe`, `unsubscribe`, `llm_chat`

### Export Permission Model
- `check_export_allowed(user)` in `security.py`
- Local mode: always allowed (single user, own data)
- Multi-user modes: checks user's `allow_export` egress default
- Does NOT gate on global egress flag (file exports are not network egress)
- Applied to all 7 export routes: workflow markdown, report-data,
  Python code, DOE CSV/JSON/XML, dataset download

### Rate Limiting
- `RateLimiter`: sliding-window, file-backed, multi-process safe (fcntl)
- Currently applied to: execution (hybrid/demo), NIST downloads, LLM
- Per-user keying: `user_{id}` or `ip:{addr}` fallback
- Response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`

### Diagnostics Nodes
- `diagnostics.outliers`: Hotelling T-squared + Q residuals (SPE)
- `diagnostics.cross_validation`: RMSECV, R-squared, confusion matrix
- PCA node embeds T-squared/SPE calculation in its output metadata
- `stats.summary`: adaptive diagnostics based on input type

---

## Frontend Infrastructure

### Mode Gating
- `useAppConfig()` composable: `appMode`, `isFeatureEnabled()`
- Router guards: local mode skips login, admin route blocked in local
- `MainLayout.vue`: "Offline Mode" badge shown in local mode
- `IntegrationsTab.vue`: SpectraSherpa Cloud section hidden in local mode
- `Topbar.vue`: Admin button hidden in local mode

### Feature Flags (AppFeatures interface)
Currently exposed from backend `to_client_safe()`:

```typescript
interface AppFeatures {
  apiTokenSettings: boolean   // Show API token settings
  cloudOffload: boolean       // GPU offload available
  demoMode: boolean           // Rate-limited demo
  agenticWorkflow: boolean    // LLM-powered workflow automation
  chatAssistant: boolean      // Chat panel (Phase 4, currently false)
  sherpaAdvisor?: boolean     // Sherpa AI advisor available
  pluginSystem?: boolean      // Plugin discovery active
  nistDownloads?: boolean     // NIST WebBook downloads
}
```

### Template System
- 10 backend-seeded templates (DB, via `/workflow-templates` API)
- 12 frontend-hardcoded templates (in-memory, in `workflow.ts`)
- Categories: exploratory, calibration, classification, curve_resolution,
  preprocessing, quality_control, clustering, comparison
- Note: the two systems are not yet unified

---

## Client-Side Readiness for Future Tiers

The following items are designed to be extended without breaking changes:

1. **`AppFeatures` uses optional fields** (`sherpaAdvisor?`, `pluginSystem?`)
   so new flags can be added without breaking existing clients

2. **`AppConfig` includes `limits?`** (optional) — currently only populated
   in demo mode but ready to carry tier-specific quotas

3. **`EgressTier` is a string enum** — adding new tiers (e.g., `"anonymized"`)
   requires no client schema change

4. **Feature flag gating pattern** (`v-if="isFeatureEnabled('x')"`) is
   established and consistent — adding new gated features follows the same
   pattern

5. **Backend `to_client_safe()`** is the single source of truth — the
   frontend never hard-codes capability assumptions; it always reads from
   the config endpoint

6. **WebSocket action dispatch** uses string matching (`action === "sherpa_sync"`)
   so new actions can be added without protocol version bumps

---

## Testing Status

### Current Coverage (18 test files, ~3,100 lines, 29 test functions)

| Area | Files | Mode Tested | Notes |
|------|-------|-------------|-------|
| Experiment CRUD | `test_experiments.py` | Local (implicit) | Async API client |
| Data Loading | `test_data_loading_golden.py` | Local (implicit) | 11 tests, SPG/CSV/SPC |
| Modeling Nodes | `test_modeling_nodes.py` | Local (implicit) | PCR, SVR, HCA, KMeans, DBSCAN |
| Gateway Auth | `test_gateway_user_api_key.py` | **Hybrid** (explicit) | Only non-local mode test |
| PCA Integration | `test_pca_integration.py` | Hits live API | Manual, not CI-runnable |
| DOE Matching | `test_spike_doe.py` | Hits live API | Manual, not CI-runnable |
| File Loaders | `backend/test_file_loaders.py` | N/A (unit) | JSON, CSV, MAT formats |
| Node Registry | `backend/test_node_registry.py` | N/A (unit) | Registry functionality |

### Gaps

- **Zero tests for demo mode** — rate limiting, enforcement middleware untested
- **No parametrized mode matrix** — no fixture that runs the same test
  against local/hybrid/demo configurations
- **No CI/CD pipeline** — no GitHub Actions, Makefile test targets, or tox.ini
- **Integration tests require a live server** — `test_pca_integration.py` and
  `test_spike_doe.py` hit `localhost:8000`/`:9000`, not runnable in automated CI
- **Remote audit logging untested** — `RemoteAuditHandler` has no test coverage

### What "Ready" Means in the Feature Matrix

"Ready" indicates the code path exists and has been manually verified during
development. It does **not** mean there is automated regression coverage for
that feature across all three modes. Priority areas for test hardening:

1. Demo enforcement middleware (rate limiting, session expiry)
2. Mode-parametrized test fixtures (`@pytest.fixture(params=["local","hybrid","demo"])`)
3. Sherpa advisor graceful degradation (mock httpx responses)
4. Export permission checks across modes
