# Validation and Model Application

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
