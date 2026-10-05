# Selection and Validation Nodes

Selection and validation nodes help choose variables, split samples, and estimate model reliability.

## Sample Partitioning

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Train/Test Split (`data.train_test_split`) | You need one explicit statistical or chemometric calibration/test design. | `X: SpectralDataset`; `y: TargetMatrix?` | `X_train`; `X_test`; `y_train`; `y_test`; `train_indices`; `test_indices` | `split_method`; `test_size`; `distance_metric`; `n_components`; `random_seed`, with method-specific closure. |

## Variable Selection

### Explicit feature engineering

**Select Columns** (`selection.select_columns`) keeps or excludes exact feature names from a SpectralDataset. Run its upstream node to populate the searchable column multi-select. Selection preserves the input column order, sample identities, target values, units, and missing values. Selecting no columns in **keep** mode is an error; in **exclude** mode it keeps every column. Unnamed features use one-based names such as `Column 1`.

**Merge Features** (`data.merge_features`) appends an **Additional Features** dataset to a **Base Dataset**. The base controls row order, sample metadata, and targets. The default join uses unique sample labels; `sample_index` instead uses retained sample-axis coordinates, not the current row positions or equal row counts. Both inputs must contain exactly the same unique sample identities. Reordered rows are aligned; unmatched/duplicate identities, conflicting targets, and conflicting inclusion masks are rejected.

For peak-feature engineering, connect Normalize to Merge Features' **Base Dataset**, Peak Finding's **Per-spectrum Peak Matrix** to Select Columns, and Select Columns to **Additional Features**. Connect **Merged Features** to Train/Test Split. Output names are prefixed `base::` and `added::` to prevent collisions. The output has a generic named feature axis, while original coordinate axes, block provenance and individual column units remain in metadata. Data View's **Columns** range selector lets you inspect appended columns beyond the first 50.

Neither node scales blocks or imputes missing values. Guide magnitudes remain measured values even when a peak is not detected; detected-peak measurements can remain missing. Choose a downstream method that supports your missing-value policy. Consider block weighting/scaling deliberately: these operations do not imply improved prediction, and distance-based splitting can change when features are appended.

Peak locations specified independently from chemical knowledge do not learn from held-out spectra. By contrast, consensus positions estimated from all input spectra are data-derived; use training-only estimation and fixed application when evaluating an inductive model. These two nodes select and combine already-computed features; they do not change Peak Finding's consensus-estimation procedure.

### Model-based selection

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Variable Selection (`selection.variable_select`) | Select wavelengths by VIP, coefficients, spectral region, peaks, or an incoming mask. | `X: Array2D`; `model: FittedModel?`; `mask: Array1D?` | `X_selected`; `mask`; `scores` | `method`; `region_start`; `region_end`; `peak_prominence`; `peak_half_window`; `threshold`; `invert`. |
| Dimension Projection (`selection.dimension_project`) | Select one exact index from every inner dimension of an n-dimensional dataset before a two-dimensional algorithm. | `X: SpectralDataset` | projected `SpectralDataset` | closed `projection` record containing one zero-based index for every inner dimension. |
| Interval PLS (`selection.ipls`) | Search spectral intervals and keep the interval set with best cross-validated PLS performance. | `X: SpectralDataset`; `y: TargetMatrix` | `X_selected`; `mask`; `scores` | `n_intervals`; `n_components`; `cv_folds`; `n_best`. |
| CARS (`selection.cars`) | Perform competitive adaptive reweighted sampling for wavelength selection. | `X: Array2D`; `y: TargetMatrix` | `X_selected`; `mask`; `scores` | `n_iterations`; `n_components`; `cv_folds`. |
| SPA (`selection.spa`) | Select variables with low collinearity using successive projections. | `X: Array2D`; `y: TargetMatrix?` | `X_selected`; `mask`; `scores` | `n_select`. |
| MC-UVE (`selection.mcuve`) | Rank measured variables by PLS-coefficient stability across Monte Carlo calibration subsets and retain the declared top count. | `X: Array2D`; `y: TargetMatrix` | `X_selected`; `mask`; `scores` | `n_components`; `n_resamples`; `calibration_fraction`; `n_variables`; `random_seed`. |
| Stability Selection (`selection.stability`) | Keep variables that repeatedly pass a declared PLS scoring rule in seeded half-samples; reports empirical selection frequency, not predictive performance or a formal false-discovery guarantee. | `X: Array2D`; `y: TargetMatrix` | `X_selected`; `mask`; `scores` | `base_method`; `base_threshold`; `selection_probability_threshold`; `n_resamples`; `n_components`; `random_seed`. |
| Compare Feature Selections (`selection.compare`) | Record Jaccard overlap among two to four exact boolean masks and build an inclusive-vote consensus without ranking the selectors. | `X`; `mask_1`; `mask_2`; optional `mask_3`; optional `mask_4` | `X_consensus`; `consensus_mask`; closed agreement `report` | `consensus_threshold`: retain when votes are at least `ceil(threshold × method_count)`; `0.5` means at least half, not a strict majority. |
| Audit Feature Selection (`selection.audit`) | Produce a deterministic, digest-bound projection of the selection provenance already recorded on a dataset. | `X: Array2D` | `X_out`; closed `audit` report | `include_scores` controls whether exact finite feature scores accompany their always-recorded digest. |

## Validation and Diagnostics

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Evaluate Nested CV Selection (`selection.nested_cv`) | Estimate performance when variable selection happens inside each outer CV fold, with selection and PLS component tuning fitted together inside each inner-training fold. | `X: Array2D`; `y: TargetMatrix` (required, one quantitative target) | `cv_metrics`; single-repeat `oof_evidence` and `stability`, or `repeated_evidence` | `selection_method`; `n_components`; `cv_folds`; `vip_threshold`; `coef_threshold`; `random_seed`; `n_repeats`. |
| Evaluate by Cross-Validation (`diagnostics.cross_validation`) | Compute CV metrics from true and predicted values. | `y_true`; `y_pred` | `cv_metrics`; `predictions`; `plots`; `model` | `cv_folds`; `cv_method`; `task_type`. |
| Evaluate Regression (`diagnostics.regression_evaluator`) | Compute the closed regression metric registry from explicit predictions and references. | predictions; `y_true` | metrics and evidence | Local workbench evaluation requires the explicit reference edge; managed evaluation receives fold authority separately. |
| Evaluate Classification (`diagnostics.classification_evaluator`) | Compute complete confusion-matrix and label metrics from held-out predictions and references. | predicted labels; `y_true` | metrics and visualization | Rejected or prediction-only labels remain visible rather than disappearing from accounting. |
| Detect Outliers (`diagnostics.outliers`) | Screen fitted PCA calibration samples by Hotelling T² and Q/SPE residuals. | PCA `diagnostic_state` | `flags`; `T2`; `Q`; `model` | `confidence_level`. Connect the typed diagnostic-state output from Fit PCA Transform. |
| Statistics (`stats.summary`) | Compute deterministic descriptive summaries without inventing diagnostics or missing data. | `default: Any` | `statistics: StatisticsSummary` | `max_samples`. |

## Interpretation

Selection can improve interpretability, but it can also overfit. Prefer nested validation or a true holdout when variable selection influences the final model. A variable-selection method that sees the full dataset before cross-validation will usually make the CV result too optimistic.

`selection.compare` is an agreement recorder, not a model-selection or performance test. It uses the Jaccard coefficient (Jaccard, 1901, DOI `10.5169/seals-266450`) for pairwise overlap and preserves the exact boolean input masks and their digests, vote counts, threshold, required vote count, union, intersection, and consensus mask in its report. That makes the agreement calculation independently replayable after upstream execution outputs are gone. Agreement between selectors does not show that the selected variables generalize; evaluate any resulting recipe under the same leakage-safe validation design used for the model.

`selection.audit` is provenance infrastructure, not a feature-selection algorithm and not an independent scientific verifier. It records a closed vocabulary of canonical selection operations, their exact bounded parameters and impacts, source order, input/output shapes, current matrix and feature-axis identities, and a digest chain over the resulting report. Source timestamps are deliberately omitted so identical scientific provenance produces identical audit bytes. The report can detect accidental or malicious changes unless the report and its unsigned digest are both replaced; it does not prove that an upstream selector's scientific calculation was correct. Selector-specific evidence and leakage-safe validation remain authoritative for that claim. Because this node performs no scientific selection calculation, it has no external algorithm citation.

`selection.nested_cv` uses seeded shuffled row-wise K-fold when no groups are bound. An explicit `groups` input enables group K-fold in both outer evaluation and inner tuning. Attached specimen groups are used only when `group_source=attached` is explicitly selected; the default `explicit_or_rows` preserves row-wise behavior for existing workflows. Grouped folds are deterministic; the seed still controls stochastic selectors. Supply enough independent groups for both levels. Temporal validation is not implied. Group IDs and complete fold membership are retained and checked on evidence replay. The result records the canonical SDK split-plan digest and complete fold membership, plus the root seed and its versioned per-fold seed derivation. RMSECV, R², and positive-overprediction bias come from the versioned metric registry. SEP is the sample standard deviation of prediction residuals after removing that bias; RER is the observed target range divided by SEP. When SEP is exactly zero, RER has no finite scientific value, so the node reports `rer: null` with `rer_status: undefined_zero_sep` instead of substituting an arbitrary numerical floor.

The nested evaluator also records a closed selector profile. CARS uses 30 iterations and at most three selector folds; MC-UVE uses 30 Monte Carlo calibration subsets, a 0.8 calibration fraction, and retains at most 20 ranked variables; SPA selects at most 20 variables. These fixed local defaults are emitted in `cv_metrics.selector_profile`, so a scientist can see the exact choices rather than inheriting hidden implementation settings.

PCA outlier screening uses the fitted model's actual eigenvalues for Hotelling T² and the Nomikos–MacGregor finite-sample F limit. Q/SPE is calculated from the reconstruction residuals in the fitted feature space. Its displayed boundary is the selected quantile of those same calibration residuals: it is useful for screening the fitted samples, but it is not an independently validated false-alarm limit. Use a separately governed validation set when making a performance or deployment claim.

### Held-out Regression with Source Labels

`diagnostics.labeled_regression_evaluator` is the workbench evaluator used by
new PLS Calibration starters. Connect predictions, explicit held-out reference
values (`y_true`), and the same held-out dataset (`sample_context`). It requires
matching row counts, response names, finite reference values in the same order,
and explicit sample labels. Comparison tables and plots retain those labels and their row order (labels need
not be unique);
metrics use the same versioned registry as the managed evaluator.

Before constructing comparison rows, the node checks a conservative limit of
500,000 counted values (including comparison expansion) and 2 MiB of text,
including repeated sample labels and response names. Excess input is refused;
select a smaller explicit cohort rather than silently truncating evaluation.
Python export uses the same evaluator and checks. The existing
`diagnostics.regression_evaluator` remains the frozen managed-fold operation;
its contract and replay identity are unchanged.

### Inner tuning authority

Each inner candidate fits its selector using only inner-training observations, fits PLS on those columns, and predicts the inner-validation observations. Squared errors are pooled by observation count. A candidate lacking enough selected columns in any inner fold is not scored on a subset of folds. The chosen selector and model are refitted on the complete outer-training fold. Outer-test targets never participate. Outer-fold selection stability remains descriptive, not an independent validation of the selected model.

### Repeated validation

Set **Validation Repeats** above one to run separately seeded nested validations.
Each repeat retains its own split, group IDs, out-of-fold predictions, selected
components and selection stability. The summary reports per-repeat RMSECV, R²,
bias and SEP with their mean, sample standard deviation and range. These are
partition-sensitivity statistics for the same dataset, not confidence intervals,
external validation or additional independent observations. Grouped repeats
randomly partition whole groups; single grouped runs remain deterministic.

Repeated mode emits `repeated_evidence` instead of a single `oof_evidence` record.
Do not feed it to a single-repeat evaluator or flatten its predictions. The
Inspector and expanded output show the repeated summary; exact evidence is
retained for export/replay. Fixed-prediction bootstrap semantics are unchanged.

The visible `max_selector_fits` budget defaults to 500 selector calls. The conservative bound is repeats × outer folds × (3 × candidate components + 1). Oversized requests stop before fitting; reduce settings or explicitly raise the budget. The existing execution timeout still applies. Outer refits adapt the component count if fewer selected features survive, retaining both the inner choice and effective count in metrics.
