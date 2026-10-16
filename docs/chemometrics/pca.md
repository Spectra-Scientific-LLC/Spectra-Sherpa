# PCA and Exploratory Analysis

Principal Component Analysis reduces a spectral matrix into latent variables that explain major sources of variation. It is the right first model for almost every new spectral dataset: it needs no labels, no targets, and no validation design, yet it exposes most of the problems that would quietly sabotage a later calibration.

## Use PCA For

- checking sample clustering
- spotting outliers
- assessing preprocessing
- inspecting loadings
- finding instrument or batch drift
- deciding whether calibration or classification is plausible

## When PCA Is Not Enough

- You have a quantitative target and need a number: use [PLS](pls.md). PCA ignores the target entirely.
- You need class membership decisions: use [classification](classification.md) or [SIMCA QC](simca.md).
- Two clusters in a score plot are not proof of two chemical classes — PCA shows variance, and variance can come from instrument drift, path length, or sample handling rather than chemistry.

## Outputs to Inspect

- **Scores**: sample positions in PC space. Clustering, gradients, and outliers live here.
- **Loadings**: spectral variables contributing to each PC. A loading that looks like noise or a baseline artifact tells you the PC models an artifact, not chemistry.
- **Explained variance / scree**: how much variance each PC captures.
- **Hotelling T² and Q residuals**: T² measures distance *inside* the model plane (an unusual but explained sample); Q measures distance *to* the plane (a sample with structure the model does not capture). A high-Q sample is often the more alarming one — its spectrum does not look like the others at all.

## Choosing the Number of Components

- Read the scree plot: keep components up to the elbow, and check the cumulative explained variance.
- Inspect the last component you plan to keep: if its loadings look like noise, you have gone too far.
- More components do not hurt exploration, but any downstream model (SIMCA class limits, outlier thresholds) inherits your choice — record why you picked it.

## Scaling

Native PCA mean-centers by default and uses a deterministic full-SVD fit. Mean-centering alone is usually right for spectra, because all channels share the same physical units. Autoscaling (unit variance) is appropriate when features have different magnitudes or units — for example mixed spectral and physical measurements — but it amplifies noisy, low-signal regions of a spectrum, so judge it on the loadings.

## Practical Interpretation

Scores show sample relationships. Loadings explain which spectral regions drive those relationships. A good PCA review looks at both, not only the score plot.

In the Workbench, use **Color by metadata** and **Symbol by metadata** to switch
among available sample-table fields such as specimen, block, operator, batch,
or an author-supplied status. The styling changes only the graph; it does not
refit PCA or change scores. Missing or misaligned sample identity is refused
rather than guessed from filenames or row order.

## Further reading

- I. T. Jolliffe, *Principal Component Analysis*, 2nd ed., Springer, 2002 — the standard reference.
- R. Bro and A. K. Smilde, *Principal component analysis*, Analytical Methods 6 (2014) 2812–2831 — a modern, spectroscopy-oriented tutorial.
- J. E. Jackson, *A User's Guide to Principal Components*, Wiley, 1991 — strong on T² and Q diagnostics.
