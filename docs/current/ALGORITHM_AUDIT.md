# Backend Algorithm Audit

## Executive Summary

**Total Nodes Implemented:** 53 (Updated: +3 SpectroChemPy algorithms)
**SpectroChemPy Algorithms Available but NOT Implemented:** 1-2 (SVD, IRIS)
**Additional Non-SpectroChemPy Algorithms Implemented:** Multiple (sklearn-based)

## Current Backend Nodes (50 total)

### Data Sources (6 nodes)
- ✅ `data.source` - SpectroChemPy/sklearn/experiment data loading
- ✅ `data.file_load` - Direct file loading
- ✅ `data.load_group` - Multiple file loading with patterns
- ✅ `data.nist_library` - NIST spectral library access
- ✅ `data.synthetic_curve` - Synthetic curve generation
- ✅ `data.train_test_split` - Train/test data splitting

### Component Analysis / Decomposition (11 nodes)
- ✅ `model.pca` - Principal Component Analysis (SpectroChemPy)
- ✅ `model.pls` - Partial Least Squares (SpectroChemPy)
- ✅ `model.mcr_als` - Multivariate Curve Resolution (SpectroChemPy MCRALS)
- ✅ `model.efa` - Evolving Factor Analysis (SpectroChemPy)
- ✅ `model.simplisma` - SIMPLISMA decomposition (SpectroChemPy) ⭐ **NEW**
- ✅ `model.nmf` - Non-negative Matrix Factorization (SpectroChemPy) ⭐ **NEW**
- ✅ `model.ica` - Independent Component Analysis (SpectroChemPy FastICA) ⭐ **NEW**
- ✅ `model.pca_transform` - Apply PCA transformation
- ✅ `model.pls_predict` - Apply PLS prediction
- ✅ `model.linear_regression` - Simple linear regression
- ❌ **MISSING: `model.svd`** - Singular Value Decomposition (SpectroChemPy HAS this)

### Classification (5 nodes)
- ✅ `classification.plsda` - PLS Discriminant Analysis (custom, uses SpectroChemPy PLS)
- ✅ `classification.simca` - Soft Independent Modeling (custom, uses SpectroChemPy PCA)
- ✅ `classification.knn` - K-Nearest Neighbors (sklearn)
- ✅ `classification.plsda_predict` - Apply PLS-DA model
- ✅ `classification.knn_predict` - Apply KNN model
- ❌ **MISSING:** SVM, Random Forest, Neural Networks (could use sklearn)
- ❌ **MISSING:** LDA (Linear Discriminant Analysis)

### Preprocessing - Baseline Correction (2 nodes)
- ✅ `baseline.als` - Asymmetric Least Squares
- ✅ `baseline.rubberband` - Rubberband baseline
- ❌ **MISSING:** Other baseline methods (polynomial, spline, etc.)

### Preprocessing - Smoothing (1 node)
- ✅ `smooth.savitzky_golay` - Savitzky-Golay filter
- ❌ **MISSING:** Other smoothing (moving average, Gaussian, etc.)

### Preprocessing - Normalization (3 nodes)
- ✅ `normalize.snv` - Standard Normal Variate
- ✅ `normalize.msc` - Multiplicative Scatter Correction
- ✅ `normalize.scale` - Min-max scaling
- ❌ **MISSING:** Other normalization methods

### Preprocessing - Derivatives (2 nodes)
- ✅ `derivative.first` - First derivative
- ✅ `derivative.second` - Second derivative

### Preprocessing - Advanced (9 nodes)
- ✅ `preprocess.cosmic_ray` - Cosmic ray removal
- ✅ `preprocess.clip_range` - Clip to wavenumber range
- ✅ `preprocess.clip_floor` - Clip to minimum value
- ✅ `preprocess.wavenumber_align` - Align wavenumber axes
- ✅ `preprocess.scale_max` - Scale to maximum
- ✅ `preprocess.center_mean` - Mean centering
- ✅ `preprocess.pareto_scaling` - Pareto scaling
- ✅ `preprocess.autoscaling` - Autoscaling
- ✅ `preprocess.osc` - Orthogonal Signal Correction
- ✅ `preprocess.emsc` - Extended Multiplicative Signal Correction
- ✅ `preprocess.sg_derivative` - Savitzky-Golay derivative

### Analysis / Peak Detection (1 node)
- ✅ `analysis.peak_finding` - Peak detection and characterization
- ❌ **MISSING:** Peak fitting, deconvolution

### Diagnostics (2 nodes)
- ✅ `diagnostics.outliers` - Outlier detection
- ✅ `diagnostics.cross_validation` - Cross-validation framework

### Time Series (2 nodes)
- ✅ `time_series.moving_window` - Moving window analysis
- ✅ `time_series.trend_removal` - Trend removal

### Output / Visualization (5 nodes)
- ✅ `output.plot` - Plotting
- ✅ `output.contour` - Contour plots
- ✅ `output.data_table` - Data tables
- ✅ `output.export` - Data export
- ✅ `stats.summary` - Statistical summary

### Synthesis / Blending (3 nodes)
- ✅ `synthesis.blend` - Spectral blending
- ✅ `synthesis.species` - Species definition
- ✅ `synthesis.merge` - Merge datasets

## Missing SpectroChemPy Algorithms (HIGH PRIORITY)

Based on [SpectroChemPy documentation](https://www.spectrochempy.fr/) and [recent research](https://pmc.ncbi.nlm.nih.gov/articles/PMC9657760/), the following algorithms are **available in SpectroChemPy but NOT implemented** in our backend:

### 1. SIMPLISMA ✅ IMPLEMENTED (2025-01-22)
**Status:** ✅ Now available as `model.simplisma`
**SpectroChemPy Class:** `scp.SIMPLISMA`
**Use Case:** Self-modeling mixture analysis for resolving pure component spectra
**Reference:** [SIMPLISMA example](https://www.spectrochempy.fr/gettingstarted/examples/gallery/auto_examples_analysis/a_decomposition/plot_simplisma.html)
**Research:** "SIMPLISMA and JADE produced the best quantitative analysis of concentration, and SIMPLISMA and MCR-ALS produced the best decompositions of binary mixtures"

**Parameters:**
- `n_components`: Number of pure components to resolve (default: 3)
- `tol`: Convergence tolerance (default: 0.1)
- `noise`: Noise level for purity calculation (default: 3.0)

### 2. NMF (Non-negative Matrix Factorization) ✅ IMPLEMENTED (2025-01-22)
**Status:** ✅ Now available as `model.nmf`
**SpectroChemPy Class:** `scp.NMF`
**Use Case:** Decomposition with non-negativity constraints (physical interpretability)
**Research:** "NMF and MCR allow better interpretability of chemical reactions than PCA, with comparable quality of fit"
**Notes:** Also available via sklearn (`sklearn.decomposition.NMF`)

**Parameters:**
- `n_components`: Number of components (default: 3)
- `method`: 'mu' (Multiplicative Update) or 'als' (default: 'mu')
- `max_iter`: Maximum iterations (default: 200)
- `tol`: Convergence tolerance (default: 0.0001)

### 3. ICA / FastICA (Independent Component Analysis) ✅ IMPLEMENTED (2025-01-22)
**Status:** ✅ Now available as `model.ica`
**SpectroChemPy Class:** `scp.FastICA`
**Reference:** [FastICA documentation](https://www.spectrochempy.fr/latest/reference/generated/spectrochempy.FastICA.html)
**Use Case:** Blind source separation, extracting underlying independent sources
**Research:** "FastICA extracts the underlying sources of the variability of a set of spectra into spectral profiles"

**Parameters:**
- `n_components`: Number of independent components (default: 3)
- `algorithm`: 'parallel' or 'deflation' (default: 'parallel')
- `fun`: Contrast function - 'logcosh', 'exp', or 'cube' (default: 'logcosh')
- `max_iter`: Maximum iterations (default: 200)
- `tol`: Convergence tolerance (default: 0.0001)

### 4. SVD (Singular Value Decomposition) ⚠️ LOW PRIORITY
**Status:** Available in SpectroChemPy, NOT implemented
**SpectroChemPy Class:** `scp.SVD`
**Reference:** [SVD documentation](https://www.spectrochempy.fr/reference/generated/spectrochempy.SVD.html)
**Use Case:** Matrix decomposition, rank determination, noise reduction

**Implementation Priority:** MEDIUM - Foundation for many chemometric methods

### 5. IRIS (Interactive Resolution) ⚠️ LOW PRIORITY
**Status:** Available in SpectroChemPy, NOT implemented
**SpectroChemPy Class:** `scp.IRIS`
**Use Case:** Interactive resolution of mixture spectra

**Implementation Priority:** LOW - Less commonly used than above methods

## Recommended Additional Algorithms (Beyond SpectroChemPy)

### sklearn-based Classification (Currently Missing)
- **SVM (Support Vector Machines)** - `sklearn.svm.SVC`
- **Random Forest** - `sklearn.ensemble.RandomForestClassifier`
- **Gradient Boosting** - `sklearn.ensemble.GradientBoostingClassifier`
- **LDA (Linear Discriminant Analysis)** - `sklearn.discriminant_analysis.LinearDiscriminantAnalysis`
- **QDA (Quadratic Discriminant Analysis)** - `sklearn.discriminant_analysis.QuadraticDiscriminantAnalysis`

### sklearn-based Regression (Currently Missing)
- **Ridge Regression** - `sklearn.linear_model.Ridge`
- **Lasso Regression** - `sklearn.linear_model.Lasso`
- **Elastic Net** - `sklearn.linear_model.ElasticNet`
- **SVR (Support Vector Regression)** - `sklearn.svm.SVR`

### Advanced Peak Analysis (Currently Missing)
- **Peak Fitting** - Gaussian/Lorentzian fitting
- **Peak Deconvolution** - Resolve overlapping peaks
- **Integration** - Calculate peak areas

## Implementation Recommendations

### Phase 1: Critical Missing Algorithms (User-Requested)
1. **SIMPLISMA** - Add `model.simplisma` node
2. **NMF** - Add `model.nmf` node
3. **ICA/FastICA** - Add `model.ica` node

### Phase 2: Foundation Algorithms
4. **SVD** - Add `model.svd` node
5. **Ridge/Lasso Regression** - Add `model.ridge` and `model.lasso` nodes

### Phase 3: Extended Classification
6. **SVM** - Add `classification.svm` node
7. **Random Forest** - Add `classification.random_forest` node
8. **LDA** - Add `classification.lda` node

### Phase 4: Advanced Analysis
9. **Peak Fitting** - Add `analysis.peak_fitting` node
10. **Peak Deconvolution** - Add `analysis.peak_deconvolution` node

## Algorithm Comparison Matrix

| Algorithm | SpectroChemPy | sklearn | Backend Status | Priority |
|-----------|---------------|---------|----------------|----------|
| PCA | ✅ | ✅ | ✅ Implemented | - |
| PLS | ✅ | ✅ | ✅ Implemented | - |
| MCR-ALS | ✅ | ❌ | ✅ Implemented | - |
| EFA | ✅ | ❌ | ✅ Implemented | - |
| **SIMPLISMA** | ✅ | ❌ | ✅ **Implemented (NEW)** | - |
| **NMF** | ✅ | ✅ | ✅ **Implemented (NEW)** | - |
| **ICA/FastICA** | ✅ | ✅ | ✅ **Implemented (NEW)** | - |
| **SVD** | ✅ | ✅ | ❌ **MISSING** | **LOW** |
| PLS-DA | Custom | ✅ | ✅ Implemented | - |
| SIMCA | Custom | ❌ | ✅ Implemented | - |
| KNN | ❌ | ✅ | ✅ Implemented | - |
| **SVM** | ❌ | ✅ | ❌ **MISSING** | **MEDIUM** |
| **Random Forest** | ❌ | ✅ | ❌ **MISSING** | **MEDIUM** |
| **LDA** | ❌ | ✅ | ❌ **MISSING** | **MEDIUM** |
| Ridge/Lasso | ❌ | ✅ | ❌ **MISSING** | **LOW** |

## Sources

- [SpectroChemPy SIMPLISMA example](https://www.spectrochempy.fr/gettingstarted/examples/gallery/auto_examples_analysis/a_decomposition/plot_simplisma.html)
- [SpectroChemPy FastICA documentation](https://www.spectrochempy.fr/latest/reference/generated/spectrochempy.FastICA.html)
- [SpectroChemPy SVD documentation](https://www.spectrochempy.fr/reference/generated/spectrochempy.SVD.html)
- [Research on chemometrics for zooplankton classification](https://pmc.ncbi.nlm.nih.gov/articles/PMC9657760/)
- [SIMPLISMA GitHub discussion](https://github.com/spectrochempy/spectrochempy/discussions/502)

## Conclusion

The backend now has **53 implemented nodes** including all priority SpectroChemPy algorithms:

**✅ COMPLETED (2025-01-22):**
1. ✅ Implemented **SIMPLISMA** (`model.simplisma`)
2. ✅ Implemented **NMF** (`model.nmf`)
3. ✅ Implemented **ICA/FastICA** (`model.ica`)

**Remaining Low-Priority Items:**
- SVD (Singular Value Decomposition) - low priority as PCA covers most use cases
- sklearn-based classifiers (SVM, Random Forest, LDA)
- Additional regression methods (Ridge, Lasso, Elastic Net)

The platform now has feature parity with SpectroChemPy for critical chemometric decomposition methods while maintaining additional sklearn-based capabilities for classification and preprocessing.
