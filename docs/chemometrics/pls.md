# PLS Calibration

Partial Least Squares regression models the relationship between spectra and quantitative targets.

## Use PLS For

- concentration calibration
- property prediction
- multi-target regression
- comparing full-spectrum and selected-region models

## Outputs to Inspect

- predicted vs measured values
- RMSEP, SEP, bias, R2, and CV metrics
- CV predictions when available
- VIP scores
- regression coefficients by spectral variable
- X and Y scores/loadings

## Validation Caution

Calibration metrics are only meaningful when the target values are aligned to the correct spectra and validation respects sample structure. Replicates, time series, and batches can inflate random cross-validation if they leak across folds.
