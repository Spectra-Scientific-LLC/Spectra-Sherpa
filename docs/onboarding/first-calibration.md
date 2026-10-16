# Your First Calibration

This walkthrough takes you from a downloaded teaching dataset to a validated
PLS calibration and a shareable report. It uses the **Corn NIR** dataset from
Eigenvector Research: 80 corn specimens measured on three NIR spectrometers
(M5, MP5, MP6) with four reference properties — Moisture, Oil, Protein, and
Starch. Everything below also applies to your own spectra once you are
comfortable with the path.

Budget about 30 minutes.

## 1. Get the data

SpectraSherpa does not download third-party datasets for you. Open **Data >
Import > Reference Datasets**, download the Corn archive independently from
the [provider's catalog](https://eigenvector.com/resources/data-sets/), select
the matching reference entry, then choose **Import downloaded file**.
SpectraSherpa verifies the file's registered size and
SHA-256 before admitting it, so you know the bytes are exactly what the
qualification record describes.

One Corn archive gives you three aligned instrument views of the same 80
specimens. The M5 view is selected for display initially; no property is
pre-selected as a target.

## 2. Choose a target and inspect

In **My Dataset**, focus the Corn package and select **Moisture** as the
target (the other three properties remain available for later analyses).
Before modeling, confirm:

- the feature axis is in the expected units and direction
- 80 samples are present, with sample identities attached
- the target column has plausible values and units

If anything looks misaligned here, fix it now — a calibration can only be as
good as its target alignment.

## 3. Run PCA before any calibration

Choose **Next: Workflow**, open **Analysis Starter**, and select **PCA
Exploration & Outlier Diagnostics** with your retained Corn selection. PCA
answers "is this dataset coherent?" before you invest in calibration:

- **Scores**: do samples cluster by instrument view, batch, or lot? Strong
  instrument clustering tells you calibration transfer may matter later.
- **Loadings**: do the influential regions look like real corn NIR bands
  (O–H combination and overtone regions for moisture), not noise or edges?
- **Hotelling T² and Q residuals**: flag candidate outliers. Mask a suspected
  outlier rather than deleting it — you can restore it later.

Inspect identity and alignment problems before interpreting a PLS calibration.

## 4. Build the PLS calibration

Return to **My Dataset**, keep the same Corn view selected, choose **Moisture**
as the target, and then use **Next: Workflow** and **Analysis Starter** to open
**PLS Calibration**. The starter must show the retained dataset and target
binding before you use it.

- **Preprocessing**: for NIR scattering data, SNV or MSC is a defensible first
  choice; a Savitzky–Golay first derivative is the common alternative. Change
  one thing at a time so you can attribute improvements.
- **Components**: start conservatively (2–5) and let validation choose. The
  training-fit error always decreases with more components; that is not
  evidence of predictive skill.
- **What to inspect**: predicted-vs-measured plot (slope bias, curvature),
  VIP scores and regression coefficients (chemically plausible regions?),
  residuals (do errors concentrate at range edges or in one batch?).

## 5. Validate honestly

Use this protocol for the current Corn M5 calibration:

1. For the single Corn M5 view, there is one spectrum per specimen: leave
   grouping unset unless you have a real batch, specimen, or other shared identity
   that must stay together. A unique row identifier alone does not require grouping.
2. For replicates or other related rows, bind the true group identity and use
   a grouped holdout or grouped cross-validation design — SpectraSherpa
   keeps complete groups together and records exactly which groups were held
   out in the split receipt.
3. Retain the starter's 25% test holdout: 60 training specimens and 20 test
   specimens. Compare candidates using five-fold CV on the same 60 training
   specimens and folds; keep the 20 test specimens outside model selection.
4. Ensure preprocessing that learns from data (MSC, OSC, autoscaling) is
   fitted inside each training fold, not once on all rows.
5. After selecting the recipe, inspect the reserved test population separately.
   Report development RMSECV and held-out RMSEP with their populations and
   declared target units. If units are absent, report **target units not declared**.

The Optimize guide's historical 0.2340 → 0.0549 figures are RMSECV from
all-data development CV on 80 specimens, with target units not declared in the
historical evidence. They are not scores for current training-only CV on 60
specimens and do not establish independent test performance. See
[Optimize a Saved Result](../workflows/optimize-saved-result.md).

Read [Designing Validation](../chemometrics/validation-design.md) for how to
choose between random, grouped, and nested designs, and why row-level
Kennard–Stone-style splits refuse grouped input.

## 6. Read the metrics

- **RMSECV / RMSEP** — typical prediction error, in target units. Compare it
  against the reference method's reproducibility, not against zero.
- **Bias** — mean of (predicted − observed). Near zero is expected in CV;
  large bias in a holdout means systematic offset.
- **SEP** — bias-corrected spread of errors; the honest "how wrong am I
  typically" number.
- **R²** — fraction of target variance explained; meaningless without the
  design that produced it.
- **RER** — reference range divided by SEP; a rough screening ratio for
  whether the model separates the observed range adequately.

Definitions and cautions are in
[Validation and Model Application](../chemometrics/validation-application.md).

## 7. Report and save

Open **Report**, toggle the sections you want a reviewer to see, and export
PDF, HTML, Markdown, or JSON. Save the fitted model as an artifact only after
you would be comfortable defending the validation design in a review.

## The same journey from Python

The SDK runs the identical node registry. A complete, deterministic PLS
calibration on synthetic data ships as an example:

```bash
python -m spectra_sherpa.examples.pls_calibration
```

It fits two-component PLS on a labeled synthetic mixture and prints the model
summary, calibration RMSE and R², and the fitted-state digest. See
[Canonical Workflows from Python](python-canonical-workflows.md) for the
save/reopen and iPLS variants.

## Common first-time pitfalls

- **Replicates leaked across folds** — random CV on replicate spectra flatters
  the model. Bind groups first.
- **Preprocessing fitted on all rows** — learn transforms inside folds when
  the model is meant to predict.
- **Too many components** — pick the count from validation, not from training
  fit.
- **Trusting VIP as chemistry** — VIP ranks influence; it is not a band
  assignment.
- **Mismatched axes at prediction time** — a saved model checks feature
  identity, units, and quantity; align new data explicitly rather than hoping
  the shapes match.
