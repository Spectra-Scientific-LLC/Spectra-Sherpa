# PCA vs PLS-DA Implementation Comparison

## Executive Summary

This document compares PCA (Principal Component Analysis) and PLS-DA (Partial Least Squares Discriminant Analysis) implementations in this codebase, highlighting methodological differences, visualization approaches, and identifying discrepancies.

**Critical Finding**: PLS-DA loadings visualization is inconsistent with PCA - PCA shows loadings as line plots across features, while PLS-DA only shows a biplot. Both should be available for consistency.

---

## 1. Core Methodology

### PCA (Principal Component Analysis)
- **Objective**: Unsupervised dimensionality reduction - maximize variance in data
- **Algorithm**: Eigenvalue decomposition of covariance matrix
- **Components**: Ordered by explained variance (PC1 explains most variance)
- **Use case**: Exploratory data analysis, noise reduction, visualization

### PLS-DA (Partial Least Squares Discriminant Analysis)
- **Objective**: Supervised classification - maximize covariance between X and Y (class labels)
- **Algorithm**: SIMPLS via scikit-learn wrapped by SpectroChemPy
- **Components**: Ordered by predictive ability for class discrimination (LV1 optimized for classification)
- **Use case**: Classification, feature selection for discrimination

**Key Difference**:
- PCA finds directions of **maximum variance** (unsupervised)
- PLS-DA finds directions of **maximum class separation** (supervised)

---

## 2. Matrix Shapes & Conventions

### PCA (from modeling.py)
```python
# SpectroChemPy PCA components
loadings_data = np.array(pca.components.data)
# Shape: (n_components, n_features)
# loadings_data[i] = PC i's loadings across all features
```

### PLS-DA (from classification.py)
```python
# SpectroChemPy PLSRegression x_loadings
X_loadings = np.array(pls.x_loadings.data)
# Shape: (n_components, n_features)  ← Same as PCA
# X_loadings[i] = LV i's loadings across all features
```

**Important**: SpectroChemPy uses **(n_components, n_features)** for both PCA and PLS, which is **transposed** from sklearn's convention of **(n_features, n_components)**.

Evidence from [classification.py:424-426](Refactored/backend/app/services/dag/nodes/classification.py#L424-L426):
```python
# SpectroChemPy returns x_weights as (n_components, n_features)
w_raw = np.array(pls_model.x_weights.data)
w = w_raw.T  # Transpose to (n_features, n_components) for VIP calculation
```

---

## 3. Loadings Visualization - **CRITICAL ISSUE IDENTIFIED**

### PCA Loadings Plot ([NodeDetailView.vue:1437-1463](Refactored/frontend/src/views/workflow-builder/NodeDetailView.vue#L1437-L1463))

**Type**: Line plots showing each PC as a spectrum/pattern across features

```typescript
const pcaLoadingsData = computed(() => {
  const loadings = metadata.loadings || [];  // Shape: (n_components, n_features)

  return loadings.map((loading: number[], i: number) => ({
    type: "scatter",
    mode: "lines",
    x: x_values,           // Feature indices, wavenumbers, or feature names
    y: loading,            // PC i's loadings (array of n_features values)
    name: pcLabels[i],     // "PC1 (45.2%)", "PC2 (23.1%)", ...
    line: { width: 2 },
  }));
});
```

**Purpose**: Shows the "spectral pattern" or "signature" of each principal component

**Interpretation**:
- High positive loading: feature positively contributes to this PC
- High negative loading: feature negatively contributes to this PC
- Near zero: feature doesn't contribute to this PC

---

### PLS-DA Loadings Plot ([classification.py:516-577](Refactored/backend/app/services/dag/nodes/classification.py#L516-L577))

**Type**: Biplot (quiver plot) showing feature relationships in LV1-LV2 space

```python
# Current implementation: BIPLOT ONLY
for i in range(n_features):
    lv1 = float(loadings[0, i])  # Feature i's loading on LV1
    lv2 = float(loadings[1, i])  # Feature i's loading on LV2

    # Create arrow from origin to (lv1, lv2)
    annotations.append({
        "x": lv1, "y": lv2,
        "ax": 0, "ay": 0,  # Arrow starts at origin
        "showarrow": True,
        "arrowhead": 2,
        "arrowcolor": "steelblue",
    })

    # Feature label at arrow tip
    annotations.append({
        "x": lv1 * 1.15,
        "y": lv2 * 1.15,
        "text": labels[i],  # Feature name
    })
```

**Purpose**: Shows which features correlate/anti-correlate in the discriminant space

**Interpretation**:
- Arrow direction: how feature relates to LV1 and LV2 axes
- Arrow length: strength of relationship
- Arrows pointing same direction: features positively correlated
- Arrows pointing opposite: features negatively correlated

---

## 4. THE PROBLEM: Inconsistent Visualization Paradigms

### Current State
| Aspect | PCA | PLS-DA |
|--------|-----|--------|
| **Loadings visualization** | Line plots (each PC = line) | Biplot (arrows in 2D space) |
| **Number of components shown** | All components simultaneously | Only 2 components (LV1 vs LV2) |
| **Feature labels** | On x-axis | At arrow tips |
| **Comparison across components** | Easy (overlay lines) | Difficult (only shows 2D projection) |

### Why This Is a Problem

1. **Inconsistent UX**: Users expect similar visualization for similar data types
2. **Limited information**: PLS-DA biplot only shows LV1 and LV2 relationship, not individual LV patterns
3. **Missing spectroscopic interpretation**: In IR/Raman spectroscopy, loadings line plots show which wavelengths contribute to each component
4. **No multi-component view**: Can't see LV3, LV4, etc. in biplot

### Recommended Solution

PLS-DA should provide **BOTH** visualization types (like mixing PCA's approach with current biplot):

**Option 1: Loadings Line Plot** (like PCA)
- Show LV1, LV2, LV3, ... as separate lines
- X-axis: wavenumbers or feature names
- Y-axis: loading magnitude
- **Use case**: "What wavelengths contribute to each discriminant direction?"

**Option 2: Loadings Biplot** (current implementation)
- Show features as arrows in LV1-LV2 space
- **Use case**: "Which features correlate in the discriminant space?"

**Option 3: Component Pair Selector** (for biplot)
- Allow selecting which components to plot (LV1 vs LV2, LV1 vs LV3, LV2 vs LV3, etc.)
- **Use case**: Exploring relationships beyond just LV1-LV2

---

## 5. Other Visualization Differences

### PCA Outputs ([modeling.py:326-368](Refactored/backend/app/services/dag/nodes/modeling.py#L326-L368))

| Plot Type | Description | Purpose |
|-----------|-------------|---------|
| **Scores Plot** | Samples in PC1-PC2 space | Sample clustering/grouping |
| **Loadings Line Plot** | Each PC as line across features | Component interpretation |
| **Scree Plot** | Variance explained by each PC | Component selection |
| **Diagnostics** | Hotelling T² and SPE | Outlier detection |

### PLS-DA Outputs ([classification.py:267-270](Refactored/backend/app/services/dag/nodes/classification.py#L267-L270))

| Plot Type | Description | Purpose |
|-----------|-------------|---------|
| **Scores Plot** | Samples in LV1-LV2 space with 95% confidence ellipses | Class separation visualization |
| **Loadings Biplot** | Features as arrows in LV1-LV2 space | Feature relationships |
| **VIP Plot** | Variable Importance in Projection scores | Feature selection |

**Missing from PLS-DA**:
- Loadings line plots (inconsistent with PCA)
- Diagnostic plots (T², SPE for outlier detection)
- Explained variance visualization (no scree plot equivalent)

---

## 6. Data Flow Comparison

### PCA Data Flow
```
Input: NDDataset (n_samples, n_features)
  ↓
PCA.fit() → components_ shape (n_components, n_features)
  ↓
Store in metadata.loadings (no transpose)
  ↓
Frontend: loadings[i] = PC i's pattern → LINE PLOT
```

### PLS-DA Data Flow
```
Input: X (n_samples, n_features), y (class labels)
  ↓
PLSRegression.fit() → x_loadings shape (n_components, n_features)
  ↓
Store in metadata.loadings (no transpose)
  ↓
Backend: loadings[0, i], loadings[1, i] → BIPLOT
Frontend: (NO LINE PLOT OPTION)
```

**Inconsistency**: Both have same shape (n_components, n_features), but PCA uses for line plots while PLS-DA uses for biplot only.

---

## 7. Metadata Structure Comparison

### PCA Metadata
```python
{
    "type": "PCA",
    "n_components": int,
    "loadings": list,  # Shape: (n_components, n_features)
    "wavenumbers": list,
    "feature_names": list,
    "explained_variance_ratio": list,
    "pc_labels": ["PC1 (45.2%)", "PC2 (23.1%)", ...],
    "sample_labels": list,
    "label_categories": list,
    "t2": list,  # Hotelling T²
    "spe": list,  # SPE diagnostics
}
```

### PLS-DA Metadata
```python
{
    "type": "PLS_DA",
    "n_components": int,
    "loadings": list,  # Shape: (n_components, n_features) ← SAME SHAPE!
    "wavenumbers": list,
    "feature_names": list,
    "vip_scores": list,
    "pc_labels": ["LV1", "LV2", ...],  # No variance percentages
    "sample_labels": list,
    "label_categories": list,
    "classes": list,
    "train_accuracy": float,
    "cv_accuracy": float,
}
```

**Similarities**:
- Both store loadings with same shape
- Both have wavenumbers, feature_names, sample_labels
- Both have pc_labels (though PLS-DA calls them "LV")

**Differences**:
- PCA has explained_variance_ratio, PLS-DA doesn't
- PLS-DA has vip_scores, classes, accuracy metrics
- PCA has T²/SPE diagnostics, PLS-DA doesn't

---

## 8. Quick Plot Modal Handling

### PCA Display Options
```typescript
// No special display mode - always shows line plot
const pcaLoadingsData = computed(() => {
  return loadings.map((loading, i) => ({
    type: "scatter",
    mode: "lines",
    ...
  }));
});
```

### PLS-DA Display Options ([QuickPlotModal.vue:300-305](Refactored/frontend/src/views/workflow-builder/modals/QuickPlotModal.vue#L300-L305))
```typescript
const plsdaDisplayMode = ref<"scores" | "loadings" | "vip">("scores");
const plsdaDisplayOptions = [
  { label: "Scores Plot (with ellipses)", value: "scores" },
  { label: "Loadings Plot", value: "loadings" },  // Shows biplot
  { label: "VIP Scores", value: "vip" },
];
```

**Issue**: "Loadings Plot" in PLS-DA shows biplot, but in PCA context it would mean line plot. This is confusing.

**Recommendation**: Rename to:
```typescript
const plsdaDisplayOptions = [
  { label: "Scores Plot", value: "scores" },
  { label: "Loadings Line Plot", value: "loadings_lines" },  // NEW
  { label: "Loadings Biplot", value: "loadings_biplot" },    // Renamed
  { label: "VIP Scores", value: "vip" },
];
```

---

## 9. The Root Cause

The core issue is that **PLS-DA loadings are interpreted differently than PCA loadings** in the visualization layer:

- **PCA**: `loadings[i]` → "PC i's spectral pattern" → line plot
- **PLS-DA**: `loadings[:, i]` → "Feature i's position in LV space" → biplot

Both interpretations are mathematically valid, but having **different defaults** creates UX inconsistency.

### Why This Happened

1. **Chemometric tradition**: PLS biplots are common in chemometrics literature for showing feature correlations
2. **Different goals**: PCA loadings show "what patterns exist", PLS-DA biplots show "which features discriminate together"
3. **Missing awareness**: Developer didn't realize PCA set the precedent for line plots

---

## 10. Recommendations

### Immediate Fix (High Priority)
1. **Add loadings line plot option to PLS-DA** (mirror PCA behavior)
   - Create `_generate_plsda_loadings_lineplot()` method
   - Show LV1, LV2, LV3, ... as separate lines
   - Use same x-axis logic (wavenumbers > feature_names > indices)

2. **Rename current biplot** to avoid confusion
   - Change label from "Loadings Plot" to "Loadings Biplot" or "Feature Correlation Biplot"

3. **Update Quick Plot Modal**
   - Add separate options for line plot vs biplot
   - Default to line plot (consistent with PCA)

### Medium Priority
4. **Add explained variance to PLS-DA**
   - Calculate variance explained by each LV
   - Add to pc_labels: "LV1 (34.5%)", "LV2 (22.1%)"
   - Add scree plot option

5. **Add diagnostic plots to PLS-DA**
   - Hotelling T² for outlier detection in LV space
   - SPE/Q-residuals for model fit

### Low Priority
6. **Add component pair selector for biplots**
   - Allow viewing LV1 vs LV3, LV2 vs LV3, etc.
   - Not just hardcoded to LV1 vs LV2

---

## 11. Code Changes Required

### Backend: classification.py

**Add new method for line plot**:
```python
def _generate_plsda_loadings_lineplot(self, loadings, n_components, wavenumbers, feature_names):
    """Generate loadings line plot (like PCA) showing each LV as a line."""
    # Priority: feature_names > wavenumbers > indices
    if feature_names and len(feature_names) == loadings.shape[1]:
        x_values = feature_names
        x_title = "Feature"
    elif wavenumbers and len(wavenumbers) == loadings.shape[1]:
        x_values = wavenumbers
        x_title = "Wavenumber (cm⁻¹)"
    else:
        x_values = list(range(loadings.shape[1]))
        x_title = "Feature Index"

    traces = []
    for i in range(n_components):
        traces.append({
            "type": "scatter",
            "mode": "lines",
            "x": x_values,
            "y": loadings[i, :].tolist(),  # LV i's loadings across all features
            "name": f"LV{i+1}",
            "line": {"width": 2},
        })

    return {
        "data": traces,
        "layout": {
            "title": "PLS-DA Loadings (Component Patterns)",
            "xaxis": {"title": x_title, "autorange": "reversed" if wavenumbers else True},
            "yaxis": {"title": "Loading"},
            "showlegend": True,
        }
    }
```

**Modify _generate_plsda_plots()**:
```python
# Add both biplot and line plot
plots["loadings_biplot"] = {...}  # Current biplot code
plots["loadings_lines"] = self._generate_plsda_loadings_lineplot(...)
plots["loadings"] = plots["loadings_lines"]  # Default to line plot for consistency with PCA
```

### Frontend: QuickPlotModal.vue

**Update display options**:
```typescript
const plsdaDisplayOptions = [
  { label: "Scores Plot", value: "scores" },
  { label: "Loadings (Lines)", value: "loadings" },
  { label: "Loadings (Biplot)", value: "loadings_biplot" },
  { label: "VIP Scores", value: "vip" },
];
```

**Update buildPLSDAPlotData()**:
```typescript
function buildPLSDAPlotData(output: any, mode: string) {
  const plots = output.plots || {};

  if (mode === "loadings") {
    return plots.loadings?.data || plots.loadings_lines?.data || [];
  } else if (mode === "loadings_biplot") {
    return plots.loadings_biplot?.data || [];
  }
  // ... rest of modes
}
```

### Frontend: NodeDetailView.vue

**Add toggle for loadings visualization**:
```vue
<div class="loadings-view-toggle">
  <Button label="Line Plot" @click="plsdaLoadingsView = 'lines'" />
  <Button label="Biplot" @click="plsdaLoadingsView = 'biplot'" />
</div>
<PlotlyChart
  :data="plsdaLoadingsView === 'lines' ? plsdaLoadingsLinesData : plsdaLoadingsBiplotData"
  :layout="plsdaLoadingsView === 'lines' ? plsdaLoadingsLinesLayout : plsdaLoadingsBiplotLayout"
/>
```

---

## 12. Summary Table

| Aspect | PCA | PLS-DA (Current) | PLS-DA (Recommended) |
|--------|-----|------------------|----------------------|
| **Loadings shape** | (n_components, n_features) | (n_components, n_features) | ✓ Same |
| **Loadings line plot** | ✓ Yes | ✗ No | ✓ Add |
| **Loadings biplot** | ✗ No | ✓ Yes | ✓ Keep |
| **Explained variance** | ✓ Yes | ✗ No | ✓ Add |
| **VIP scores** | ✗ No | ✓ Yes | ✓ Keep |
| **Confidence ellipses** | ✗ No | ✓ Yes | ✓ Keep |
| **Diagnostics (T², SPE)** | ✓ Yes | ✗ No | ✓ Add (optional) |
| **Default visualization** | Line plot | Biplot | **Line plot** (for consistency) |

---

## 13. Conclusion

The identified problem is that **PLS-DA loadings visualization is inconsistent with PCA**, providing only a biplot when users expect (based on PCA precedent) to see line plots showing each component's pattern across features.

**Root cause**: Different chemometric traditions led to different default visualizations, but both matrix shapes are identical and could support both views.

**Solution**: Provide both line plot and biplot options for PLS-DA loadings, defaulting to line plot for UX consistency with PCA.

---

**Document Version**: 1.0
**Date**: 2026-01-24
**Status**: Issue identified, solution proposed, implementation pending
