# Exploratory Nodes

Exploratory nodes reveal structure before supervised modeling.

## PCA, Decomposition, and Curve Resolution

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| PCA (`model.pca`) | Explore variance, scores, loadings, outliers, and compressed features. | `default: Array2D` | `scores`; `loadings`; `explained_variance`; `model` | `n_components`; `standardized`; `scaled`. Requires SpectroChemPy. Keep scaling choices consistent with your spectroscopy convention. |
| PCA Transform (`model.pca_transform`) | Project new spectra into an already fitted PCA model. | `X_new: SpectralDataset`; `model: DecompositionResult` | `scores: ScoreMatrix` | no parameters. Use the same preprocessing as the fitted PCA model. |
| NMF (`model.nmf`) | Resolve non-negative concentration-like and spectrum-like factors. | `default: SpectralDataset` | `concentrations`; `spectra`; `reconstruction_error`; `model` | `n_components`; `solver`; `max_iter`; `tol`. Input must be non-negative; use Clip Floor or baseline correction first if needed. |
| FastICA (`model.ica`) | Blind source separation when independent latent sources are plausible. | `default: SpectralDataset` | `sources`; `mixing_matrix`; `components`; `model` | `n_components`; `algorithm`; `fun`; `max_iter`; `tol`. |
| MCR-ALS (`model.mcr_als`) | Resolve mixture concentration profiles and pure spectra with constraints. | `default: SpectralDataset` | `C`; `St`; `residuals`; `ground_truth_comparison`; `model` | `n_components`; `non_negative_C`; `non_negative_St`; `max_iter`; `tol`; `normSpec`; validation indices. Requires SpectroChemPy. |
| EFA (`model.efa`) | Estimate evolving rank/component count in ordered mixture or process data. | `default: SpectralDataset` | `forward_eigenvalues`; `backward_eigenvalues`; `model` | `n_components`. Requires SpectroChemPy. |
| SIMPLISMA (`model.simplisma`) | Estimate pure variables/components by purity maximization. | `default: SpectralDataset` | `concentrations`; `spectra`; `purity_values`; `model` | `n_components`; `tol`; `noise`. Requires SpectroChemPy. |

SpectroChemPy's MCR-ALS and baseline documentation are useful background for constrained curve-resolution thinking: <https://www.spectrochempy.fr/0.7.0/userguide/analysis/mcr_als.html> and <https://www.spectrochempy.fr/0.8.3/userguide/processing/baseline.html>.

## Clustering

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| HCA (`model.hca`) | Build hierarchical clusters and dendrograms from spectra or scores. | `default: Array2D` | `labels`; `cluster_summary`; `linkage_matrix`; `dendrogram_data`; `embedding`; `model` | `n_clusters`; `linkage`; `metric`. Ward linkage expects Euclidean distance. |
| K-Means (`model.kmeans`) | Partition samples into a chosen number of compact clusters. | `default: Array2D` | `labels`; `centroids`; `cluster_summary`; `embedding`; `model` | `n_clusters`; `n_init`; `max_iter`; `random_state`. |
| DBSCAN (`model.dbscan`) | Find density-based clusters and noise/outlier samples. | `default: Array2D` | `labels`; `cluster_summary`; `embedding`; `model` | `eps`; `min_samples`; `metric`. Tune `eps` carefully after scaling. |

## Peak and Library Nodes

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Peak Finding (`analysis.peak_finding`) | Detect candidate spectral peaks for interpretation, masking, or library workflows. | `default: SpectralDataset` | `peaks`; `annotated_spectrum`; `spectrum` | `height`; `threshold`; `distance`; `prominence`; `width`. These mirror the main controls in SciPy `find_peaks`. |
| Peak ID (`analysis.peak_id`) | Ask the configured primary LLM for tentative vibration assignments for detected peaks. | `peaks: Array1D` | assigned peak list | `compound`; `max_peaks`; `min_relative_height`. Treat as interpretive assistance, not proof. |
| Compare vs. Library (`analysis.compare_library`) | Rank a sample against selected reference spectra using HQI and cosine similarity. | `sample: SpectralDataset`; `library: SpectralDataset` | ranking dictionary with scores and diagnostics | `top_n`; `library_filter`; `hqi_mode`; diagnostic bands and overlap thresholds. |

SciPy documents the `find_peaks` controls for height, threshold, distance, prominence, and width here: <https://docs.scipy.org/doc/scipy-1.16.0/reference/generated/scipy.signal.find_peaks.html>.

## Practical Use

Use exploratory nodes to understand variation, outliers, clusters, pure-component estimates, and candidate spectral features before locking in a calibration or classification model. Prefer scores plots for sample structure, loadings or coefficients for variable interpretation, and residual/limit plots for model adequacy.
