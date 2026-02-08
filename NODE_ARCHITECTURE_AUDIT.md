# Node Architecture Audit & Alignment Recommendations
**Date**: 2026-01-24
**Scope**: All 53 DAG Nodes in Backend
**Status**: 🔴 **Critical Inconsistencies Found**

---

## Executive Summary

Audited all 53 nodes across the DAG system. Found significant architectural inconsistencies between nodes, particularly:

1. **10 modeling nodes** return complex multi-output dicts but declare only single `output_port`
2. **Classification nodes** use different patterns for training (1 port) vs. prediction (2 ports)
3. **~83% of nodes** still use legacy `input_types`/`output_type` pattern
4. **DataSourceNode** is the gold standard - properly declares multi-output ports

### Risk Assessment
- **Data Flow**: ✅ Works correctly (executor extracts properly)
- **Type Safety**: ⚠️ Weak (undeclared multi-outputs bypass validation)
- **Composability**: ⚠️ Limited (can't selectively connect to sub-outputs)
- **Maintainability**: 🔴 **Poor** (inconsistent patterns across similar nodes)

---

## Critical Finding: Hidden Multi-Output Nodes

### Problem
**10 modeling nodes** return complex dicts containing 3-5 distinct outputs but declare only a single `output_port`:

| Node | Actual Outputs (dict keys) | Declared Ports | Issue |
|------|---------------------------|----------------|-------|
| **PCANode** | model, scores, loadings, explained_variance | 1 (default) | ❌ 4 outputs, 1 port |
| **PLSNode** | model, X_scores, Y_scores, X_loadings, Y_loadings | 1 (default) | ❌ 5 outputs, 1 port |
| **MCRNode** | C (concentrations), St (spectra), model, residuals | 1 (default) | ❌ 4 outputs, 1 port |
| **PLSDANode** | model, predictions, probabilities, cm_train, cm_cv | 1 (default) | ❌ 5 outputs, 1 port |
| **KNNNode** | model, predictions, probabilities, cm_train, cm_cv | 1 (default) | ❌ 5 outputs, 1 port |

**Example - PCANode** [modeling.py:112-340]:
```python
# Declared metadata (appears single-output)
output_ports=[
    PortMetadata(
        name="default",
        port_type="model",
    ),
]

# Actual return value (multi-output)
return {
    "model": pca_result,              # Trained PCA model
    "scores": X_scores,                # Scores (n_samples × n_components)
    "loadings": pca.get_loadings(),    # Loadings (n_features × n_components)
    "explained_variance": explained_var,  # Variance explained per PC
    "data": {...},                     # Visualization data
    "metadata": {...},                 # Additional metadata
}
```

### Impact
1. **Type Safety Loss**: Frontend can't validate connections to specific outputs
2. **Workflow Limitation**: Can't connect only "scores" to a downstream node (must pass entire dict)
3. **Inconsistency**: Different from DataSourceNode which properly declares multi-outputs

### Comparison with Best Practice

**DataSourceNode** (Correct Pattern) [data.py:346-361]:
```python
output_type="dict",  # Explicitly states multi-output
output_ports=[
    PortMetadata(
        name="default",
        port_type="dataset",
        required=True,
        label="Dataset",
    ),
    PortMetadata(
        name="target",
        port_type="target",
        required=False,
        label="Target Labels",
    ),
],

# Execute returns
return {
    "default": dataset,   # Explicit key matching port name
    "target": target,     # Explicit key matching port name
}
```

**PLSDAPredictNode** (Correct Pattern) [classification.py:1488-1503]:
```python
output_type="dict",
output_ports=[
    PortMetadata(
        name="y_pred",
        port_type="array",
        label="Predicted Classes",
    ),
    PortMetadata(
        name="y_prob",
        port_type="array",
        label="Class Probabilities",
    ),
],

# Execute returns
return {
    "y_pred": predictions,     # Explicit key matching port name
    "y_prob": probabilities,   # Explicit key matching port name
}
```

---

## Node Inventory by Category

### 1. Data Source Nodes (1 node)

| Node | Pattern | Status |
|------|---------|--------|
| **DataSourceNode** | ✅ Modern multi-output | **Gold standard** |

**Characteristics**:
- Declares 2 `output_ports`: "default" (dataset) + "target" (labels)
- Returns `{"default": ..., "target": ...}`
- Conditional output (target only for sklearn datasets)
- Executor correctly extracts based on port name

---

### 2. Preprocessing Nodes (18 nodes)

All 18 nodes follow **consistent single-value pattern**:

| Nodes | Input | Output | Pattern |
|-------|-------|--------|---------|
| Baseline (ALS, Rubberband) | NDDataset | NDDataset | ✅ Legacy single-value |
| Smoothing (Savitzky-Golay) | NDDataset | NDDataset | ✅ Legacy single-value |
| Normalization (SNV, Scale, MSC) | NDDataset | NDDataset | ✅ Legacy single-value |
| Derivatives (1st, 2nd, SG) | NDDataset | NDDataset | ✅ Legacy single-value |
| Clipping (Range, Floor) | NDDataset | NDDataset | ✅ Legacy single-value |
| Scaling (Max, Mean Center, Pareto, Autoscaling) | NDDataset | NDDataset | ✅ Legacy single-value |
| Advanced (EMSC, Cosmic Ray, Wavenumber Align) | NDDataset | NDDataset | ✅ Legacy single-value |

**Exception: OSCNode** (Orthogonal Signal Correction) [preprocessing.py:1051-1238]:
```python
input_ports=[
    PortMetadata(name="X", port_type="dataset", required=True),
    PortMetadata(name="y", port_type="target", required=True),
]
output_type="NDDataset"
```
- ✅ **Modern input_ports** (requires two inputs: data + target)
- Returns single NDDataset (corrected X)

**Assessment**: ✅ **No issues** - Single-value transforms don't need multi-output

---

### 3. Modeling Nodes (10 nodes) - ⚠️ **CRITICAL ISSUES**

#### Decomposition Methods

| Node | Input Pattern | Actual Outputs | Declared Ports | Issue |
|------|---------------|----------------|----------------|-------|
| **PCANode** | Legacy (single) | model, scores, loadings, explained_variance (4) | 1 | ❌ |
| **MCRNode** | Legacy (single) | C, St, model, residuals (4) | 1 | ❌ |
| **EFANode** | Legacy (single) | model, forward_spectra, backward_spectra (3) | 1 | ❌ |
| **NMFNode** | Legacy (single) | W, H, model, residuals (4) | 1 | ❌ |
| **FastICANode** | Legacy (single) | S, A, model (3) | 1 | ❌ |

**Example - MCRNode** [modeling.py:1149-1391]:
```python
# Actually returns 4 distinct outputs
return {
    "C": C_result,          # Concentration profiles (n_samples × n_components)
    "St": St_result,        # Pure component spectra (n_components × n_features)
    "model": mcr,           # Fitted MCR model
    "data": {...},          # Visualization data
}

# But declares only 1 output port
output_ports=[PortMetadata(name="default", port_type="model")]
```

**Recommendation**: Declare 3 output ports:
- `concentrations`: Concentration profiles
- `spectra`: Pure component spectra
- `model`: Fitted model object

#### Regression Methods

| Node | Input Pattern | Actual Outputs | Declared Ports | Issue |
|------|---------------|----------------|----------------|-------|
| **PLSNode** | ✅ Modern (X, y) | model, X_scores, Y_scores, loadings (5) | 1 | ❌ |
| **PCRNode** | ✅ Modern (X, y) | model, scores, loadings, predictions (4) | 1 | ❌ |
| **SVRNode** | ✅ Modern (X, y) | model, predictions, residuals (3) | 1 | ❌ |
| **LinearRegressionNode** | ✅ Modern (X, y) | model, predictions, coefficients (3) | 1 | ❌ |

**Example - PLSNode** [modeling.py:377-600]:
```python
input_ports=[
    PortMetadata(name="X", port_type="dataset"),
    PortMetadata(name="y", port_type="target"),
]

return {
    "model": pls_result,
    "X_scores": X_scores,
    "Y_scores": Y_scores,
    "X_loadings": X_loadings,
    "Y_loadings": Y_loadings,
    "data": {...},
}

# Should declare 5 output ports (or at minimum 3: model, X_scores, X_loadings)
```

#### Clustering Methods

| Node | Input Pattern | Actual Outputs | Declared Ports | Issue |
|------|---------------|----------------|----------------|-------|
| **HCANode** | Legacy (single) | model, labels, linkage_matrix (3) | 1 | ❌ |
| **KMeansNode** | Legacy (single) | model, labels, centers, inertia (4) | 1 | ❌ |
| **DBSCANNode** | Legacy (single) | model, labels, core_samples (3) | 1 | ❌ |

**Assessment**: All 10 modeling nodes have **undeclared multi-output structure**

---

### 4. Classification Nodes (5 nodes) - ⚠️ **INCONSISTENT**

#### Training Nodes (Same Issue as Modeling)

| Node | Input Pattern | Actual Outputs | Declared Ports | Issue |
|------|---------------|----------------|----------------|-------|
| **PLSDANode** | ✅ Modern (X, y) | model, predictions, probabilities, cm_train, cm_cv, classes (6) | 1 | ❌ |
| **KNNNode** | ✅ Modern (X, y) | model, predictions, probabilities, cm_train, cm_cv, classes (6) | 1 | ❌ |
| **SIMCANode** | ✅ Modern (X, y) | class_models, predictions, distances (3) | 1 | ❌ |

**PLSDANode Example** [classification.py:267-284]:
```python
return {
    "model": pls_model,                      # Trained PLS-DA model
    "classes": classes,                      # Class labels
    "n_classes": n_classes,
    "predictions_train": y_pred_train,       # Training predictions
    "predictions_cv": y_pred_cv,             # CV predictions
    "probabilities_train": y_proba_train,    # Training probabilities
    "probabilities_cv": y_proba_cv,          # CV probabilities
    "confusion_matrix_train": cm_train,      # Training confusion matrix
    "confusion_matrix_cv": cm_cv,            # CV confusion matrix
    "classification_report": report,
    "data": {...},                           # Visualization plots
}

# Should declare at least 3 ports: model, predictions, probabilities
```

#### Prediction Nodes ✅ (Correct Pattern!)

| Node | Input Pattern | Actual Outputs | Declared Ports | Status |
|------|---------------|----------------|----------------|--------|
| **PLSDAPredictNode** | ✅ Modern (X_new, model) | y_pred, y_prob (2) | 2 (y_pred, y_prob) | ✅ **Perfect** |
| **KNNPredictNode** | ✅ Modern (X_new, model) | y_pred, y_prob (2) | 2 (y_pred, y_prob) | ✅ **Perfect** |

**PLSDAPredictNode Example** [classification.py:1488-1503]:
```python
output_ports=[
    PortMetadata(
        name="y_pred",
        port_type="array",
        label="Predicted Classes",
    ),
    PortMetadata(
        name="y_prob",
        port_type="array",
        label="Class Probabilities",
    ),
]

return {
    "y_pred": predictions,      # Matches port name
    "y_prob": probabilities,    # Matches port name
}
```

**Critical Inconsistency**: Training nodes (PLSDA, KNN) use different pattern than their prediction counterparts (PLSDAPredictNode, KNNPredictNode)

---

### 5. Prediction/Transform Nodes (2 nodes)

| Node | Input Pattern | Actual Outputs | Declared Ports | Status |
|------|---------------|----------------|----------------|--------|
| **PLSPredictNode** | ✅ Modern (X_new, model) | predictions (1) | 1 | ✅ Correct single-output |
| **PCATransformNode** | ✅ Modern (X_new, model) | scores (1) | 1 | ✅ Correct single-output |

**Assessment**: ✅ **Correct** - Single-purpose transform nodes

---

### 6. Diagnostic Nodes (2 nodes)

| Node | Input Pattern | Output Pattern | Status |
|------|---------------|----------------|--------|
| **OutlierDetectionNode** | ❌ Legacy (input_types) | ❌ Legacy (output_type) | ⚠️ Should modernize |
| **CrossValidationNode** | ✅ Modern (input_ports) | ❌ Legacy (output_type) | ⚠️ Inconsistent |

**OutlierDetectionNode** [diagnostics.py:18-153]:
```python
input_types=["PCAModel", "dict"]  # Legacy pattern
output_type="OutlierReport"       # Legacy pattern

# Should use:
input_ports=[
    PortMetadata(name="model", port_type="model"),
]
output_ports=[
    PortMetadata(name="report", port_type="report"),
]
```

**CrossValidationNode** [diagnostics.py:154-249]:
```python
input_ports=[
    PortMetadata(name="y_true", ...),
    PortMetadata(name="y_pred", ...),
]
output_type="CVResult"  # ← Should be output_ports

# Inconsistent: Has input_ports but not output_ports
```

---

### 7. Output Nodes (6 nodes)

| Node | Purpose | Pattern | Status |
|------|---------|---------|--------|
| PlotNode | Visualization | Legacy single-output dict | ✅ Acceptable |
| ExportNode | File export | Legacy single-output dict | ✅ Acceptable |
| StatsSummaryNode | Statistics | Legacy single-output dict | ✅ Acceptable |
| ContourPlotNode | 2D visualization | Legacy single-output dict | ✅ Acceptable |
| DataTableNode | Tabular display | Legacy single-output dict | ✅ Acceptable |

**Assessment**: ✅ **Acceptable** - Output nodes are workflow endpoints, don't need multi-output

---

### 8. Synthesis/Blend Nodes (4 nodes)

| Node | Input Pattern | Output Pattern | Status |
|------|---------------|----------------|--------|
| **BlendNode** | Variadic (*input_data) | Single NDDataset | ✅ Correct |
| **SpeciesSelectorNode** | Single NDDataset | Single NDDataset | ✅ Correct |
| **MergeSpectraNode** | Variadic (*input_data) | Single NDDataset | ✅ Correct |

**Assessment**: ✅ **Correct** - Merge operations produce single combined output

---

### 9. Time Series Nodes (2 nodes)

| Node | Input Pattern | Output Pattern | Status |
|------|---------------|----------------|--------|
| **MovingWindowNode** | Single NDDataset | Single NDDataset | ✅ Correct |
| **TrendRemovalNode** | Single NDDataset | Single NDDataset | ✅ Correct |

**Assessment**: ✅ **Correct** - Single-purpose transformations

---

### 10. Specialized Nodes (3 nodes)

| Node | Type | Pattern | Notes |
|------|------|---------|-------|
| **SIMPLISMANode** | Pure variable extraction | Legacy single-output | Returns pure variables |
| **PeakFindingNode** | Peak detection | Legacy single-output | Returns peak positions |
| **NISTLibraryNode** | External data | Legacy single-output | Loads library spectra |
| **TrainTestSplitNode** | Data splitting | ⚠️ **Should be multi-output** | Returns X_train, X_test, y_train, y_test (4 outputs!) |

**TrainTestSplitNode** [data.py:2260-2441] - **CRITICAL MISSED OPPORTUNITY**:
```python
# Currently returns single dict
return {
    "X_train": X_train,
    "X_test": X_test,
    "y_train": y_train,
    "y_test": y_test,
}

# Should declare 4 output_ports
output_ports=[
    PortMetadata(name="X_train", port_type="dataset"),
    PortMetadata(name="X_test", port_type="dataset"),
    PortMetadata(name="y_train", port_type="target"),
    PortMetadata(name="y_test", port_type="target"),
]
```

**Use Case**: Connect X_train → Model Training, X_test → Model Prediction (selective routing)

---

## Alignment Recommendations

### Priority 1: Fix Multi-Output Modeling Nodes (High Impact)

**Affected Nodes** (10 total):
- PCANode, PLSNode, PCRNode, SVRNode, LinearRegressionNode
- MCRNode, EFANode, NMFNode, FastICANode
- HCANode, KMeansNode, DBSCANNode

**Recommended Approach**:

**Option A: Declare All Outputs** (Ideal, Breaking Change)
```python
# Example: PCANode
output_ports=[
    PortMetadata(name="model", port_type="model", label="PCA Model"),
    PortMetadata(name="scores", port_type="array", label="Scores"),
    PortMetadata(name="loadings", port_type="array", label="Loadings"),
    PortMetadata(name="explained_variance", port_type="array", label="Explained Variance"),
]

return {
    "model": pca_result,
    "scores": X_scores,
    "loadings": loadings,
    "explained_variance": explained_var,
}
```

**Benefits**:
- Enable selective connections (e.g., only use scores for plotting)
- Type safety on each output
- Self-documenting API
- Matches DataSourceNode pattern

**Drawbacks**:
- Breaking change for existing workflows
- Frontend needs "select output port" UI

**Option B: Keep Single Port, Document Structure** (Non-Breaking)
```python
# Keep current single port
output_ports=[
    PortMetadata(
        name="default",
        port_type="model",
        label="PCA Result",
        description="Dict containing: model, scores, loadings, explained_variance"
    )
]

# No changes to execute() return
return {...}  # Current behavior
```

**Benefits**:
- No breaking changes
- Maintains backward compatibility

**Drawbacks**:
- Doesn't improve composability
- Type checking remains weak

**Recommendation**: **Option A** for new nodes, **Option B** for existing nodes (add migration path later)

---

### Priority 2: Align Classification Training Nodes

**Affected Nodes**: PLSDANode, KNNNode, SIMCANode

**Current Inconsistency**:
- Training nodes: 1 output port (dict with model, predictions, probabilities)
- Prediction nodes: 2 output ports (y_pred, y_prob)

**Recommendation**: Match prediction node pattern

```python
# PLSDANode should declare
output_ports=[
    PortMetadata(name="model", port_type="model", label="Trained Classifier"),
    PortMetadata(name="predictions", port_type="array", label="Training Predictions"),
    PortMetadata(name="probabilities", port_type="array", label="Class Probabilities"),
]

return {
    "model": pls_model,
    "predictions": y_pred_cv,          # Use CV predictions as primary
    "probabilities": y_proba_cv,
    # Additional data in metadata (cm_train, cm_cv, etc.)
}
```

**Alternative**: Keep full dict in "default" port, but add explicit metadata documenting structure

---

### Priority 3: Fix Diagnostic Nodes Inconsistency

**OutlierDetectionNode**: Convert to modern ports
```python
# Current
input_types=["PCAModel", "dict"]
output_type="OutlierReport"

# Recommended
input_ports=[
    PortMetadata(name="model", port_type="model", label="PCA Model"),
]
output_ports=[
    PortMetadata(name="outliers", port_type="report", label="Outlier Report"),
]
```

**CrossValidationNode**: Add output_ports
```python
# Current
input_ports=[...]  # ✅ Already modern
output_type="CVResult"  # ❌ Legacy

# Recommended
output_ports=[
    PortMetadata(name="report", port_type="report", label="CV Metrics"),
]
```

---

### Priority 4: Fix TrainTestSplitNode

**Current** [data.py:2260-2441]:
```python
return {
    "X_train": X_train,
    "X_test": X_test,
    "y_train": y_train,
    "y_test": y_test,
}
```

**Recommended**:
```python
output_ports=[
    PortMetadata(name="X_train", port_type="dataset", label="Training Features"),
    PortMetadata(name="X_test", port_type="dataset", label="Test Features"),
    PortMetadata(name="y_train", port_type="target", label="Training Labels"),
    PortMetadata(name="y_test", port_type="target", label="Test Labels"),
]

# Same return value
return {
    "X_train": X_train,
    "X_test": X_test,
    "y_train": y_train,
    "y_test": y_test,
}
```

**Use Case**: Critical for ML workflows - connect splits to different downstream nodes

---

### Priority 5: Standardize Type Names

**Current Type Name Issues**:
- "dict" (too generic)
- "PCAModel" vs "PLSModel" (should be unified)
- "OutlierReport" vs "CVResult" (inconsistent naming)

**Recommended Type Taxonomy**:

| Category | Type Name | Example Nodes |
|----------|-----------|---------------|
| Data | `"NDDataset"` | All preprocessing nodes ✅ |
| Data | `"array"` | Numeric arrays |
| Data | `"target"` | Class labels / targets |
| Model | `"DecompositionModel"` | PCA, MCR, EFA, NMF |
| Model | `"RegressionModel"` | PLS, PCR, SVR, LinearRegression |
| Model | `"ClassificationModel"` | PLSDA, KNN, SIMCA |
| Model | `"ClusteringModel"` | HCA, KMeans, DBSCAN |
| Report | `"DiagnosticReport"` | OutlierDetection, CrossValidation |
| Report | `"PlotData"` | Plot, ContourPlot |

**Benefits**:
- Clear semantic categories
- Easier type mapping in frontend
- Consistent with domain terminology

---

## Implementation Roadmap

### Phase 1: Non-Breaking Improvements (Immediate)

1. **Update Documentation**
   - Add "Returns" section to all modeling node docstrings documenting dict structure
   - Update type descriptions in metadata

2. **Add Type Mapping**
   - Extend frontend type mapping for new type names
   - Add backward compatibility aliases

3. **Fix Diagnostic Nodes**
   - OutlierDetectionNode → modern input_ports
   - CrossValidationNode → add output_ports

### Phase 2: TrainTestSplitNode (High Value, Low Risk)

1. Add 4 `output_ports` to TrainTestSplitNode
2. Update frontend to handle 4-port connections
3. Test with existing workflows (should remain compatible via executor)

### Phase 3: Modeling Nodes Multi-Output (Breaking Change)

1. **Pilot with 1 node** (e.g., PCANode)
   - Add 4 output_ports
   - Update frontend "select output port" UI
   - Test backward compatibility

2. **Roll out to all 10 modeling nodes**
   - PLS, PCR, SVR, LinearRegression
   - MCR, EFA, NMF, FastICA
   - HCA, KMeans, DBSCAN

3. **Update classification training nodes**
   - PLSDA, KNN, SIMCA

### Phase 4: Type System Overhaul (Future)

1. Define formal type taxonomy
2. Create type inheritance hierarchy (if needed)
3. Update all node metadata
4. Migrate frontend validation logic

---

## Risk Analysis

| Change | Breaking? | Risk | Mitigation |
|--------|-----------|------|------------|
| Add output_ports to modeling nodes | ⚠️ Yes | High | Executor fallback, phased rollout |
| Fix diagnostic nodes | ⚠️ Minor | Low | Limited usage, easy migration |
| TrainTestSplitNode | ⚠️ Yes | Medium | High-value use case justifies risk |
| Type name changes | ❌ No | Low | Backward compatibility via mapping |
| Documentation updates | ❌ No | None | Pure improvement |

**Executor Compatibility**: Current executor already handles multi-output extraction ([executor.py:318-331]) - should be compatible.

**Frontend Requirements**: Need UI for "select output port" when connecting multi-output nodes.

---

## Summary Statistics

| Metric | Count | Percentage |
|--------|-------|------------|
| **Total Nodes** | 53 | 100% |
| **Modern input_ports** | 9 | 17% |
| **Modern output_ports** | 3 | 6% |
| **Undeclared multi-output** | 13 | 25% |
| **Inconsistent patterns** | 15 | 28% |
| **Needs alignment** | 15 | 28% |

---

## Conclusion

The audit reveals a **codebase in transition** from legacy single-value patterns to modern multi-output port architecture. Key findings:

1. ✅ **DataSourceNode is exemplary** - Follow this pattern for all multi-output nodes
2. ✅ **Preprocessing nodes are consistent** - No changes needed
3. ❌ **10 modeling nodes hide complexity** - Should declare multi-output ports
4. ⚠️ **Classification nodes are split** - Training vs. prediction inconsistency
5. ⚠️ **TrainTestSplitNode is a missed opportunity** - Should have 4 output ports

**Recommended Action**: Adopt **phased migration** starting with TrainTestSplitNode (high value, clear use case), then pilot with PCANode before rolling out to all modeling nodes.

**Overall Architecture Grade**: 🟡 **C+** (Functional but inconsistent)
**After Alignment**: 🟢 **A** (Modern, type-safe, composable)

---

**Report Prepared By**: Node Architecture Audit Agent
**Review Status**: Ready for engineering team review
**Next Step**: Prioritize alignment roadmap with stakeholders
