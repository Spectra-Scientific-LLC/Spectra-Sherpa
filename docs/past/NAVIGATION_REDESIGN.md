# Navigation Redesign: 6-Page Architecture

## Purpose

Replace the current 7-route navigation (Workspace + 3 Operations + Templates +
Settings + system pages) with a 6-page architecture that follows the
chemometrician's natural workflow and creates clear boundaries for AI autonomy.

The current design has three standalone pages (Process, Analysis, Calibration)
that execute SCP methods outside the workflow DAG. This creates parallel
execution paths that Sherpa cannot observe, results that don't feed into
workflows, and parameters that aren't captured in the provenance graph.

---

## Architecture

```
Project ──▶ Data ──▶ Workflow ──▶ Experiments ──▶ Deploy ──▶ Report

  Human       Human     Human        AI-driven      AI-driven    Auto-gen
  defines     loads     builds       explores        monitors     documents
  context     & QC's    the graph    the space       & serves     everything
```

### AI Autonomy Boundaries

| Page | Who drives | Sherpa's role |
|------|-----------|---------------|
| **Project** | Human | Advisory — suggest technique, recall similar projects |
| **Data** | Human | Automated analysis — flag outliers, QC score, suggest splits |
| **Workflow** | **Human only** | Advisory only — suggest nodes, never modifies graph |
| **Experiments** | **AI autonomous** within human-defined bounds | Design sweeps, run combinations, rank results |
| **Deploy** | **AI autonomous** monitoring | Drift detection, anomaly flagging, retraining triggers |
| **Report** | Auto-generated, human reviews | Narrative generation, regulatory templates |

The Workflow page is where expert trust is built (Sherpa doesn't touch my graph).
The Experiments and Deploy pages are where Sherpa earns its subscription fee.

---

## Customer Persona Mapping

### University Researcher (PhD student / postdoc)
- Journey: Project → Data → Workflow ↔ Experiments (iterate 50x) → Report
- Never deploys. Endpoint is a paper, not a production system
- 80% of time in Workflow ↔ Experiments loop
- Killer feature: Experiments (parameter optimization in minutes vs. weeks)

### Industrial Engineer (QC Lab)
- Journey: Deploy (receives model from chemometrician) → batch predict → monitor
- Rarely builds workflows. Uses Deploy and Report daily
- Killer feature: Deploy monitoring + drift alerts (subscription anchor)

### Academic Chemometrician (Professor)
- Journey: Project → Data → Workflow (with custom plugin nodes) → Experiments → Report
- Needs extensibility, rigorous validation, fair method comparison
- Killer feature: Experiments comparison + Report reproducibility packages

### Applied Chemometrician (Consultant)
- Journey: Full pipeline, optimized for speed and professional delivery
- Builds models for clients, deploys, writes reports, moves on
- Killer feature: Speed across entire pipeline (2 weeks → 2 days)

---

## Model Labeling Strategy

A chemometric model is simply a **Workflow** combined with a specific **Execution Run** (parameters + trained state).
Instead of a complex "Model Identity" lifecycle, we use **Labels** (tags) on Execution Runs to denote their status.

```
#production  -> The run currently powering the factory line
#staging     -> The candidate run being validated
#deprecated  -> Old runs kept for audit
```

**Entity: ExecutionRun.labels** — connects Workflow → Experiments → Deploy → Report

This answers questions simply:
- "Which model is deployed?" → Filter Runs by `#production` label
- "What preprocessing did v2 use?" → Compare `#production` vs `#staging` runs
- "Generate FDA report" → Select run with `#validated` label

---

## Migration Map: Current → New

### What MOVES

| Current location | New page | Action |
|---|---|---|
| `Topbar.vue` project selector dropdown | **Project** | Promote to full page |
| `ProjectDialog.vue`, `ProjectDetailsDrawer.vue` | **Project** | Reuse as-is |
| `project.ts` store | **Project** | Reuse as-is |
| `FileLoadModal.vue` (in workflow-builder/modals/) | **Data** | Extract from modal to page section |
| `DataTableModal.vue` (in workflow-builder/modals/) | **Data** | Extract from modal to page section |
| `QuickPlotModal.vue` (in workflow-builder/modals/) | **Data** | Extract from modal to page section |
| `experiment.ts` store (file management part) | **Data** | Reuse for file/dataset management |
| `builder.ts` store (synthesis part) | **Data** | Reuse for synthesis tab |
| `experiments.py` routes (file CRUD) | **Data** | Reuse for dataset management |
| `builder.py` routes (`synthesize`, `blend`, `curves`) | **Data** | Reuse for synthesis tab |
| `datasets.py` routes | **Data** | Reuse as-is |
| `TemplatesContent.vue` (standalone route) | **Workflow** | Merge as "Start from template" panel |
| `workflow_templates.py` routes | **Workflow** | Reuse as-is |
| `WorkflowBuilderContent.vue` + all workflow-builder/ | **Workflow** | Reuse as-is (already 90% built) |
| `workflow.ts` store | **Workflow** | Reuse as-is |
| DOE system (`doe.py`, `doe_config.py`, 8 DB models) | **Experiments** | Reuse as "DOE Planning" tab |
| `experiment.ts` store (version comparison part) | **Experiments** | Extend with run history |
| `predict.py` route | **Deploy** | Reuse as prediction backend |
| `jobs.py` routes, `job.ts` store | **Deploy** | Reuse for batch job tracking |
| `workflow_export.py` routes (markdown, report-data) | **Report** | Reuse as export backend |
| `workflows.py` route (Python export) | **Report** | Reuse as-is |
| `llm.py` route (`write-report` endpoint) | **Report** | Reuse for AI narrative generation |

### What gets DELETED

| File/Directory | Reason |
|---|---|
| `frontend/src/views/process/ProcessContent.vue` | Functionality exists as DAG nodes (SNV, baseline, smoothing, etc.) |
| `frontend/src/views/analysis-methods/AnalysisMethodsContent.vue` | Functionality exists as DAG nodes (PCA, PLS, MCR, etc.) |
| `frontend/src/views/calibrations/` (entire directory) | PLS/PCR workflow nodes replace standalone calibration builder |
| `frontend/src/views/analysis/` (entire directory) | Superseded by `workflow-builder/` — duplicate canvas, inspector, etc. |
| `frontend/src/views/_legacy_backup/` (entire directory) | Dead code (BuilderView, ExperimentsView, NistView) |
| `frontend/src/views/templates/TemplatesContent.vue` | Merges into Workflow page as panel/dialog |
| `frontend/src/views/CalibrationsView.vue` | Entry point for deleted calibrations |
| `frontend/src/views/ChatView.vue` | Placeholder, superseded by LlmChatView + Sherpa panel |
| `frontend/src/views/SettingsView.vue` | Entry point, replaced by Settings in new nav |
| `frontend/src/stores/calibration.ts` | Backend for deleted calibration UI |
| `frontend/src/stores/nist.ts` | NIST library — niche, no active UI, not DAG-integrated |
| `frontend/src/stores/builder.ts` | Split: synthesis → Data page, rest deleted |
| `src/.../routes/process.py` (8 endpoints) | Replaced by preprocessing DAG nodes |
| `src/.../routes/analysis.py` (7 endpoints) | Replaced by modeling DAG nodes |
| `src/.../routes/calibrations.py` (10 endpoints) | Replaced by PLS/PCR DAG nodes |
| `src/.../routes/nist.py` (4 endpoints) | Niche, not DAG-integrated |
| `src/.../models/nist_library.py` | Backend for deleted NIST system |
| `src/.../schemas/nist.py` | Schema for deleted NIST system |

### What's NEW (must be built)

| Component | Page | Description |
|---|---|---|
| `ProjectContent.vue` | **Project** | Landing page: recent projects, create/import, project metadata |
| `DataContent.vue` | **Data** | Unified data page: Load tab, Explore tab, Synthesis tab |
| `DataQualityPanel.vue` | **Data** | Sample count, wavenumber range, outlier flags, class balance |
| `ExperimentsContent.vue` | **Experiments** | Parameter sweep definition, run history, comparison table |
| `RunComparisonPanel.vue` | **Experiments** | Side-by-side metrics, parameter diff, overlay plots |
| `DeployContent.vue` | **Deploy** | Batch predict UI, model version selector, monitoring dashboard |
| `DriftMonitorPanel.vue` | **Deploy** | RMSEP tracking over time, anomaly alerts |
| `ReportContent.vue` | **Report** | Report preview, template selector, export (PDF/Markdown/Python) |
| `execution_history.py` (DB model) | **Experiments** | Persist execution results for comparison |
| `execution_runs.py` (routes) | **Experiments** | CRUD for stored runs, comparison endpoint |
| `deploy.py` (routes) | **Deploy** | Batch predict UI wrapper, folder watches, label management |

---

## New Router Configuration

```typescript
const routes = [
  { path: "/login", component: LoginView, meta: { public: true } },
  { path: "/", redirect: "/project" },

  // 6 main pages
  { path: "/project",     component: ProjectContent,     meta: { nav: "project" } },
  { path: "/data",        component: DataContent,        meta: { nav: "data" } },
  { path: "/data/:tab",   component: DataContent,        meta: { nav: "data" } },
  { path: "/workflow",    component: WorkflowContent,    meta: { nav: "workflow" } },
  { path: "/experiments", component: ExperimentsContent, meta: { nav: "experiments" } },
  { path: "/deploy",      component: DeployContent,      meta: { nav: "deploy" } },
  { path: "/report",      component: ReportContent,      meta: { nav: "report" } },

  // Supporting routes (not in main nav)
  { path: "/workflow/node/:nodeId", component: NodeDetailView, meta: { standalone: true } },
  { path: "/settings",    component: SettingsContent },
  { path: "/admin",       component: AdminView, meta: { requiresAdmin: true } },
  { path: "/logs",        component: LogsView },
  { path: "/llm-chat",    component: LlmChatView, meta: { standalone: true } },

  // Legacy redirects
  { path: "/workspace",           redirect: "/workflow" },
  { path: "/workspace/:rest(.*)", redirect: "/workflow" },
  { path: "/operations/:rest(.*)", redirect: "/workflow" },
  { path: "/templates",           redirect: "/workflow" },
];
```

## New Sidebar

```typescript
const mainNavItems = [
  { label: "Project",     to: "/project",     icon: "pi pi-folder" },
  { label: "Data",        to: "/data",        icon: "pi pi-database" },
  { label: "Workflow",    to: "/workflow",     icon: "pi pi-sitemap" },
  { label: "Experiments", to: "/experiments", icon: "pi pi-chart-bar" },
  { label: "Deploy",      to: "/deploy",      icon: "pi pi-cloud-upload" },
  { label: "Report",      to: "/report",      icon: "pi pi-file-pdf" },
];

const secondaryNavItems = [
  { label: "Settings", to: "/settings", icon: "pi pi-sliders-h" },
];
```

---

## Backend Route Disposition (Complete)

Every existing route file mapped to its fate:

| Route file | Endpoints | Disposition |
|---|:---:|---|
| `workflows.py` | 18 | **Keep** — serves Workflow + Report pages |
| `workflow_templates.py` | 4 | **Keep** — serves Workflow page (template panel) |
| `workflow_organization.py` | 10 | **Keep** — serves Project page (folders, tags) |
| `workflow_export.py` | 2 | **Keep** — serves Report page |
| `builder.py` | 7 | **Keep** — synthesis/blend endpoints serve Data page |
| `datasets.py` | 2 | **Keep** — serves Data page |
| `experiments.py` | 10 | **Keep** — serves Data page (file mgmt) + Experiments page |
| `doe.py` | 16 | **Keep** — serves Experiments page (DOE planning tab) |
| `doe_config.py` | 6 | **Keep** — serves Experiments page |
| `predict.py` | 1 | **Keep** — serves Deploy page |
| `jobs.py` | 3 | **Keep** — serves Deploy page (batch tracking) |
| `config.py` | 14 | **Keep** — cross-cutting configuration |
| `api_keys.py` | 3 | **Keep** — serves Settings page |
| `llm.py` | 8 | **Keep** — serves Sherpa chat (cross-cutting) |
| `llm_config.py` | 4 | **Keep** — serves Settings page |
| `egress.py` | 8 | **Keep** — cross-cutting security |
| `health.py` | 1 | **Keep** — infrastructure |
| `logs.py` | 2 | **Keep** — system page |
| `compute.py` | 1 | **Keep** — backend execution |
| `process.py` | 8 | **DELETE** — replaced by preprocessing DAG nodes |
| `analysis.py` | 7 | **DELETE** — replaced by modeling DAG nodes |
| `calibrations.py` | 10 | **DELETE** — replaced by PLS/PCR DAG nodes |
| `nist.py` | 4 | **DELETE** — niche, not DAG-integrated |

**Summary: 19 route files kept, 4 deleted (29 endpoints removed)**

---

## Frontend Store Disposition

| Store | Disposition |
|---|---|
| `workflow.ts` | **Keep** — core DAG state |
| `project.ts` | **Keep** — project management |
| `auth.ts` | **Keep** — authentication |
| `llm.ts` | **Keep** — Sherpa chat |
| `sherpa.ts` | **Keep** — Sherpa advisor |
| `index.ts` (app config) | **Keep** — global state |
| `job.ts` | **Keep** — Deploy page job tracking |
| `experiment.ts` | **Refactor** — split: file mgmt → Data, version comparison → Experiments |
| `builder.ts` | **Refactor** — synthesis methods → Data page, rest deleted |
| `calibration.ts` | **DELETE** — calibration UI removed |
| `nist.ts` | **DELETE** — NIST UI removed |

**New stores needed:**
- `data.ts` — dataset registry, QC state, metadata matching
- `experiments.ts` — run history, comparison state, sweep definition
- `deploy.ts` — folder watches, batch jobs, label management
- `report.ts` — report generation state, template selection

---

## Sherpa Preparation Strategy

Sherpa (AI advisor) will be introduced ~3 months after the navigation redesign
ships. The OSS branch ships first WITHOUT Sherpa features, but the architecture
must be Sherpa-ready so integration is additive (new code), not invasive
(rewriting existing pages).

### Principle: Build the data layer now, add the AI layer later

Every page has two layers:
1. **Human layer** (OSS, ships now) — manual workflows, manual comparison, manual reports
2. **AI layer** (Sherpa, ships +3 months) — automated suggestions, autonomous sweeps, narratives

The human layer must produce the same data structures that Sherpa will later
consume and produce. If the human can manually compare 3 runs in a table,
Sherpa can later auto-populate that same table with 30 runs.

### Sherpa Hooks to Build Now (without Sherpa code)

| Page | Data structure to build now | Sherpa plugs in later |
|---|---|---|
| **Project** | `project.technique`, `project.sample_type` fields on Workflow model | Sherpa reads these to set context |
| **Data** | `DataQualityReport` dict (sample_count, feature_count, outlier_indices, nan_count) | Sherpa generates QC narrative from this dict |
| **Workflow** | Already done: `NodeResult.diagnostics`, type system, connection validator | Sherpa reads node metadata to suggest pipeline |
| **Experiments** | `ExecutionRun` DB model with params_snapshot + metrics_summary | Sherpa creates runs programmatically via same API |
| **Deploy** | `ExecutionRun.labels` (list of strings) | Sherpa monitors runs with `#production` label for drift |
| **Report** | Structured report data endpoint (JSON, not just markdown) | Sherpa generates narrative from structured data |

### What NOT to build now

- No Sherpa chat integration in new pages (already exists in sidebar)
- No "AI suggest" buttons — add those when Sherpa ships
- No autonomous sweep execution — build manual sweep first
- No drift detection algorithms — build prediction logging first
- No AI narrative generation — build structured data export first

The pattern: **build the plumbing (data models, stores, API endpoints) that
both humans and AI will use**. Sherpa becomes a power user of the same API.

---

## Execution Plan (OSS-First, Sherpa-Ready)

### Phase 1: Cleanup & Navigation Shell (1-2 days)

**Goal:** Delete dead code, establish new 6-page nav with redirects.

1. Delete `_legacy_backup/` directory
2. Delete `views/analysis/` directory (5 files, superseded by workflow-builder/)
3. Delete `views/ChatView.vue` (placeholder)
4. Update router: add all 6 routes (Project, Data, Workflow, Experiments,
   Deploy, Report) — stub pages with "Coming Soon" for unbuilt ones
5. Update Sidebar: new 6-item nav
6. Add legacy redirects (`/workspace` → `/workflow`, `/operations/*` → `/workflow`,
   `/templates` → `/workflow`)
7. Delete backend: `process.py`, `analysis.py`, `calibrations.py`, `nist.py`
8. Delete stores: `calibration.ts`, `nist.ts`
9. Delete models/schemas: `nist_library.py`, `nist.py` schema

**Backend deletions:** 4 route files (29 endpoints removed). These endpoints
duplicate functionality that already exists as DAG nodes.

### Phase 2: Project Page (1 day)

**Goal:** Build the entry point.

1. Build `ProjectContent.vue`:
   - Recent projects list (reuse `project.ts` store)
   - Create/import project (reuse `ProjectDialog.vue`)
   - Project metadata: name, description, technique, sample type
2. Add `technique` and `sample_type` fields to Workflow model
   (Sherpa hook — these become context signals later)
3. Set `/project` as default landing page (`/` → `/project`)

**Backend:** Add 2 nullable columns to Workflow model. No new routes.

### Phase 3: Data Page (2-3 days)

**Goal:** Unify data loading, exploration, and synthesis.

1. Build `DataContent.vue` with 3 tabs:
   - **Load** — extract `FileLoadModal.vue` content into standalone section
   - **Explore** — `DataTableModal.vue` + `QuickPlotModal.vue` content + QC panel
   - **Synthesis** — reuse `builder.py` endpoints (synthesize, blend, curves)
2. Build `DataQualityPanel.vue`: sample count, feature count, wavenumber range,
   NaN count, outlier count, class balance
   (Sherpa hook — returns structured `DataQualityReport` dict)
3. Create `data.ts` store: loaded datasets, active dataset, QC state
4. Delete `ProcessContent.vue`, `AnalysisMethodsContent.vue`
5. Delete `views/calibrations/` (5 files)
6. Refactor `builder.ts`: extract synthesis methods → `data.ts`, delete rest

**Backend:** No new routes. Data page uses existing `datasets.py`,
`experiments.py`, `builder.py`. QC computation runs client-side from
loaded dataset metadata.

### Phase 4: Workflow Consolidation (1 day) — DONE

**Goal:** Merge templates, clean up routing.

1. ~~Move `TemplatesContent.vue` content into a dialog/drawer within
   `WorkflowBuilderContent.vue`~~ — DONE: Created `TemplateGallery.vue`,
   added "Templates" toolbar button + PrimeVue Sidebar drawer.
   Deleted `TemplatesContent.vue`.
2. ~~Delete standalone `/templates` route~~ — DONE (Phase 1: redirects to `/workflow`)
3. ~~Remove `MainContentView.vue` dispatcher~~ — DONE (Phase 1)
4. ~~Route `/workflow` directly to `WorkflowBuilderContent.vue`~~ — DONE (Phase 1)

**Backend:** No changes.

### Phase 5: Experiments Page — Manual Mode (3-5 days) ✅ DONE

**Goal:** Build human-driven experiment comparison. Sherpa adds
autonomous sweeps later.

**Completed:**
- `ExecutionRun` DB model (`app/models/execution_run.py`): id, workflow_id, workflow_version_id, user_id, name, status, params_snapshot (JSON), results_summary (JSON), diagnostics (JSON), node_statuses (JSON), error, integrity_hash, executed_at, created_at, notes
- `execution_runs.py` schemas: `SaveRunRequest`, `ExecutionRunOut`, `ExecutionRunList`, `CompareRunsRequest`, `ComparisonResponse`
- `execution_runs.py` routes: `GET /workflows/{id}/runs`, `GET /workflows/{id}/runs/{run_id}`, `POST /workflows/{id}/runs` (save), `DELETE /workflows/{id}/runs/{run_id}`, `POST /workflows/{id}/runs/compare`
- Alembic migration `e5b3c8d1f204` for `execution_run` table
- Frontend types: `ExecutionRunSummary`, `ExecutionRunDetail`, `ComparisonResult`
- `runs.ts` Pinia store: fetchRuns, saveRun, deleteRun, compareRuns, selection management
- `ExperimentsContent.vue`: 2-tab layout (Run History + Compare), save dialog, delete confirmation, metric extraction, relative timestamps
- `ComparisonPanel.vue`: metrics comparison DataTable, parameter diff section, delta/best-value highlighting
- "Save Run" button in `WorkflowBuilderContent.vue` toolbar with dialog
- Design: scalar metrics only (not full arrays) → DB stays lean; frontend extracts metrics; backend fills params_snapshot from current workflow

### Phase 6: Deploy Page — Manual Mode (3-5 days)

**Goal:** Build batch prediction and folder watching.

1. **Backend:**
   - `deploy.py` routes:
     - `POST /workflows/{id}/predict/batch` — upload CSV/folder → apply workflow → save results
     - `GET /runs/{id}/predictions` — list per-file results
     - `PATCH /runs/{id}/labels` — apply tags like `#production`, `#archived`
     - `POST /deploy/watches` — create folder watch (auto-ingest)
   - `FolderWatch` DB model:
     - Monitors local/network folder, triggers workflow on new files
     - Creates new `ExecutionRun` for each batch
2. **Frontend:**
   - `DeployContent.vue`:
     - **Folder Watches** — config table (path, pattern, enabled/disabled)
     - **Run Management** — list previous runs, edit labels
     - **Batch History** — view prediction results for a run
3. **Manual workflow:**
   - User identifies best run in Experiments
   - User tags it `#production` in Deploy/Experiments page
   - User sets up a Folder Watch using that workflow
   - System auto-processes new files using that workflow ID
   - (Later: Sherpa monitors drill-down of these production runs)

### Phase 7: Report Page (2-3 days)

**Goal:** Build report preview and export.

1. **Frontend:**
   - `ReportContent.vue`:
     - **Preview** — render markdown in-browser (reuse `workflow_export.py`)
     - **Scope** — select what to include: workflow, diagnostics, experiment
       comparison, model history
     - **Export** — Markdown, Python script (PDF future)
   - Include `NodeResult.diagnostics` in report body
   - `report.ts` store
2. **Backend:**
     `include_runs` query params
   - Structured data endpoint: `GET /workflows/{id}/export/report-data`
     returns JSON (Sherpa hook — AI narrative generator consumes this later)
3. **Manual workflow:**
   - User selects workflow → previews report → adjusts scope → exports
   - (Later: Sherpa generates narrative paragraphs from structured data)

---

## Build Order Rationale

```
Phase 1 (Cleanup + Shell)  ← Day 1-2:  Delete dead code, establish nav
Phase 2 (Project)          ← Day 2-3:  Landing page, Sherpa context hooks
Phase 3 (Data)             ← Day 3-5:  Biggest cleanup, unified data page
Phase 4 (Workflow)         ← Day 5-6:  Consolidation only
Phase 5 (Experiments)      ← Day 6-10: Core differentiator (manual mode)
Phase 6 (Deploy)           ← Day 10-14: Revenue anchor (manual mode)
Phase 7 (Report)           ← Day 14-16: Ties everything together
```

Phases 1-4 are cleanup/reorganization (~6 days). Net code REMOVED.
Phases 5-7 are new capabilities (~10 days). New DB models, routes, pages.

Total: ~16 working days for the full OSS navigation redesign.

When Sherpa ships (+3 months), it plugs into:
- Project page: reads `technique`/`sample_type` for context
- Data page: generates QC narrative from `DataQualityReport`
- Workflow page: suggests nodes via existing MCP tools (already built)
- Experiments page: creates `ExecutionRun` records via same API
- Deploy page: monitors runs with `#production` label for drift
- Report page: generates narrative from structured report-data endpoint

---

## What SpectraSherpa Does NOT Do

- Instrument control (vendor software — Bruker OPUS, Thermo OMNIC)
- LIMS / sample tracking (LabWare, STARLIMS)
- General-purpose data science (Jupyter, Python — but exports TO Python)
- Statistical process control dashboards (MES/ERP territory)
- Wet lab experiment execution (ELN territory)

SpectraSherpa's domain: **the space between raw spectra and actionable
predictions**, with AI guidance throughout the chemometrician's workflow.
