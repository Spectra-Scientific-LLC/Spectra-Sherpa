# Exploratory Nodes

!!! abstract "Summary"
    Reference: nodes for exploring data without targets — PCA, clustering, peak finding, and related diagnostics.

Exploratory nodes reveal structure before supervised modeling.

## PCA, Decomposition, and Curve Resolution

- [`model.pca`](exploratory.md#registry-reference): Explore variance, scores, loadings, outliers, and compressed features. Uses Sherpa's native exact full-SVD authority. `n_components="mle"` uses Minka's automatic dimensionality method and requires `n_samples >= n_features`. Keep scaling choices consistent with your spectroscopy convention.
- [`model.pca_transform`](exploratory.md#registry-reference): Project new spectra into an already fitted PCA model. Use the same preprocessing as the fitted PCA model.
- [`model.nmf`](exploratory.md#registry-reference): Resolve non-negative concentration-like and spectrum-like factors. Input must be non-negative; use Clip Floor or baseline correction first if needed.
- [`model.ica`](exploratory.md#registry-reference): Blind source separation when independent latent sources are plausible.
- [`model.parafac`](exploratory.md#registry-reference): Resolve components in sample-first or spatial-first multiway data while keeping every physical mode distinct. Input rank is 3–6 with explicit mode roles. Uses deterministic native CP-ALS. A three-mode image cube may carry an exact binary mask over its first two spatial modes; every ALS update and the reconstruction error honor that mask. No hidden unfolding is performed.
- [`model.mcr_als`](exploratory.md#registry-reference): Resolve mixture concentration profiles and pure spectra with constraints. Requires SpectroChemPy.
- [`model.efa`](exploratory.md#registry-reference): Estimate evolving rank/component count in ordered mixture or process data. Requires SpectroChemPy.
- [`model.simplisma`](exploratory.md#registry-reference): Estimate pure variables/components by purity maximization. Requires SpectroChemPy.

MCR and FastICA application also require the recorded feature axis and signal
identity; refit older states that lack this information.

PCA rejects requested components whose eigenvalues are at or below `1e-12`
times the largest retained eigenvalue. Reduce `n_components` to the resolved
numerical rank. PCA and outlier screening use this same relative tolerance and
the same T² calculation, without an absolute eigenvalue floor. Calibration T²
uses the Jackson F limit without the new-sample mean-uncertainty factor. Q uses
the Jackson–Mudholkar residual-spectrum limit, with an explicitly reported
chi-squared moment fallback if the JM shape parameter is nonpositive. When all feature
directions are retained, Q is zero because no orthogonal residual space remains;
floating-point reconstruction error alone does not create Q outliers.

PCA Transform requires the fitted signal units, quantity, and measurement mode
as well as the fitted feature axis. Explicitly convert incompatible inputs and
refit PCA states created before this input identity was recorded.

Library comparison also requires matching signal units, quantity, and measurement
mode before similarity scoring. Convert percent transmittance to absorbance
explicitly when comparing against an absorbance library.

SpectroChemPy's MCR-ALS and baseline documentation are useful background for constrained curve-resolution thinking: <https://www.spectrochempy.fr/0.7.0/userguide/analysis/mcr_als.html> and <https://www.spectrochempy.fr/0.8.3/userguide/processing/baseline.html>.

PARAFAC is deliberately an expert-only canvas node in 0.6.0: no analysis
starter references it. A supported pixels-by-features Eigenvector image DSO
exposes a second, explicitly named image-cube scientific result. Select that
result and add `model.parafac` manually. The exact IASIM16 Test 1 source has a
private, data-free qualification receipt, but that exploratory decomposition
does not establish melamine detection or challenge performance.

## Clustering

- [`model.hca`](exploratory.md#registry-reference): Build hierarchical clusters and dendrograms from spectra or scores. Ward linkage expects Euclidean distance.
- [`model.kmeans`](exploratory.md#registry-reference): Partition samples into a chosen number of compact clusters.
- [`model.dbscan`](exploratory.md#registry-reference): Find density-based clusters and noise/outlier samples. Tune `eps` carefully after scaling.

## Peak and Library Nodes

- [`analysis.peak_finding`](exploratory.md#registry-reference): Detect candidate spectral peaks for interpretation, masking, or library workflows. Detection controls mirror SciPy `find_peaks`; consensus tolerance groups detections by their axis position.
- [`analysis.compare_library`](exploratory.md#registry-reference): Rank a sample against selected reference spectra using HQI and cosine similarity.

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
| Distance | Clearing it passes `distance=None`. Legacy `0` also explicitly disables it; other values must be at least 1 sample point. See the generated reference for the new-node default. |
| Prominence | Blank: `prominence=None`, no prominence filter. Otherwise in response units. |
| Width | Blank: `width=None`. Legacy `0` also explicitly disables the filter. Otherwise minimum half-prominence width in sample points. |
| Consensus tolerance | Zero groups only identical positions. Positive values set the maximum consensus-bin span in feature-axis units. This is a Sherpa postprocessing setting, not a SciPy argument. See the generated reference for its default and admission metadata. |

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

The Q limit follows [Eigenvector's residual-limit convention](https://www.eigenvectordocs.com/index.php?title=Residuallimit),
and the calibration T² limit follows [its documented F formula](https://www.eigenvectordocs.com/index.php?title=Tsqlim).
These are model-based screening limits, not robust-fit guarantees or independent validation.

<!-- BEGIN GENERATED NODE REFERENCE -->

<!-- NODE HELP REFERENCES {"help_reference": "docs/nodes/exploratory.md", "node_types": ["analysis.compare_library", "analysis.peak_finding", "model.dbscan", "model.efa", "model.hca", "model.ica", "model.kmeans", "model.mcr_als", "model.nmf", "model.parafac", "model.pca", "model.pca_transform", "model.simplisma"]} -->

## Registry reference

Generated from registered node metadata. Edit methodology and examples outside the marked section.
Defaults and options below are JSON values; `null` means no concrete default is declared.
Internal parameters are retained for contract inspection and are not scientist-editable controls.
Conditional visibility describes the editor; execution admission remains node-owned.

| Node | Operation |
| --- | --- |
| Compare vs. Library | <code>analysis.compare_library</code> |
| Peak Finding | <code>analysis.peak_finding</code> |
| Fit DBSCAN Clustering | <code>model.dbscan</code> |
| Fit EFA Decomposition | <code>model.efa</code> |
| Fit HCA Clustering | <code>model.hca</code> |
| Fit FastICA Decomposition | <code>model.ica</code> |
| Fit K-Means Clustering | <code>model.kmeans</code> |
| Fit MCR-ALS Decomposition | <code>model.mcr_als</code> |
| Fit NMF Decomposition | <code>model.nmf</code> |
| Fit PARAFAC Decomposition | <code>model.parafac</code> |
| Fit PCA Transform | <code>model.pca</code> |
| Apply PCA Transform | <code>model.pca_transform</code> |
| Fit SIMPLISMA Pure Components | <code>model.simplisma</code> |

### Compare vs. Library (`analysis.compare_library`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>sample</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>library</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/Comparison/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>data</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>metadata</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>ranking</code> | <code>spectrasherpa://types/Comparison/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>hqi_report</code> | <code>spectrasherpa://types/Comparison/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>best_matches</code> | <code>spectrasherpa://types/Comparison/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>plots</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>top_n</code> | <code>number</code> | <code>false</code> | <code>10</code> | — | <code>{&quot;max_value&quot;: 10000, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of ranked library species to report for each sample spectrum Bounds ranking output size and pairwise local-worker cost. |
| <code>library_filter</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Optional comma-separated library labels to compare; blank compares all library spectra |
| <code>hqi_mode</code> | <code>select</code> | <code>false</code> | <code>&quot;whole_spectrum&quot;</code> | <code>[&quot;whole_spectrum&quot;, &quot;band_limited&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Whole-spectrum uses conventional full-overlap HQI. Band-limited uses library diagnostic bands scaled by each band peak, which is better for multi-component mixture screening. |
| <code>diagnostic_band_threshold</code> | <code>number</code> | <code>false</code> | <code>0.2</code> | — | <code>{&quot;max_value&quot;: 1, &quot;min_value&quot;: 0, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Library relative peak threshold used to define band-limited HQI regions A relative diagnostic-band threshold is a fraction of the library peak. |
| <code>hqi_accept_threshold</code> | <code>number</code> | <code>false</code> | <code>750</code> | — | <code>{&quot;max_value&quot;: 1000, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Mark candidates at or above this HQI as auto-selected for review The declared HQI scale spans zero through 1000. |
| <code>hqi_reject_threshold</code> | <code>number</code> | <code>false</code> | <code>500</code> | — | <code>{&quot;max_value&quot;: 1000, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | If a sample&#x27;s best HQI is below this value, mark every candidate for that sample as rejected The declared HQI scale spans zero through 1000. |
| <code>min_overlap_coverage</code> | <code>number</code> | <code>false</code> | <code>0.5</code> | — | <code>{&quot;max_value&quot;: 1, &quot;min_value&quot;: 0, &quot;step&quot;: 0.05}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum fraction of both spectra&#x27;s x-axis span required before strong or excellent HQI labels are allowed Overlap coverage is a fraction of each spectrum&#x27;s measured span. |
| <code>min_overlap_points</code> | <code>number</code> | <code>false</code> | <code>20</code> | — | <code>{&quot;max_value&quot;: 1000000, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum matched x-axis points required before strong or excellent HQI labels are allowed Bounds resampled vectors and pairwise local-worker memory. |
| <code>baseline_gap_threshold</code> | <code>number</code> | <code>false</code> | <code>0.25</code> | — | <code>{&quot;max_value&quot;: 2, &quot;min_value&quot;: 0, &quot;step&quot;: 0.05}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Flag matches where uncentered cosine exceeds Pearson correlation by this amount, suggesting baseline or offset dominance The maximum gap between two similarities on [-1, 1] is two. |

### Peak Finding (`analysis.peak_finding`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>peaks</code> | <code>spectrasherpa://types/PeakTable/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>plots</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>per_spectrum</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>height</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum peak height in response units. Blank passes height=None (no height filter). |
| <code>threshold</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum vertical distance to neighbors in response units. Blank passes threshold=None. |
| <code>distance</code> | <code>number</code> | <code>false</code> | <code>10</code> | — | <code>{&quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum horizontal distance in sample points (default 10). Blank or 0 passes distance=None (disabled); otherwise must be &gt;= 1. |
| <code>prominence</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum prominence in response units. Blank passes prominence=None (no prominence filter). |
| <code>width</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum width at half prominence in sample points. Blank or 0 passes width=None (no width filter). |
| <code>consensus_tolerance</code> | <code>number</code> | <code>true</code> | <code>0.0</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Maximum span of one cross-sample consensus bin in feature-axis units; enter 0 to group only identical positions. Required; not a SciPy find_peaks argument. |

### Fit DBSCAN Clustering (`model.dbscan`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/FittedModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>labels</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>cluster_assignment</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>cluster_summary</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>embedding</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>visualization</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>n_clusters</code> | <code>spectrasherpa://types/Scalar/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>metadata</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>eps</code> | <code>number</code> | <code>true</code> | <code>0.5</code> | — | <code>{&quot;min_value&quot;: 0.01, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Neighborhood radius |
| <code>min_samples</code> | <code>number</code> | <code>true</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 100000, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum samples within the neighborhood radius, including the point itself, for a core point. This is not a minimum cluster-size filter. Points not density-connected to a core point are labeled noise. Bounds neighborhood support bookkeeping to a finite cohort-scale request. |
| <code>metric</code> | <code>select</code> | <code>false</code> | <code>&quot;euclidean&quot;</code> | <code>[&quot;euclidean&quot;, &quot;manhattan&quot;, &quot;cosine&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Distance metric |

### Fit EFA Decomposition (`model.efa`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>forward_eigenvalues</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>backward_eigenvalues</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>false</code> | <code>10</code> | — | <code>{&quot;max_value&quot;: 500, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of components to compute Bound exploratory rank and memory use on local workbench data |

### Fit HCA Clustering (`model.hca`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/FittedModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>labels</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>cluster_assignment</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>cluster_summary</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>linkage_matrix</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>dendrogram_data</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>embedding</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_clusters</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;max_value&quot;: 500, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of clusters to form Bounds the quadratic hierarchy and scientist-facing dendrogram output. |
| <code>linkage</code> | <code>select</code> | <code>false</code> | <code>&quot;ward&quot;</code> | <code>[{&quot;label&quot;: &quot;Ward&quot;, &quot;value&quot;: &quot;ward&quot;}, {&quot;label&quot;: &quot;Average&quot;, &quot;value&quot;: &quot;average&quot;}, {&quot;label&quot;: &quot;Complete&quot;, &quot;value&quot;: &quot;complete&quot;}, {&quot;label&quot;: &quot;Single&quot;, &quot;value&quot;: &quot;single&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Linkage criterion |
| <code>metric</code> | <code>select</code> | <code>false</code> | <code>&quot;euclidean&quot;</code> | <code>[{&quot;label&quot;: &quot;Euclidean&quot;, &quot;value&quot;: &quot;euclidean&quot;}, {&quot;label&quot;: &quot;Manhattan&quot;, &quot;value&quot;: &quot;manhattan&quot;}, {&quot;label&quot;: &quot;Cosine&quot;, &quot;value&quot;: &quot;cosine&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Distance metric (ward requires euclidean) |

### Fit FastICA Decomposition (`model.ica`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>sources</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>components</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>mixing_matrix</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>unmixing_matrix</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>residuals</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;max_value&quot;: 50, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Bounds whitening and fixed-point solver cost. |
| <code>algorithm</code> | <code>select</code> | <code>false</code> | <code>&quot;parallel&quot;</code> | <code>[&quot;parallel&quot;, &quot;deflation&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | — |
| <code>fun</code> | <code>select</code> | <code>false</code> | <code>&quot;logcosh&quot;</code> | <code>[&quot;logcosh&quot;, &quot;exp&quot;, &quot;cube&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | — |
| <code>whiten</code> | <code>select</code> | <code>false</code> | <code>&quot;unit-variance&quot;</code> | <code>[&quot;unit-variance&quot;, &quot;arbitrary-variance&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | — |
| <code>max_iter</code> | <code>number</code> | <code>false</code> | <code>400</code> | — | <code>{&quot;max_value&quot;: 2000, &quot;min_value&quot;: 50, &quot;step&quot;: 50}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Bounds fixed-point solver cost. |
| <code>tol</code> | <code>number</code> | <code>false</code> | <code>0.0001</code> | — | <code>{&quot;min_value&quot;: 1e-08, &quot;step&quot;: 0.0001}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | — |
| <code>random_seed</code> | <code>number</code> | <code>false</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 2147483647, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Matches the deterministic 32-bit solver seed domain. |

### Fit K-Means Clustering (`model.kmeans`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/FittedModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>labels</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>cluster_assignment</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>cluster_summary</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>centroids</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>embedding</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>visualization</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>inertia</code> | <code>spectrasherpa://types/Scalar/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>n_clusters</code> | <code>spectrasherpa://types/Scalar/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>metadata</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_clusters</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;max_value&quot;: 500, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of clusters to form Bounds K-means memory, fit cost, and the scientist-facing centroid table. |
| <code>n_init</code> | <code>number</code> | <code>false</code> | <code>10</code> | — | <code>{&quot;max_value&quot;: 100, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Number of k-means initializations Bounds repeated K-means fits while preserving robust multi-start use. |
| <code>max_iter</code> | <code>number</code> | <code>false</code> | <code>300</code> | — | <code>{&quot;max_value&quot;: 10000, &quot;min_value&quot;: 1, &quot;step&quot;: 50}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Maximum iterations per initialization Bounds one initialization&#x27;s iterative work and recorded convergence budget. |
| <code>random_state</code> | <code>number</code> | <code>false</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Random seed for reproducibility Matches the closed unsigned 32-bit seed domain used by the fitted implementation. |

### Fit MCR-ALS Decomposition (`model.mcr_als`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>C</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>St</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>residuals</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>ground_truth_comparison</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;max_value&quot;: 50, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of pure components to resolve Bounds SVD initialization and alternating least-squares cost. |
| <code>non_negative_C</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Enforce non-negative concentration profiles |
| <code>non_negative_St</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Enforce non-negative spectra |
| <code>max_iter</code> | <code>number</code> | <code>false</code> | <code>200</code> | — | <code>{&quot;max_value&quot;: 2000, &quot;min_value&quot;: 10, &quot;step&quot;: 10}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Maximum ALS iterations. Raised from 50 → 200 in v0.4.3 to give the tighter default tolerance (1e-5) room to converge on typical spectra. Bounds alternating least-squares work in the interactive runtime. |
| <code>tol</code> | <code>number</code> | <code>false</code> | <code>1e-05</code> | — | <code>{&quot;min_value&quot;: 1e-08, &quot;step&quot;: 1e-06}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Relative change in St between successive ALS iterations at which the solver stops. Lowered from 0.1 → 1e-5 in v0.4.3 to match mdatools / pyMCR convention; values &gt;1e-3 emit a &#x27;loose-tolerance&#x27; warning. References: Tauler et al. (Chemom. Intell. Lab. Syst. 1995); pyMCR uses 1e-5, mdatools &#96;mcrals()&#96; uses 1e-6. |
| <code>normSpec</code> | <code>select</code> | <code>false</code> | <code>&quot;euclid&quot;</code> | <code>[{&quot;label&quot;: &quot;Euclidean norm&quot;, &quot;value&quot;: &quot;euclid&quot;}, {&quot;label&quot;: &quot;Maximum intensity&quot;, &quot;value&quot;: &quot;max&quot;}, {&quot;label&quot;: &quot;None&quot;, &quot;value&quot;: &quot;none&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Normalize resolved pure spectra during MCR-ALS. Euclidean normalization stabilizes the concentration/spectrum scale ambiguity for shape comparison. |
| <code>validation_target_index</code> | <code>number</code> | <code>false</code> | <code>1</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;validation&quot;}</code> | 1-based ground-truth concentration column to compare. Only this user-selected target is emitted to ValidationResult. |
| <code>validation_component_index</code> | <code>number</code> | <code>false</code> | <code>1</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;validation&quot;}</code> | 1-based recovered MCR concentration profile to compare against the selected target. MCR component matching is intentionally user-controlled. |

### Fit NMF Decomposition (`model.nmf`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/FittedModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>concentrations</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>spectra</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>reconstruction_error</code> | <code>spectrasherpa://types/Scalar/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;max_value&quot;: 500, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of components to extract Bounds factor-state size and iterative decomposition cost. |
| <code>solver</code> | <code>select</code> | <code>false</code> | <code>&quot;mu&quot;</code> | <code>[&quot;mu&quot;, &quot;cd&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | NMF solver: &#x27;mu&#x27; (Multiplicative Update) or &#x27;cd&#x27; (Coordinate Descent) |
| <code>max_iter</code> | <code>number</code> | <code>false</code> | <code>200</code> | — | <code>{&quot;max_value&quot;: 10000, &quot;min_value&quot;: 1, &quot;step&quot;: 50}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Maximum number of iterations Bounds the declared convergence budget. |
| <code>tol</code> | <code>number</code> | <code>false</code> | <code>0.0001</code> | — | <code>{&quot;max_value&quot;: 0.1, &quot;min_value&quot;: 1e-12, &quot;step&quot;: 0.0001}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Convergence tolerance Prevents a tolerance so loose that factorization stops without useful refinement. |
| <code>random_state</code> | <code>number</code> | <code>false</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Seed for deterministic initialization and fixed-basis application Matches the closed unsigned 32-bit seed domain. |

### Fit PARAFAC Decomposition (`model.parafac`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>sample_scores</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>component_weights</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>relative_reconstruction_error</code> | <code>spectrasherpa://types/Scalar/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;max_value&quot;: 20, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Bounds factor-state size and CP-ALS computation. |
| <code>max_iter</code> | <code>number</code> | <code>false</code> | <code>200</code> | — | <code>{&quot;max_value&quot;: 500, &quot;min_value&quot;: 1, &quot;step&quot;: 10}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Bounds deterministic CP-ALS execution time. |
| <code>tol</code> | <code>number</code> | <code>false</code> | <code>1e-06</code> | — | <code>{&quot;max_value&quot;: 0.1, &quot;min_value&quot;: 1e-10, &quot;step&quot;: 1e-06}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Prevents accepting a tolerance too loose for meaningful convergence. |
| <code>ridge</code> | <code>number</code> | <code>false</code> | <code>1e-12</code> | — | <code>{&quot;max_value&quot;: 1.0, &quot;min_value&quot;: 0.0, &quot;step&quot;: 1e-12}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Bounds regularization so it cannot dominate the decomposition. |

### Fit PCA Transform (`model.pca`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>model</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>scores</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_scores</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>loadings</code> | <code>spectrasherpa://types/LoadingMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_loadings</code> | <code>spectrasherpa://types/LoadingMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>variable_correlations</code> | <code>spectrasherpa://types/LoadingMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>explained_variance</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>eigenvalues</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>diagnostic_state</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>component_curve</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>text</code> | <code>true</code> | <code>&quot;2&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of components: integer (e.g., &#x27;2&#x27;), &#x27;mle&#x27; (Minka maximum-likelihood automatic selection), or float 0-1 (e.g., &#x27;0.95&#x27; for 95% variance) Must be ≤ min(n_samples, n_features). The &#x27;mle&#x27; choice additionally requires n_samples ≥ n_features. This is checked at execution time — a value that is too large will raise an error. Use &#x27;0.95&#x27; to automatically retain enough components for 95% explained variance. |
| <code>standardized</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Subtract the column mean AND divide by column standard deviation before PCA (full standardization). Use when variables have different units or scales, e.g. mixing spectral and non-spectral predictors. |
| <code>scaled</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Apply min-max scaling, (X - column minimum) / column range, then center the scaled variables before PCA. Rarely appropriate for spectral data — prefer &#x27;Mean Center + Unit Variance&#x27; or leave both off to use mean-centering only (the spectroscopy default). |

### Apply PCA Transform (`model.pca_transform`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X_new</code> | <code>spectrasherpa://types/Array2D/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>model</code> | <code>spectrasherpa://types/DecompositionResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>scores</code> | <code>spectrasherpa://types/ScoreMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

No parameters.

### Fit SIMPLISMA Pure Components (`model.simplisma`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>concentrations</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>spectra</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>purity_values</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;max_value&quot;: 500, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of pure components to resolve Bound local decomposition rank and memory use |
| <code>tol</code> | <code>number</code> | <code>false</code> | <code>0.1</code> | — | <code>{&quot;max_value&quot;: 100.0, &quot;min_value&quot;: 0.001, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Convergence tolerance Closed percentage tolerance accepted by SpectroChemPy SIMPLISMA |
| <code>noise</code> | <code>number</code> | <code>false</code> | <code>3.0</code> | — | <code>{&quot;max_value&quot;: 15.0, &quot;min_value&quot;: 0.0, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Noise level for purity calculation SpectroChemPy documents the SIMPLISMA noise range as 0-15 percent |

<!-- END GENERATED NODE REFERENCE -->
