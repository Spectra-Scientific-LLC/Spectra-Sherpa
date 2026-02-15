# Complete Node Capabilities - Spectral Analysis Platform

**Total Nodes**: 44 registered algorithms
**Last Updated**: 2026-01-16
**Status**: All nodes accessible via frontend Add Node dropdown

---

## 📊 PREPROCESSING (21 nodes - 47.7%)

### Baseline Correction
| Node | Type | Description |
|------|------|-------------|
| **Baseline (ALS)** | `baseline.als` | Asymmetric Least Squares baseline correction |
| **Baseline (Rubberband)** | `baseline.rubberband` | Rubberband (convex hull) baseline correction |

### Smoothing
| Node | Type | Description |
|------|------|-------------|
| **Smooth (Savitzky-Golay)** | `smooth.savitzky_golay` | Savitzky-Golay polynomial smoothing filter |

### Normalization
| Node | Type | Description |
|------|------|-------------|
| **Normalize (SNV)** | `normalize.snv` | Standard Normal Variate normalization |
| **Normalize (Scale)** | `normalize.scale` | Scale normalization (to max, area, or range) |
| **Normalize (MSC)** | `normalize.msc` | Multiplicative Scatter Correction |

### Derivatives
| Node | Type | Description |
|------|------|-------------|
| **1st Derivative** | `derivative.first` | First derivative using Savitzky-Golay |
| **2nd Derivative** | `derivative.second` | Second derivative using Savitzky-Golay |
| **SG Derivative** | `preprocess.sg_derivative` | Savitzky-Golay smoothing + derivative (combined) |

### Spectral Preprocessing
| Node | Type | Description |
|------|------|-------------|
| **Cosmic Ray Removal** | `preprocess.cosmic_ray` | Remove spike outliers using local median and MAD |
| **Clip Range** | `preprocess.clip_range` | Crop spectrum to specified wavenumber range |
| **Clip Floor** | `preprocess.clip_floor` | Clip values below floor (remove negatives) |
| **Wavenumber Align** | `preprocess.wavenumber_align` | Align spectra to common wavenumber grid |
| **Scale to Max** | `preprocess.scale_max` | Normalize each spectrum to target maximum |
| **Mean Center** | `preprocess.center_mean` | Subtract mean spectrum from all spectra |

### Chemometric Scaling
| Node | Type | Description |
|------|------|-------------|
| **Pareto Scaling** | `preprocess.pareto_scaling` | Scale by sqrt of standard deviation |
| **Autoscaling** | `preprocess.autoscaling` | Mean centering + unit variance scaling |
| **OSC Filter** | `preprocess.osc` | Orthogonal Signal Correction |
| **EMSC** | `preprocess.emsc` | Extended MSC with polynomial baseline |

### Time Series
| Node | Type | Description |
|------|------|-------------|
| **Trend Removal** | `time_series.trend_removal` | Remove systematic trends and drift |

---

## 🔬 MODELING (8 nodes - 18.2%)

### Dimensionality Reduction
| Node | Type | Description |
|------|------|-------------|
| **PCA** | `model.pca` | Principal Component Analysis |
| **EFA** | `model.efa` | Evolving Factor Analysis for rank determination |

### Regression/Calibration
| Node | Type | Description |
|------|------|-------------|
| **PLS** | `model.pls` | Partial Least Squares regression |
| **Linear Regression** | `model.linear_regression` | Simple linear regression |

### Mixture Analysis
| Node | Type | Description |
|------|------|-------------|
| **MCR-ALS** | `model.mcr_als` | Multivariate Curve Resolution |

### Peak Analysis
| Node | Type | Description |
|------|------|-------------|
| **Peak Finding** | `analysis.peak_finding` | Find peaks with domain-specific algorithms |

### Diagnostics
| Node | Type | Description |
|------|------|-------------|
| **Outlier Detection** | `diagnostics.outliers` | Hotelling T² and Q statistics |
| **Cross-Validation** | `diagnostics.cross_validation` | Calculate cross-validation metrics |

---

## 🎯 CLASSIFICATION (3 nodes - 6.8%)

| Node | Type | Description |
|------|------|-------------|
| **PLS-DA** | `classification.plsda` | Partial Least Squares Discriminant Analysis |
| **KNN Classifier** | `classification.knn` | K-Nearest Neighbors classification |
| **SIMCA** | `classification.simca` | Soft Independent Modeling of Class Analogy |

---

## 💾 DATA (4 nodes - 9.1%)

| Node | Type | Description |
|------|------|-------------|
| **Data Source** | `data.source` | Load from experiments, files, or synthetic |
| **File Load** | `data.file_load` | Load from experiment files |
| **NIST Library** | `data.nist_library` | Load reference spectra from NIST |
| **Synthetic Curve** | `data.synthetic_curve` | Generate synthetic concentration curves |

---

## 📤 OUTPUT (4 nodes - 9.1%)

| Node | Type | Description |
|------|------|-------------|
| **Plot** | `output.plot` | Create plot visualization |
| **Contour Plot** | `output.contour` | Create 2D contour/heatmap visualization |
| **Export** | `output.export` | Export data to file |
| **Data Table** | `output.data_table` | Interactive table with sorting and filtering |

---

## 📊 ANALYSIS (1 node - 2.3%)

| Node | Type | Description |
|------|------|-------------|
| **Statistics** | `stats.summary` | Compute adaptive statistics |

---

## 🧪 SYNTHESIS (3 nodes - 6.8%)

| Node | Type | Description |
|------|------|-------------|
| **Blend** | `synthesis.blend` | Create synthetic mixtures with concentration curves |
| **Species** | `synthesis.species` | Mark spectrum as species for blending |
| **Merge Spectra** | `synthesis.merge` | Combine multiple spectra into stacked dataset |

---

## ✅ Verification Status

### Backend Registration
- ✅ **44 nodes** registered with `@register_node` decorator
- ✅ All nodes have complete metadata (type, category, label, description, parameters)
- ✅ Distributed across **9 Python modules** in `app/services/dag/nodes/`

### API Exposure
- ✅ All nodes exposed via `/api/v1/workflows/nodes/library` endpoint
- ✅ Dynamic node library loading implemented
- ✅ Node metadata includes parameters, input/output types, descriptions

### Frontend Access
- ✅ Frontend loads nodes dynamically from backend API ([NodeLibrary.vue:89-109](frontend/src/views/analysis/NodeLibrary.vue#L89-L109))
- ✅ All categories displayed: Preprocessing, Modeling, Classification, Diagnostics, Data, Output, Synthesis
- ✅ Search functionality available across all nodes

---

## 🔍 How to Find Nodes in Frontend

1. **By Category**: Nodes are organized in collapsible sections:
   - Data (4 nodes)
   - Preprocessing (21 nodes)
   - Modeling (8 nodes)
   - Classification (3 nodes)
   - Analysis (1 node)
   - Synthesis (3 nodes)
   - Output (4 nodes)

2. **By Search**: Use the search bar at top of Node Library panel to filter by:
   - Node label (e.g., "PCA", "Baseline")
   - Description text (e.g., "normalization", "derivative")
   - Node type (e.g., "model.pca")

3. **Common Algorithms**:
   - **MCR-ALS**: Look under "Modeling" → "MCR-ALS"
   - **PLS-DA**: Look under "Classification" → "PLS-DA"
   - **Outlier Detection**: Look under "Modeling" → "Outlier Detection"
   - **EMSC**: Look under "Preprocessing" → "EMSC"
   - **OSC**: Look under "Preprocessing" → "OSC Filter"

---

## 📝 Notes

- All nodes are fully functional with parameter validation
- Some advanced nodes (MCR-ALS, SIMCA) require specific input formats
- Nodes support both single spectra and multi-spectrum datasets
- Most preprocessing nodes can be chained for complex workflows
- All modeling nodes return serializable results (no raw sklearn/numpy objects)

---

**If you still cannot find a specific node**, please:
1. Restart the backend server to ensure latest node registry
2. Clear browser cache and reload frontend
3. Check browser console for API errors
4. Verify backend is running: `curl http://localhost:8000/api/v1/workflows/nodes/library`
