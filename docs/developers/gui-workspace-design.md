# GUI workspace design

**Status:** proposed target arrangement, 1 October 2026. This is a design authority
for future changes, not a statement that the redesign has shipped. The appendix
records the changes needed from the reviewed frontend. Keep release and user
documentation tied to implemented behavior.

This document governs the shared application shell, page navigation, subtabs,
actions, project objects and Advisor context. It applies to the browser and
desktop application, including pages contributed by the managed server. Product
capabilities and authorization remain deployment-specific.

The [Scientific Result Surface Contract](scientific-result-surface-contract.md)
continues to govern scientific meaning. A cleaner page must still disclose data,
executed parameters, population, units, exclusions and provenance.

## 1. The arrangement

Use the same order, vocabulary and interaction rules everywhere.

| Main page | Page subtabs, in order | Purpose |
| --- | --- | --- |
| Dashboard | **Your Project, Archive, Storage** | Choose/manage projects by default; restore archived projects; inspect and reclaim storage across projects. |
| Project | None | Understand and manage the active project and its objects. |
| Data | Import, Synthesis, Upload, Library, Multi-well, My Dataset | Acquire, prepare and inspect project data. Preserve existing capability restrictions. |
| Workflow | **None** | Build and execute workflows. Keep the existing sheet tabs **inside the canvas**. |
| Runs | **History, Inspect, Compare, Artifacts, Batch** | Open a run name in Inspect, compare saved executions, inspect their artifacts and apply fitted models. |
| Optimize | **Campaigns, New round, Results** | Browse project campaigns, prepare a round and evaluate/inspect results. |
| Deploy | **Application, Folder Watches, Prediction History** | Select a fitted application, operate watches and inspect predictions. |
| Report | **Setup, Preview, ISO Validation** | Configure a report, inspect/export it and follow the validation-evidence walkthrough. |

Use `Workflow` as the main-page label. `Workflows →` on Project describes its
collection. Existing `/workflow` URLs and internal component names need not be
renamed to achieve this vocabulary.

Settings, Documentation, Logs, Audit, account/billing, administration and
authentication keep their appropriate global or contextual entry points. They
are not extra scientific main pages. Managed-only features remain contributed
through the existing extension boundary; OSS must not import server UI code.

## 2. Shared page anatomy

```text
GLOBAL    Active project                         status · jobs · Advisor · account
HEADER    Page title                              essential actions for this view
CONTEXT   Selected object · relevant facts · scope/status               summary
SUBTABS   First    Second    Third ...                  (left aligned, stable order)
CONTENT   One full-width active panel
```

1. **Global state:** the topbar owns the active project selector. Its current
   behavior of hiding the selector while Advisor is open is acceptable; this
   redesign does not require a persistent duplicate. Keep status indicators and
   other global controls at the right. Hiding the name must not change the
   underlying project binding or Advisor context. Dashboard can have no active
   project. Other project pages show a useful selection state when none is selected.
2. **Header:** left-aligned stable page title, right-aligned essential actions.
   Campaign names, run names and modes belong in the context row. No generic
   subtitle beneath Workflow, Runs, Deploy or Report. Project's name and
   description remain useful project content.
3. **Context:** describe the active subtab and selected resource. Do not repeat a
   Project tile. Show the facts needed to understand the current operation, not
   a wall of badges. Use human-readable names in headers and the context row;
   technical identifiers belong behind Details or a copy button, with their
   authoritative full values accessible.
4. **Subtabs:** one horizontal, left-aligned strip below the context row. The
   active panel spans the available workspace width. “Full width” refers to the
   panel, not equal-width stretching of every tab label. Tables and plot/detail
   splits can still use multiple columns inside a panel.
5. **Content:** adopt Data's spacing, tab treatment, surface colors and typography
   as the shared baseline, expressed through shared theme tokens/components.
   Report's iframe and generated preview must use a compatible document theme;
   removing only the surrounding black background is insufficient.

Use common building blocks for the page header, context strip, subtab strip,
empty/error/loading state and action presentation. Reuse existing responsive
header and theme infrastructure where possible. Do not create an independent
shell in Optimize. Shared navigation and command definitions should also be
usable by future Windows/macOS menus, with the same resource and capability
checks as their browser equivalents.

## 3. Subtab and action rules

### A subtab is a view

- Use short, stable nouns. Selecting a subtab changes what is visible; it never
  runs a workflow, starts billing, approves a proposal or reveals protected data.
- Give each subtab a stable string ID, independent of its index or displayed
  label. Keep order stable within a deployment. Changing a label must not change
  stored state or Advisor memory identity.
- Do not add a second page-level tab strip inside a panel. Local plot/table
  selectors and saved-run Summary/Results/Validation views remain legitimate
  controls for the selected object. Their visual hierarchy is subordinate.
- Campaigns, New round and Results are views of a retained process, not a
  compulsory wizard. Seed, proposal and approval are sections of one New round
  form; live evaluation and inspection share Results. Moving between sections
  never restarts work or silently creates missing evidence.
- Use native tab semantics, selected state, keyboard navigation and visible
  focus. At small widths, scroll the strip without clipping labels or mixing
  tabs into a “More actions” menu. Keep the active tab visible.

### An action does something

- Put the active view's essential actions in the shared header, normally with
  one visually primary next action. Less frequent page actions use a consistent
  overflow menu; row actions remain beside the row they operate on.
- Filters, selection controls, parameter editors and contextual row actions
  stay in the panel. Moving an action to the header must preserve its selected
  object, effective parameters and disabled/reason state.
- Use verbs for mutations or computation: Generate Report, Run Batch, Approve,
  Start Evaluation. Use destination arrows for navigation: Data →, Workflows →,
  Runs →, Campaigns →, Workflow →. An arrow never means “execute”.
- Put **Reclaim Storage on Dashboard**, because it works across the user's
  projects. Storage has its own Dashboard subtab; Runs must not execute
  reclamation there. Preserve the scope, retention disclosures and recovery flow;
  following the link alone must not remove anything.
- Remove routine Refresh/Reload buttons, including nested evidence panels.
  Load on entry, update after successful changes, and synchronize ongoing jobs.
  Show stale/disconnected state and a contextual **Retry** when retrieval fails.
  Never auto-retry a charge, execution or destructive action under this rule.
- Do not turn design cleanup into new scientific gates. In particular, local
  folder watch does not require a successful dry run or analytical qualification.
  Existing integrity, authorization and incompatible-input handling still apply.

### Every subtab has a contract

Before implementation, specify its purpose, selected object, context facts,
actions, resulting records, empty/error states, persistence and Advisor focus.
The page tables below supply these contracts. A new subtab requires the same
description and a destination for every function it replaces.

| Panel state | Required presentation |
| --- | --- |
| Nothing selected | Say which object to select and provide the selection action; do not imply a missing dataset when one is already selected. |
| Empty collection | Explain that this project/object has no records and offer the appropriate create/import/source action. |
| Loading or running | Identify the operation, preserve useful retained content, and show progress/Stop where supported. Loading must not look like an empty collection. |
| Partial or stale evidence | Identify what is retained, missing or outdated and its scope. Keep inspection/export where valid. |
| Read failure or disconnect | Keep context, show the actual failure and a scoped Retry. |
| Unsupported capability or lost access | Explain the actual deployment/access limitation and the available route forward; do not show a generic empty collection. |

Counts distinguish selected, displayed/filtered and total records. Status badges
describe retained state; they do not become navigation controls or substitute
for approval. Selectors in the context row and selectors in the active panel
must share the same authoritative state.

### Copy and disclosure

- Navigation, field and section labels use short nouns. Action buttons use short
  verbs that name the action; do not use sentences as labels.
- At most **one plain explanatory sentence per section** is visible by default.
  Put longer guidance, limitations and implementation explanations behind a
  consistently labeled **Details** toggle. Do not keep several disclaimer cards
  to work around this limit.
- Keep essential scientific scope, exclusions and irreversible-action consequences
  visible as concise labels/values or that one sentence. Details expands the
  explanation; it must not conceal which population or operation is involved.
- No technical IDs, UUIDs, hashes or digests in page/section headers. Use names
  and human-readable revision labels. Full identity is available through a copy
  button or Details; shortening the display must not alter retained evidence.
- Example approval summary: **Rounds remaining: 3 · Trials: 9 (including seed)**.
  Follow with one sentence explaining what Start does; technical authority and
  execution-limit explanations belong in Details.

### State and lifetime

- Back/Forward, a deep link and reopening a window restore the project, object
  and subtab. Resolve ownership/access on the server. Never load an object into
  an unrelated active project just because its ID was in a URL.
- Scope cached selection and draft state to actor, project and resource. Clear
  stale selections and discard late responses when any authority changes.
  Navigation can remember the last authorized view; it cannot expand access.
- Keep unsaved work across ordinary subtab navigation. Warn before genuinely
  destructive navigation. Multiple browser/desktop windows must not silently
  retarget each other's active operation through shared local storage.
- Navigating away from Results does not cancel a campaign. Display a global
  job indication with a return link; explicit Stop/Cancel owns interruption.
- Preserve old route/query aliases, including Runs `tab=models`, and old memory
  scopes through explicit migration or aliases. A redirect must carry object
  identity and return context, not just land on the default page.

## 4. Page contracts

### Dashboard and Project

Dashboard opens on **Your Project**, followed by **Archive** and **Storage**.
Place **Project →** immediately to the right of **New Analysis**, leaving the
project's relative update time right-aligned in its context row. Preserve project selection, archive,
restore, permanent deletion and any profile-specific removal semantics.

Dashboard’s **Storage** subtab owns account-wide storage and **Reclaim Storage**. Existing `/dashboard#storage` links select that subtab.
Expose its across-project scope, retained-output protection and outcome here.
Opening Storage never performs reclamation; the explicit action remains inside that subtab.

Runs opens a run name in **Inspect**, within the Runs workspace. Existing
`/runs/:runId` links retain their run, project and result context. Show the run
identity first, a spaced action row next, and incomplete durable evidence after
the retained details. Compare retains its comparison matrix and evidence-based
ranking restrictions; it does not expose a Result pairing section.

Project has no subtabs. Give its name/description most of the available width.
Move **Edit** and **Export** to the header. Keep New Project, Import, Audit,
Memory Map and deletion/removal discoverable through primary or secondary
actions. Memory Map must include campaigns and their relationships when the
managed memory capability is available.

The project overview presents Data, Workflows, Runs, Artifacts and Campaigns as
distinct collections with truthful counts. Use **Data →**, **Workflows →**,
**Runs →** and **Campaigns →**. An artifact link goes directly to Runs → Artifacts.
Keep the useful timestamps and short descriptions beside collection entries.
Do not rename an artifact count as a run count: a run may produce zero, one or
several artifacts. Campaign trial counts are not saved-run counts.

Preserve imported-project/package verification, exact local data binding,
application workflow links, campaign reproduction and reproduction-report
download. A concise imported-application section can link to Deploy → Application
without hiding the steps required to reproduce the imported result.

### Data

Keep the current subtab order and functional contents. Remove the duplicate
Project context cell and left-align the tab strip. The context row follows the
active acquisition/inspection view.

| Subtab | Context and retained functions |
| --- | --- |
| Import | Provider/source and selected dataset; catalogs, availability explanations, previews, local/reference imports and Add to My Dataset. Respect download/egress policy. |
| Synthesis | Recipe, selected components and generated population; composition/curve editing, load/save curves, preview, bundle operations and guide. |
| Upload | Destination dataset and selected files; file-format handling, validation/diagnostics, scientific-asset selection and upload outcome. |
| Library | Provider/query, selection count and job state; search, preview, basket and import. |
| Multi-well | Selected dataset/acquisition plan and save state; samples, mixtures, factors, wells, run order and file assignments. |
| My Dataset | Dataset/file/asset identity, dimensions and selection; preview plots, data contents, metadata, quality/statistics, roles, rename/delete and source-file selection. |

The Workflow → Data selection journey retains its explicit target sheet/source
node, selected files or assets, target/group roles and **Apply to this sheet** /
Cancel actions. Page cleanup must not replace an exact source binding with the
most recently viewed dataset.

### Workflow

No page subtabs. Preserve the present sheet tabs inside the canvas and all their
operations. The context row starts with **Active Sheet**, then **Active Data**,
then a right-aligned **Canvas** summary. Allocate about twice the width to each
of the first two cells relative to the summary, adapting to long names and
narrow windows. Remove the duplicate Project cell and generic subtitle.

Keep the settings/gear control as tall as adjacent header controls, even if it
is narrower. Preserve Analysis Starter, Run, Export, Audit, autosave, version
history, run-all settings, templates, sheet editing, catalog/graph operations,
Inspector, expanded node detail and typed result views. Imported campaign
trial views keep their source/evidence identity. Existing sheet tabs are neither
replaced nor restyled into the page-level subtab mechanism.

### Runs

| Subtab | Context | Primary contents and actions |
| --- | --- | --- |
| History | Filtered/total saved runs, run kind, selected count | Sort/filter/page, inspect, select for comparison, save/label/delete where supported. Clicking a name inspects; checking a row selects. |
| Compare | Exact selected run identities and compatible metric/population scope | Existing comparisons, result pairing/Check evaluation and report/export paths; retain compatibility explanations and selection limits. |
| Artifacts | Artifact count, selected artifact, source run and model/feature authority | Existing Models catalog under its corrected label; rename, inspect, readiness annotations, application history, Batch and Deploy links. |
| Batch | Selected fitted artifacts, input dataset/asset and cohort | Existing durable-dataset and authorized private-upload prediction paths; explicit Run Batch and partial/failure results. Completed saved runs link to History. |

Header: Export on the same line as Runs, with no storage link.
The reclaim action lives only on Dashboard. Remove
the generic subtitle and Project cell; the context row identifies History,
Compare, Artifacts or Batch. Saved-run detail retains Summary, Results and
Validation, node outputs, effective parameters and links to Report/Optimize.
These detail controls do not add main Runs subtabs.

Artifact existence, a human deployment-readiness annotation and analytical
qualification are distinct facts. Preserve their labels and evidence. The
Application tab is the home for operational application selection; Runs remains
the home for the artifact's recorded source and execution history.

### Optimize

Use the shared Data-style shell and the stable title **Optimize**. Campaigns
belong to the active project. Account and organization administration remain
outside this page. Round allowance and trial count are visible in New round's
approval section because they affect the decision to execute.

| Subtab | Context | Contents and action ownership |
| --- | --- | --- |
| Campaigns | Project campaign count; selected campaign and lifecycle status | Project-only campaign list and lineage, including draft, running and terminal work as applicable; select/resume a round, inspect its summary or start a new campaign. Lifecycle labels reflect server state. |
| New round | Campaign, seed revision, source workflow/run and validation scope | One page containing seed selection, proposal and approval. Preserve saved-run/starter/promoted seeds, source recovery, all three search methods, grid/recipes, questions/hypotheses, user selection and workflow differences. Show rounds remaining and trial count before explicit Start. |
| Results | Selected campaign/round/trial, progress and scientific scope | Live evaluation and inspection together: worker recovery, stop/cancel, provisional/final rankings, partial results, metrics/plots/refusals, keep/promote, confirmation, verification report, package/key export and Workflow →. |

Campaigns places list/lineage on the left and selected-campaign context on the
right. Results combines the live dashboard and selected-trial inspection rather
than requiring another stage change. New round is one continuous form; do not
recreate Seed/Proposal/Approval as nested tabs or a mandatory stepper.

**Iteration:** selecting a retained round opens Results directly. Keep/promote
can open a prefilled New round with the chosen seed and retained context; the
scientist reviews the proposal and starts from that same page. Finishing a round
retains its evidence under the campaign and never automatically adds every trial
to Runs. Draft inputs and the selected campaign/round survive tab switches.

**Approval is usage-based, not a cost forecast.** Show server-reported rounds
remaining and the selected trial count, explicitly including the unchanged seed
when counted. When the server reports no weekly round limit, say so; unavailable
allowance must not be displayed as unlimited or zero. Pro has no monetary cost
cap. Do not invent a predicted price or budget to approve. The server rechecks
allowance and recorded usage at Start. Allow users to deselect proposed trials
before starting; any changed selection requires a new approval. Retain the exact proposal/selection
approval receipt, expiry, idempotency and operational safety limits; changes
invalidate the old approval. Technical receipt and limit details go in Details.

**Independent confirmation remains in Results.** Select/freeze the candidate and
protocol, review authorization and the irreversible reveal through explicit
inline actions, then show progress and the terminal record in the same view.
Preserve governed recovery and development-versus-confirmation distinctions.
Opening Results must never consume authorization or reveal protected data.

**Handoff to Runs:** the agreed simple implementation is **Workflow →** from the
selected result in Results, using the existing workflow-opening path. It is
a destination action, not a fourth subtab. The scientist deliberately executes
and saves that workflow to create a new Run. Preserve campaign/trial/seed links,
source data binding and validation scope. A new run is not the original campaign
evaluation and does not automatically prove equivalent reproduction.

**Add to Runs** remains an optional later shortcut, not a prerequisite for this
redesign. If implemented, it must create an explicit, idempotent retained record
with original evidence and scope; it must not copy metrics onto an unrelated
execution or remove the original campaign record. The Workflow → route must
remain available, including when direct materialization is unsupported.

### Deploy

| Subtab | Context | Contents and actions |
| --- | --- | --- |
| Application | Selected application name, origin, source and evidence status | Full application selector; model/package information; source workflow/run, local reproduction/import links and optional qualification/evidence. Digests/technical IDs are in Details or copy controls. |
| Folder Watches | Selected application or explicit all-applications scope; watch/job state | New Watch, existing model binding/settings, enable/disable, optional Try a file, delete, uncertainty record and QC/maintenance controls. |
| Prediction History | Application/watch filters and visible/total records | Existing saved predictions, per-file status/errors, labels, artifact identity, QC snapshots and exports. |

Moving the full application selector to the first tab must not hide which
application a watch targets. Keep a compact selected-application indicator/link
in the context row and explicit bindings on watch rows. Changing selection must
not silently rebind existing watches. Disclose whether a list shows all project
applications or only the selected one; don't silently narrow existing lists.

Keep the campaign-evidence yellow star with its exact scope: recorded campaign
validation evidence does not certify predictions on new samples. Local dry runs
and qualification remain optional. In hosted profiles without folder-watch
execution, preserve the honest Workbench handoff and available export/batch
paths; don't render active controls that call refused endpoints.

### Report

| Subtab | Context | Contents and actions |
| --- | --- | --- |
| Setup | Workflow and selected run names; report length and data-disclosure choices | Workflow/run filters, selected-run chips, short/detailed option, section choices and explicit row-level plot/data opt-in. Full IDs remain available in Details/copy controls. **Generate Report** belongs to this view's header. |
| Preview | Generated report's source identities, scope and generation/staleness status | The actual report, AI narrative attribution where available and Export. Preserve supported PDF/HTML/Markdown/JSON formats and scoped current-workflow Python/notebook export. |
| ISO Validation | Selected workflow/run, audit availability and walkthrough scope | Existing ISO 17025 walkthrough, assumptions, limitations, Audit link and evidence-pack route. The title is not a compliance or accreditation claim. |

Setup describes the next generation request. Preview describes the last generated
result. Changing Setup keeps the previous preview with a visible “settings
changed” indication until explicit regeneration; exports must identify the
preview they export. Keep selected IDs/section choices and row-level disclosure
consistent across preview and export. Enabling an AI narrative remains an
explicit action with existing privacy/usage behavior, not a side effect of tab
navigation. A generated report need not become a new backend model for this
layout; a retained generation snapshot is the minimum authority.

Use the shared Data-style page background in all three tabs and a readable
document surface in Preview. Preserve the explicit notice that exporting a
current workflow's Python/notebook is not historical-run replay. ISO Validation
organizes the existing walkthrough and Audit → evidence-pack journey; it must
not silently replace analytical qualification or imply that a walkthrough
validates the scientist's method.

## 5. Campaigns as canonical project objects

**An optimization campaign is owned by its Project. Organization supplies
accounting context, not scientific ownership or the history collection.** Reuse the
existing long-lived optimization campaign, seeds, examinations, iterations and
promotion records. The bounded execution batch remains a distinct execution
authority. Do not introduce another competing campaign identity.

```text
Project
  Data · Workflows · saved Runs · Artifacts
  Optimization campaign
    Source workflow/run → seed → examination → iteration → trials/evidence
                                ↑ promotion to a new seed ← selected trial
```

Required implementation contracts:

- Durable, unambiguous project binding and authorization through the project.
  Source run/workflow project and campaign project must agree. Preserve the
  existing access policy during migration; accounting membership alone must not
  expose another project's campaigns.
- Project-filtered list/detail/count/search APIs, authorized on the server. A
  browser filter on an organization-wide response is insufficient.
- Resolve billing account, round allowance and recorded usage separately on
  the server. Retain the account charged for each execution; a project transfer
  cannot rewrite historic charges. Organization controls do not belong on the
  scientific campaign page. This separates responsibilities without duplicating
  campaign records or removing commercial enforcement.
- Canonical IDs exposed in Project, Optimize, Memory Map, exported evidence and
  workflow/run handoffs. Distinguish campaign, iteration, execution batch and
  trial IDs instead of overloading one `campaign_id` field.
- Draft and running work must survive navigation and restart under the same
  identity. Idempotency and retained proposal/approval/execution links survive
  UI retries; a second click does not create another study or charge.
- Define project archive, removal, export/import and authorized transfer behavior
  for campaigns and retained evidence. Never orphan lineage or silently move it
  to whichever project is active. OSS imports supported scientific packages and
  evidence; it need not acquire the managed campaign execution service.
- Backfill older records only from unambiguous retained source authority. Expose
  unresolved records through an authorized recovery path. Do not guess ownership
  from titles or current browser state. Preserve existing access restrictions,
  including source-run ownership when opening a trial in Workflow.

## 6. Advisor memory and attention

The durable memory anchor is the authorized **project + object identity**.
Subtab/stage and active node/plot/table describe attention within that object.
They must not create unrelated conversation buckets whenever the user moves
between New round sections or from Campaigns to Results.

Pass project, page/subtab, resource type/ID, applicable seed/iteration/trial,
workflow/run and focused node/plot IDs through the shared context mechanism.
The server resolves their contents and checks authorization/disclosure; browser
focus is a hint, never access authority. Preserve existing memory-topic choices,
history and attribution through scope aliases/migration. Switching project,
actor, object or focused plot clears stale context before another AI request.

Memory Map gains project campaign nodes and their source/derived links. Account
settings do not become campaign memory. OSS BYOK chat and managed Advisor keep
their existing feature/privacy boundaries while using consistent visible focus.

## 7. Acceptance and change discipline

The design is not complete merely because the pages look consistent. For every
moved function record: old source, destination, object identity, action outcome,
profile availability and an acceptance journey. Keep dated source inventories
separate from this canonical document.

Minimum implementation checks:

1. All eight pages at wide/narrow sizes and with Advisor open; stable underlying
   project binding, keyboard navigation and no duplicate Project tiles. The
   topbar's existing hide-while-Advisor-is-open behavior is allowed. Check short
   labels, one explanatory sentence per section, working Details toggles and no
   technical IDs in headers.
2. Deep links, Back/Forward, reload and project/actor switching; no stale results,
   wrong-project actions, lost drafts or orphaned memory.
3. All Data sources and Workflow sheet operations; exact data/target/group binding
   survives navigation and the canvas sheet tabs remain unchanged.
4. All four Runs tabs, saved-run detail, comparison, artifact provenance, batch
   outcomes and direct Dashboard Storage navigation. Reclaim Storage executes only
   on Dashboard, with across-project scope and retained-output protection.
5. All three campaign search methods across the three tabs, single-page round
   creation, approval showing rounds/trials, stop/partial outcomes, confirmation
   and export. Keep → prefilled New round avoids a stage wizard; completion does
   not flood Runs. No cost forecast or Pro monetary cap is introduced.
6. Campaign → Workflow → explicit execution/save → Runs; verify linked identities
   and distinguish development evidence from a fresh execution.
7. Cloud package → local import/bind/reproduce → Application → Folder Watches →
   Prediction History, with optional qualification and no new local enable gate.
8. Report Setup → Generate → Preview → export, changed-Setup disclosure, row-data
   opt-in and ISO walkthrough → Audit → evidence pack.
9. OSS, Demo and Pro capability differences; navigation does not create new
   entitlements or hide promised features. Existing administrative/system pages
   remain reachable for authorized users.

Use the scientific contract's deliberately dissimilar data cases as well as
these navigation journeys. A source audit establishes a destination for each
function; only implementation tests and browser evidence establish it works.

## Appendix A. Changes from the reviewed frontend

Baseline: monorepo `444232f781261f88b187a4acb42ceffc1007a017` (merged #1214).
Paths below are relative to the repository; `FE` means
`packages/spectra-sherpa/frontend/src`, `Managed FE` means
`packages/spectra-server/frontend/src`, and `Server` means
the separately distributed managed server source.

| Area / current source | Current arrangement | Required change / preservation condition |
| --- | --- | --- |
| `FE/components/Topbar.vue` | Project selector hidden when chat is open | Keep this accepted behavior; preserve the underlying project and Advisor scope when removing page duplicates. |
| `FE/layouts/MainLayout.vue`, `FE/components/Sidebar.vue`, server module navigation | Shared shell plus contributed pages | Use one page/subtab/action grammar; keep status, jobs, version, system pages and profile authority. |
| `FE/views/dashboard/SimplifiedDashboard.vue` | Current-project icon arrow; no storage action | Label Project →; preserve project management; host account-wide storage/reclaim under the Storage subtab. |
| `FE/views/project/ProjectContent.vue` | Narrow description; Edit/Export below; artifact list/count; no campaign collection | Wider identity; header actions; distinct Runs/Artifacts/Campaigns lists and counts; keep import/reproduction controls. |
| `FE/views/data/DataContent.vue` | Duplicate Project cell | Remove cell, align tabs; retain every data view and workflow-binding action. |
| `FE/views/workflow-builder/WorkflowBuilderContent.vue` | Project/Sheet/Data/Canvas context; canvas workbook tabs | Remove Project, enlarge Sheet/Data, right-align Canvas, normalize gear height; keep canvas tabs/operations. |
| `FE/views/models/ModelsContent.vue` | History/Compare/Models/Batch; storage/qualification above | Rename Models to Artifacts, keep Batch, move Reclaim Storage to Dashboard; remove the Runs storage link; use subtab context. Qualification remains accessible through Deploy. |
| `FE/views/models/RunDetailContent.vue` | Summary/Results/Validation detail views | Preserve under selected-run inspection, including exact saved evidence and Report/Optimize actions. |
| `Managed FE/campaign/views/CampaignsView.vue` and children | Launch, planning, allowance review, confirmation, history and monitor intermixed | Remap to Campaigns/New round/Results; one-page seed/proposal/approval, combined live/inspection dashboard. Show rounds/trials, not a cost forecast; preserve all search methods and reduce copy. |
| `Server/models/optimization_campaign.py`, `Server/routes/harness.py` | Persistent campaign stored with org ownership; list lacks project filter | Make Project the scientific owner/list/access scope; retain organization as accounting context, bounded execution batches and lineage. |
| `Server/models/advisor_memory.py`, `Server/memory_map.py`, `FE/lib/sherpaAttention.ts` | Existing project/tab/subscope memories; partial focus IDs | Evolve scopes with aliases; add campaign relationships and precise stage/resource focus without orphaning existing topics. |
| `FE/views/deploy/DeployContent.vue` | Application catalog above Folder Watches/Prediction History | Put catalog/qualification under first Application tab; keep compact context and per-watch binding elsewhere. |
| `FE/views/deploy/QualificationPanel.vue`, `InstrumentQCPanel.vue`, Data acquisition panel | Nested Refresh/Reload actions | Synchronize after changes/on entry; retain explicit error Retry and all evidence/export/edit functions. |
| `FE/views/report/ReportContent.vue`, `FE/utils/reportGenerator.ts` | Setup/preview/walkthrough on one page; dark iframe and generated HTML styling | Split Setup/Preview/ISO Validation; retain report-length/section/data options; align page and generated preview theme. |
| `FE/views/report/ValidationWalkthroughPanel.vue` | Walkthrough beneath report | Move to ISO Validation; preserve Audit/pack path and limitations, no certification claim. |
| Router, stores and managed navigation callbacks | Index/alias-based tabs and different object query conventions | Stable tab IDs; retain legacy links and object context; prevent late-response/project leakage. |
| Historical `docs/plan/runs-navigation.md` | Earlier two-tab plan | Keep as historical evidence and point to this four-tab authority. |

## Appendix B. Implementation order

1. Shared shell and stable project/state/command contracts.
2. Canonical campaign/project authority, source scoping and memory migration plan.
3. Data/Project/Workflow/Runs layout, preserving four Runs tabs and canvas tabs.
4. Optimize three-tab presentation over existing services, including all confirmation
   and workflow/export paths; no new scientific or commercial authority in UI.
5. Deploy and Report layouts, then the cross-page acceptance journeys above.

These are dependency boundaries, not authorization to implement or a prescribed
PR count. Do not delete a current path until its mapped replacement is reachable.

## 2026-10-02 visual correction

- Shared page headers and context rows own vertical spacing. Page containers do not add a second flex gap; use Workflow’s compact title/context/content rhythm.
- Every subtab label has a visible rim on all sides. The selected tab uses the primary border and a light tint; retain keyboard focus and disabled states. Remove page-specific tab rules that override the shared component.
- Dashboard has **Your Project** (default) and **Storage** subtabs; project archive/restore remains with projects. Reclamation remains account-wide and never runs merely by opening a tab.
- Remove “Storage on Dashboard” from Runs.
- Report uses the same workspace background as Data, Runs and Deploy. The report document itself retains its print-friendly presentation.

## Project availability lights

Traffic-light colors report basic availability, separately from the provenance
checks shown on the detail page. Green means present, grey means absent or not
checked, and red indicates an operational problem such as unreadable source/model
files, an inactive model, or a failed latest run. A dataset record remains available
even if its source files need attention; the Source light reports that separately.

Uploaded files and project datasets do not require a named view, a target, a
selection event, or a completed workflow to be available. New Analysis projects
and existing projects follow the same rule. An active model with readable stored
files is available regardless of which dataset or workflow the user last selected.
Campaign/package lights indicate recorded items, not scientific qualification.

The API retains each record's provenance `state` and adds a separate
`availability` state/detail. Both the topbar and the detail-page dots use the
latter. Green is **not** a claim of predictive quality, full model verification,
deployment readiness, or a complete provenance chain. Existing integrity checks,
admission rules, and immutable scientist-choice records are unchanged.
