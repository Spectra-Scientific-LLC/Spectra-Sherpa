# Selection and Validation Nodes

Selection and validation nodes help choose variables, split samples, and estimate model reliability.

## Sample Partitioning

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Sample Partition (`selection.sample_partition`) | You need train/test splits designed for chemometrics rather than only random shuffling. | `X: Array2D`; `y: TargetMatrix?` | `X_train`; `X_test`; `y_train`; `y_test`; `train_indices`; `test_indices` | `method`; `test_size`; `metric`; `n_pcs`; `random_seed`. Methods include chemometric designs such as Kennard-Stone-style selection where available. |

## Variable Selection

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Variable Selection (`selection.variable_select`) | Select wavelengths by VIP, coefficients, spectral region, peaks, or an incoming mask. | `X: Array2D`; `model: FittedModel?`; `mask: Array1D?` | `X_selected`; `mask`; `scores` | `method`; `region_start`; `region_end`; `peak_prominence`; `peak_half_window`; `threshold`; `invert`. |
| Interval PLS (`selection.ipls`) | Search spectral intervals and keep the interval set with best cross-validated PLS performance. | `X: SpectralDataset`; `y: TargetMatrix` | `X_selected`; `mask`; `scores` | `n_intervals`; `n_components`; `cv_folds`; `n_best`. |
| CARS (`selection.cars`) | Perform competitive adaptive reweighted sampling for wavelength selection. | `X: Array2D`; `y: TargetMatrix` | `X_selected`; `mask`; `scores` | `n_iterations`; `n_components`; `cv_folds`. |
| SPA (`selection.spa`) | Select variables with low collinearity using successive projections. | `X: Array2D`; `y: TargetMatrix?` | `X_selected`; `mask`; `scores` | `n_select`. |
| UVE (`selection.uve`) | Remove uninformative variables using Monte Carlo stability benchmarking. | `X: Array2D`; `y: TargetMatrix` | `X_selected`; `mask`; `scores` | `n_components`; `n_resamples`; `test_fraction`. |
| Stability Selection (`selection.stability`) | Keep variables that survive repeated subsampling. | `X: Array2D`; `y: TargetMatrix` | `X_selected`; `mask`; `scores` | `base_method`; `base_threshold`; `stability_threshold`; `n_bootstrap`; `n_components`; `subsample_fraction`. |
| Compare Feature Selections (`selection.compare`) | Compare multiple masks and build a consensus selection. | `X`; `mask_1`; `mask_2`; optional `mask_3`; optional `mask_4` | `X_consensus`; `consensus_mask`; `report` | `consensus_threshold`. |
| Audit Feature Selection (`selection.audit`) | Inspect and document selection decisions before reporting or model handoff. | `X: Array2D` | `X_out`; `audit` | `include_scores`. |

## Validation and Diagnostics

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Evaluate Nested CV Selection (`selection.nested_cv`) | Estimate performance when variable selection happens inside each CV fold. | `X: Array2D`; `y: TargetMatrix?` | `cv_metrics`; `y_pred`; `stability` | `selection_method`; `n_components`; `cv_folds`; `vip_threshold`; `coef_threshold`. |
| Evaluate by Cross-Validation (`diagnostics.cross_validation`) | Compute CV metrics from true and predicted values. | `y_true`; `y_pred` | `cv_metrics`; `predictions`; `plots`; `model` | `cv_folds`; `cv_method`; `task_type`. |
| Evaluate Holdout Set (`diagnostics.holdout_evaluation`) | Compute final test-set metrics from held-out predictions. | `y_true`; `y_pred`; optional context and training predictions | `metrics`; `visualization`; `predictions` | `task_type` (`regression` or `classification`). |
| Detect Outliers (`diagnostics.outliers`) | Flag PCA-model outliers by Hotelling T² and Q/SPE residuals. | PCA/model output | `flags`; `T2`; `Q`; `model` | `confidence_level`. Connect directly to PCA model output when possible. |
| Statistics (`stats.summary`) | Summarize a dataset, model output, metrics dictionary, or plot payload. | `default: Any` | `statistics: ValidationResult` | `compute_outliers`; `outlier_threshold`; `max_samples`. |

## Interpretation

Selection can improve interpretability, but it can also overfit. Prefer nested validation or a true holdout when variable selection influences the final model. A variable-selection method that sees the full dataset before cross-validation will usually make the CV result too optimistic.
