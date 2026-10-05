# Scientific Result Surface Contract

For the surrounding page layout, subtabs, navigation and action placement, use
the [GUI workspace design](gui-workspace-design.md). This contract continues to
govern the scientific meaning of every surface within that arrangement.

This is the canonical design and review contract for scientific GUI surfaces.
It states requirements; it does not certify that every current surface already
satisfies them. Dated audits record observations against particular revisions.

## Reusable rule for every scientific GUI surface

Every plot, table, statistics panel, workflow editor, and export surface should satisfy the same contract.

### 1. Input authority

The surface must know and expose, where relevant:

- Dataset and result identity.
- Sample and feature dimensions.
- Sample, target, class, group, and metadata roles.
- Axis values and units.
- Masks, exclusions, missing values, and active cohort.

### 2. Operation authority

The displayed result must be tied to:

- The exact node and operation.
- Effective parameter values, including defaults.
- Fit, transform, predict, or evaluate mode.
- Random seed and selection state where applicable.

Parameters should come from the saved execution graph, rather than being reconstructed from current UI state.

### 3. Output authority

The UI must preserve:

- Output type, shape, and scientific meaning.
- Row-to-sample and column-to-feature mappings.
- Labels and units.
- Model, run, and source-result identity.

A renderer should consume a typed result or presentation contract. It should not infer meaning from node names or array shape.

### 4. Claim scope

The surface must state which population and claim it represents:

- Calibration, cross-validation, held-out test, or external prediction.
- Exploratory projection or fitted model.
- Training population versus displayed population.
- Converged, provisional, rank deficient, or otherwise qualified.
- Rejected and excluded observations.

A projection containing more than one declared population must separate and
label those populations, or explicitly refuse the mixed projection. Never
assign the first row's calibration/CV/test role to the entire plot. Row ordering
must not change the scientific claim. Preserve per-row sample and target
identity; a legend is not a license to compute a pooled validation metric.

#### Optimization population boundary

Campaign tuning and its optimization curve use cross-validation on the training
population. If the source run has a held-out split, preserve its exact retained
row membership and order; never reconstruct that split after changing preprocessing.
Fit every candidate preprocessing step inside each CV training fold. Held-out
values and metrics are inspection-only and cannot inform proposals or ranking.

A returned candidate sheet preserves the source's held-out prediction and
inspection branch and adds a separately labelled training-CV result. Its test
preprocessing uses training-fitted references or masks. Re-running that sheet must
reproduce the campaign's training-CV metrics within numerical tolerance and keep
held-out metrics separate. A new campaign from that sheet inherits the same
population boundary. No test label or plot may disguise a CV result.

### 5. Transformation disclosure

Any operation that changes what is displayed must be visible:

- Filtering or exclusion.
- Aggregation.
- Subsampling or truncation.
- Normalization or scaling.
- Spectral range selection.
- Cube unfolding or spatial reduction.
- Missing-value handling.

### 6. Lifecycle fidelity

The same scientific meaning should survive:

1. Run.
2. Save.
3. Reopen.
4. Export.
5. Reimport.
6. Apply to compatible new data.

#### Canonical node artifact acceptance

Every canonical node must have a reviewed retention disposition. A successful
numerical call alone does not satisfy the lifecycle contract:

| Output role | Required retained destination | Application obligation |
| --- | --- | --- |
| Reusable fitted model or decomposition | Runs → Artifacts, with source run, workflow/version and project | Selectable in local Deploy; reopen and apply the exact fitted state without refitting |
| Cohort-only fitted result (for example HCA or DBSCAN) | Runs → Artifacts and exact run evidence | Explicitly describe cohort replay; do not advertise new-observation prediction |
| Fitted preprocessing, selection or transfer state | Exact run evidence and the saved pipeline that consumes it | Replay the saved transformation with its feature/axis/target authority |
| Stateless data, diagnostics, metrics and presentation | Typed saved-run output | Preserve interpretation on reopen/export; no fabricated model artifact |

For **every model-producing canonical node**, qualification must execute a
synthetic fixture through fitting, executor artifact capture, persistent model
registration, saved-run association, project artifact listing, reopening, Deploy
application selection, and prediction or transformation on compatible data.
Compare reopened outputs with the original fitted implementation. Application
must not require incoming targets or invoke fitting. Test incompatible axes,
missing/corrupt state, project isolation and non-applicable cohort-only results.
Verify the final application consumer and its result semantics, not just the
lower-level numerical adapter. Use the real storage and listing/application paths; mocks that manufacture an
artifact UID or tests that stop at an in-memory model do not establish this.

`tests/test_canonical_model_artifact_lifecycle.py` maintains the registry census
and these model journeys. Adding a canonical model without its lifecycle fixture
must fail qualification. Extend pipeline-state and ordinary output-retention
coverage when adding a node in either of those categories. No silent omission
is acceptable: persistence failure must not become a successful reusable-model
run with an empty artifact list.

### 7. Explicit refusal

Surfaces should have defined behavior for:

- Empty and singleton data.
- All missing or nonfinite values.
- One-class supervised inputs.
- All-noise clustering.
- Missing target or feature authority.
- Incompatible model application.
- Result limits and unavailable retained output.

Silent dropping or a generic blank plot should fail this requirement.

### 8. Encoding fidelity

A scientifically valid payload can still produce a misleading picture. Geometry, scale,
color and displayed precision must faithfully encode the declared scientific quantities.

- **Geometry:** when distance or angles are interpreted in commensurate score coordinates,
  use equal data-unit scaling on both axes. Independently stretched axes must be an explicit
  qualified view, not an undisclosed default. Different units or intentionally standardized
  coordinates require a declared metric/normalization; do not imply Euclidean distances.
- **Color:** signed scientific values use a diverging scale centered on the meaningful zero,
  with a disclosed, symmetric range when comparing sign/magnitude. Nonnegative magnitudes use
  a sequential scale. Selection of a scale must preserve the declared value semantics; a
  signed residual is not equivalent to an unsigned intensity. Comparable panels share limits
  or disclose independent normalization. Color must not be the sole indicator of class or sign.
- **Precision:** axes, hover text, statistics and exports must not round scientifically distinct
  values into the same reported value. Use magnitude-aware significant digits/scientific notation;
  keep exact identifiers and coordinates available. Never report a small nonzero residual as zero
  solely because of fixed decimal formatting. Magnitude handling and precision declaration are
  separate obligations: preserve trailing zeros when a producer or presentation policy declares
  decimal places or significant digits. Never coerce the formatted result back through a number.
  Bare JSON numbers do not retain source significant figures; a renderer must not infer them.
  Keep display policy distinct from measurement uncertainty. Default component percentages use
  one decimal place, evaluation summaries three, and regression-builder metrics four. Below
  a decimal policy's resolution, use scientific notation with the same number of mantissa
  decimal places (`0.940`, `20.0%`, `1.000e-6`, `4.0e-2%`). Exact-coordinate views use round-trip
  numeric text unless explicit precision metadata is available. Test ordinary trailing zeros and
  small nonzero values together, including agreement between summary and detailed views.
- **Component orientation:** signs of latent components can differ between separate fits without
  a scientific change. Preserve the stored fit's paired scores/loadings/model orientation through
  save/reopen/export. Cross-fit comparisons must disclose arbitrary sign (and possible component
  rotation/order ambiguity), or use an explicit, recorded paired alignment. A renderer must not
  silently flip scores, loadings or model coefficients independently.
- **Uncertainty:** identify available interval/spread estimates, their method, confidence level,
  evaluation population and assumptions. When a view supplies only point estimates, state that
  uncertainty/stability is not provided. Do not infer prediction intervals from residual spread,
  treat fold variability as a confidence interval, or invent VIP stability without retained evidence.
- **Degeneracy:** empty/constant axes, singleton/two-point clouds and near-zero ranges need faithful
  finite extents and explicit limits on interpretation. Do not manufacture separation or precision.

These requirements apply to rendered pixels and exported figures as well as the data/layout
objects. Inspect representative actual renderings; a correct axis label cannot compensate for
misleading geometry or color.

## Minimum test matrix for a new surface

A new plot or statistics surface does not need hundreds of permutations. It should have at least five deliberately dissimilar cases:

1. Unsupervised spectral data.
2. Supervised spectral data with a held-out cohort.
3. Non-spectral tabular data.
4. Data containing missing or rejected observations.
5. A lifecycle case: save, reopen, export, or model application.

Add multiway or spatial data when supported.

Each case should verify more than rendering. It should assert:

- Which observations are included.
- The denominator used by statistics.
- Axis values and units.
- Group labels and counts.
- Visible versus total rows.
- Effective method and parameters.
- Exclusions, truncation, or aggregation.
- Connection to the originating saved run.

For plots and statistics specifically, the plotted population and the metric population must match or their difference must be disclosed.

## Visual regime matrix

Use visual regimes as a second axis alongside the five scientific data/lifecycle scenarios.
Select at least one case for each applicable regime; a combinatorial cross-product is unnecessary.

| Regime | Encoding assertions and rendered evidence |
| --- | --- |
| Anisotropic scores: PC1 variation much greater than PC2 | Equal units map to equal pixel lengths; no independent axis stretching; labels and explained variance remain exact. |
| Signed matrix with positive, zero and negative values | Zero is the neutral midpoint; equal opposite magnitudes receive balanced colors; limits and normalization are disclosed. |
| Values spanning six orders of magnitude and closely spaced channels | Hover/statistics preserve nonzero values and distinguish adjacent coordinates; use scientific notation where appropriate. |
| Two fits with a paired score/loading sign flip | Saved-run replay is unchanged; cross-fit comparison warns of orientation ambiguity or records paired alignment; no silent independent sign change. |
| Singleton, two-point and nearly degenerate clouds | Finite ranges, faithful aspect ratio and no fabricated class separation or confidence; interpretation limits are visible. |

Where intervals or fold ensembles exist, test one retained uncertainty case and one point-only
case. Verify method, population, level and missing-uncertainty disclosure. Image review complements
numeric assertions; retain a screenshot/export for geometry, palette and hover-format checks.

## Where I would keep the canonical document

I would make this the primary document:

[scientific-result-surface-contract.md](scientific-result-surface-contract.md)

Then link it from:

- `docs/developers/adding-a-node.md`, especially its presentation section.
- `docs/developers/testing-release.md`.
- `docs/nodes/output.md`.
- The pull request checklist for nodes, plots, statistics, and result views.

The dated audit directory should remain evidence of what was observed. It should not become the canonical design guide.

## Architectural invariant

[ADR-0004: Typed presentation projections preserve scientific chain of custody](https://github.com/Spectra-Scientific-LLC/spectra/blob/main/docs/architecture/adr/0004-typed-scientific-presentation-projections.md)
records the architectural decision. A scientific GUI is part of the
computation's chain of custody. Every scientific surface must consume a typed
presentation projection bound to the authoritative value and its source or
execution context. Automated tests check **identity, population, parameters,
interpretation, and replay**, alongside whether controls and charts render.

Use the existing renderer-neutral presentation contracts and shared projection
path. This requirement does not introduce a second wire schema. A renderer may
validate shape against a declared type; it must not use shape or a node name to
invent that type. A source preview or unexecuted editor view identifies its
source/draft state rather than inventing a saved run.

Saved effective parameters belong to the executed record, including its
resolved defaults. The authored graph may contain only explicit values;
reading that sparse graph alone is insufficient. When execution authority was
not retained, show that limitation instead of resolving today's defaults.

## Practical review checklist

- [ ] Identify the typed source value, presentation kind, ports and source/run
  identity before choosing a renderer; distinguish source previews from results.
- [ ] Preserve sample/feature mappings, targets/classes/groups, axis values and
  units, masks and the active cohort. Never treat class names as target columns.
- [ ] Read effective method, parameters, defaults, mode and seed from saved
  execution authority where applicable; separate current draft settings.
- [ ] State the scientific interpretation: exploratory or fitted; calibration,
  cross-validation, held-out or external; and any convergence/rank qualification.
- [ ] Account for selected, included, displayed, rejected and total observations.
  Disclose the metric denominator and any difference from the plotted population.
- [ ] Declare each display transformation and preserve a mapping to its inputs.
  Tables, downloadable figures and exports carry the same scope or explicitly
  identify a bounded visual extract.
- [ ] Check save/reopen/export/reimport and compatible application where
  supported. Preserve lineage; a new application has its own result identity.
- [ ] Exercise empty, singleton, missing, rejected, incompatible and unavailable
  cases. A singleton spectrum or a legitimate one-class method may be valid;
  refusal depends on the declared operation, not a blanket rule.
- [ ] Check encoding fidelity: metric/aspect ratio, zero and color limits, significant digits,
  component orientation, uncertainty and degenerate ranges. Review actual rendered/exported pixels.
- [ ] Add a regression and review the original evidence for each addressed
  issue. A passed shared adapter test does not close every consumer defect.

## Concrete acceptance examples

These are small synthetic scenarios, not descriptions of shipped behavior.
Use them to implement the five-case matrix above without private source files.

| Scenario | Assertions beyond rendering |
| --- | --- |
| Unsupervised spectral projection: six labeled spectra, one excluded before PCA | Fitted and score populations contain the five admitted IDs; exclusion is visible; wavelength values and units are exact; preprocessing and effective PCA parameters are bound to the run. If a view displays fewer points, it reports that reduction separately. |
| Supervised held-out prediction: eight samples split into five calibration and three test samples | Test figure and its metric use the same three test IDs and a denominator of three valid pairs; training membership is distinct; claim says held-out; stored split/seed, model and run identities are preserved. A calibration metric is not attached to this figure as if it were test performance. |
| Non-spectral table: four rows with mass and temperature features | Feature names and their respective units survive table/export/reimport; columns are not interpreted as a spectral axis. For a display limited to two rows, show two of four and declare whether statistics use two or four. |
| Missing/rejected observations: six selected samples, one missing reference and one independently rejected sample | If the declared evaluation policy excludes these two, identify the four admitted sample IDs and denominator four; missing and rejection counts are distinct. If the operation cannot support that policy, refuse with the specific reason. No silent row dropping or invented class names. |
| Lifecycle: run A uses two components; later draft B uses five | Reopen A and verify its identity, effective two-component parameters, interpretation and population. Export/reimport must preserve A's applicable authority or state/refuse unsupported replay. Applying A's fitted model to compatible new data yields a new result bound to A's model and the new input. |

For supported multiway/spatial data, add a small labeled cube. Verify dimension
roles, exact pixel/sample mapping, unfolding or spatial reduction, axis units,
excluded pixels and the resulting statistical population. Do not count a
silent reshape as a successful projection.

Keep plotting-library assertions (traces, controls, downloadable image) alongside
these scientific assertions. A snapshot of a chart is not evidence that its
points, metric denominator or historical parameters are correct.

## Review the entire scientific claim path

The contract also applies to nonvisual consumers: advisor/chat summaries, report prompts,
comparison prose, serializers, workflow stores, and downloadable artifacts. A list of Vue
components is a discovery aid, not a complete review boundary.

Trace each representative case through producer → typed presentation → renderer or prose
adapter → retained run → export/provider. Verify qualifications survive each boundary.
Use the executed materialized presentation list and source ports; a declaration alone does
not prove a result was produced. A retained digest is a receipt unless its integrity was
independently verified. State default projected selections separately from the current UI view.

Include these transitions in the minimum test matrix:

- Change parameters after execution; never associate prior results with the edited operation.
- Execute only a node and its dependencies; verify downstream results cannot appear to belong
  to the new execution.
- Execute in a second client before saving the displayed run; save by the displayed run ID.
- Compare a branched graph with multiple split nodes; preserve topology and node-scoped settings.
- Switch between overlay, heatmap, table and statistics; keep the active population consistent
  or disclose the difference and its denominator.
- Mix valid and invalid rows; report invalid/excluded counts rather than silently dropping rows.
- Send a refused projection to a shared renderer and an advisor; preserve refusal, block stale
  chart export, and keep private identifiers out of outbound summaries.

Typed projection qualifications are reviewed scientific assertions. Arbitrary Plotly metadata
must not authorize a held-out claim or impossible population counts. Provider formatting must
preserve reviewed qualifications without reconstructing meaning from plot labels.


## Execution snapshot invariants

A visible result belongs to one immutable execution snapshot. Carry its exact run ID,
executed definition and effective parameter record together with results, descriptors,
materialized presentations, diagnostics and execution statuses. Editor nodes and edges
are draft authority and must never relabel an earlier result.

- **Draft edits:** after a semantic edit, either inspect the producing execution explicitly
  or refuse result interpretation in draft-based panels and advisor contexts. A stale badge
  alone does not make mixed draft/result prose authoritative.
- **Partial execution:** replace the visible execution snapshot with the returned execution,
  or bind every retained result individually and disclose distinct executions. Never merge
  new ancestors with old descendants as one completed graph. Invalidate descriptors,
  presentations, diagnostics and statuses together with invalidated numerical results.
- **Saving:** save/name the exact displayed run ID. A latest-run lookup is not equivalent:
  another browser or execution can advance it before the user saves. Missing identity refuses
  naming rather than selecting a different execution.
- **Concurrent changes:** a response may update the run it belongs to, but must not rebind an
  edited draft, switched workflow or later execution to that response without explicit identity.

## Provenance is a graph, not an ordered list

Comparison surfaces may show unordered executed-node inventories when topology is absent.
An arrow path requires the exact saved edges; object insertion order, node names and result
availability do not prove connectivity. Preserve parallel branches and disconnected nodes.

Split settings, seeds, feature counts and effective parameters stay attached to the producing
node and operation. Do not combine fields found in different nodes into a synthetic method.
When a summary lacks this authority, show unavailable or the explicitly qualified raw snapshot.

## Population conservation across projections

Every projection declares its source, active and displayed populations and maintains their
mappings. Switching encoding (overlay, heatmap, table, statistics) must not silently change
which observations or features belong to the active cohort. A table may inspect all retained
rows only when it identifies excluded rows and clearly distinguishes retained from active scope.

For an ordinary masked retained matrix, counts satisfy
`active + excluded = retained` and `displayed <= active <= retained`. A display limit is a
separate reduction from exclusion. Sample and feature masks must have exact boolean alignment
with their respective dimensions; malformed or all-excluded inputs refuse explicitly when no
scientific view remains. A mask indicates exclusion, not statistical rejection or an outlier verdict.

Record-oriented plots must validate every retained row. If the declared contract does not
specify a policy for partial missing/invalid records, refuse the projection with counts and a
reason; do not quietly plot only the valid subset. A supported exclusion policy must retain
included and excluded identities, distinguish missingness from rejection, and expose the metric
denominator. Do not reuse metrics computed for a different population without disclosure.

## Required transition regressions

| Failure class | Minimal regression and acceptance |
| --- | --- |
| Draft/result substitution | Run A, edit a semantic parameter or edge, ask both advisors: use A's immutable authority or explicitly refuse result claims. |
| Wrong run saved | Display A, execute B elsewhere, save: the request and named record must identify A. |
| Mixed execution epochs | Run source → transform → model; rerun only transform: old downstream values, descriptors, presentations and statuses cannot masquerade as part of the new execution. |
| Invented provenance | Compare a branched graph and two split nodes: no invented edges or cross-node composite settings. |
| Silent partial row loss | Mix finite and missing response/peak/feature records: exact included/excluded counts and identities under a declared policy, or a visible refusal. |
| Cross-view cohort drift | Switch masked spectra from overlay to heatmap and retained table: preserve active sample/feature identities or explicitly label the different inspection scope; repeat after JSON reopen. |

These transition tests supplement the five dissimilar scientific scenarios. A fix is complete
only when its regression passes and its original observation is reviewed. A final deep scan
must follow both data and claims through serializers, stores, renderers, comparisons, reports,
exports and application—not merely enumerate components or count passing tests.


### Boundary cases for execution and encoding reviews

- Bind the execute request to the graph the caller reviewed. A save followed by an execute is
  not atomic across clients: reject an intervening graph change, and execute the frozen graph
  that was admitted. Snapshot checks must precede consuming quota or publishing scientific results.
- A newly started or failed attempt must not inherit the authority of a prior successful run.
  Retain the old run in History with its own identity. Unscoped progress events cannot authorize
  node completion. Superseded responses must not reach component caches after navigation.
- Naming a run must preserve its identity on reopen. A save dialog captures the reviewed run ID;
  if the displayed run changes before submission, reopen the dialog rather than naming another run.
- Filtering an axis filters **all** aligned fields: classes, exclusion reasons, sample-table
  columns, selection scores, alternate scales and label/class sets, as well as values and labels.
  Preserve typed class identity (for example, integer `1`, string `"1"`, and boolean `true`).
- Check precision through metadata-colored scores, selected-spectra and multi-dataset adapters,
  table cells and range headers. Testing only the primary plot builder misses reachable encodings.
- Equal-unit constraints must remain readable in actual pixels: expanding a display range is
  preferable to collapsing the plot domain to a strip with overlapping ticks. This changes the
  visible range, never the score values. Include a pixel geometry check alongside layout assertions.

## Validation boundaries and observation ledgers

A train/test split is a scientific boundary. Ordinary canvas execution must
refuse fitted preprocessing, feature selection or models upstream of that
boundary: executing them once on the whole input can leak held-out information.
Stateless transforms may precede it. Training-fit/test-apply and qualified
fold-local execution remain the supported fitted-operation paths.

A sample-level ledger must consume an identified comparison contract with
aligned sample identities, references, predictions and population roles. Plot
reference lines, fitted lines, confidence bands and other drawing primitives
are not observations and must never enter a ledger or its CSV export. Missing
identity or inconsistent counts must produce an explicit unavailable state,
not generated sample IDs or silent truncation to the shorter array.

Regression tests must pass an actual producer payload through save/reopen and
ledger export; a hand-written marker-only plot fixture cannot prove that
reference geometry is excluded.

## Recorded runtime evidence

Run inspection and evidence export must use the stored environment snapshot,
never today's server versions as a substitute for historical evidence. New run
writers inherit capture from the shared run model; explicit historical absence
remains absent. The UI must distinguish unavailable capture, absent optional
packages, and an unrecorded historical environment.

A package/version inventory and loaded-library snapshot support investigation;
they do not guarantee deterministic replay or prove the cause of a numerical
change. Preserve the capture scope, originating run identity, and workflow digest
when exporting this evidence. General historical replay requires its own retained
input and execution contract and must not be inferred from current-graph export.

## Computational boundary obligations

These requirements extend the same scientific contract through producers,
fit/apply boundaries, typed values, serializers and consumers. They are normative
requirements, not a certification that every existing operation meets them.
Changes to retained-state meaning require an explicit version and compatibility
policy. Audit reports remain observations against a particular source revision.

### Population and response binding

- An operation's declared sample effect must match its actual behavior, including
  missing-response handling. Filtering must retain original, admitted and excluded
  sample identities/counts, reasons, selected response and the output-to-input row
  mapping. A source dataset identifier alone is not an exclusion receipt.
- Separate labeled X and Y inputs must have identical ordered sample identities,
  or pass through an explicit identity join with a retained mapping. Equal row
  counts are insufficient. Reject contradictory, duplicate or incomplete identity;
  do not discard labels before checking them.
- Bare positional arrays may be supported by a declared API. Their positional
  meaning must be explicit and cannot override conflicting supplied identities.
  They do not independently establish a qualified held-out claim.
- Response identity belongs to the fitted model: ordered names, units and any
  selected-response authority must survive retained-state export and application.
  A typed value or mandatory verified execution envelope may own that information.
  New prediction-input metadata must not relabel a model's responses.

### Fitted input compatibility

- Bind ordered feature identity and applicable signal quantity/units to fitted
  state. State what missing authority permits and what it prevents claiming.
  Wavelength units do not establish absorbance, transmittance or intensity units.
- Check compatibility before arithmetic in live reference-input, retained-state,
  generated-code and imported-model paths. A declaration that a transform changes
  units does not waive compatibility checks on its reference inputs.
- Equivalent unit spellings may normalize without changing science. Coordinate
  reordering and physical signal conversion require an explicit, retained mapping
  or operation; do not silently repair incompatible input.
- Record applicable acquisition/instrument assumptions for qualified use without
  fabricating those facts for ordinary exploratory arrays.

### Missingness and numerical meaning

- Define supported missing target cells and optional metadata consistently across
  admission, subsetting, hashing, model construction and serialization. Missing
  values are distinct from invalid nonfinite predictors, rejected observations
  and unavailable retained output. Do not broadly coerce infinity into missingness.
- An unselected missing property must not block a model whose required inputs are
  valid. If a method filters selected missing targets, retain the exclusion receipt.
- Every metric identifies its formula/version, response, units, population,
  denominator and undefined reason. Report response-specific dimensional errors;
  combining different quantities requires an explicit scientific normalization and
  weighting policy. Merely retaining per-response values does not justify an
  additional mixed-unit headline metric.
- Mathematical degeneracy and metric validity must not depend on arbitrary unit
  scale or origin. For a shared affine unit change, R² and regression slope remain
  invariant; dimensional error measures and intercept transform appropriately.
  Treat negligible variation relative to measurement precision as a separate,
  explicitly justified assessment. Direct and pooled evaluation must agree for
  identical observation/prediction pairs, regardless of their partitioning.
- Preserve original historical metric evidence. Label unsupported historical
  aggregates as such; never silently present them under a corrected definition.

### Qualification and ongoing use

Keep executable/released, reproduced, independently evaluated, analytically
qualified, applicability and QC claims distinct. Qualification binds its evidence
and policy to the model, preprocessing, intended population, reference method and
relevant instrument conditions; define changes that invalidate that qualification.

Application results must expose applicability as assessed, outside the supported
domain, or unavailable. Diagnostic methods, limits and their provenance must be
retained; a fitted-state digest proves integrity, not applicability. Uncertainty
records must distinguish aggregate metric uncertainty from individual prediction
intervals and preserve method/version, confidence level, assumptions and reasons
for unavailability through save, export, reimport and application.

For qualified continuous use, bind QC observations, control limits, due status,
instrument maintenance and revalidation to deployment. Warnings or quarantine are
explicit policies; do not silently adjust slope/bias or hide results. Laboratory
sampling independence and reference precision cannot be manufactured by software.
Exploratory execution remains available with accurate, limited claims.

### Boundary acceptance matrix

In addition to the surface matrix above, verify the following independently:

| Boundary | Required adverse case and positive control |
| --- | --- |
| X/Y binding | Shuffled response IDs refuse; aligned IDs preserve numerical results. |
| Fit/apply | Reversed features and incompatible signal units refuse; explicit correct conversion preserves predictions. |
| Missingness | Valid selected response with unrelated missing metadata succeeds; invalid required inputs refuse. |
| Population | Filtering preserves every excluded identity/reason and admitted denominator; no-filter case preserves all rows. |
| Metrics | Unequal-unit responses stay separate; unit transformations and direct/pooled evaluation obey their declared definitions. |
| Persistence | Reopened state preserves model/response identity and qualifications; unsupported historical evidence stays explicitly unsupported. |
| Applicability/QC | Unknown or outside-domain status remains visible; a properly supported control retains its qualified status. |

Review numerical expectations against independent calculations, not just a second
call to the same implementation. A passing shared adapter test does not establish
that every producer and consumer obeys these obligations.

### Portable PLS screening

See [the PLS screening contract](pls-applicability-screening.md) for retained
methods, row identity, unavailable authority and the distinction between global
screening and analytical applicability qualification.

### Individual prediction intervals

See [reference measurements and prediction intervals](prediction-uncertainty.md)
for frozen-pipeline split-conformal calibration, explicit population acceptance,
reference precision, separate sidecar portability and point-only refusal states.
An interval sidecar is integrity-checked evidence, not laboratory qualification
or a publisher-signed model package.

### Intended-use qualification authority

Operational readiness, computed validation criteria, laboratory declarations and
human acceptance must remain distinct. Use the
[analytical qualification contract](analytical-qualification.md) for frozen
application evidence. Never convert a deploy-ready badge, imported digest, or
historical acceptance into a current instrument/population qualification claim.

### Instrument status is time-scoped evidence

[QC and maintenance status](instrument-qc.md) must retain the model, declared
material/lot/reference, configuration, policy, observation/recording times, and
all concurrent reasons. A report-only status must never imply predictions were
held. Later policy changes or review decisions must not rewrite a saved run's
batch-start status, and policy transitions must not erase unacknowledged failures.


## Validation design and interpretation

Scientific validation reports distinguish computational reproduction from
predictive generalization. Hyperparameter tuning fits the complete supervised
pipeline, including feature selection, within each inner-training fold. Recorded
groups stay intact in both inner and outer folds. The standalone nested-CV path
and canonical campaign fold executor must preserve this same separation.

Repeated evaluation retains repeat identity, seeds and folds. Show per-repeat
scores and their spread; never count repeated predictions as additional specimens.
Bootstrap intervals for fixed predictions retain that narrower interpretation.

Independence has three evidence levels: computed comparison of recorded IDs,
operator declarations, and unknown. Computed separation is scoped to matching
namespaces and the recorded roles. It does not authenticate collection history
or establish independent sampling. Reports expose unknown roles and known overlap.

Extend the saved-run summary and campaign verification report, not a parallel
report format. Include saved parameters, population, exclusions, metric formulas
and units, tuning design, selection history and claim limits. Derive figures from
retained observations and predictions. Disclose unavailable or oversized plots;
never silently subsample. No arbitrary RPD thresholds or certification badge.
