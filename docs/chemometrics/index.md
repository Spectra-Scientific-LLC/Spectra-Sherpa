# Chemometrics Overview

!!! abstract "Summary"
    A practical map of the chemometrics in SpectraSherpa — what each method family answers and which page explains it. New to chemometrics? Do [Your First Calibration](../onboarding/first-calibration.md) first.

SpectraSherpa focuses on practical chemometrics workflows for spectra. Your First
Calibration takes one dataset through one PCA, one validated PLS model, and one
report.

## Main Questions

- What structure is visible in my spectra? Use [PCA](pca.md).
- Can spectra predict a concentration or property? Use [PLS regression](pls.md).
- Can spectra assign a known class? Use [KNN, PLS-DA, or SIMCA](classification.md).
- Is a sample consistent with a reference class? Use [SIMCA QC](simca.md).
- Can overlapping mixture components be resolved? Use [MCR-ALS](mcr-als.md) or SIMPLISMA-style tools.
- Which peaks or regions matter? Use peak finding, variable selection, VIP, or library comparison.
- Is my data genuinely multiway (e.g., excitation–emission or image cubes)? [PARAFAC](../nodes/exploratory.md) is available as a native, expert-level node for explicitly modeled rank-3–6 data; it has no guided starter in this release.
- How do I prove the model works on new samples? Start with [Designing Validation](validation-design.md).

## Start With PCA

For most new datasets, PCA is the first serious model. It reveals clustering, outliers, drift, preprocessing effects, and whether labels or targets plausibly align with spectral variation.

## Validate Before You Believe

Every quantitative claim in chemometrics stands or falls on its validation
design. Before quoting an RMSEP or an accuracy, read
[Designing Validation](validation-design.md) — it covers grouped splits,
fold-local preprocessing, nested selection, and the metric definitions this
release uses.
