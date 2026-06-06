# Optional SpectroChemPy Nodes

SpectroChemPy support is optional.

```bash
pip install "spectra-sherpa[scp]"
```

## What It Enables

The extra enables SpectroChemPy-backed example datasets, readers, and selected spectral-analysis nodes. It is especially relevant for spectroscopy-native files and algorithms where SpectroChemPy provides mature coordinate-aware handling.

## Nodes That Currently Require SpectroChemPy

| Node | Why It Needs the Extra | Main Inputs | Main Outputs | Main Configuration |
| --- | --- | --- | --- | --- |
| Load Group (`data.load_group`) | Uses SpectroChemPy readers and coordinate handling for grouped native spectroscopy files. | none | grouped spectral dataset | `folder_path`; `pattern`; `recursive`; `sort_by`; `validate_axes`. |
| Baseline Rubberband (`baseline.rubberband`) | Uses SpectroChemPy's rubberband baseline implementation. | `SpectralDataset` | corrected spectral dataset | `ranges`. |
| OSC Filter (`preprocess.osc`) | Uses SpectroChemPy-backed OSC behavior. | `X`; optional `y` | filtered spectral dataset | `n_components`; `tol`; `max_iter`. |
| PCA (`model.pca`) | Uses SpectroChemPy PCA behavior and model structure. | `Array2D` | scores, loadings, explained variance, model | `n_components`; `standardized`; `scaled`. |
| PLS Regression (`model.pls`) | Uses SpectroChemPy PLS behavior and exported calibration structure. | `X`; optional `y` | model, scores, loadings, CV predictions, VIP, coefficients | `n_components`; `scale`; `cv_method`; `cv_folds`. |
| PLS-DA (`classification.plsda`) | Uses PLS machinery for latent-variable classification. | `X`; optional class labels | model, predictions, probabilities, scores, metrics | `n_components`; `scale`; `cv_folds`. |
| SIMCA (`classification.simca`) | Uses class-wise PCA/SIMCA model behavior. | `X`; optional class labels | model, class assignment, distances, confusion matrix, plots | `n_components`; `confidence_level`; `critical_limits_method`; `cv_folds`. |
| MCR-ALS (`model.mcr_als`) | Uses constrained curve-resolution support. | `SpectralDataset` | concentration profiles, pure spectra, residuals, model | `n_components`; non-negativity flags; `max_iter`; `tol`. |
| EFA (`model.efa`) | Uses Evolving Factor Analysis support. | `SpectralDataset` | forward/backward eigenvalues, model | `n_components`. |
| SIMPLISMA (`model.simplisma`) | Uses purity-maximization component estimation. | `SpectralDataset` | concentrations, spectra, purity values, model | `n_components`; `tol`; `noise`. |

If the extra is missing, these nodes should fail early with the install message rather than fail deep in workflow execution.

## Why Optional

Keeping SpectroChemPy optional preserves a clean license and dependency boundary. Base SpectraSherpa remains installable without it, while users who need those readers and algorithms can opt in explicitly.

## User-Facing Expectation

The app should disclose when a file format or node requires the extra and should fail early with a clear installation message if the extra is missing.
