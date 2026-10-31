# Compare results and review a final model

!!! abstract "Summary"
    Compare runs fairly and decide when a model is ready to promote: same data, same folds, recorded evidence. Works locally without an account.

This journey works locally without an account, provider key or Advisor. The
initial common-evaluation implementation supports retained PLS regression
recipes. Other retained results remain inspectable; missing evidence is shown
explicitly.

## Start with a saved run

1. Build and execute the workflow with the intended development samples.
2. Open **Runs → History → Inspect**. Check the response, units, split and fitted
   artifact. Unsaved workflow edits do not change the saved run.
3. Optionally select two saved runs in History and choose **Compare**. The
   workflow canvas's **Compare runs** shortcut leads to the same workspace.

Comparison and robustness are optional development tools. A single model does
not need a competitor to be reviewed for use. External candidate providers may
link into this workspace; their origin is retained and they do not become
ordinary run IDs.

## Read the comparison workspace

**Summary** retains the source, response, units and population of each result.
**Results** groups measures, plots and specimen values by evaluation role.
**Validation** contains methodology and optional common-evaluation controls.
Use the section arrows to collapse details without losing them.

The result tables use the same run names and **Delta (2 − 1)** convention.
Metrics align by their retained scientific role, not by the name of the node
that produced them. A held-out RMSEP is never paired with a training RMSECV.
Deltas appear only when the evidence qualifies that pair. **Workflow details
and recorded measures** preserves the original node-specific values and settings;
those descriptive values alone do not prove a paired improvement.

The descriptive **Results** matrix inside **Workflow details and recorded
measures** currently matches stored metric keys literally. A run with one
metric source may show `RMSE`, while a run with several sources shows
`eval 1 · RMSE` and `training cv · RMSE`. These prefixes identify producing
nodes; they do not identify different metric formulas. A dash can therefore
mean that the stored keys differ, rather than that an evaluation is absent.
Use the role-qualified evaluation sections and their population checks to
assess comparability. Keep held-out RMSEP separate from training RMSECV;
matching metric names alone is insufficient.

## Read each result in its own role

| Section | Meaning | What it does not establish |
| --- | --- | --- |
| Calibration: RMSEC and calibration R² | Fit to the calibration specimens | Predictive superiority |
| Training CV: RMSECV and OOF Q² | Predictions made with each validation fold excluded from fitting | Independent external validation |
| Held-out validation: RMSEP, bias and predictive R² | Frozen-model predictions on a retained population excluded from fitting | That the specimens have never influenced development |
| Outlier challenge | Detection, misses and prediction consequences for declared unusual specimens | Ordinary population accuracy |

Residual plots use **reference minus prediction**. Compare units and response
identity before interpreting a difference. A missing CV receipt does not hide
an otherwise valid held-out comparison. Unknown population counts are not zero.

**Comparable** means the relevant retained population, response and evaluation
conditions match. **Descriptive only** means you may inspect values but cannot
claim a paired improvement. **Common evaluation needed** names a mismatch.
**Unavailable** means this comparison role could not be qualified. Read its
reason: evidence may be missing or invalid, or the evaluation family may not
yet be supported. Classification evaluation ranking is not currently supported;
the saved classification results remain available for individual inspection.
An unsupported comparison does not mean those runs lack recorded metrics, and
inspecting their metrics does not establish a qualified ranking.

Some externally supplied evaluations retain verified aggregate scores and
paired partition receipts, but no individual predictions. They can support an
aggregate comparison when those exact receipts match; they cannot supply
sample plots. Reproduce and execute a recipe to obtain additional run evidence.

## Optional common evaluation and robustness

In a two-run comparison, choose each PLS output and explicitly choose which
saved development population to use. Review the protocol before starting it.
The two recipes use identical partitions and refit learned preprocessing within
each fold. Declared held-out rows stay outside training and CV. Each recipe is
also fitted once on the full declared development population. That frozen fit
produces separate calibration and held-out predictions; it does not use held-out
responses to fit or select anything. Those two sections stay the same when you
switch between CV repetitions. No held-out section is invented for an unsplit
source. These evaluation fits are evidence, not deploy-ready artifacts.

Use one repetition for a common CV assessment. Use multiple distinct repeated
partitions for a robustness check of two already selected recipes. The reported
differences describe those paired development assessments, not an unbiased
estimate of the complete model-selection procedure. If selection itself is
being evaluated, use a suitably designed nested-validation protocol.

Grouped evaluation requires enough distinct groups for the requested folds and
enough training rows for both models in every fold. The current grouped splitter
supports a single grouped assessment; repeated grouped partitions are refused
rather than silently substituting ungrouped folds. Repeated identical partitions
are not additional robustness evidence.

Repeated `specimen_id`, `subject_id` or `patient_id` values require an explicit
independent **Groups** binding in My Dataset, followed by a new saved workflow
run. The grouping must keep each specimen together. Paired evaluation also
refuses a historical train/test split that divides these declared groups; it
does not repair or relabel old evidence. These checks apply to retained recipes
with and without a holdout, including older sources without typed target metadata.

**Run evaluation** creates a separate saved evaluation. Source runs are not
rewritten. Use **Open saved evaluation** to inspect completed repetitions and
download the exact record later. Cancellation is explicit. An interrupted job
is incomplete; restart it as a new evaluation rather than assuming a resumable
checkpoint. An evaluation-only record is not a deployable model.

## Review the exact fitted model

From **Inspect → Review for promotion**, choose the produced artifact if the run
made several models. The same review is available in **Runs → Models**, including
imported fitted applications.

1. Verify the artifact and fitted population.
2. Reuse the existing fitted artifact if it matches the selected recipe and
   intended development population. A workflow execution may already have fitted
   all training samples. There is no compulsory second fit at promotion.
3. If the recipe or fitting population must change, choose **Open workflow to fit
   a new artifact**, explicitly execute it, and review that new artifact. Opening
   a sheet never executes it automatically. A frozen imported application sheet
   applies existing state; use a training recipe to produce new fitted state.
4. Choose intended use and a qualification protocol. Exploratory use makes no
   independent-validation claim. An accepted external-validation protocol requires
   a current dossier bound to this exact artifact and intended use.
5. Record the rationale and choose **Confirm deploy-ready**. This records readiness;
   it neither fits a model nor starts deployment.

Validate the frozen artifact on a named validation population when your intended
claim requires it. Declare the reference method, units, intended population,
acceptance limits and chronology before looking at results. Limits are laboratory
decisions; the software does not manufacture universal thresholds. Known specimen
overlap, selection use and available validation results are disclosed from the
retained evidence. Changing a display name does not change an evidence identity.
Missing history does not prove that data was unseen.

## Optional outlier challenge

Use a separate named view of deliberately unusual specimens, with their outlier
type and label basis declared. The frozen model's existing applicability limits
are used; this action does not tune thresholds or refit. Inspect detected,
missed and unavailable counts and any prediction errors separately from ordinary
validation. Where an imported application lacks fitting specimen identities,
overlap remains unknown rather than being claimed absent.

## Scientific basis and limits

The **Scientific basis** disclosures summarize the same general guidance used by
the optional interpretation extension. No LLM is needed to read or follow it.

The reviewed ASTM E1655 passages distinguish development CV (§15.3.6) from
separate validation of the resulting calibration (§§18.1–18.3, 25.1.5.1), and
require attention to revalidation after a model update (§24.2). Section 18.2.5
describes the value, when feasible, of a separate outlier validation set to
investigate detection and consequences. These passages do not prescribe our
buttons, a search campaign, or repeated random seeds. Check section numbering
against your licensed edition; this guide does not claim ASTM conformity or
distribute the standard.

Eigenvector's [cross-validation guidance](https://www.eigenvectordocs.com/index.php?title=Using_Cross-Validation)
and [variable-selection guidance](https://www.eigenvectordocs.com/index.php?title=Variable_Selection)
support separating calibration fit, CV and testing, and avoiding replicate or
selection leakage. General guidance helps design an assessment; it cannot
replace the scientist's knowledge of sampling, laboratory methods and intended use.

## API compatibility

`POST /runs/compare-evidence` owns scientific compatibility decisions. The older
project and workflow `/compare` routes remain deprecated adapters for existing
clients: their `scientific_comparison` field comes from that same authority,
while historical scalar matrices remain available for descriptive inspection.
`POST /models/compare` is an explicit frozen-model application operation. Its
prediction disagreements do not establish CV comparability, independent
validation or readiness.


### Reuse the final fit, or explicitly fit a changed workflow

Review for promotion reuses the exact fitted artifact. When its specimen register matches the retained training split, the review states that all declared development samples are already fitted and displays the held-out count. A fitted sample count alone does not establish complete population coverage.

For a deliberate recipe or population change, choose **Open workflow to prepare final fit**. The sheet displays the verified source artifact and Run as context, but its current editable recipe is not a pinned replay. Review data selection, exclusions, preprocessing and components, save, and explicitly click **Run**. Inspect the resulting new Run and artifact before reviewing it for promotion. Opening the sheet neither fits a model nor adds held-out or outlier-challenge samples; previous validation does not automatically qualify a new artifact.

A canonical application's sheet applies frozen state. To change that fit, return to its original training recipe rather than treating the application sheet as a training workflow.
