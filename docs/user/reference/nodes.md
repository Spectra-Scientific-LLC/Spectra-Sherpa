# Node Reference

This reference lists the available processing nodes in the Workflow Builder, including their parameters and default values.

Nodes marked with **[SCP]** require [SpectroChemPy](https://www.spectrochempy.fr/) (`pip install spectra-sherpa[scp]`). All other nodes run on NumPy/SciPy/scikit-learn.

## Preprocessing Nodes

### Baseline Correction

#### Baseline (ALS)
*   **Node Type**: `baseline.als`
*   **Description**: Asymmetric Least Squares baseline correction. Effective for removing broad, varying baselines while preserving peaks.
*   **Parameters**:
    *   `lam` (number, default: `100000`): Smoothness parameter. Larger values = smoother baseline. Range: 1e2 - 1e9.
    *   `p` (number, default: `0.001`): Asymmetry parameter. Smaller values allow the baseline to stay lower (under peaks). Range: 0.0001 - 0.1.

#### Baseline (Rubberband) **[SCP]**
*   **Node Type**: `baseline.rubberband`
*   **Description**: Convex hull "rubberband" baseline correction.
*   **Powered by**: [spectrochempy.basc](https://www.spectrochempy.fr/reference/generated/spectrochempy.basc.html)
*   **Parameters**:
    *   `ranges` (text): Optional spectral ranges to force baseline points (e.g., `'4000:3800, 1800:1700'`).

### Smoothing & Filtering

#### Smooth (Savitzky-Golay)
*   **Node Type**: `smooth.savitzky_golay`
*   **Description**: Polynomial smoothing filter. Reduces noise while preserving peak shapes better than moving averages.
*   **Parameters**:
    *   `size` (number, default: `11`): Window size. Must be an odd number.
    *   `order` (number, default: `2`): Order of the polynomial fit.

#### Cosmic Ray Removal
*   **Node Type**: `preprocess.cosmic_ray`
*   **Description**: Removes spike-like outliers (cosmic rays) using local median statistics.
*   **Parameters**:
    *   `window` (number, default: `7`): Window size for local statistics (must be odd).
    *   `zscore` (number, default: `3.0`): Z-score threshold for detection. Points > z-score * MAD are replaced.

### Normalization & Scaling

#### Normalize (SNV)
*   **Node Type**: `normalize.snv`
*   **Description**: Standard Normal Variate. Subtracts mean and divides by standard deviation for each spectrum. No parameters.

#### Normalize (MSC)
*   **Node Type**: `normalize.msc`
*   **Description**: Multiplicative Scatter Correction. Corrects for light scattering effects.
*   **Parameters**:
    *   `reference` (select, default: `mean`): Reference spectrum to use (`mean`, `median`, `first`).

#### Normalize (Scale)
*   **Node Type**: `normalize.scale`
*   **Description**: Scales spectra based on specific criteria.
*   **Parameters**:
    *   `method` (select, default: `max`): `max`, `area`, `minmax`.

#### Autoscaling
*   **Node Type**: `preprocess.autoscaling`
*   **Description**: Scale to unit variance (mean centering + standardization).
*   **Parameters**:
    *   `center` (boolean, default: `True`): Subtract mean before scaling.

#### Pareto Scaling
*   **Node Type**: `preprocess.pareto_scaling`
*   **Description**: Scale by square root of standard deviation (chemometrics standard).
*   **Parameters**:
    *   `center` (boolean, default: `True`): Subtract mean before scaling.

#### Center Mean
*   **Node Type**: `preprocess.center_mean`
*   **Description**: Subtract the mean spectrum from all spectra. No parameters.

#### Scale to Max
*   **Node Type**: `preprocess.scale_max`
*   **Description**: Normalize each spectrum to a target maximum value.
*   **Parameters**:
    *   `target_max` (number, default: `1.0`): Target maximum absorbance value.

### Derivatives

#### 1st Derivative
*   **Node Type**: `derivative.first`
*   **Description**: First derivative using Savitzky-Golay filter.
*   **Parameters**:
    *   `size` (number, default: `11`): Window size.
    *   `order` (number, default: `2`): Polynomial order.

#### 2nd Derivative
*   **Node Type**: `derivative.second`
*   **Description**: Second derivative using Savitzky-Golay filter. Useful for resolving overlapping peaks.
*   **Parameters**:
    *   `size` (number, default: `11`): Window size.
    *   `order` (number, default: `2`): Polynomial order.

#### SG Derivative
*   **Node Type**: `preprocess.sg_derivative`
*   **Description**: Combined Savitzky-Golay smoothing and derivative.
*   **Parameters**:
    *   `size` (number, default: `11`): Window size.
    *   `order` (number, default: `2`): Polynomial order.
    *   `deriv` (select, default: `1`): Derivative order (`0`, `1`, `2`).

### Advanced Correction

#### OSC Filter **[SCP]**
*   **Node Type**: `preprocess.osc`
*   **Description**: Orthogonal Signal Correction - remove variation uncorrelated with Y.
*   **Powered by**: [spectrochempy.PLSRegression](https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html)
*   **Parameters**:
    *   `n_components` (number, default: `1`): Number of orthogonal components.
    *   `tol` (number, default: `1e-6`): Convergence tolerance.
    *   `max_iter` (number, default: `100`): Maximum iterations.

#### EMSC
*   **Node Type**: `preprocess.emsc`
*   **Description**: Extended MSC with polynomial baseline correction.
*   **Parameters**:
    *   `reference` (select, default: `mean`): Reference spectrum (`mean`, `median`, `first`).
    *   `poly_order` (number, default: `2`): Order of polynomial baseline.

### Utilities

#### Clip Range
*   **Node Type**: `preprocess.clip_range`
*   **Description**: Crops data to a specific wavenumber region.
*   **Parameters**:
    *   `min_wavenumber` (number, default: `400`): Lower bound.
    *   `max_wavenumber` (number, default: `4000`): Upper bound.

#### Clip Floor
*   **Node Type**: `preprocess.clip_floor`
*   **Description**: Sets a minimum value floor (e.g., to remove negative absorbance).
*   **Parameters**:
    *   `floor` (number, default: `0.0`): Minimum allowed value.

#### Wavenumber Align
*   **Node Type**: `preprocess.wavenumber_align`
*   **Description**: Align spectra to a common wavenumber grid via interpolation.
*   **Parameters**:
    *   `method` (select, default: `pchip`): `pchip`, `linear`, `sinc`.
    *   `merge_tolerance` (number, default: `0.5`): Tolerance for merging near-duplicate points.

### Time Series Preprocessing

#### Moving Window
*   **Node Type**: `time_series.moving_window`
*   **Description**: Slides a window over time series data for batch analysis.
*   **Parameters**:
    *   `window_size` (number, default: `10`): Number of consecutive spectra.
    *   `step_size` (number, default: `1`): Overlap step.
    *   `aggregation` (select, default: `none`): `none`, `mean`, `median`, `std`.

#### Trend Removal
*   **Node Type**: `time_series.trend_removal`
*   **Description**: Removes systematic trends and drift from time series data.
*   **Parameters**:
    *   `method` (select, default: `linear`): `linear`, `polynomial`, `difference`, `moving_average`.
    *   `poly_order` (number, default: `2`): For polynomial method.
    *   `window_size` (number, default: `5`): For moving average baseline.

---

## Modeling Nodes

### Decomposition & Analysis

#### PCA **[SCP]**
*   **Node Type**: `model.pca`
*   **Description**: Principal Component Analysis.
*   **Powered by**: [spectrochempy.PCA](https://www.spectrochempy.fr/reference/generated/spectrochempy.PCA.html)
*   **Parameters**:
    *   `n_components` (text, default: `5`): Number of components (int), 'mle', or variance ratio (float 0-1).
    *   `standardized` (boolean, default: `False`): Apply standardization.
    *   `scaled` (boolean, default: `False`): Apply scaling.

#### MCR-ALS **[SCP]**
*   **Node Type**: `model.mcr_als`
*   **Description**: Multivariate Curve Resolution - Alternating Least Squares. Resolves mixtures into pure components.
*   **Powered by**: [spectrochempy.MCRALS](https://www.spectrochempy.fr/reference/generated/spectrochempy.MCRALS.html)
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of pure components.
    *   `max_iter` (number, default: `50`): Maximum iterations.
    *   `tol` (number, default: `0.1`): Convergence tolerance.
    *   `non_negative_C` (boolean, default: `True`): Enforce non-negative concentrations.
    *   `non_negative_St` (boolean, default: `True`): Enforce non-negative spectra.

#### EFA **[SCP]**
*   **Node Type**: `model.efa`
*   **Description**: Evolving Factor Analysis. Determines chemical rank of evolving systems.
*   **Powered by**: [spectrochempy.EFA](https://www.spectrochempy.fr/reference/generated/spectrochempy.EFA.html)
*   **Parameters**:
    *   `n_components` (number, default: `10`): Number of eigenvalues to compute.

#### SIMPLISMA **[SCP]**
*   **Node Type**: `model.simplisma`
*   **Description**: Self-modeling mixture analysis using purity maximization. Identifies pure variables in spectral mixtures.
*   **Powered by**: [spectrochempy.SIMPLISMA](https://www.spectrochempy.fr/reference/generated/spectrochempy.SIMPLISMA.html)
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of pure components to resolve.
    *   `tol` (number, default: `0.1`): Convergence tolerance.
    *   `noise` (number, default: `3.0`): Noise level threshold.
*   **Outputs**: `model`, `concentrations`, `spectra` (pure component spectra), `purity_values`.

#### Peak Finding
*   **Node Type**: `analysis.peak_finding`
*   **Description**: Identifies peaks using `scipy.signal`.
*   **Parameters**:
    *   `height` (number): Minimum peak height.
    *   `threshold` (number): Minimum vertical distance to neighbors.
    *   `distance` (number, default: `10`): Minimum horizontal distance (points).
    *   `prominence` (number): Peak prominence.
    *   `width` (number): Expected peak width.

### Regression

#### PLS **[SCP]**
*   **Node Type**: `model.pls`
*   **Description**: Partial Least Squares Regression.
*   **Powered by**: [spectrochempy.PLSRegression](https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html)
*   **Inputs**: `X` (Spectra), `y` (Concentrations).
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of latent variables.
    *   `scale` (boolean, default: `True`): Auto-scale data.

#### PCR
*   **Node Type**: `model.pcr`
*   **Description**: Principal Component Regression (PCA + Linear Regression).
*   **Inputs**: `X` (Spectra), `y` (Targets).
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of PCA components.
    *   `scale` (boolean, default: `True`): Auto-scale data.

#### SVR
*   **Node Type**: `model.svr`
*   **Description**: Support Vector Regression.
*   **Inputs**: `X` (Spectra), `y` (Targets).
*   **Parameters**:
    *   `kernel` (select, default: `rbf`): `rbf`, `linear`, `poly`, `sigmoid`.
    *   `C` (number, default: `1.0`): Regularization parameter.
    *   `epsilon` (number, default: `0.1`): Epsilon-tube width.
    *   `gamma` (select, default: `scale`): Kernel coefficient.
    *   `degree` (number, default: `3`): Degree for poly kernel.
    *   `coef0` (number, default: `0.0`): Independent term.
    *   `scale` (boolean, default: `True`): Scale data.

#### Linear Regression
*   **Node Type**: `model.linear_regression`
*   **Description**: Simple linear regression.
*   **Parameters**:
    *   `fit_intercept` (boolean, default: `True`): Calculate intercept.

### Classification

#### PLS-DA **[SCP]**
*   **Node Type**: `classification.plsda`
*   **Description**: Partial Least Squares Discriminant Analysis.
*   **Powered by**: [spectrochempy.PLSRegression](https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html)
*   **Inputs**: `X` (Spectra), `y` (Classes - optional, auto-extracted from X).
*   **Parameters**:
    *   `n_components` (number, default: `2`): Number of components.
    *   `scale` (boolean, default: `True`): Scale data.
    *   `cv_folds` (number, default: `5`): Cross-validation folds.
*   **Outputs**: Model dict with train/CV predictions, confusion matrices, and classification report.
*   **Notes**: If `X` includes class labels in its y-axis, you can omit `y` to auto-extract. For train/test workflows, split data with `data.train_test_split`, train with `X_train` (+ `y_train` if provided), then use `classification.plsda_predict` on `X_test` and feed `y_test` + `y_pred` into `diagnostics.cross_validation` for a confusion matrix.

#### Apply PLS-DA Model **[SCP]**
*   **Node Type**: `classification.plsda_predict`
*   **Description**: Apply a trained PLS-DA model to new samples.
*   **Inputs**: `X_new` (Spectra), `model` (PLS-DA model dict).
*   **Outputs**: `y_pred` (Predicted classes), `y_prob` (Class probabilities).

#### KNN Classifier
*   **Node Type**: `classification.knn`
*   **Description**: K-Nearest Neighbors classification.
*   **Inputs**: `X` (Features), `y` (Classes - optional).
*   **Parameters**:
    *   `n_neighbors` (number, default: `5`): Number of neighbors (k).
    *   `weights` (select, default: `uniform`): `uniform`, `distance`.
    *   `metric` (select, default: `euclidean`): Distance metric.
    *   `cv_folds` (number, default: `5`): Cross-validation folds.
*   **Outputs**: Model dict with train/CV predictions, confusion matrices, and classification report.
*   **Notes**: If `X` includes class labels in its y-axis, you can omit `y` to auto-extract. For train/test workflows, split data with `data.train_test_split`, train with `X_train` (+ `y_train` if provided), then use `classification.knn_predict` on `X_test` and feed `y_test` + `y_pred` into `diagnostics.cross_validation` for a confusion matrix.

#### Apply KNN Model
*   **Node Type**: `classification.knn_predict`
*   **Description**: Apply a trained KNN model to new samples.
*   **Inputs**: `X_new` (Features), `model` (KNN model dict).
*   **Outputs**: `y_pred` (Predicted classes), `y_prob` (Class probabilities).

#### SIMCA **[SCP]**
*   **Node Type**: `classification.simca`
*   **Description**: Soft Independent Modeling of Class Analogy.
*   **Powered by**: [spectrochempy.PCA](https://www.spectrochempy.fr/reference/generated/spectrochempy.PCA.html) (per-class PCA models)
*   **Inputs**: `X` (Features), `y` (Classes - optional).
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of PCs per class.
    *   `confidence_level` (number, default: `0.95`): For T² and Q limits.
*   **Outputs**: Model dict with predictions, confusion matrix, and classification report.
*   **Notes**: If `X` includes class labels in its y-axis, you can omit `y` to auto-extract.

### Clustering

#### HCA
*   **Node Type**: `model.hca`
*   **Description**: Hierarchical Cluster Analysis (Agglomerative).
*   **Parameters**:
    *   `n_clusters` (number, default: `3`): Number of clusters.
    *   `linkage` (select, default: `ward`): `ward`, `average`, `complete`, `single`.
    *   `metric` (select, default: `euclidean`): Distance metric.
*   **Outputs**: Cluster labels and 2D embedding for visualization.
*   **Notes**: To compare clusters to known class labels, feed ground-truth labels and the HCA `labels` output into `diagnostics.cross_validation` to generate a confusion matrix.

#### KMeans
*   **Node Type**: `model.kmeans`
*   **Description**: K-Means clustering.
*   **Parameters**:
    *   `n_clusters` (number, default: `3`): Number of clusters.
    *   `n_init` (number, default: `10`): Number of initializations.
    *   `max_iter` (number, default: `300`): Max iterations.
    *   `random_state` (number, default: `42`): Random seed.

#### DBSCAN
*   **Node Type**: `model.dbscan`
*   **Description**: Density-Based Spatial Clustering of Applications with Noise.
*   **Parameters**:
    *   `eps` (number, default: `0.5`): Neighborhood radius.
    *   `min_samples` (number, default: `5`): Minimum samples per cluster.
    *   `metric` (select, default: `euclidean`): Distance metric.

### Diagnostics

#### Outlier Detection
*   **Node Type**: `diagnostics.outliers`
*   **Description**: Hotelling T² and Q statistics for PCA models.
*   **Inputs**: `PCAModel`.
*   **Parameters**:
    *   `confidence_level` (number, default: `0.95`): Limit threshold.

#### Cross-Validation
*   **Node Type**: `diagnostics.cross_validation`
*   **Description**: Computes regression or classification metrics from paired `y_true` and `y_pred`.
*   **Inputs**: `y_true`, `y_pred`.
*   **Parameters**:
    *   `cv_folds` (number, default: `5`): Number of folds.
*   **Outputs**: For classification, accuracy, confusion matrix, and a classification report. For regression, RMSE, MAE, R2, Q2, and residuals.

### Model Persistence

#### Load & Apply Model
*   **Node Type**: `model.load_apply`
*   **Description**: Load a saved model artifact and apply it to new data. Supports all model types: PCA, PLS, MCR, SIMPLISMA (transform), PLS-DA, KNN, SIMCA (classify). EFA models cannot be applied (diagnostic only).
*   **Inputs**: `X_new` (SpectralDataset), `model_ref` (ModelReference — optional, overrides parameter).
*   **Parameters**:
    *   `model_id` (model_select): UUID of the saved model artifact.
*   **Outputs**: `result` (transformed/predicted data), `labels` (class labels, classification only), `model_id` (artifact UID).
*   **Notes**: The model_ref input port takes priority over the model_id parameter. Use the model selector in the inspector to browse saved models.

---

## Data & Output Nodes

### Data Sources

#### Data Source
*   **Node Type**: `data.source`
*   **Description**: Generic data loader for single files or synthetic data.
*   **Parameters**:
    *   `source` (select): `spectrochempy`, `sklearn`, `experiment`, `file`, `library`, `synthetic`.
    *   `example_dataset` (select): `irdata`, `ramandata`, `nmrdata`.
    *   `sklearn_dataset` (select): `iris`, `wine`, `breast_cancer`, `digits`.
    *   `example_file` (text): Specific file within example dataset (e.g., `CO@Mo_Al2O3.SPG`).
    *   `experiment_id` (number): ID (for experiment source).
    *   `file_path` (text): Absolute path (for file source).
    *   `transpose_on_load` (boolean): Swap rows/cols.
*   **Notes**: Sklearn datasets include class labels on the y-axis, which supervised nodes can auto-extract. The node also exposes an optional `target` output port (labels) alongside the default dataset output.

#### Train/Test Split
*   **Node Type**: `data.train_test_split`
*   **Description**: Split a dataset into training and test subsets.
*   **Inputs**: `X` (Dataset), `y` (Targets - optional, used for stratified splits).
*   **Parameters**:
    *   `test_size` (number, default: `0.2`): Fraction of samples for testing.
    *   `split_method` (select, default: `random`): `random`, `stratified`, `sequential`.
    *   `random_seed` (number, default: `42`): Seed for reproducible splits.
    *   `shuffle` (boolean, default: `True`): Shuffle before splitting.
*   **Outputs**: `X_train`, `X_test`, `y_train` (if provided), `y_test` (if provided).
*   **Notes**: The split preserves y-axis labels in `X_train` and `X_test`. For stratified splits and `y_train`/`y_test` outputs, pass a target array into `y`.

#### Load Group **[SCP]**
*   **Node Type**: `data.load_group`
*   **Description**: Load multiple files from a folder and concatenate them. Uses SpectroChemPy file readers.
*   **Parameters**:
    *   `folder_path` (text): Path to folder.
    *   `pattern` (text, default: `*.spa`): File pattern (glob).
    *   `recursive` (boolean, default: `False`): Scan subdirectories.
    *   `sort_by` (select, default: `filename`): `filename`, `numeric_suffix`, `modified_time`.
    *   `validate_axes` (boolean, default: `True`): Ensure identical x-axes.
    *   `group_title` (text): Custom title for the grouped dataset.

#### NIST Library
*   **Node Type**: `data.nist_library`
*   **Description**: Loads a spectrum from the internal NIST database. Uses a standalone JCAMP-DX reader (no SpectroChemPy dependency).
*   **Parameters**:
    *   `library_id` (number): Database ID of the entry.

#### Synthetic Curve
*   **Node Type**: `data.synthetic_curve`
*   **Description**: Generates a concentration profile (for testing/simulation).
*   **Parameters**:
    *   `curve_type` (select): `sigmoid`, `gaussian`, `linear`, `exponential`, `step`.
    *   `n_points` (number): Length of the curve.
    *   `max_concentration` (number): Peak value.
    *   `center` (number): Center position (0-1).
    *   `width` (number): Curve width.

### Synthesis (Blending)

#### Blend
*   **Node Type**: `synthesis.blend`
*   **Description**: Create synthetic mixtures from multiple spectra inputs.
*   **Parameters**:
    *   `n_timepoints` (number, default: `100`): Time points in mixture.
    *   `model_type` (select, default: `linear`): `linear` (Beer-Lambert), `saturation`.
    *   `pathlength` (number, default: `0.01`): Pathlength in meters.
    *   `noise_level` (number, default: `0.01`): Noise fraction.

#### Species
*   **Node Type**: `synthesis.species`
*   **Description**: Mark a spectrum as a species component for blending.
*   **Parameters**:
    *   `species_name` (text): Name identifier.
    *   `molar_absorptivity` (number, default: `1.0`): Coefficient.

#### Merge Spectra
*   **Node Type**: `synthesis.merge`
*   **Description**: Combine multiple spectra into a single stacked dataset.
*   **Parameters**:
    *   `align_wavenumbers` (boolean, default: `True`): Interpolate to common grid.

### Visualization & Export

#### Plot
*   **Node Type**: `output.plot`
*   **Description**: Creates standard spectral or scatter plots.
*   **Parameters**:
    *   `plot_type` (select): `spectra`, `scores`, `loadings`, `scatter`.
    *   `x_axis` (number): Index/label for X.
    *   `y_axis` (number): Index/label for Y.

#### Contour Plot
*   **Node Type**: `output.contour`
*   **Description**: 2D heatmaps/contours for time-series or multi-sample data.
*   **Parameters**:
    *   `plot_type` (select): `heatmap`, `contour`, `surface`.
    *   `colorscale` (select): `Viridis`, `Hot`, `RdBu`, etc.
    *   `reverse_x` (boolean): Reverse X-axis (standard for IR).
    *   `transpose` (boolean): Swap axes.

#### Data Table
*   **Node Type**: `output.data_table`
*   **Description**: Interactive table for numerical results.
*   **Parameters**:
    *   `max_rows` (number, default: `100`).
    *   `transpose` (boolean).
    *   `show_index` (boolean).

#### Statistics
*   **Node Type**: `stats.summary`
*   **Description**: Comprehensive statistics (Mean, Std, Min/Max) for datasets.
*   **Parameters**:
    *   `compute_outliers` (boolean).
    *   `outlier_threshold` (number).
    *   `max_samples` (number).

#### Export
*   **Node Type**: `output.export`
*   **Description**: Save results to file.
*   **Parameters**:
    *   `filename` (text).
    *   `format` (select): `csv`, `json`, `jdx`.
