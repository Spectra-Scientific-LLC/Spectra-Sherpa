# Designing Validation

Validation estimates how a model performs on samples it has not seen. For
spectra, the design of the validation matters more than the number of decimal
places in the metric: a poorly designed split can make a useless model look
excellent.

## Why random splits mislead for spectra

Spectral datasets are rarely rows of independent measurements. They contain:

- **replicates** — repeated spectra of the same specimen
- **batches and lots** — groups measured together or produced together
- **time order** — drift, lamp aging, and process trends
- **instruments** — the same specimens measured on different units

A random split freely mixes these structures across training and test. Two
replicate spectra of one specimen are highly correlated; putting one in
training and one in test makes prediction artificially easy and inflates your
estimated performance. This is the single most common source of over-optimistic
chemometrics results.

## Choose the design that matches your question

| Question | Design | What it estimates |
| --- | --- | --- |
| Performance on new replicates of the same specimens | Random cross-validation | Repeatability within the measured population (usually over-optimistic for new samples) |
| Performance on new specimens | Grouped CV or grouped holdout, with specimen as group | Generalization to unseen samples |
| Performance on future batches or time periods | Time-ordered or batch-holdout split | Robustness to drift |
| Model + settings selection (components, variables, preprocessing) | Nested CV, or grouped development + one final holdout | An honest estimate after tuning |
| Prediction on a new instrument | Instrument-holdout plus calibration transfer | Transferability |

Rules of thumb:

- **Declare groups before splitting.** In SpectraSherpa, bind the
  validation-group column (specimen, batch, or block identity) and the split
  keeps complete groups together, recording their identities in the split
  receipt.
- **Tune on development data only.** Select component counts, intervals, and
  preprocessing inside cross-validation on the training partition. Touch the
  final holdout exactly once.
- **Fit learned preprocessing inside folds.** MSC, OSC, autoscaling, and any
  fitted transform must be re-estimated from each fold's training rows.
  A transform fitted on all rows leaks test information into training.
- **Refit at the end.** After selection, refit on all development data and
  confirm once on the untouched holdout.

## What SpectraSherpa enforces

- Random, stratified, and sequential splits consume the bound validation-group
  authority and hold complete groups out; the receipt names the held-out
  groups.
- Observation-level Kennard–Stone, DUPLEX, and SPXY **refuse grouped input**
  rather than inventing an unqualified group-distance method.
- Local evaluator nodes score the prediction and reference arrays supplied to
  them; they do not independently verify whether those predictions came from
  training, out-of-fold, or held-out samples. Treat a local evaluator score as
  validation evidence only when the retained run and split lineage establish
  the evaluated cohort. Managed fold evaluation has its own custody checks.
- A saved holdout score is excluded from optimization seeding when a fitted
  transform was learned from all rows before the split.

These checks are structural. They cannot prove your groups are scientifically
the right ones — that judgment is still yours.

## Metric definitions used in this release

- **Bias** = mean of (predicted − observed). Sign convention matters when
  comparing with other software.
- **SEP** = spread of residuals after removing the mean bias; the bias-
  corrected "typical error".
- **RMSEP / RMSECV** = root-mean-square prediction error on held-out or
  out-of-fold predictions.
- **Slope / intercept** = ordinary least-squares line of predicted on
  observed; slope away from 1 indicates compression or expansion of the
  prediction range.
- **RER** = observed reference range divided by SEP; undefined when SEP is
  zero or cannot be estimated.
- **Classification** = confusion matrix, per-class sensitivity and
  specificity; SIMCA additionally reports unassigned and multiple-acceptance
  rates, and specificity is unavailable without a representative challenge
  population.

## A minimal checklist before quoting a number

1. Are replicates and specimens grouped correctly, and does the split receipt
   show them held out as complete groups?
2. Was every learned transform fitted inside the training folds?
3. Was the final holdout touched only once, after all tuning?
4. Does the validation target range cover the intended use range?
5. Are the metrics reported per response, in the response's own units?

## Further reading

- K. H. Esbensen and P. Geladi, *Principles of Proper Validation: use and
  abuse of re-sampling for validation*, Journal of Chemometrics 24 (2010)
  168–187.
- F. Westad and F. Marini, *Validation of chemometric models — a tutorial*,
  Analytica Chimica Acta 893 (2015) 14–24.
- H. Martens and T. Næs, *Multivariate Calibration*, Wiley, 1989 — the
  classical treatment of validation for spectroscopic calibration.
- ASTM E1655, *Standard Practices for Infrared Multivariate Quantitative
  Analysis* — terminology and practice for RMSEP, bias, and validation in
  regulated environments.
## Component selection

The model's component parameter selects the fitted PC or LV count. A component
curve, when eligible, compares candidate counts by cross-validation; it is not
an independent test-set assessment. Keep held-out samples outside model and
component selection.

Execution uses bound group identities when available and otherwise eligible row
folds. Repeated measurements from the same specimen belong in the same group.
The preview cannot establish independent specimen identity. Check the retained
run for exact fold membership, preprocessing eligibility, and any reason that
validation was unavailable. A PCA model alone does not create a test partition.

The saved component count remains a workflow parameter: curve suggestions do not
refit the model automatically. Scaling and model fitting occur within each training
fold for the canonical component-validation paths. Inspect retained diagnostics
for the actual eligible design and any exclusions.
