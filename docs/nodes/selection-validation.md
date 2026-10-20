# Selection and Validation Nodes

Selection and validation nodes help choose variables, split samples, and estimate model reliability.

## Sample Partitioning

- [`data.train_test_split`](data.md#registry-reference): You need one explicit statistical or chemometric calibration/test design.

## Variable Selection

### Explicit feature engineering

**Select Columns** (`selection.select_columns`) keeps or excludes exact feature names from a SpectralDataset. Run its upstream node to populate the searchable column multi-select. Selection preserves the input column order, sample identities, target values, units, and missing values. Selecting no columns in **keep** mode is an error; in **exclude** mode it keeps every column. Unnamed features use one-based names such as `Column 1`.

**Merge Features** (`data.merge_features`) appends an **Additional Features** dataset to a **Base Dataset**. The base controls row order, sample metadata, and targets. The default join uses unique sample labels; `sample_index` instead uses retained sample-axis coordinates, not the current row positions or equal row counts. Both inputs must contain exactly the same unique sample identities. Reordered rows are aligned; unmatched/duplicate identities, conflicting targets, and conflicting inclusion masks are rejected.

For peak-feature engineering, connect Normalize to Merge Features' **Base Dataset**, Peak Finding's **Per-spectrum Peak Matrix** to Select Columns, and Select Columns to **Additional Features**. Connect **Merged Features** to Train/Test Split. Output names are prefixed `base::` and `added::` to prevent collisions. The output has a generic named feature axis, while original coordinate axes, block provenance and individual column units remain in metadata. Data View's **Columns** range selector lets you inspect appended columns beyond the first 50.

Neither node scales blocks or imputes missing values. Guide magnitudes remain measured values even when a peak is not detected; detected-peak measurements can remain missing. Choose a downstream method that supports your missing-value policy. Consider block weighting/scaling deliberately: these operations do not imply improved prediction, and distance-based splitting can change when features are appended.

Peak locations specified independently from chemical knowledge do not learn from held-out spectra. By contrast, consensus positions estimated from all input spectra are data-derived; use training-only estimation and fixed application when evaluating an inductive model. These two nodes select and combine already-computed features; they do not change Peak Finding's consensus-estimation procedure.

### Model-based selection

- [`selection.variable_select`](selection-validation.md#registry-reference): Select wavelengths by VIP, coefficients, spectral region, peaks, or an incoming mask.
- [`selection.dimension_project`](selection-validation.md#registry-reference): Select one exact index from every inner dimension of an n-dimensional dataset before a two-dimensional algorithm. The closed projection record contains one zero-based index for every inner dimension.
- [`selection.ipls`](selection-validation.md#registry-reference): Search spectral intervals and keep the interval set with best cross-validated PLS performance.
- [`selection.cars`](selection-validation.md#registry-reference): Perform competitive adaptive reweighted sampling for wavelength selection.
- [`selection.spa`](selection-validation.md#registry-reference): Select variables with low collinearity using successive projections.
- [`selection.mcuve`](selection-validation.md#registry-reference): Rank measured variables by PLS-coefficient stability across Monte Carlo calibration subsets and retain the declared top count.
- [`selection.stability`](selection-validation.md#registry-reference): Keep variables that repeatedly pass a declared PLS scoring rule in seeded half-samples; reports empirical selection frequency, not predictive performance or a formal false-discovery guarantee.
- [`selection.compare`](selection-validation.md#registry-reference): Record Jaccard overlap among two to four exact boolean masks and build an inclusive-vote consensus without ranking the selectors. Retain a variable when votes are at least `ceil(threshold × method_count)`; `0.5` means at least half, not a strict majority.
- [`selection.audit`](selection-validation.md#registry-reference): Produce a deterministic, digest-bound projection of the selection provenance already recorded on a dataset. `include_scores` controls whether exact finite feature scores accompany their always-recorded digest.

## Validation and Diagnostics

- [`selection.nested_cv`](selection-validation.md#registry-reference): Estimate performance when variable selection happens inside each outer CV fold, with selection and PLS component tuning fitted together inside each inner-training fold. Requires one quantitative target. Single-repeat and repeated-validation evidence have different replay semantics, described below.
- [`diagnostics.cross_validation`](selection-validation.md#registry-reference): Summarize one producer-bound regression out-of-fold evidence record; it does not split or refit. Rejects missing or unbound evidence.
- [`diagnostics.regression_evaluator`](selection-validation.md#registry-reference): Compute the closed regression metric registry from explicit predictions and references. Local workbench evaluation requires the explicit reference edge; managed evaluation receives fold authority separately.
- [`diagnostics.classification_evaluator`](selection-validation.md#registry-reference): Compute confusion-matrix and label metrics from explicit predictions and references. The local evaluator does not verify held-out status; establish it from retained split/run lineage. Rejected or prediction-only labels remain visible.
- [`diagnostics.outliers`](selection-validation.md#registry-reference): Screen fitted PCA calibration samples by Hotelling T² and Q/SPE residuals. Connect the typed diagnostic-state output from Fit PCA Transform.
- [`stats.summary`](output.md#registry-reference): Compute deterministic descriptive summaries without inventing diagnostics or missing data.

## Interpretation

Selection can improve interpretability, but it can also overfit. Prefer nested validation or a true holdout when variable selection influences the final model. A variable-selection method that sees the full dataset before cross-validation will usually make the CV result too optimistic.

`selection.compare` is an agreement recorder, not a model-selection or performance test. It uses the Jaccard coefficient (Jaccard, 1901, DOI `10.5169/seals-266450`) for pairwise overlap and preserves the exact boolean input masks and their digests, vote counts, threshold, required vote count, union, intersection, and consensus mask in its report. That makes the agreement calculation independently replayable after upstream execution outputs are gone. Agreement between selectors does not show that the selected variables generalize; evaluate any resulting recipe under the same leakage-safe validation design used for the model.

`selection.audit` is provenance infrastructure, not a feature-selection algorithm and not an independent scientific verifier. It records a closed vocabulary of canonical selection operations, their exact bounded parameters and impacts, source order, input/output shapes, current matrix and feature-axis identities, and a digest chain over the resulting report. Source timestamps are deliberately omitted so identical scientific provenance produces identical audit bytes. The report can detect accidental or malicious changes unless the report and its unsigned digest are both replaced; it does not prove that an upstream selector's scientific calculation was correct. Selector-specific evidence and leakage-safe validation remain authoritative for that claim. Because this node performs no scientific selection calculation, it has no external algorithm citation.

`selection.nested_cv` uses seeded shuffled row-wise K-fold when no groups are bound. An explicit `groups` input enables group K-fold in both outer evaluation and inner tuning. Attached specimen groups are used only when `group_source=attached` is explicitly selected; `explicit_or_rows` uses explicit groups when connected and otherwise row-wise folds. See the generated registry reference below for the current default. Grouped folds are deterministic; the seed still controls stochastic selectors. Supply enough independent groups for both levels. Temporal validation is not implied. Group IDs and complete fold membership are retained and checked on evidence replay. The result records the canonical SDK split-plan digest and complete fold membership, plus the root seed and its versioned per-fold seed derivation. RMSECV, R², and positive-overprediction bias come from the versioned metric registry. SEP is the sample standard deviation of prediction residuals after removing that bias; RER is the observed target range divided by SEP. When SEP is exactly zero, RER has no finite scientific value, so the node reports `rer: null` with `rer_status: undefined_zero_sep` instead of substituting an arbitrary numerical floor.

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

The visible `max_selector_fits` budget limits selector calls; its current default is in the generated registry reference below. The conservative bound is repeats × outer folds × (3 × candidate components + 1). Oversized requests stop before fitting; reduce settings or explicitly raise the budget. The existing execution timeout still applies. Outer refits adapt the component count if fewer selected features survive, retaining both the inner choice and effective count in metrics.

<!-- BEGIN GENERATED NODE REFERENCE -->

<!-- NODE HELP REFERENCES {"help_reference": "docs/nodes/selection-validation.md", "node_types": ["data.merge_features", "diagnostics.classification_evaluator", "diagnostics.cross_validation", "diagnostics.labeled_regression_evaluator", "diagnostics.outliers", "diagnostics.regression_evaluator", "selection.audit", "selection.cars", "selection.compare", "selection.dimension_project", "selection.ipls", "selection.mcuve", "selection.nested_cv", "selection.select_columns", "selection.spa", "selection.stability", "selection.variable_select"]} -->

## Registry reference

Generated from registered node metadata. Edit methodology and examples outside the marked section.
Defaults and options below are JSON values; `null` means no concrete default is declared.
Internal parameters are retained for contract inspection and are not scientist-editable controls.
Conditional visibility describes the editor; execution admission remains node-owned.

| Node | Operation |
| --- | --- |
| Merge Features | <code>data.merge_features</code> |
| Reference Classification Evaluator (v2) | <code>diagnostics.classification_evaluator</code> |
| Evaluate Out-of-Fold Predictions | <code>diagnostics.cross_validation</code> |
| Held-out Regression with Source Labels | <code>diagnostics.labeled_regression_evaluator</code> |
| Detect Outliers | <code>diagnostics.outliers</code> |
| Reference Regression Evaluator (v2) | <code>diagnostics.regression_evaluator</code> |
| Audit Feature Selection | <code>selection.audit</code> |
| CARS | <code>selection.cars</code> |
| Compare Feature Selections | <code>selection.compare</code> |
| Dimension Projection | <code>selection.dimension_project</code> |
| Interval PLS (iPLS) | <code>selection.ipls</code> |
| MC-UVE | <code>selection.mcuve</code> |
| Evaluate Nested CV Selection | <code>selection.nested_cv</code> |
| Select Columns | <code>selection.select_columns</code> |
| SPA-MLR Variable Selection (Araújo 2001) | <code>selection.spa</code> |
| Stability Selection | <code>selection.stability</code> |
| Variable Selection Rule | <code>selection.variable_select</code> |

### Merge Features (`data.merge_features`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>base</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>additional</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>match_by</code> | <code>select</code> | <code>true</code> | <code>&quot;sample_labels&quot;</code> | <code>[&quot;sample_labels&quot;, &quot;sample_index&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Unique sample labels or retained sample-axis coordinates, not row count |

### Reference Classification Evaluator (v2) (`diagnostics.classification_evaluator`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Categorical/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>y_true</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>comparison</code> | <code>spectrasherpa://types/ClassificationComparison/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>visualization</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

No parameters.

### Evaluate Out-of-Fold Predictions (`diagnostics.cross_validation`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>evidence</code> | <code>spectrasherpa://types/OutOfFoldEvidence/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>cv_metrics</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>observations</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>predictions</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fold_assignments</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>plots</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

No parameters.

### Held-out Regression with Source Labels (`diagnostics.labeled_regression_evaluator`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>y_true</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>sample_context</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>comparison</code> | <code>spectrasherpa://types/RegressionComparison/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>target_names</code> | <code>string_list</code> | <code>false</code> | <code>[]</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Exact response labels inherited from the selected dataset target. |

### Detect Outliers (`diagnostics.outliers`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>flags</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>T2</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>Q</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>confidence_level</code> | <code>number</code> | <code>true</code> | <code>0.95</code> | — | <code>{&quot;max_value&quot;: 0.999, &quot;min_value&quot;: 0.8, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Confidence level for the calibration Hotelling T² and residual-spectrum Q/SPE limits Keeps the F-distribution limit finite and bounds unstable extreme-tail screening |

### Reference Regression Evaluator (v2) (`diagnostics.regression_evaluator`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>y_true</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>comparison</code> | <code>spectrasherpa://types/RegressionComparison/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>target_names</code> | <code>string_list</code> | <code>false</code> | <code>[]</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Exact response labels inherited from the selected dataset target. |

### Audit Feature Selection (`selection.audit`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| output | <code>X_out</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>audit</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>include_scores</code> | <code>boolean</code> | <code>true</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Include finite per-feature scores when present; their digest is always recorded |

### CARS (`selection.cars`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_selected</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>mask</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>scores</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_iterations</code> | <code>number</code> | <code>true</code> | <code>50</code> | — | <code>{&quot;max_value&quot;: 200, &quot;min_value&quot;: 10, &quot;step&quot;: 5}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of sampling iterations Bounds stochastic PLS fits and interactive runtime while retaining a dense CARS path. |
| <code>max_components</code> | <code>number</code> | <code>true</code> | <code>2</code> | — | <code>{&quot;max_value&quot;: 50, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Maximum latent variables evaluated for each recorded subset PLS latent-variable cap; runtime also restricts it to sample and feature support. |
| <code>cv_folds</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 20, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Cross-validation folds Bounds repeated PLS fitting and prevents impractically small validation folds. |
| <code>calibration_fraction</code> | <code>number</code> | <code>true</code> | <code>0.9</code> | — | <code>{&quot;max_value&quot;: 0.95, &quot;min_value&quot;: 0.5, &quot;step&quot;: 0.05}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Fraction of samples used for each stochastic coefficient fit Leaves at least five percent outside each Monte Carlo calibration draw. |
| <code>component_selection</code> | <code>select</code> | <code>true</code> | <code>&quot;one_standard_deviation&quot;</code> | <code>[&quot;minimum_rmsecv&quot;, &quot;one_standard_deviation&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Choose the global RMSECV minimum or the simplest component count whose MSE lies within one sample-error standard deviation of that minimum |
| <code>cv_order</code> | <code>select</code> | <code>true</code> | <code>&quot;sorted_target&quot;</code> | <code>[&quot;sorted_target&quot;, &quot;seeded_random&quot;, &quot;input_order&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Author-defined sample ordering before cyclic fold assignment |
| <code>random_seed</code> | <code>number</code> | <code>true</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Exact seed for Monte Carlo draws, adaptive sampling, and fixed CV folds Exact unsigned 32-bit seed accepted by the canonical CARS random generator. |

### Compare Feature Selections (`selection.compare`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>mask_1</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>mask_2</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>mask_3</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| input | <code>mask_4</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_consensus</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>consensus_mask</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>report</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>consensus_threshold</code> | <code>number</code> | <code>true</code> | <code>0.5</code> | — | <code>{&quot;max_value&quot;: 1.0, &quot;min_value&quot;: 0.0, &quot;step&quot;: 0.05}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Retain a feature when selected by at least ceil(fraction x method count) methods; 0.5 means at least half, not strictly more than half A vote fraction cannot exceed all admitted methods. |

### Dimension Projection (`selection.dimension_project`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>projection</code> | <code>json</code> | <code>true</code> | <code>{&quot;schema_version&quot;: &quot;spectrasherpa-dimension-projection/1&quot;, &quot;selections&quot;: []}</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | One exact zero-based index for every inner dimension |

### Interval PLS (iPLS) (`selection.ipls`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_selected</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>mask</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>scores</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_intervals</code> | <code>number</code> | <code>true</code> | <code>20</code> | — | <code>{&quot;max_value&quot;: 100, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of contiguous, non-overlapping intervals spanning the complete feature axis Bounds the number of independently cross-validated local PLS models. |
| <code>max_components</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 30, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Maximum PLS latent variables evaluated independently for each interval Bounds latent-variable fitting for every local and full-spectrum model. |
| <code>cv_folds</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 20, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Venetian-blinds folds shared by every interval and the full-spectrum reference Bounds repeated local PLS fitting and requires supported held-out folds. |
| <code>cv_order</code> | <code>select</code> | <code>true</code> | <code>&quot;sorted_target&quot;</code> | <code>[&quot;sorted_target&quot;, &quot;seeded_random&quot;, &quot;input_order&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Sample order before cyclic Venetian-blinds fold assignment |
| <code>random_seed</code> | <code>number</code> | <code>true</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Seed for the optional seeded-random sample order Exact unsigned 32-bit seed used only by seeded-random CV ordering. |

### MC-UVE (`selection.mcuve`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_selected</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>mask</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>scores</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 50, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Bounds latent-variable fitting and calibration-subset support. |
| <code>n_resamples</code> | <code>number</code> | <code>true</code> | <code>100</code> | — | <code>{&quot;max_value&quot;: 500, &quot;min_value&quot;: 20, &quot;step&quot;: 10}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Hard cap on the number of PLS models fitted by one node execution. |
| <code>calibration_fraction</code> | <code>number</code> | <code>true</code> | <code>0.8</code> | — | <code>{&quot;max_value&quot;: 0.95, &quot;min_value&quot;: 0.5, &quot;step&quot;: 0.05}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Leaves at least five percent outside each Monte Carlo calibration subset. |
| <code>n_variables</code> | <code>number</code> | <code>true</code> | <code>20</code> | — | <code>{&quot;max_value&quot;: 500, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Bounds the canonical retained-variable decision and exported state size. |
| <code>random_seed</code> | <code>number</code> | <code>true</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Exact unsigned 32-bit seed used for Monte Carlo calibration subsets. |

### Evaluate Nested CV Selection (`selection.nested_cv`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>groups</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>repeated_evidence</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>cv_metrics</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>oof_evidence</code> | <code>spectrasherpa://types/OutOfFoldEvidence/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>stability</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>group_source</code> | <code>select</code> | <code>true</code> | <code>&quot;explicit_or_rows&quot;</code> | <code>[{&quot;label&quot;: &quot;Row-wise unless Groups input is connected&quot;, &quot;value&quot;: &quot;explicit_or_rows&quot;}, {&quot;label&quot;: &quot;Use attached specimen groups&quot;, &quot;value&quot;: &quot;attached&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Existing workflows remain row-wise. Attached groups require explicit selection; insufficient groups never silently fall back. |
| <code>max_selector_fits</code> | <code>number</code> | <code>true</code> | <code>500</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Conservative bound: repeats × outer folds × (3 × maximum components + 1). Each CARS/MCUVE call fits many models. Raising this budget does not raise the 120-second node limit. |
| <code>n_repeats</code> | <code>number</code> | <code>true</code> | <code>1</code> | — | <code>{&quot;max_value&quot;: 20, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Separate seeded repeats; spread measures partition sensitivity, not new specimens. Repeated nested fitting multiplies selector and model work. |
| <code>selection_method</code> | <code>select</code> | <code>true</code> | <code>&quot;vip&quot;</code> | <code>[{&quot;label&quot;: &quot;VIP&quot;, &quot;value&quot;: &quot;vip&quot;}, {&quot;label&quot;: &quot;&#124;Coefficient&#124;&quot;, &quot;value&quot;: &quot;coef_abs&quot;}, {&quot;label&quot;: &quot;CARS&quot;, &quot;value&quot;: &quot;cars&quot;}, {&quot;label&quot;: &quot;MC-UVE&quot;, &quot;value&quot;: &quot;mcuve&quot;}, {&quot;label&quot;: &quot;SPA&quot;, &quot;value&quot;: &quot;spa&quot;}, {&quot;label&quot;: &quot;None (full spectrum)&quot;, &quot;value&quot;: &quot;none&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Variable selection method applied inside each fold |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 50, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Maximum latent variables considered by the inner CV loop Bounds the inner PLS search inside the declared local resource envelope. |
| <code>cv_folds</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 20, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of outer cross-validation folds Bounds repeated outer and inner fitting inside the declared local resource envelope. |
| <code>vip_threshold</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.1, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;, &quot;visible_when&quot;: {&quot;selection_method&quot;: [&quot;vip&quot;]}}</code> | VIP threshold (for VIP method) |
| <code>coef_threshold</code> | <code>number</code> | <code>true</code> | <code>0.01</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.001}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;, &quot;visible_when&quot;: {&quot;selection_method&quot;: [&quot;coef_abs&quot;]}}</code> | Absolute PLS coefficient threshold (for &#124;Coefficient&#124; method) |
| <code>random_seed</code> | <code>number</code> | <code>true</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Exact seed for outer folds, inner folds, and stochastic selectors. Exact unsigned 32-bit root seed; per-fold seeds use overflow-safe hash derivation. |

### Select Columns (`selection.select_columns`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>mode</code> | <code>select</code> | <code>true</code> | <code>&quot;keep&quot;</code> | <code>[&quot;keep&quot;, &quot;exclude&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>columns</code> | <code>string_list</code> | <code>true</code> | <code>[]</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Exact column names; run the upstream node to populate the selector |

### SPA-MLR Variable Selection (Araújo 2001) (`selection.spa`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_selected</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>mask</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>scores</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>min_variables</code> | <code>number</code> | <code>true</code> | <code>1</code> | — | <code>{&quot;max_value&quot;: 30, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Smallest projection-chain prefix evaluated by MLR cross-validation Matches the bounded exhaustive projection and MLR search envelope. |
| <code>max_variables</code> | <code>number</code> | <code>true</code> | <code>20</code> | — | <code>{&quot;max_value&quot;: 30, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Largest projection-chain prefix evaluated by MLR cross-validation Bounds exhaustive projection-chain construction and MLR evaluation. |
| <code>cv_folds</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 20, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Venetian-blinds folds shared by every candidate subset Bounds repeated MLR fitting for every candidate chain prefix. |
| <code>cv_order</code> | <code>select</code> | <code>true</code> | <code>&quot;sorted_target&quot;</code> | <code>[&quot;sorted_target&quot;, &quot;seeded_random&quot;, &quot;input_order&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Sample order before cyclic Venetian-blinds fold assignment |
| <code>random_seed</code> | <code>number</code> | <code>true</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Seed for the optional seeded-random sample order Exact unsigned 32-bit seed used only by seeded-random CV ordering. |

### Stability Selection (`selection.stability`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_selected</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>mask</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>scores</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>base_method</code> | <code>select</code> | <code>true</code> | <code>&quot;vip&quot;</code> | <code>[{&quot;label&quot;: &quot;VIP&quot;, &quot;value&quot;: &quot;vip&quot;}, {&quot;label&quot;: &quot;&#124;Coefficient&#124;&quot;, &quot;value&quot;: &quot;coef_abs&quot;}, {&quot;label&quot;: &quot;Selectivity Ratio&quot;, &quot;value&quot;: &quot;selectivity_ratio&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | PLS variable score thresholded in every half-sample |
| <code>base_threshold</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;max_value&quot;: 1000000.0, &quot;min_value&quot;: 1e-06, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Bounds the closed base-selector decision envelope. |
| <code>selection_probability_threshold</code> | <code>number</code> | <code>true</code> | <code>0.6</code> | — | <code>{&quot;max_value&quot;: 1.0, &quot;min_value&quot;: 0.500001, &quot;step&quot;: 0.05}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum empirical half-sample selection frequency A probability may not exceed one. |
| <code>n_resamples</code> | <code>number</code> | <code>true</code> | <code>100</code> | — | <code>{&quot;max_value&quot;: 500, &quot;min_value&quot;: 20, &quot;step&quot;: 10}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Hard cap on PLS fits per node execution. |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 50, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Bounds latent-variable fitting and half-sample support. |
| <code>random_seed</code> | <code>number</code> | <code>true</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Exact unsigned 32-bit sampling seed. |

### Variable Selection Rule (`selection.variable_select`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>model</code> | <code>spectrasherpa://types/FittedModel/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| input | <code>mask</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| input | <code>importance_scores</code> | <code>spectrasherpa://types/VariableImportance/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_selected</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>mask</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>scores</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>selection_report</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>method</code> | <code>select</code> | <code>true</code> | <code>&quot;vip&quot;</code> | <code>[{&quot;label&quot;: &quot;Spectral Interval&quot;, &quot;value&quot;: &quot;interval&quot;}, {&quot;label&quot;: &quot;Peak Window&quot;, &quot;value&quot;: &quot;peak_window&quot;}, {&quot;label&quot;: &quot;Apply Existing Mask&quot;, &quot;value&quot;: &quot;apply_mask&quot;}, {&quot;label&quot;: &quot;VIP (PLS)&quot;, &quot;value&quot;: &quot;vip&quot;}, {&quot;label&quot;: &quot;Normalized Coefficient Magnitude&quot;, &quot;value&quot;: &quot;coef_abs&quot;}, {&quot;label&quot;: &quot;Target-Projection Selectivity Ratio&quot;, &quot;value&quot;: &quot;selectivity_ratio&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>region_start</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;interval&quot;]}}</code> | — |
| <code>region_end</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;interval&quot;]}}</code> | — |
| <code>peak_prominence</code> | <code>number</code> | <code>true</code> | <code>0.1</code> | — | <code>{&quot;min_value&quot;: 0.001, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;peak_window&quot;]}}</code> | — |
| <code>peak_half_window</code> | <code>number</code> | <code>true</code> | <code>10</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;peak_window&quot;]}}</code> | — |
| <code>include_negative_extrema</code> | <code>boolean</code> | <code>true</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;advanced&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;peak_window&quot;]}}</code> | — |
| <code>threshold</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;vip&quot;, &quot;coef_abs&quot;, &quot;selectivity_ratio&quot;]}}</code> | — |
| <code>invert</code> | <code>boolean</code> | <code>true</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | — |

<!-- END GENERATED NODE REFERENCE -->
