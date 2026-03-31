# Node Reference

This reference lists the available processing nodes in the Workflow Builder, organized by toolbar section. Each node's type string, parameters, and port definitions are shown.

Nodes marked with **[SCP]** require [SpectroChemPy](https://www.spectrochempy.fr/) (`pip install spectra-sherpa[scp]`). All other nodes run on NumPy/SciPy/scikit-learn.

Nodes marked with **[Export]** support Python code export via the `/workflows/{id}/export/python` endpoint. The exported script reproduces the workflow as runnable Python code (requires `pip install spectra-sherpa`). Nodes without **[Export]** are visualization/output nodes or specialized algorithms not yet supported for export.

**Consolidated nodes** use a `method` dropdown to select among multiple algorithms.

---

## Data Nodes

#### Data Source **[Export]**
*   **Node Type**: `data.source`
*   **Description**: Generic data loader for bundled examples, uploaded experiment files, and direct file-backed sources.
*   **Parameters**:
    *   `source` (select): `spectrochempy`, `sklearn`, `eigenvector`, `file`, `experiment`.
    *   `example_dataset` (select): `irdata`, `ramandata`, `nmrdata`.
    *   `sklearn_dataset` (select): `iris`, `wine`, `breast_cancer`, `digits`.
    *   `eigenvector_dataset` (select): Eigenvector Research benchmarks (`diesel_nir`, `corn_m5`, `nir_shootout_cal1`, etc.).
    *   `example_file` (text): Specific file within example dataset (e.g., `CO@Mo_Al2O3.SPG`).
    *   `experiment_id` (number): Experiment to load when `source=experiment`.
    *   `file_id` (number): Optional specific file within the experiment.
    *   `stage` (select): Experiment stage such as `raw`.
    *   `file_path` (text): Absolute path (for file source).
    *   `transpose_on_load` (boolean): Swap rows/cols.
*   **Outputs**: `default` (Dataset), `target` (target/property values if available).
*   **Notes**: Export is supported for built-in reference datasets as well as `file` and `experiment` sources. For file-backed and experiment-backed workflows, the exported Python/notebook code loads from a relative `data/` directory by default and can be redirected with `SHERPA_DATA_DIR`. Data/Explore overrides such as x-axis name, x-axis units, data quantity, and time-series status are emitted as explicit assignments in the exported code so runnable exports stay aligned with the prepared dataset used in the GUI.

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

#### My Dataset
*   **Node Type**: `data.my_dataset`
*   **Description**: Load from your personal dataset collection.

#### File Load
*   **Node Type**: `data.file_load`
*   **Description**: Load spectral data from local files.

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

#### Attach Target **[Export]**
*   **Node Type**: `data.attach_target`
*   **Description**: Attach target values to a dataset for supervised modeling.
*   **Inputs**: `X` (Dataset), `y` (Target values).
*   **Parameters**:
    *   `target_type` (select, default: `continuous`): `continuous`, `categorical`.
*   **Outputs**: Dataset with embedded target values.

#### Train/Test Split **[Export]**
*   **Node Type**: `data.train_test_split`
*   **Description**: Split a dataset into training and test subsets.
*   **Inputs**: `X` (Dataset), `y` (Targets - optional, used for stratified splits).
*   **Parameters**:
    *   `test_size` (number, default: `0.2`): Fraction of samples for testing.
    *   `split_method` (select, default: `random`): `random`, `stratified`, `sequential`.
    *   `random_seed` (number, default: `42`): Seed for reproducible splits.
    *   `shuffle` (boolean, default: `True`): Shuffle before splitting.
*   **Outputs**: `X_train`, `X_test`, `y_train` (if provided), `y_test` (if provided).

---

## Synthesis Nodes

#### Species
*   **Node Type**: `synthesis.species`
*   **Description**: Mark a spectrum as a species component for blending.
*   **Parameters**:
    *   `species_name` (text): Name identifier.
    *   `molar_absorptivity` (number, default: `1.0`): Coefficient.

#### Blend
*   **Node Type**: `synthesis.blend`
*   **Description**: Create synthetic mixtures from multiple spectra inputs.
*   **Parameters**:
    *   `n_timepoints` (number, default: `100`): Time points in mixture.
    *   `model_type` (select, default: `linear`): `linear` (Beer-Lambert), `saturation`.
    *   `pathlength` (number, default: `0.01`): Pathlength in meters.
    *   `noise_level` (number, default: `0.01`): Noise fraction.

#### Merge Spectra
*   **Node Type**: `synthesis.merge`
*   **Description**: Combine multiple spectra into a single stacked dataset.
*   **Parameters**:
    *   `align_wavenumbers` (boolean, default: `True`): Interpolate to common grid.

---

## Preprocessing Nodes

### Consolidated Nodes

These nodes consolidate multiple related algorithms behind a single `method` dropdown. The Inspector panel hides irrelevant parameters automatically via conditional visibility (`visible_when`).

#### Smooth **[Export]**
*   **Node Type**: `preprocess.smooth`
*   **Description**: Smoothing filters for noise reduction.
*   **Method** (select): `savitzky_golay`, `whittaker`, `gaussian`.
*   **Parameters**:
    *   `size` (number, default: `11`): Window size — must be odd. *Visible when: savitzky_golay.*
    *   `order` (number, default: `2`): Polynomial order. *Visible when: savitzky_golay.*
    *   `lam` (number, default: `1000`): Smoothness parameter. *Visible when: whittaker.*
    *   `d` (number, default: `2`): Difference order. *Visible when: whittaker.*
    *   `sigma` (number, default: `2.0`): Gaussian standard deviation. *Visible when: gaussian.*

#### Derivative **[Export]**
*   **Node Type**: `preprocess.derivative`
*   **Description**: Compute spectral derivatives.
*   **Method** (select): `savitzky_golay`, `norris_williams`.
*   **Parameters**:
    *   `deriv` (select, default: `1`): Derivative order (`0`, `1`, `2`).
    *   `size` (number, default: `11`): Window size. *Visible when: savitzky_golay.*
    *   `order` (number, default: `2`): Polynomial order. *Visible when: savitzky_golay.*
    *   `gap` (number, default: `5`): Gap size. *Visible when: norris_williams.*
    *   `segment` (number, default: `5`): Segment size. *Visible when: norris_williams.*

#### Normalize **[Export]**
*   **Node Type**: `preprocess.normalize`
*   **Description**: Normalize spectra using scatter correction or scaling methods.
*   **Method** (select): `snv`, `msc`, `scale`.
*   **Parameters**:
    *   `reference` (select, default: `mean`): Reference spectrum (`mean`, `median`, `first`). *Visible when: msc.*
    *   `scale_method` (select, default: `max`): Scaling method (`max`, `area`, `minmax`). *Visible when: scale.*
*   **Notes**: EMSC (Extended MSC) remains a separate node due to its dual input ports and polynomial baseline logic.

#### Scale / Center **[Export]**
*   **Node Type**: `preprocess.scale`
*   **Description**: Scale or center spectra.
*   **Method** (select): `mean_center`, `autoscale`, `pareto`, `scale_max`.
*   **Parameters**:
    *   `center` (boolean, default: `True`): Subtract mean before scaling. *Visible when: autoscale, pareto.*
    *   `target_max` (number, default: `1.0`): Target maximum value. *Visible when: scale_max.*

### Baseline Correction

#### Baseline (Penalized LS) **[Export]**
*   **Node Type**: `baseline.penalized_ls`
*   **Description**: Penalized least squares baseline correction.
*   **Method** (select): `als`, `arpls`, `airpls`.
*   **Parameters**:
    *   `lam` (number, default: `100000`): Smoothness parameter. Range: 1e2 – 1e9.
    *   `p` (number, default: `0.001`): Asymmetry parameter. *Visible when: als.* Range: 0.0001 – 0.1.

#### Baseline (Rubberband) **[SCP]** **[Export]**
*   **Node Type**: `baseline.rubberband`
*   **Description**: Convex hull "rubberband" baseline correction.
*   **Powered by**: [spectrochempy.basc](https://www.spectrochempy.fr/reference/generated/spectrochempy.basc.html)
*   **Parameters**:
    *   `ranges` (text): Optional spectral ranges to force baseline points (e.g., `'4000:3800, 1800:1700'`).

### Advanced Correction

#### EMSC **[Export]**
*   **Node Type**: `preprocess.emsc`
*   **Description**: Extended MSC with polynomial baseline correction.
*   **Parameters**:
    *   `reference` (select, default: `mean`): Reference spectrum (`mean`, `median`, `first`).
    *   `poly_order` (number, default: `2`): Order of polynomial baseline.

#### OSC Filter **[SCP]** **[Export]**
*   **Node Type**: `preprocess.osc`
*   **Description**: Orthogonal Signal Correction — removes variation uncorrelated with Y.
*   **Powered by**: [spectrochempy.PLSRegression](https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html)
*   **Parameters**:
    *   `n_components` (number, default: `1`): Number of orthogonal components.
    *   `tol` (number, default: `1e-6`): Convergence tolerance.
    *   `max_iter` (number, default: `100`): Maximum iterations.

#### Cosmic Ray Removal **[Export]**
*   **Node Type**: `preprocess.cosmic_ray`
*   **Description**: Removes spike-like outliers (cosmic rays) using local median statistics.
*   **Parameters**:
    *   `window` (number, default: `7`): Window size for local statistics (must be odd).
    *   `zscore` (number, default: `3.0`): Z-score threshold for detection.

### Utilities

#### Clip Range **[Export]**
*   **Node Type**: `preprocess.clip_range`
*   **Description**: Crops data to a specific wavenumber region.
*   **Parameters**:
    *   `min_wavenumber` (number, default: `400`): Lower bound.
    *   `max_wavenumber` (number, default: `4000`): Upper bound.

#### Clip Floor **[Export]**
*   **Node Type**: `preprocess.clip_floor`
*   **Description**: Sets a minimum value floor (e.g., to remove negative absorbance).
*   **Parameters**:
    *   `floor` (number, default: `0.0`): Minimum allowed value.

#### Wavenumber Align **[Export]**
*   **Node Type**: `preprocess.wavenumber_align`
*   **Description**: Align spectra to a common wavenumber grid via interpolation.
*   **Parameters**:
    *   `method` (select, default: `pchip`): `pchip`, `linear`, `sinc`.
    *   `merge_tolerance` (number, default: `0.5`): Tolerance for merging near-duplicate points.

### Time Series

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

## Exploratory Nodes

#### PCA **[SCP]** **[Export]**
*   **Node Type**: `model.pca`
*   **Description**: Principal Component Analysis.
*   **Powered by**: [spectrochempy.PCA](https://www.spectrochempy.fr/reference/generated/spectrochempy.PCA.html)
*   **Parameters**:
    *   `n_components` (text, default: `5`): Number of components (int), 'mle', or variance ratio (float 0-1).
    *   `standardized` (boolean, default: `False`): Apply standardization.
    *   `scaled` (boolean, default: `False`): Apply scaling.

#### Apply PCA **[SCP]**
*   **Node Type**: `model.pca_transform`
*   **Description**: Transform new data using a trained PCA model.
*   **Inputs**: `X_new` (Spectra), `model` (PCA model).
*   **Outputs**: Scores in PCA space.

#### MCR-ALS **[SCP]** **[Export]**
*   **Node Type**: `model.mcr_als`
*   **Description**: Multivariate Curve Resolution — Alternating Least Squares. Resolves mixtures into pure components.
*   **Powered by**: [spectrochempy.MCRALS](https://www.spectrochempy.fr/reference/generated/spectrochempy.MCRALS.html)
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of pure components.
    *   `max_iter` (number, default: `50`): Maximum iterations.
    *   `tol` (number, default: `0.1`): Convergence tolerance.
    *   `non_negative_C` (boolean, default: `True`): Enforce non-negative concentrations.
    *   `non_negative_St` (boolean, default: `True`): Enforce non-negative spectra.

#### SIMPLISMA **[SCP]** **[Export]**
*   **Node Type**: `model.simplisma`
*   **Description**: Self-modeling mixture analysis using purity maximization. Identifies pure variables in spectral mixtures.
*   **Powered by**: [spectrochempy.SIMPLISMA](https://www.spectrochempy.fr/reference/generated/spectrochempy.SIMPLISMA.html)
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of pure components to resolve.
    *   `tol` (number, default: `0.1`): Convergence tolerance.
    *   `noise` (number, default: `3.0`): Noise level threshold.
*   **Outputs**: `model`, `concentrations`, `spectra` (pure component spectra), `purity_values`.

#### EFA **[SCP]** **[Export]**
*   **Node Type**: `model.efa`
*   **Description**: Evolving Factor Analysis. Determines chemical rank of evolving systems.
*   **Powered by**: [spectrochempy.EFA](https://www.spectrochempy.fr/reference/generated/spectrochempy.EFA.html)
*   **Parameters**:
    *   `n_components` (number, default: `10`): Number of eigenvalues to compute.

#### NMF **[Export]**
*   **Node Type**: `model.nmf`
*   **Description**: Non-negative Matrix Factorization.
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of components.
    *   `max_iter` (number, default: `200`): Maximum iterations.

#### ICA **[Export]**
*   **Node Type**: `model.ica`
*   **Description**: Independent Component Analysis (FastICA).
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of independent components.

#### Peak Finding
*   **Node Type**: `analysis.peak_finding`
*   **Description**: Identifies peaks using `scipy.signal`.
*   **Parameters**:
    *   `height` (number): Minimum peak height.
    *   `threshold` (number): Minimum vertical distance to neighbors.
    *   `distance` (number, default: `10`): Minimum horizontal distance (points).
    *   `prominence` (number): Peak prominence.
    *   `width` (number): Expected peak width.

---

## Regression Nodes

#### PLS **[SCP]** **[Export]**
*   **Node Type**: `model.pls`
*   **Description**: Partial Least Squares Regression.
*   **Powered by**: [spectrochempy.PLSRegression](https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html)
*   **Inputs**: `X` (Spectra), `y` (Concentrations).
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of latent variables.
    *   `scale` (boolean, default: `True`): Auto-scale data.

#### Apply PLS **[SCP]** **[Export]**
*   **Node Type**: `model.pls_predict`
*   **Description**: Predict using a trained PLS model.
*   **Inputs**: `X_new` (Spectra), `model` (PLS model).
*   **Outputs**: Predicted Y values.

#### PCR **[Export]**
*   **Node Type**: `model.pcr`
*   **Description**: Principal Component Regression (PCA + Linear Regression).
*   **Inputs**: `X` (Spectra), `y` (Targets).
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of PCA components.
    *   `scale` (boolean, default: `True`): Auto-scale data.

#### SVR **[Export]**
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

#### Linear Regression **[Export]**
*   **Node Type**: `model.linear_regression`
*   **Description**: Simple linear regression.
*   **Parameters**:
    *   `fit_intercept` (boolean, default: `True`): Calculate intercept.

#### Load & Apply Model **[Export]**
*   **Node Type**: `model.load_apply`
*   **Description**: Load a saved model artifact and apply it to new data. Supports all model types: PCA, PLS, MCR, SIMPLISMA (transform), PLS-DA, KNN, SIMCA (classify). EFA models cannot be applied (diagnostic only).
*   **Inputs**: `X_new` (SpectralDataset), `model_ref` (ModelReference — optional, overrides parameter).
*   **Parameters**:
    *   `model_id` (model_select): UUID of the saved model artifact.
*   **Outputs**: `result` (transformed/predicted data), `labels` (class labels, classification only), `model_id` (artifact UID).
*   **Notes**: The model_ref input port takes priority over the model_id parameter. Use the model selector in the inspector to browse saved models.

---

## Classification Nodes

#### PLS-DA **[SCP]** **[Export]**
*   **Node Type**: `classification.plsda`
*   **Description**: Partial Least Squares Discriminant Analysis.
*   **Powered by**: [spectrochempy.PLSRegression](https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html)
*   **Inputs**: `X` (Spectra), `y` (Classes — optional, auto-extracted from X).
*   **Parameters**:
    *   `n_components` (number, default: `2`): Number of components.
    *   `scale` (boolean, default: `True`): Scale data.
    *   `cv_folds` (number, default: `5`): Cross-validation folds.
*   **Outputs**: Model dict with train/CV predictions, confusion matrices, and classification report.
*   **Notes**: If `X` includes class labels in its y-axis, you can omit `y` to auto-extract. For train/test workflows, split data with `data.train_test_split`, train on `X_train`, then feed the model output into `classification.predict` along with `X_test`.

#### KNN Classifier **[Export]**
*   **Node Type**: `classification.knn`
*   **Description**: K-Nearest Neighbors classification.
*   **Inputs**: `X` (Features), `y` (Classes — optional).
*   **Parameters**:
    *   `n_neighbors` (number, default: `5`): Number of neighbors (k).
    *   `weights` (select, default: `uniform`): `uniform`, `distance`.
    *   `metric` (select, default: `euclidean`): Distance metric.
    *   `cv_folds` (number, default: `5`): Cross-validation folds.
*   **Outputs**: Model dict with train/CV predictions, confusion matrices, and classification report.

#### SIMCA **[SCP]** **[Export]**
*   **Node Type**: `classification.simca`
*   **Description**: Soft Independent Modeling of Class Analogy. Builds per-class PCA models and classifies based on Hotelling T² and Q residual distances.
*   **Inputs**: `X` (Features), `y` (Classes — optional).
*   **Parameters**:
    *   `n_components` (number, default: `3`): Number of PCs per class.
    *   `confidence_level` (number, default: `0.95`): For T² and Q limits.
*   **Outputs**: Model dict with predictions, confusion matrix, and classification report.

#### Apply Classifier **[Export]**
*   **Node Type**: `classification.predict`
*   **Description**: Apply a trained classification model (PLS-DA, KNN, or SIMCA) to new samples. Auto-detects the model type from the input dict.
*   **Inputs**: `X_new` (Spectra), `model` (Trained model dict from any classification training node).
*   **Outputs**: `y_pred` (Predicted classes), `y_prob` (Class probabilities or distances).
*   **Notes**: Replaces the individual Apply PLS-DA, Apply KNN, and Apply SIMCA nodes. PLS-DA prediction requires SpectroChemPy; KNN and SIMCA prediction use pure numpy/sklearn.

---

## Clustering Nodes

#### K-Means **[Export]**
*   **Node Type**: `model.kmeans`
*   **Description**: K-Means clustering.
*   **Parameters**:
    *   `n_clusters` (number, default: `3`): Number of clusters.
    *   `n_init` (number, default: `10`): Number of initializations.
    *   `max_iter` (number, default: `300`): Max iterations.
    *   `random_state` (number, default: `42`): Random seed.

#### DBSCAN **[Export]**
*   **Node Type**: `model.dbscan`
*   **Description**: Density-Based Spatial Clustering of Applications with Noise.
*   **Parameters**:
    *   `eps` (number, default: `0.5`): Neighborhood radius.
    *   `min_samples` (number, default: `5`): Minimum samples per cluster.
    *   `metric` (select, default: `euclidean`): Distance metric.

#### HCA **[Export]**
*   **Node Type**: `model.hca`
*   **Description**: Hierarchical Cluster Analysis (Agglomerative).
*   **Parameters**:
    *   `n_clusters` (number, default: `3`): Number of clusters.
    *   `linkage` (select, default: `ward`): `ward`, `average`, `complete`, `single`.
    *   `metric` (select, default: `euclidean`): Distance metric.
*   **Outputs**: Cluster labels and 2D embedding for visualization.

---

## Validation Nodes

#### Cross-Validation **[Export]**
*   **Node Type**: `diagnostics.cross_validation`
*   **Description**: Computes regression or classification metrics from paired `y_true` and `y_pred`.
*   **Inputs**: `y_true`, `y_pred`.
*   **Parameters**:
    *   `cv_folds` (number, default: `5`): Number of folds.
*   **Outputs**: For classification, accuracy, confusion matrix, and a classification report. For regression, RMSE, MAE, R², Q², and residuals.

#### Outlier Detection **[Export]**
*   **Node Type**: `diagnostics.outliers`
*   **Description**: Hotelling T² and Q statistics for PCA models.
*   **Inputs**: `PCAModel`.
*   **Parameters**:
    *   `confidence_level` (number, default: `0.95`): Limit threshold.

#### Statistics
*   **Node Type**: `stats.summary`
*   **Description**: Comprehensive statistics (Mean, Std, Min/Max) for datasets.
*   **Parameters**:
    *   `compute_outliers` (boolean).
    *   `outlier_threshold` (number).
    *   `max_samples` (number).

---

## Output Nodes

#### Scatter Plot
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

#### Export
*   **Node Type**: `output.export`
*   **Description**: Save results to file.
*   **Parameters**:
    *   `filename` (text).
    *   `format` (select): `csv`, `json`, `jdx`.

---

## Deployment Nodes

These nodes act as entry and exit points for headless prediction pipelines (batch prediction, folder watching, and the headless serve-model API).

#### Deploy Input **[Export]**
*   **Node Type**: `deploy.input`
*   **Description**: Injects external data streams into prediction pipelines. In interactive (bench) mode, returns dummy data. In deploy mode, the execution engine injects the actual payload.
*   **Parameters**:
    *   `stream_name` (text, default: `sample`): Unique identifier for the incoming data stream.

#### Deploy Output **[Export]**
*   **Node Type**: `deploy.output`
*   **Description**: Formats results for the headless prediction server API.
*   **Parameters**:
    *   `output_format` (select, default: `json`): `json`, `csv`, `plain_text`.
    *   `key_value_separator` (text, default: `=`): Separator for plain_text mode.
    *   `end_of_message_tag` (text, default: `\n`): Termination string for plain_text mode.
