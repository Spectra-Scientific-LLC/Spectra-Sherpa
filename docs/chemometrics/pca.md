# PCA and Exploratory Analysis

Principal Component Analysis reduces a spectral matrix into latent variables that explain major sources of variation.

## Use PCA For

- checking sample clustering
- spotting outliers
- assessing preprocessing
- inspecting loadings
- finding instrument or batch drift
- deciding whether calibration or classification is plausible

## Outputs to Inspect

- scores: sample positions in PC space
- loadings: spectral variables contributing to each PC
- explained variance / scree
- Hotelling T2 and Q residual diagnostics when available

## Practical Interpretation

Scores show sample relationships. Loadings explain which spectral regions drive those relationships. A good PCA review looks at both, not only the score plot.
