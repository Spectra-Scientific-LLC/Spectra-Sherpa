# Validation and Model Application

!!! abstract "Summary"
    Reading validation results and applying a model to new data: metrics, prediction intervals, qualification checks, and what each warning means.

Designing the validation comes first — see
[Designing Validation](validation-design.md) for grouped splits, fold-local
preprocessing, and metric definitions. This page covers reading and applying
the saved result.

## Read the saved validation summary

Select a saved execution in **Report**. Its validation summary identifies the
run, recorded data/target/group selections and saved operation settings. When an
exact train/test split was retained, it also shows the method, seed, development
and test row counts, and any recorded whole-group holdout. Row numbers refer to
the input to that split; they are not a replacement for sample identifiers.
Long row lists are labelled as previews; the retained split output contains the
complete list.

A verified out-of-fold regression evaluation reports its denominator and fold
sizes separately from an external held-out test. If several evaluations exist,
inspect their individual retained results; this summary does not choose one for
you. Calibration and classification results remain available in their original
result views; missing summary evidence does not make their metrics
cross-validation metrics. A selected group column alone does not prove group
separation, and a workflow's preprocessing steps alone do not prove that they
were fitted inside every fold.

The report preview, HTML, Markdown and report JSON preserve the same saved-run
summary. Unavailable evidence is labelled rather than filled from the current
editor. Historical Python/notebook replay is not provided by this report.

### Repeated and grouped validation

The v0.6.0 nested evaluator can use explicit specimen groups at both the outer
evaluation and inner tuning levels. Select grouping deliberately: attached
groups are not consumed by default, and a grouped design never silently falls
back to row-wise folds. The report retains the group source, complete fold
membership, split-plan digest, root seed and per-fold seed derivation.

Validation repeats are separately seeded runs over partitions of the same
dataset. Each repeat retains its own folds, predictions, selected components
and selector stability. The summary reports the mean, sample standard
deviation and range of the per-repeat metrics. These are sensitivity measures,
not confidence intervals, external validation or additional independent
specimens. Do not pass repeated evidence to a single-repeat evaluator or
replace its retained predictions with a flattened array.

The selector-call budget is checked before fitting. It estimates compute and
does not replace the normal execution timeout. If an outer refit has fewer
features after selection, the report keeps both the requested component count
and the effective count used for that fold.

### Retained figures and claim limits

Run reports can explicitly opt in to row-level reference, prediction and
residual values and their figures. Residuals are prediction minus reference;
the report carries formulas, undefined cases and retained target units. Each
repeat receives its own denominator and panel. Above 5,000 rows, figures are
declined without subsampling while numeric evidence remains available.

Recorded specimen or batch lists may be compared when supplied, but that
comparison does not authenticate the register or prove independent sampling.
Keep recorded identity evidence, operator declarations and qualification
decisions as separate parts of the dossier.

Validation estimates whether a model generalizes beyond the samples used to fit it.

!!! note "Junior-user note"
    Start by asking **which samples are being evaluated** and **which samples
    were used to fit the model**. Then check the target units, split or fold
    design, preprocessing scope and denominator. A high-looking score is not
    interpretable until those four items are clear.

## Regression Metrics

Current regression evaluation reports RMSE, MAE, positive prediction bias,
R2, SEP, slope, intercept, and RER. SEP removes the mean residual bias before
estimating the residual standard deviation. Slope and intercept describe the
ordinary least-squares line of predicted values on observed values. RER is the
observed reference range divided by SEP and is undefined when SEP is zero or
cannot be estimated. Multi-response PLS2 results retain one metric set per
named response; Sherpa does not blend quantities with different units into a
single score.

## Classification Metrics

Common classification outputs include confusion matrices, accuracy, sensitivity/recall, specificity where applicable, and per-class summaries.

## Split Design

Random splits are often not enough for spectra. Consider sample grouping,
replicate structure, batches, time order, and instrument changes when
interpreting validation results. When a validation-group column is bound,
random, sequential, and stratified train/test splitting keeps every group
wholly in training or testing. X-space methods that cannot honor group
boundaries refuse rather than silently reverting to row-level splitting.

## Applying Saved Models

When applying a saved model, confirm that the new spectra match the training contract: preprocessing, spectral axis, feature count, units, and target context. A model can produce numbers for incompatible spectra if the data shape matches but the scientific contract does not.

### Compare saved models in a project

The Models project view lists active saved models without an optimization
campaign. Each row identifies its target and units, source dataset,
preprocessing, component count, calibration size, and any exact retained
component-curve statistics. RMSEC and R² describe calibration. RMSECV and Q²
describe the executed development cross-validation for the selected component
count. A blank RMSEP or independent-test count means that this saved-model
receipt does not establish an external result. It does not mean zero error.

The view groups models for numerical comparison only when their target, units,
exact fitted scientific cohort and exclusions, source view, and executed CV split
match. Rows without those receipts remain
inspectable but cannot be ranked. Open a row to inspect its exact saved
diagnostics and ask Sherpa about supported diagnostic evidence. Export the
current table page, or export one model's compact evidence dossier, to retain
model, run, source-view, curve, and split identities alongside the stated gaps.

Deploy-ready records operational readiness. Analytical qualification requires
a separate current, model-bound intended-use assessment and human decision.
Workflow qualification history for a canonical application does not qualify an
ordinary saved model. Changes to the data view, response mapping, fitted
preprocessing, exclusions, or model identity require renewed assessment.
Native PLS artifacts retain fitted specimen IDs to detect validation overlap;
the qualification record retains the external specimen register and intended-use
context. Project exports include model artifacts and source data, so treat them
as data-bearing archives and share them only under the project's data policy.
The qualification screen verifies the currently materialized validation cohort
again before showing or accepting a decision. Observed interval coverage uses
only screened rows with available intervals and is not a population claim.


## Local folder watches

Choose a fitted model, choose a folder, and enable the watch. A local model does
not need a separate Deploy-ready designation or a successful trial prediction.
Settings can be changed while monitoring. Source or model changes receive a new
configuration identity so predictions are not attributed to the wrong model.
Polling-only changes preserve file history and any current processing lease.

**Try a file (optional)** applies the saved model without refitting or marking
the file processed, even while monitoring is enabled. Choose a settled file
inside the folder matching the watch pattern. The check supports files up to
256 MiB. Save its JSON receipt or inspect the retained run for full predictions.
Failed or outdated checks do not prevent activation. They describe that file
and configuration, not the accuracy of predictions on future samples.

Polling uses positive whole seconds; settling uses nonnegative whole seconds.
Scheduling checks once per second; processing time can delay subsequent polls.
Choose timings appropriate to how your instrument finishes writing files.
Missing dependencies, incompatible inputs, and damaged model artifacts still
produce actionable execution errors. Qualification evidence is optional.

A yellow star indicates recorded validation evidence in an imported campaign
package. It does not certify performance on new samples or restrict other models.
## Qualification and prediction intervals

Deploy-ready describes operational readiness, not intended-use acceptance or
regulatory compliance. Qualification needs independent validation and human review
against a previously frozen laboratory policy. Post-hoc thresholds are exploratory.

Prediction intervals require a calibration record for the exact frozen pipeline.
Use distinct specimens with explicit sample IDs and reference values and units;
average repeated measurements first. Calibration specimens must not have been used
to fit or select the model. Declare the intended population, reference method,
independence and exchangeability. The reported level is per-response marginal
coverage, not laboratory qualification. Without a selected record, predictions
are point estimates.

## Instrument QC

QC records inform review while predictions continue. Declared absolute tolerances
are not statistical process control or laboratory certification. Records are
immutable; a policy change does not clear failures. Recovery requires a new passing
control and acknowledgement. Revalidation requires post-maintenance validation
and the current accepted qualification decision.

## Diagnostic review

Diagnostic plots belong to their fitted source run. Selecting an observation
links it across plots and the sample table. A screening flag asks for inspection;
it does not by itself establish a bad measurement or validate predictions.

New PCA/PLS sample reviews require a typed, unique `sample_id` column. Display
labels can change without changing those IDs. If IDs are missing, attach a sample
table with IDs or re-import with typed IDs, then rerun; labels are not promoted
to verified identity. Historical review evidence remains readable, and previously
recorded exclusions can be restored without authorizing new label-based decisions.

New project imports of the built-in Wine, Iris and Breast Cancer tables persist
typed observation IDs through the CSV sample-metadata contract. IDs name the
catalog dataset, its feature/target table revision and a row in that revision.
Separate neutral display labels (`Sample 1`, `Sample 2`, …) are not part of
the ID revision and can change without changing observation identity.
Identical imports retain the same IDs; changed values or row order establish a
different revision. These are catalog observation identities, not evidence of
independent specimens or new acquisitions. This applies only to newly
materialized files: existing imports and saved runs are unchanged. For an older
import without typed IDs, attach a sample table with explicit IDs or import a new
source with typed IDs, then rerun to obtain a new diagnostic review receipt.

New retained PCA/PLS reviews may include the source's display label for GUI
tables and plots. Labels can repeat; selections and decisions still use the
full typed ID. Older receipts without labels remain readable with their exact
IDs, without rewriting history. These GUI labels do not extend Advisor evidence.

Loadings describe variables in a component, not selected-sample T²/Q contributions.
Influence limits use all fitted components, with limits appropriate to calibration
or projected application roles. Classifier contribution bars show additive Q and
signed T² terms. Later dataset or workflow decisions do not change a saved fit.

Selection frequency counts the fraction of outer-fold selections containing each
variable; it is not a loading or a probability of chemical importance. PCA
reconstruction describes predictor-space compression, not response accuracy.

## Reference values

Record the reference method, units and precision used for each response.
Unknown method or precision remains a qualification gap. Replicate counts and
digests document a declaration; review the source measurements and their
specimen mapping before treating precision as verified. Reference precision
does not by itself create prediction intervals.
