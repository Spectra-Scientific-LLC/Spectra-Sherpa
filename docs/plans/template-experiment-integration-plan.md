# Plan: Template-to-Experiment Integration & New User Onboarding

**Date:** 2026-03-08
**Status:** Final
**Objective:** Upon sign-in, a new user can immediately see available templates under experiments, select one, bind data (or use bundled example data), and follow a guided procedure through analysis to deployment.

---

## 1. Current State Analysis

### 1.1 Two Disconnected Template Systems (High)

The codebase has two independent template registries that never communicate:

| Aspect | Backend (DB) | Frontend (Store) |
|--------|-------------|-----------------|
| Location | `src/spectra_sherpa/app/core/workflow_templates.py` | `frontend/src/stores/workflow.ts` (line 143, `TEMPLATES` const) |
| Count | 9 templates | ~13 templates |
| Storage | `workflow_template` DB table, seeded on startup | Hardcoded JS object in Pinia store |
| API | `GET/POST /api/v1/workflow-templates` | Never called by the frontend |
| Instantiation | `POST /workflow-templates/{id}/instantiate` (dead code) | `loadTemplate(templateId)` reads from local const |
| Template IDs | Integer (auto-increment) | String slugs ("project1", "ir_opus_analysis") |

The backend template API (list, get, instantiate, categories) is fully implemented but dead code. The frontend gallery (`TemplateGallery.vue`) drives everything from the hardcoded `TEMPLATES` object. Any template added to the DB is invisible to users. This guarantees drift and prevents backend-managed templates from being the source of truth.

### 1.2 Templates Are Not Runnable as Loaded (High)

Both backend seed templates and frontend templates use the `data.source` node with `source: "experiment"` but **no `experiment_id`**. The `DataSourceNode.execute()` method at `source.py:429` has an explicit guard:

```python
elif source == "experiment" and experiment_id:
    ...
else:
    raise ValueError("Invalid or incomplete data source configuration...")
```

Without `experiment_id`, execution falls through to the `else` branch and raises. Meanwhile, the WorkflowInspector (`WorkflowInspector.vue:2237`) explicitly treats `experiment` and `library` as **legacy sources** — they are not listed in the primary source selector dropdown. The only listed options are `file`, `spectrochempy`, `sklearn`, and `eigenvector`. A user loading a template gets a `data.source` node configured for a legacy path that requires manual repair in the inspector before it can run.

### 1.3 Project Context Is Not Carried Through Creation Flows (High)

`Experiment` and `Workflow` both have `project_id` in the data model, but:

- Template instantiation (`workflow_templates.py:165`) does not set `project_id` on the created workflow
- Experiment creation/import does not accept or infer the current project
- Linking experiments and workflows to projects is a separate manual operation via `POST /projects/{id}/experiments/{exp_id}` and `POST /projects/{id}/workflows/{wf_id}`
- The topbar project selector acts as a navigation context only, not as an active workspace that new objects inherit from

This is the main disconnect from project/data/workflow management: the plumbing exists, but nothing populates it automatically.

### 1.4 First-Run Onboarding Does Not Surface Templates (Medium)

- `/` redirects to `/project` (`router/index.ts:13`)
- The `OnboardingBanner` shows 3 steps: "Create a Project", "Load Data", "Build a Workflow" — no mention of templates
- The workflow page autoloads the most recent workflow (`WorkflowBuilderContent.vue:476-477`)
- The `/experiments` route is runs/batch/compare history only (`ExperimentsContent.vue`), not data management or templates
- Templates are only discoverable inside the workflow builder's sidebar panel — the place where a new user expects "templates under experiments" does not exist

### 1.5 No Guided Path from Execution to Deployment (Medium)

Deployment infrastructure exists (batch prediction, folder watches, model artifacts are auto-saved on execution) but there is no guided continuation:

- After a successful run that produces a model, the user sees results but no "Deploy" action
- Reaching deployment requires navigating to `/deploy`, selecting the workflow again, and configuring folder paths
- No template includes deployment nodes — all pipelines terminate at `output.plot` or `output.data_table`

### 1.6 Workflow Model Has No Template Provenance (Low)

The `Workflow` model has no `source_template_id` field. Once instantiated, there is no link back to the source template.

---

## 2. Gap Summary

| # | Gap | Severity | Root Cause |
|---|-----|----------|------------|
| G1 | Two template systems, frontend ignores backend API | High | Frontend was built with local templates before backend API existed; never migrated |
| G2 | Templates not executable — `source="experiment"` without `experiment_id` rejected by DataSourceNode | High | Templates assume dataset binding happens later; no mechanism for it |
| G3 | Project context not carried through creation/instantiation flows | High | `project_id` treated as optional FK, never set by template or creation APIs |
| G4 | Templates not visible outside workflow builder; onboarding ignores them | Medium | Templates treated as a workflow-builder feature, not a first-class launch surface |
| G5 | No execution-to-deploy handoff | Medium | Deploy page is standalone; no deep-linking from run results |
| G6 | No template provenance on workflows | Low | `Workflow` model lacks FK to `workflow_template` |

---

## 3. Agreements and Disagreements with Proposed Remediation

### Where I Fully Agree

**1. Make backend templates canonical.** The frontend hardcoded catalog must go. The backend `workflow_template` table with its existing API should be the single source of truth. The frontend should fetch from the API and use the `instantiate` endpoint. This is non-negotiable foundation work.

**2. Replace legacy `source="experiment"` with immediately executable data or a `dataset_ref` contract.** The user's observation that the inspector already treats `experiment` and `library` as legacy sources is critical — my initial plan missed this. Templates should either:
- Use sources that work immediately (`spectrochempy`, `sklearn`, `eigenvector`) for the "Run With Example Data" path
- Use a `dataset_ref` parameter that the instantiation flow resolves into `experiment_id`/`file_id`/`stage` for the "Use My Dataset" path

**3. Make template launch transactional with project/data/workflow creation.** "Use Template" should be a single guided operation: select/create project, select/create experiment, instantiate workflow, and set `project_id` on every created object. My original plan had these as separate phases; they should be one atomic flow.

**4. Topbar project selection as active workspace context.** This is an important insight I underemphasized. All new creations (experiments, workflows, models) should default into the active project. This prevents the "orphaned objects" problem structurally rather than relying on manual linking.

**5. Two launch modes per template.** "Run With Example Data" (immediate success path) and "Use My Dataset" (short wizard) is the right UX split. My original plan had a single 3-step wizard that tried to serve both cases.

**6. Execution-to-deploy handoff.** After a successful model-producing run, surface "Save Run / Open Report / Deploy" actions. Deploy should deep-link with `workflow_id` and project prefilled.

**7. Add acceptance tests for the full starter path.** This was missing from my original plan and should be explicit from the start.

### Where I Partially Disagree

**1. First-run redirect to Experiments > Templates tab.**

The proposal says: redirect post-login to `/experiments` and show a Templates tab there.

I agree templates need a first-class surface, but I think `/experiments` is the wrong place because:
- The existing `/experiments` page is run history (execution runs, batch comparisons) — that's a well-established concept
- Adding a "Templates" tab to a "Run History" page creates semantic confusion
- The real first-run surface should be `/project` (where the user already lands) with a redesigned onboarding that offers template-driven quick starts

**My adjustment:** Keep `/experiments` as run history. Add a "Quick Start from Template" section to the `/project` landing page (where `OnboardingBanner` already renders). For first-run users, make this the dominant UI element. The full template gallery stays in the workflow builder sidebar but is also accessible via a dedicated `/templates` route or modal from the project page.

**2. Schema expansion on WorkflowTemplate (slug, featured, starter_dataset_mode, default_project_metadata, supports_deploy, expected_outputs, wizard_steps).**

This is directionally right but risks over-engineering the model before we know exactly what the wizard needs. I'd add columns incrementally:
- Phase 1: `slug` only (stable lookup ID)
- Phase 2: `starter_dataset_mode` and `data_requirements` (inside `template_data` JSON, not as columns — keeps schema flexible)
- Phase 3+: `featured`, `supports_deploy`, `difficulty` as needed

Putting wizard metadata in `template_data` JSON is better than adding 6 new columns, because template presentation metadata evolves faster than the schema migration cycle.

**3. "Preserve current backend capabilities rather than inventing a new deployment engine."**

I fully agree — the deployment engine (batch prediction, folder watches, model artifacts) is complete. No new deployment backend is needed. The only work is UI: surface "Deploy this trained workflow" as a post-execution action.

### Where I Disagree

**Nothing substantive.** The user's analysis is more precise than mine in two important areas:
- Correctly identifying that `source="experiment"` is treated as legacy in the inspector (I missed this)
- The transactional project/data/workflow creation concept (my original plan spread this across 3 phases)

The user's analysis should be taken as the authoritative problem statement.

---

## 4. Final Plan

### Phase 1: Unify Template Registry & Fix Executability

**Goal:** Single source of truth for templates. Every template is immediately runnable via at least one data path.

#### 1A. Backend becomes canonical template store

Files changed:
- `src/spectra_sherpa/app/models/workflow_template.py` — add `slug` column (String, unique, indexed)
- `src/spectra_sherpa/app/core/workflow_templates.py` — merge all 13+ frontend templates into seed data with slugs; change `data.source` nodes from `source: "experiment"` to immediately executable sources (`spectrochempy`, `sklearn`, `eigenvector`) with a `starter_dataset` flag in `template_data`
- `src/spectra_sherpa/app/api/v1/routes/workflow_templates.py` — add slug-based lookup `GET /workflow-templates/by-slug/{slug}`
- `src/spectra_sherpa/alembic/versions/` — migration adding `slug` column
- `src/spectra_sherpa/app/db/seeder.py` — no change needed (startup already calls `ensure_workflow_templates`)

#### 1B. Frontend fetches from API, removes hardcoded catalog

Files changed:
- `frontend/src/stores/workflow.ts` — remove `TEMPLATES` const (~200 lines); add `fetchTemplates()` action calling `GET /workflow-templates`; update `loadTemplate()` to call `POST /workflow-templates/{id}/instantiate`
- `frontend/src/views/workflow-builder/TemplateGallery.vue` — render from API response; keep category grouping and visual styling
- `frontend/src/views/workflow-builder/WorkflowBuilderContent.vue` — wire template gallery to API-backed store

#### 1C. Fix template data sources for immediate executability

For each template, set the `data.source` node to use a source that works without user configuration:

| Template | Default Source | Example Dataset |
|----------|---------------|-----------------|
| PCA Exploratory | `spectrochempy` | `irdata` |
| PLS Calibration | `spectrochempy` | `irdata` (with concentration target) |
| Classification (PCA + PLS-DA) | `sklearn` | `wine` |
| MCR-ALS | `spectrochempy` | `irdata` |
| Preprocessing Pipeline | `spectrochempy` | `irdata` |
| SIMCA QC | `sklearn` | `wine` |
| Hierarchical Clustering | `sklearn` | `iris` |
| KNN Classification | `sklearn` | `wine` |
| IR OPUS Analysis | `spectrochempy` | `irdata` |
| Raman Processing | `spectrochempy` | `ramandata` |

Each template also carries a `user_dataset_mode` field in `template_data` describing what kind of user data it accepts (technique, requires_target, min_samples) for Phase 2.

**Acceptance criteria:**
- `GET /workflow-templates` returns all templates with slugs
- Frontend gallery renders from API
- Every template loads and executes successfully without user editing any node parameters
- Backend `TEMPLATES` const in `workflow.ts` is deleted

---

### Phase 2: Transactional Template Launch with Project & Data Binding

**Goal:** "Use Template" is a single guided operation that creates project + experiment + workflow in one flow, with all `project_id` fields populated.

#### 2A. Template launch wizard (frontend)

New component: `TemplateWizard.vue` — a 2-3 step modal:

**Step 1 — Choose Data Mode:**
- "Run With Example Data" — uses the template's default `spectrochempy`/`sklearn`/`eigenvector` source as-is. Skips to Step 3.
- "Use My Dataset" — proceeds to Step 2.

**Step 2 — Select Dataset (only for "Use My Dataset"):**
- Shows the existing `TreeSelect` dataset picker (already implemented in WorkflowInspector)
- User selects experiment > stage > file
- Selection produces a `dataset_ref` object: `{ source, experiment_id, stage, file_id }`

**Step 3 — Confirm & Launch:**
- Shows template name, selected data source, target project
- Project defaults to the topbar-selected project (or auto-creates one named after the template)
- "Start Analysis" button triggers the transactional creation

#### 2B. Transactional instantiation endpoint

Extend `POST /workflow-templates/{id}/instantiate`:

```json
{
  "workflow_name": "My PCA Analysis",
  "project_id": 3,
  "auto_create_project": true,
  "data_bindings": {
    "data_1": {
      "source": "experiment",
      "experiment_id": 5,
      "stage": "raw",
      "file_id": 12
    }
  }
}
```

Backend behavior:
1. If `auto_create_project` and no `project_id`: create project with template name, set `technique` from template metadata
2. Create workflow from template with `project_id` set
3. If `data_bindings` provided: override `data.source` node parameters with the binding values
4. If `data_bindings` not provided: keep template defaults (example data)
5. Return workflow + project IDs

Files changed:
- `src/spectra_sherpa/app/api/v1/routes/workflow_templates.py` — extend `InstantiateTemplateRequest` schema and handler
- `src/spectra_sherpa/app/schemas/workflows.py` — if needed for response shape
- `frontend/src/views/workflow-builder/TemplateWizard.vue` — new component
- `frontend/src/views/workflow-builder/WorkflowBuilderContent.vue` — integrate wizard
- `frontend/src/stores/workflow.ts` — update instantiation to use extended payload

#### 2C. Active project context propagation

The topbar project selector should set an active workspace context. All creation operations default into it:

Files changed:
- `frontend/src/stores/project.ts` — expose `activeProjectId` as a reactive global
- `frontend/src/stores/workflow.ts` — `saveWorkflow()` sets `project_id` from active project
- `frontend/src/stores/experiment.ts` — `createExperiment()` sets `project_id` from active project
- `src/spectra_sherpa/app/api/v1/routes/workflows.py` — accept optional `project_id` on create
- `src/spectra_sherpa/app/api/v1/routes/experiments.py` — accept optional `project_id` on create

**Acceptance criteria:**
- "Run With Example Data" on any template: one click → workflow runs → results displayed. No manual node configuration.
- "Use My Dataset": 2-click wizard (pick data, confirm) → workflow runs with user data.
- `project_id` is set on all created objects (project, experiment, workflow).
- Topbar project selection carries through to all creation operations.

---

### Phase 3: First-Run Onboarding & Template Discoverability

**Goal:** New users see templates immediately. Templates are the primary entry point, not an afterthought hidden in the builder sidebar.

#### 3A. Redesign project landing page for first-run users

When `OnboardingBanner` detects first-run (`isFirstRun: true` from `/health/onboarding`):

Replace the current 3-step text list with an actionable layout:
- **Primary CTA:** "Quick Start from Template" — shows 3-4 featured template cards inline
- **Secondary:** "Upload Your Data" → `/data`
- **Tertiary:** "Create Empty Project" → current project creation flow

Clicking a template card opens the Phase 2 wizard.

Files changed:
- `frontend/src/components/OnboardingBanner.vue` — redesign with template cards and CTAs
- `frontend/src/composables/useOnboarding.ts` — add template fetch to onboarding state

#### 3B. Template gallery accessible from project page

Add a "Browse Templates" action to the project page that opens the full `TemplateGallery` in a dialog/drawer without navigating to `/workflow`. This surfaces templates where users expect to start work.

Files changed:
- `frontend/src/views/project/ProjectContent.vue` — add "Browse Templates" button + dialog
- Reuse existing `TemplateGallery.vue` (now API-backed from Phase 1)

#### 3C. Template route alias

Add `/templates` as an alias route that either:
- Opens the workflow builder with template gallery expanded, or
- Opens a standalone template browser page

This replaces the current redirect `{ path: "/templates", redirect: "/workflow" }` with something that actually shows templates prominently.

Files changed:
- `frontend/src/router/index.ts` — update `/templates` route

**Acceptance criteria:**
- Brand-new user signs in → lands on `/project` → sees template quick-start cards without any navigation
- At least one template per major analysis type (exploratory, calibration, classification) runs successfully with bundled data on first click
- User never needs to navigate to `/workflow` and find the sidebar to discover templates

---

### Phase 4: Execution-to-Deploy Handoff

**Goal:** After a successful model-producing run, the user can reach deployment in one click.

#### 4A. Post-execution action bar

After workflow execution completes successfully, show an action bar with:
- **Save Run** — bookmark the execution run (existing capability)
- **Open Report** — navigate to `/report` with run data
- **Deploy** (only if execution produced a `ModelArtifact`) — deep-link to `/deploy` with `workflow_id` and `project_id` prefilled, suggested mode (batch or folder watch)

Files changed:
- `frontend/src/views/workflow-builder/WorkflowBuilderContent.vue` — add post-execution action bar
- `frontend/src/views/deploy/DeployContent.vue` — accept query params for prefill (`?workflow_id=X&project_id=Y`)
- `frontend/src/router/index.ts` — ensure `/deploy` accepts query params

#### 4B. Extended template variants (optional, parallel work)

For templates that produce models (PLS, PCA, SIMCA, KNN, PLS-DA), create "-full" variants that include deployment nodes:

| Base Template | Adds |
|--------------|------|
| PLS Calibration | `output.export` (calibration report CSV) |
| Classification | `output.data_table` (confusion matrix) |
| SIMCA QC | `output.data_table` (pass/fail report) |

These are new seed entries in `workflow_templates.py`, not modifications to existing templates.

**Acceptance criteria:**
- After a successful model-producing run, user sees "Deploy" button
- Clicking "Deploy" opens deploy page with workflow and project already selected
- User only needs to specify input folder/pattern to start batch processing

---

### Phase 5: Template Provenance (Low Priority)

**Goal:** Track which template generated a workflow.

#### 5A. Add provenance fields

- `Workflow.source_template_id` — nullable FK to `workflow_template`
- `Workflow.source_template_slug` — denormalized for display (survives template deletion)
- Set during `instantiate`

Files changed:
- `src/spectra_sherpa/app/models/workflow.py` — add columns
- `src/spectra_sherpa/alembic/versions/` — migration
- `src/spectra_sherpa/app/api/v1/routes/workflow_templates.py` — set fields during instantiate
- Frontend workflow list/detail — show "Based on: {template_name}" badge

**Acceptance criteria:**
- Workflows created from templates display their source template name
- Provenance survives template updates or deletion

---

## 5. Implementation Order & Dependencies

```
Phase 1 (Unify + Fix Executability)     FOUNDATION — must be first
  |
  +---> Phase 2 (Transactional Launch)  CORE UX — highest user impact
  |       |
  |       +---> Phase 3 (Discoverability)  depends on Phase 1+2 being stable
  |       |
  |       +---> Phase 4 (Deploy Handoff)   independent of Phase 3, can parallel
  |
  +---> Phase 5 (Provenance)            independent, can start after Phase 1
```

Phases 3, 4, and 5 can proceed in parallel once Phase 2 is stable.

---

## 6. Target User Procedure

This is the procedure to publish as the target workflow for users once implemented:

1. **Sign in.** Land on Project page with Quick Start template cards (first-run) or your project dashboard (returning user).
2. **Choose a template card** and click either **Run With Example Data** or **Use My Dataset**.
3. **Confirm the project.** If none exists, the app creates a starter project automatically.
4. **Confirm the dataset.** For example mode, the template's built-in reference dataset is used. For user mode, select from existing experiments or upload new data.
5. **The app creates a project-linked experiment and a project-linked workflow** from the chosen template, with dataset bindings already resolved.
6. **Click Run Analysis**, or let the app auto-run for example data mode.
7. **Review outputs** in the workflow builder's results panel (plots, tables, metrics).
8. **Click Save Run** to bookmark results. If the workflow trained a model, the saved model is attached to the same project automatically.
9. **Click Open Report** for a summary view, or **Deploy** if this workflow should process future files.
10. **In Deploy**, choose Batch Run (one-time folder) or Folder Watch (continuous monitoring). The workflow is already selected; supply only the input folder and file pattern.

---

## 7. Acceptance Criteria (Full)

| # | Criterion |
|---|-----------|
| AC1 | A brand-new signed-in user sees templates on the landing page without navigating to the workflow builder |
| AC2 | At least one template per major analysis type (exploratory, calibration, classification, curve resolution, preprocessing) runs successfully with bundled reference data on first click |
| AC3 | `project_id` is populated automatically on the project, experiment, workflow, and saved model created during the starter flow |
| AC4 | The user never has to manually repair `data.source` parameters to make a starter template executable |
| AC5 | "Use My Dataset" wizard allows selecting existing experiment data and resolves it into `dataset_ref`/`experiment_id` before workflow creation |
| AC6 | A successful model-producing template run presents a Deploy action that deep-links to the deploy page with workflow prefilled |
| AC7 | Frontend `TEMPLATES` hardcoded constant is deleted; all templates served from backend API |
| AC8 | Integration tests cover: first-run redirect, template listing from backend, template instantiation with project linkage, reference dataset execution, model artifact persistence, and deploy prefill |

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Breaking existing workflows that reference frontend template IDs | Map old string IDs to backend slugs; keep slug-based lookup as stable contract |
| SpectroChemPy not installed — example datasets unavailable | Templates also include `sklearn`/`eigenvector` fallbacks that require only numpy/scikit-learn |
| Transactional instantiation too complex for single endpoint | Keep it idempotent — if project exists, reuse; if experiment exists, reuse; only create what's missing |
| Onboarding flow annoying for power users | Respect `onboarding_dismissed` localStorage flag; auto-dismiss when all steps complete |
| Template `data_requirements` over-specified | Keep requirements advisory (UI hints), not blocking — warn but allow any data source override |
| Schema migrations for slug/provenance columns | Both are nullable additions — backward compatible, no data loss risk |

---

## 9. Files Inventory

### Phase 1
| File | Change |
|------|--------|
| `src/spectra_sherpa/app/models/workflow_template.py` | Add `slug` column |
| `src/spectra_sherpa/app/core/workflow_templates.py` | Merge all templates, fix data sources, add slugs |
| `src/spectra_sherpa/app/api/v1/routes/workflow_templates.py` | Add slug-based lookup |
| `src/spectra_sherpa/alembic/versions/` | New migration for slug |
| `frontend/src/stores/workflow.ts` | Remove `TEMPLATES`, add API fetch, update `loadTemplate()` |
| `frontend/src/views/workflow-builder/TemplateGallery.vue` | Render from API response |

### Phase 2
| File | Change |
|------|--------|
| `src/spectra_sherpa/app/api/v1/routes/workflow_templates.py` | Extend instantiate with project + data bindings |
| `frontend/src/views/workflow-builder/TemplateWizard.vue` | New component (launch wizard) |
| `frontend/src/views/workflow-builder/WorkflowBuilderContent.vue` | Integrate wizard |
| `frontend/src/stores/project.ts` | Expose `activeProjectId` |
| `frontend/src/stores/workflow.ts` | Use active project on save |
| `frontend/src/stores/experiment.ts` | Use active project on create |

### Phase 3
| File | Change |
|------|--------|
| `frontend/src/components/OnboardingBanner.vue` | Redesign with template cards |
| `frontend/src/composables/useOnboarding.ts` | Add template fetch |
| `frontend/src/views/project/ProjectContent.vue` | Add Quick Start + Browse Templates |
| `frontend/src/router/index.ts` | Update `/templates` route |

### Phase 4
| File | Change |
|------|--------|
| `frontend/src/views/workflow-builder/WorkflowBuilderContent.vue` | Post-execution action bar |
| `frontend/src/views/deploy/DeployContent.vue` | Accept prefill query params |
| `src/spectra_sherpa/app/core/workflow_templates.py` | Optional extended template variants |

### Phase 5
| File | Change |
|------|--------|
| `src/spectra_sherpa/app/models/workflow.py` | Add `source_template_id`, `source_template_slug` |
| `src/spectra_sherpa/alembic/versions/` | Migration for provenance columns |
| `src/spectra_sherpa/app/api/v1/routes/workflow_templates.py` | Set provenance on instantiate |
