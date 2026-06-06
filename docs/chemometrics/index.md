# Chemometrics Overview

SpectraSherpa focuses on practical chemometrics workflows for spectra.

## Main Questions

- What structure is visible in my spectra? Use PCA.
- Can spectra predict a concentration or property? Use PLS regression.
- Can spectra assign a known class? Use KNN, PLS-DA, or SIMCA.
- Is a sample consistent with a reference class? Use SIMCA QC.
- Can overlapping mixture components be resolved? Use MCR-ALS or SIMPLISMA-style tools.
- Which peaks or regions matter? Use peak finding, variable selection, VIP, or library comparison.

## Start With PCA

For most new datasets, PCA is the first serious model. It reveals clustering, outliers, drift, preprocessing effects, and whether labels or targets plausibly align with spectral variation.
