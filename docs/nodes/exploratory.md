# Exploratory Nodes

Exploratory nodes reveal structure before supervised modeling.

## PCA, Decomposition, and Curve Resolution

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| PCA (`model.pca`) | Explore variance, scores, loadings, outliers, and compressed features. | `default: Array2D` | `scores`; `loadings`; `explained_variance`; `model` | `n_components`; `standardized`; `scaled`. Uses Sherpa's native exact full-SVD authority. `n_components="mle"` uses Minka's automatic dimensionality method and requires `n_samples >= n_features`. Keep scaling choices consistent with your spectroscopy convention. |
| PCA Transform (`model.pca_transform`) | Project new spectra into an already fitted PCA model. | `X_new: SpectralDataset`; `model: DecompositionResult` | `scores: ScoreMatrix` | no parameters. Use the same preprocessing as the fitted PCA model. |
| NMF (`model.nmf`) | Resolve non-negative concentration-like and spectrum-like factors. | `default: SpectralDataset` | `concentrations`; `spectra`; `reconstruction_error`; `model` | `n_components`; `solver`; `max_iter`; `tol`. Input must be non-negative; use Clip Floor or baseline correction first if needed. |
| FastICA (`model.ica`) | Blind source separation when independent latent sources are plausible. | `default: SpectralDataset` | `sources`; `mixing_matrix`; `components`; `model` | `n_components`; `algorithm`; `fun`; `max_iter`; `tol`. |
| PARAFAC (`model.parafac`) | Resolve components in sample-first or spatial-first multiway data while keeping every physical mode distinct. | `default: SpectralDataset` with rank 3–6 and explicit mode roles | mode-1 `sample_scores`; `component_weights`; `relative_reconstruction_error`; data-free `model` | `n_components`; `max_iter`; `tol`; `ridge`. Uses deterministic native CP-ALS. A three-mode image cube may carry an exact binary mask over its first two spatial modes; every ALS update and the reconstruction error honor that mask. No hidden unfolding is performed. |
| MCR-ALS (`model.mcr_als`) | Resolve mixture concentration profiles and pure spectra with constraints. | `default: SpectralDataset` | `C`; `St`; `residuals`; `ground_truth_comparison`; `model` | `n_components`; `non_negative_C`; `non_negative_St`; `max_iter`; `tol`; `normSpec`; validation indices. Requires SpectroChemPy. |
| EFA (`model.efa`) | Estimate evolving rank/component count in ordered mixture or process data. | `default: SpectralDataset` | `forward_eigenvalues`; `backward_eigenvalues`; `model` | `n_components`. Requires SpectroChemPy. |
| SIMPLISMA (`model.simplisma`) | Estimate pure variables/components by purity maximization. | `default: SpectralDataset` | `concentrations`; `spectra`; `purity_values`; `model` | `n_components`; `tol`; `noise`. Requires SpectroChemPy. |

SpectroChemPy's MCR-ALS and baseline documentation are useful background for constrained curve-resolution thinking: <https://www.spectrochempy.fr/0.7.0/userguide/analysis/mcr_als.html> and <https://www.spectrochempy.fr/0.8.3/userguide/processing/baseline.html>.

PARAFAC is deliberately an expert-only canvas node in 0.6.0: no analysis
starter references it. A supported pixels-by-features Eigenvector image DSO
exposes a second, explicitly named image-cube scientific result. Select that
result and add `model.parafac` manually. The exact IASIM16 Test 1 source has a
private, data-free qualification receipt, but that exploratory decomposition
does not establish melamine detection or challenge performance.

## Clustering

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| HCA (`model.hca`) | Build hierarchical clusters and dendrograms from spectra or scores. | `default: Array2D` | `labels`; `cluster_summary`; `linkage_matrix`; `dendrogram_data`; `embedding`; `model` | `n_clusters`; `linkage`; `metric`. Ward linkage expects Euclidean distance. |
| K-Means (`model.kmeans`) | Partition samples into a chosen number of compact clusters. | `default: Array2D` | `labels`; `centroids`; `cluster_summary`; `embedding`; `model` | `n_clusters`; `n_init`; `max_iter`; `random_state`. |
| DBSCAN (`model.dbscan`) | Find density-based clusters and noise/outlier samples. | `default: Array2D` | `labels`; `cluster_summary`; `embedding`; `model` | `eps`; `min_samples`; `metric`. Tune `eps` carefully after scaling. |

## Peak and Library Nodes

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Peak Finding (`analysis.peak_finding`) | Detect candidate spectral peaks for interpretation, masking, or library workflows. | `default: SpectralDataset` | `peaks` (consensus PeakTable); `plots`; `per_spectrum` (measurement matrix) | `height`; `threshold`; `distance`; `prominence`; `width`; `consensus_tolerance`. Detection controls mirror SciPy `find_peaks`; consensus tolerance groups detections by their axis position. |
| Compare vs. Library (`analysis.compare_library`) | Rank a sample against selected reference spectra using HQI and cosine similarity. | `sample: SpectralDataset`; `library: SpectralDataset` | ranking dictionary with scores and diagnostics | `top_n`; `library_filter`; `hqi_mode`; diagnostic bands and overlap thresholds. |

PeakTable includes the numbered consensus group, position statistics, detection fraction, labels, and complete detection membership. The former Salient Features port is consolidated into this table; existing editable-workflow connections migrate automatically, while historical run records remain unchanged. Re-run the workflow after upgrading to generate the merged table.

For each spectrum, the measurement matrix contains four columns per consensus group: `peak_position_N`, `magnitude_at_peak_N`, `group_position_N`, and `magnitude_at_group_position_N`. An undetected peak leaves the first two values missing; the nearest measured coordinate to the consensus guide and its magnitude remain available. Connect either table to Data Table and use Quick Plot's Column selector to plot any scalar column against its one-based row index. A downstream Plot node offers the same column choice. Missing values remain gaps, text values use a categorical axis, and nested membership lists should be inspected in Data View.

SciPy documents the `find_peaks` controls for height, threshold, distance, prominence, and width here: <https://docs.scipy.org/doc/scipy-1.16.0/reference/generated/scipy.signal.find_peaks.html>.

### Peak-finding input and replay semantics

Numeric editors preserve typed decimals and scientific notation. They do not round
values to the suggested step or clamp them to a bound. Invalid entries remain
visible and block execution. Blank optional inputs are saved as `null`, which
becomes Python `None`.

| Field | Effective meaning |
| --- | --- |
| Height | Blank: `height=None`, no height filter. Otherwise a minimum in response units. |
| Threshold | Blank: `threshold=None`, no neighbor-threshold filter. Otherwise in response units. |
| Distance | New-node default: **10**, shown as an entered value. Clearing it passes `distance=None`. Legacy `0` also explicitly disables it; other values must be at least 1 sample point. |
| Prominence | Blank: `prominence=None`, no prominence filter. Otherwise in response units. |
| Width | Blank: `width=None`. Legacy `0` also explicitly disables the filter. Otherwise minimum half-prominence width in sample points. |
| Consensus tolerance | Required; default **0**, shown in the editor. Zero groups only identical positions. Positive values set the maximum consensus-bin span in feature-axis units. This is a Sherpa postprocessing setting, not a SciPy argument. |

New results retain the exact `scipy.signal.find_peaks` keyword arguments, including
`wlen=None`, `rel_height=0.5`, and `plateau_size=None`, together with the SciPy
version. **Executed peak-finding inputs** shows the retained call in both the
Inspector and expanded view. It describes the result's execution, independently
of subsequent edits to the settings. Historical results without that record are
explicitly marked unavailable; current settings are not used to reconstruct it.

Reported widths are measured separately using
`scipy.signal.peak_widths(spectrum, indices, rel_height=0.5, prominence_data=None, wlen=None)`
and mapped to the feature axis. To reproduce a run, use the same upstream spectral
matrix, axis and sample ordering as well as the recorded calls and version.
Consensus markers and full-height dotted vertical guides are visible in new plots.
Rerun Peak Finding to obtain these guides and the new matrix; historical run outputs are unchanged.

The **Per-spectrum Peak Matrix** output connects directly to **Data Table**. It retains
one row per spectrum and four columns for each consensus group `x` (numbered from 1
in ascending consensus-position order): `peak_position_x`, `magnitude_at_peak_x`,
`group_position_x`, and `magnitude_at_group_position_x`. The first pair is NaN when
no peak was detected for that spectrum. The second pair always uses the measured
feature coordinate nearest the consensus guide and its actual magnitude, without
interpolation. Equidistant coordinates use the lower coordinate. If a spectrum has
multiple detections within one group, the nearest detection to the guide supplies
the first pair (ties use the lower position); all detections remain in Peak List.
Column-specific units and the exact guide positions are retained as metadata.
The original **Peak List** remains the consensus/membership summary; connect the
new matrix output for a rectangular per-spectrum table and CSV export. Data Table's
Quick Plot offers each numeric column separately, with null detections left as gaps.

## Practical Use

Use exploratory nodes to understand variation, outliers, clusters, pure-component estimates, and candidate spectral features before locking in a calibration or classification model. Prefer scores plots for sample structure, loadings or coefficients for variable interpretation, and residual/limit plots for model adequacy.

LLM-assisted peak interpretation is available through the privacy-gated Sherpa Advisor conversation after deterministic Peak Finding. Advisor responses are human-reviewed interpretation, not canonical DAG execution or independently reproducible scientific evidence.
