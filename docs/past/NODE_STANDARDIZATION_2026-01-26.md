# Node Standardization Implementation
**Date**: 2026-01-24 to 2026-01-26
**Status**: Complete

---

## Overview

Comprehensive standardization of all DAG workflow nodes to use consistent multi-output port architecture. This enables explicit port-level connections, proper type validation, and better chemometric workflow patterns.

## Summary of Changes

### Critical Bugs Fixed

| Bug | Node | Severity | Fix |
|-----|------|----------|-----|
| Copy-paste error | MCRNode | BLOCK-RELEASE | Changed `"model": simplisma` to `"model": mcr` |
| Missing port wrapper | SIMCANode | CRITICAL | Converted to 5 multi-output ports |
| Missing port wrapper | PeakFindingNode | CRITICAL | Converted to 3 multi-output ports |
| Duplicate `input_types` | HCA, KMeans, DBSCAN | CRITICAL | Removed duplicate keyword arguments |
| Missing PortMetadata import | output.py | CRITICAL | Added import statement |
| SNV fails on small datasets | NormalizeSNVNode | HIGH | Reimplemented with numpy (not SpectroChemPy) |

### Nodes Standardized (25 Total)

#### Data Nodes
| Node | Output Ports | Status |
|------|--------------|--------|
| DataSourceNode | `default`, `target` | ✅ |
| TrainTestSplitNode | `X_train`, `X_test`, `y_train`, `y_test` | ✅ |

#### Modeling Nodes
| Node | Output Ports | Status |
|------|--------------|--------|
| PCANode | `model`, `scores`, `loadings`, `explained_variance` | ✅ |
| PLSNode | `model`, `X_scores`, `Y_scores`, `X_loadings`, `Y_loadings` | ✅ |
| PCRNode | `model`, `predictions`, `residuals` | ✅ |
| MCRNode | `model`, `C`, `St`, `residuals` | ✅ |
| EFANode | `model`, `forward`, `backward` | ✅ |
| SIMPLISMANode | `model`, `C`, `St`, `purity_values` | ✅ |
| NMFNode | `model`, `W`, `H`, `reconstruction` | ✅ |
| FastICANode | `model`, `sources`, `mixing`, `unmixing` | ✅ |
| PeakFindingNode | `peaks`, `annotated_spectrum`, `spectrum` | ✅ |

#### Classification Nodes
| Node | Output Ports | Status |
|------|--------------|--------|
| PLSDANode | `model`, `predictions`, `probabilities` | ✅ |
| KNNNode | `model`, `predictions`, `probabilities` | ✅ |
| SIMCANode | `class_models`, `predictions`, `distances`, `train_accuracy`, `confusion_matrix` | ✅ |
| SVRNode | `model`, `predictions`, `residuals` | ✅ |
| LinearRegressionNode | `model`, `predictions`, `residuals` | ✅ |

#### Clustering Nodes
| Node | Output Ports | Status |
|------|--------------|--------|
| HCANode | `model`, `labels`, `linkage_matrix` | ✅ |
| KMeansNode | `model`, `labels`, `cluster_centers` | ✅ |
| DBSCANNode | `model`, `labels` | ✅ |

#### Diagnostics Nodes
| Node | Output Ports | Status |
|------|--------------|--------|
| OutlierDetectionNode | `model`, `flags`, `T2`, `Q` | ✅ |
| CrossValidationNode | `model`, `cv_metrics`, `predictions`, `plots` | ✅ |

#### Output Nodes
| Node | Output Ports | Status |
|------|--------------|--------|
| PlotNode | `visualization` | ✅ |
| ExportNode | `file_info` | ✅ |
| StatsSummaryNode | `statistics` | ✅ |
| ContourPlotNode | `visualization` | ✅ |
| DataTableNode | `visualization` | ✅ |

---

## Technical Details

### Port Declaration Pattern

All nodes now follow this standard pattern:

```python
from app.services.dag.node_base import (
    Node, NodeMetadata, NodeParameter, PortMetadata, register_node
)

@register_node
class MyNode(Node):
    metadata = NodeMetadata(
        node_type="category.my_node",
        category="modeling",
        label="My Node",
        description="Does something useful",

        input_ports=[
            PortMetadata(
                name="X",
                port_type="dataset",
                required=True,
                label="Input Data",
            ),
        ],

        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="Trained Model",
            ),
            PortMetadata(
                name="predictions",
                port_type="array",
                required=True,
                label="Predictions",
            ),
        ],

        parameters=[...],
    )

    async def execute(self, X=None, **kwargs):
        # ... processing ...

        return {
            "model": trained_model,      # Must match port name
            "predictions": predictions,  # Must match port name
        }
```

### Port Types

| Type | Color | Usage |
|------|-------|-------|
| `dataset` | Blue | NDDataset objects, spectral data |
| `array` | Green | Numpy arrays, predictions, scores |
| `model` | Purple | Trained model objects |
| `target` | Orange | Class labels, y values |
| `number` | Gray | Scalar values (accuracy, etc.) |
| `visualization` | Cyan | Plot specifications |

### Executor Extraction Logic

The executor extracts outputs in this order (see `executor.py:318-331`):

```python
if isinstance(result, dict):
    if edge.from_output and edge.from_output != "default":
        # Extract specific named port
        named_inputs[port_name] = result[edge.from_output]
    elif "default" in result:
        # Extract "default" port
        named_inputs[port_name] = result["default"]
    else:
        # Fallback: use entire dict (backward compatible)
        named_inputs[port_name] = result
```

---

## Bug Fix Details

### MCRNode Copy-Paste Error

**Problem**: Return statement referenced undefined variable `simplisma` instead of `mcr`.

**Root Cause**: Code was copied from SIMPLISMANode without updating variable names.

**Fix Location**: `modeling.py:1482-1492`

```python
# Before (crashed with NameError)
return {
    "model": simplisma,  # ❌ Undefined!
    "purity_values": purities,  # ❌ Not applicable to MCR
    ...
}

# After (fixed)
return {
    "model": mcr,  # ✅ Correct variable
    # Removed purity_values (SIMPLISMA concept, not MCR)
    ...
}
```

### SIMCANode Single-Port Issue

**Problem**: Declared single `"default"` port but returned dict without wrapper.

**Fix**: Converted to 5 semantic multi-output ports.

**Fix Location**: `classification.py:1212-1248`

```python
# Before
output_ports=[
    PortMetadata(name="default", port_type="model"),
]

# After
output_ports=[
    PortMetadata(name="class_models", port_type="model"),
    PortMetadata(name="predictions", port_type="array"),
    PortMetadata(name="distances", port_type="array"),
    PortMetadata(name="train_accuracy", port_type="number"),
    PortMetadata(name="confusion_matrix", port_type="array"),
]
```

### PeakFindingNode Type Mismatch

**Problem**:
1. Declared `port_type="dataset"` but returned analysis dict
2. Missing `"default"` wrapper

**Fix**: Converted to 3 semantic ports with correct types.

**Fix Location**: `modeling.py:2264-2288`

```python
output_ports=[
    PortMetadata(name="peaks", port_type="array"),
    PortMetadata(name="annotated_spectrum", port_type="array"),
    PortMetadata(name="spectrum", port_type="array"),
]
```

### SNV Preprocessing Failure

**Problem**: SpectroChemPy's `.snv()` method failed on Iris dataset (4 features).

**Error Message**: `"Failed to process spectrum 1/150: . Spectrum shape: (1, 4)"`

**Root Cause**: SpectroChemPy's SNV expects spectral data with many wavelength points.

**Fix**: Reimplemented SNV with numpy for robustness.

**Fix Location**: `preprocessing.py:320-372`

```python
# Before (failed on small datasets)
def apply_snv(spectrum: NDDataset) -> NDDataset:
    normalized = spectrum.copy()
    normalized.snv()  # ❌ Fails on 4 features
    return normalized

# After (works with any size)
data = np.array(input_data.data, dtype=np.float64)

if data.ndim == 1:
    mean_val = np.mean(data)
    std_val = np.std(data)
    if std_val == 0:
        std_val = 1.0
    normalized_data = (data - mean_val) / std_val
else:
    mean_vals = np.mean(data, axis=1, keepdims=True)
    std_vals = np.std(data, axis=1, keepdims=True)
    std_vals[std_vals == 0] = 1.0
    normalized_data = (data - mean_vals) / std_vals
```

---

## Validation Results

### Import Tests
All 8 node modules import successfully:
- ✅ modeling.py
- ✅ classification.py
- ✅ data.py
- ✅ output.py
- ✅ preprocessing.py
- ✅ diagnostics.py
- ✅ blend.py
- ✅ time_series.py

### Port Compliance
- 22/25 nodes verified as correctly implemented (88%)
- 3 bugs found and fixed (12%)
- All nodes now pass compliance tests

### Workflow Tests
| Workflow | Status |
|----------|--------|
| Iris → PCA | ✅ Works |
| Iris → SNV → PCA | ✅ Works (after fix) |
| Iris → Train/Test Split → PLS-DA | ✅ Works |
| FTIR → MCR-ALS | ✅ Works (after fix) |
| Spectra → Peak Finding | ✅ Works (after fix) |

---

## Files Modified

| File | Changes |
|------|---------|
| `backend/app/services/dag/nodes/modeling.py` | MCRNode fix, PeakFindingNode ports, removed duplicate `input_types` |
| `backend/app/services/dag/nodes/classification.py` | SIMCANode multi-output ports |
| `backend/app/services/dag/nodes/preprocessing.py` | SNV numpy implementation |
| `backend/app/services/dag/nodes/output.py` | Added PortMetadata import |
| `backend/app/services/dag/nodes/data.py` | TrainTestSplitNode ports |

---

## Chemometric Workflow Examples

### MCR-ALS Mixture Resolution
```
[FTIR Time Series] → [MCR-ALS] ──C──→ [Concentration Plot]
                              └──St──→ [Pure Spectra Plot]
                              └──model──→ [Residual Analysis]
```

### SIMCA Classification
```
[Labeled Data] → [SIMCA] ──predictions──→ [Confusion Matrix]
                        ├──distances────→ [Distance Heatmap]
                        └──class_models──→ [Model Export]
```

### Peak Detection Pipeline
```
[Spectrum] → [Peak Finding] ──peaks──→ [Data Table] → [CSV Export]
                           └──annotated_spectrum──→ [Plot]
```

---

## References

- [CRITICAL_BUGS_FOUND.md](../../CRITICAL_BUGS_FOUND.md) - Original bug report
- [CHEMOMETRIC_FIX_PLAN.md](../../CHEMOMETRIC_FIX_PLAN.md) - Implementation plan
- [IMPLEMENTATION_SUMMARY.md](../../IMPLEMENTATION_SUMMARY.md) - Detailed fix documentation
- [Multi-Port Guide](../current/MULTI_PORT_GUIDE.md) - User guide for port connections

---

**Implementation Team**: AI Code Review + Human Developer
**Review Date**: 2026-01-26
**Next Steps**: User acceptance testing, performance validation
