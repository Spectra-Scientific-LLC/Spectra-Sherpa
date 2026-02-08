# CRITICAL IMPLEMENTATION BUGS - Node Standardization
**Date**: 2026-01-24
**Review Type**: Critical Bug Detection
**Status**: 🔴 **3 CRITICAL BUGS FOUND**

---

## Executive Summary

Performed comprehensive code review of all standardized nodes. Found **3 critical bugs** where declared `output_ports` don't match the actual `return` dictionaries:

1. 🔴 **SIMCANode**: Missing "default" wrapper
2. 🔴 **PeakFindingNode**: Missing "default" wrapper
3. 🔴 **MCRNode**: Missing "model" key in return dict

---

## Bug #1: SIMCANode - Missing Port Wrapper 🔴

**Severity**: CRITICAL - Will cause connection failures
**File**: [classification.py:1152-1488](Refactored/backend/app/services/dag/nodes/classification.py#L1152-L1488)

### The Problem

**Declared Port** (Lines 1212-1220):
```python
output_ports=[
    PortMetadata(
        name="default",      # ← Declares port named "default"
        port_type="model",
        required=True,
        label="SIMCA Model",
    ),
],
```

**Actual Return** (Lines 1454-1488):
```python
result = {
    "class_models": serializable_models,  # ❌ No "default" key!
    "classes": classes.tolist(),
    "n_classes": n_classes,
    "n_components": n_components,
    "predictions": predictions.tolist(),
    "distances": [...],
    "train_accuracy": train_accuracy,
    # ... more fields ...
}

return result
```

### Impact

When executor tries to extract the "default" port:
```python
# executor.py:322
if edge.from_output and edge.from_output != "default":
    named_inputs[port_name] = result[edge.from_output]  # ← KeyError: "default"
elif "default" in result:  # ← FALSE - key doesn't exist!
    named_inputs[port_name] = result["default"]
```

**Result**: ❌ **Downstream connections will fail** because executor cannot extract "default" key.

### Fix Required

**Option A**: Wrap entire dict in "default" key (standard pattern)
```python
return {
    "default": {
        "class_models": serializable_models,
        "classes": classes.tolist(),
        # ... all existing fields ...
    }
}
```

**Option B**: Declare multi-output ports (better)
```python
output_ports=[
    PortMetadata(name="class_models", port_type="model", label="Class Models"),
    PortMetadata(name="predictions", port_type="array", label="Predictions"),
    PortMetadata(name="distances", port_type="array", label="Distances"),
],

# Return as-is (already has correct keys)
return {
    "class_models": ...,
    "predictions": ...,
    "distances": ...,
    # ...
}
```

**Recommendation**: **Option B** - Matches the modern multi-output pattern you've established.

---

## Bug #2: PeakFindingNode - Missing Port Wrapper 🔴

**Severity**: CRITICAL - Same as Bug #1
**File**: [modeling.py:2198-2402](Refactored/backend/app/services/dag/nodes/modeling.py#L2198-L2402)

### The Problem

**Declared Port** (Lines 2272-2280):
```python
output_ports=[
    PortMetadata(
        name="default",      # ← Declares port named "default"
        port_type="dataset",
        required=True,
        label="Peak Data",
    ),
],
```

**Actual Return** (Lines 2364-2402):
```python
result = {
    "peaks": {              # ❌ No "default" key!
        "count": len(peak_indices),
        "positions": peak_positions,
        "heights": peak_heights,
        # ...
    },
    "spectrum": spectrum.tolist(),
    "annotated_spectrum": annotated_spectrum.tolist(),
    "x_axis": [...],
    # ...
}

return result
```

### Impact

Same as Bug #1 - executor cannot extract "default" port.

### Additional Issue

Port declares `port_type="dataset"` (expecting NDDataset object) but returns a complex analysis dict. This is a **semantic type mismatch**.

### Fix Required

**Option A**: Wrap in "default" key
```python
return {
    "default": {
        "peaks": {...},
        "spectrum": [...],
        # ...
    }
}
```

**Option B**: Use multi-output ports (better)
```python
output_ports=[
    PortMetadata(name="peaks", port_type="array", label="Peak Positions"),
    PortMetadata(name="spectrum", port_type="array", label="Spectrum"),
    PortMetadata(name="annotated_spectrum", port_type="array", label="Annotated Spectrum"),
],

# Return as-is
return {
    "peaks": {...},
    "spectrum": [...],
    "annotated_spectrum": [...],
}
```

**Option C**: Change port_type
```python
output_ports=[
    PortMetadata(
        name="default",
        port_type="analysis",  # ← Not "dataset"
        label="Peak Analysis",
    ),
],

# Wrap in "default"
return {"default": {...}}
```

**Recommendation**: **Option B** - Expose peak data as separate connectable outputs.

---

## Bug #3: MCRNode - Copy-Paste Bug with Undefined Variable 🔴

**Severity**: CRITICAL - Code will crash immediately with NameError
**File**: [modeling.py:1251-1520](Refactored/backend/app/services/dag/nodes/modeling.py#L1251-L1520)

### The Problem

**MCR Model Definition** (Line 1403):
```python
# Create and fit MCR-ALS model
mcr = scp.MCRALS(max_iter=max_iter, tol=tol)  # ← Model stored in 'mcr'
mcr.fit(input_data, C0)
```

**Actual Return** (Lines 1484-1520):
```python
# Get purity values if available
if hasattr(simplisma, "purities"):  # ❌ NameError: 'simplisma' is not defined!
    purities = np.array(simplisma.purities).tolist()

return {
    "model": simplisma,  # ❌ NameError: should be 'mcr'!
    "C": C_data.tolist(),
    "St": St_data.tolist(),
    "purity_values": purities if purities is not None else [],  # ❌ Also uses undefined 'purities'
    # ... rest of fields ...
}
```

### Impact

**This code will crash immediately when executed**:
```python
NameError: name 'simplisma' is not defined
```

1. **Line 1484**: References undefined variable `simplisma` in hasattr() check
2. **Line 1488**: Returns undefined variable `simplisma` instead of `mcr`
3. **Complete execution failure**: Node cannot run at all

### Root Cause

This is a **copy-paste error** from SIMPLISMANode code. The MCR-ALS implementation was likely copied from SIMPLISMA code and the variable names weren't updated.

- MCR uses variable name: `mcr`
- SIMPLISMA uses variable name: `simplisma`
- The return statement still references `simplisma`

### Fix Required

```python
# Delete lines 1484-1485 (purity values don't exist in MCR-ALS)
# MCR-ALS doesn't compute purities - that's a SIMPLISMA concept

return {
    "model": mcr,  # ← CHANGE from 'simplisma' to 'mcr'
    "C": C_data.tolist(),
    "St": St_data.tolist(),
    # ← REMOVE "purity_values" line (not applicable to MCR-ALS)
    "n_components": n_components,
    # ... rest of fields ...
}
```

**Specific changes**:
1. **Line 1488**: Change `"model": simplisma,` → `"model": mcr,`
2. **Lines 1484-1485**: Delete the purities check (not applicable to MCR-ALS)
3. **Line 1491**: Remove `"purity_values": purities if purities is not None else [],`

---

## Summary Table

| Node | Bug Type | Declared Ports | Return Keys | Issue | Severity |
|------|----------|---------------|-------------|-------|----------|
| **SIMCANode** | Missing wrapper | `default` | class_models, predictions, ... | Missing `default` wrapper | 🔴 CRITICAL |
| **PeakFindingNode** | Missing wrapper | `default` | peaks, spectrum, ... | Missing `default` wrapper | 🔴 CRITICAL |
| **MCRNode** | NameError | `model`, C, St, residuals | Returns undefined `simplisma` | Code crashes immediately | 🔴 CRITICAL |

---

## Impact Analysis

### Executor Behavior

The executor tries to extract outputs in this order ([executor.py:318-331](Refactored/backend/app/services/dag/executor.py#L318-L331)):

1. If `edge.from_output` is specified → Extract `result[edge.from_output]`
2. Else if `"default"` in result → Extract `result["default"]`
3. Else → Use entire result dict

**For SIMCANode and PeakFindingNode**:
- No explicit `from_output` → Falls to step 2
- `"default" in result` → **FALSE** (key missing)
- Falls to step 3 → Uses entire dict
- **Problem**: Frontend expects to extract specific port but receives entire dict

**For MCRNode**:
- If user tries to connect "model" port → `result["model"]` → **KeyError!**
- App crashes at connection time

### Frontend Impact

The port selection UI ([WorkflowCanvas.vue:288-305](Refactored/frontend/src/views/workflow-builder/WorkflowCanvas.vue#L288-L305)) shows buttons for each port:

**SIMCANode**:
- User clicks "SIMCA Model" button
- Frontend sends `fromPort: "default"` to executor
- Executor tries `result["default"]` → **KeyError** or wrong data

**MCRNode**:
- User clicks "MCR Model" button
- Frontend sends `fromPort: "model"` to executor
- Executor tries `result["model"]` → **KeyError!** 💥

---

## Testing Recommendations

### Unit Tests (Add These)

```python
async def test_node_returns_all_declared_ports():
    """Verify return dict contains all required output port keys."""
    node = SIMCANode(parameters={...})
    result = await node.execute(test_data, test_labels)

    # Get required port names from metadata
    required_ports = [
        p.name for p in node.metadata.output_ports
        if p.required
    ]

    # Verify all required ports present in result
    for port_name in required_ports:
        assert port_name in result, f"Missing required port: {port_name}"
```

### Integration Tests

```python
async def test_simca_connection_flow():
    """Test SIMCANode → downstream node connection."""
    workflow = {
        "nodes": [
            {"id": 1, "type": "data.source"},
            {"id": 2, "type": "classification.simca"},
            {"id": 3, "type": "output.plot"},
        ],
        "edges": [
            {"from": 1, "to": 2},
            {"from": 2, "to": 3, "fromPort": "default"},  # ← Should work!
        ]
    }

    result = await execute_workflow(workflow)
    assert result.success
```

---

## Recommended Fix Priority

### Priority 1: MCRNode 🔴🔴🔴
**Impact**: **CODE CRASHES IMMEDIATELY** - NameError on execution
**Fix Time**: 5 minutes
**Urgency**: BLOCK-RELEASE - This node cannot run at all

```python
# Lines 1484-1491 - Fix the copy-paste error:

# DELETE these lines (1484-1485):
# if hasattr(simplisma, "purities"):
#     purities = np.array(simplisma.purities).tolist()

# UPDATE return statement (line 1487-1520):
return {
    "model": mcr,  # ← CHANGE from 'simplisma' to 'mcr'
    "C": C_data.tolist(),
    "St": St_data.tolist(),
    # REMOVE: "purity_values": purities if purities is not None else [],
    "n_components": n_components,
    "n_samples": n_samples,
    # ... rest unchanged ...
}
```

### Priority 2: SIMCANode 🔴
**Impact**: Connection failures, unexpected behavior
**Fix Time**: 15 minutes
**Choice**: Wrap in "default" (5 min) OR declare multi-output ports (15 min)

### Priority 3: PeakFindingNode 🔴
**Impact**: Connection failures, type mismatch
**Fix Time**: 20 minutes
**Choice**: Wrap in "default" (5 min) OR refactor to multi-output (20 min)

---

## Pattern Violation Analysis

### Correct Pattern (PLSDANode, KNNNode, PLSNode)

✅ **Multi-output with explicit port names**:
```python
output_ports=[
    PortMetadata(name="model", ...),
    PortMetadata(name="predictions", ...),
    PortMetadata(name="probabilities", ...),
]

return {
    "model": trained_model,        # ← Keys match port names
    "predictions": preds,
    "probabilities": probs,
    # ... additional fields OK ...
}
```

### Incorrect Pattern (SIMCANode, PeakFindingNode)

❌ **Single port "default" but return without wrapper**:
```python
output_ports=[
    PortMetadata(name="default", ...),  # ← Says "default"
]

return {
    "field1": ...,  # ❌ No "default" key!
    "field2": ...,
}
```

**Should be**:
```python
return {
    "default": {    # ← Wrap entire dict
        "field1": ...,
        "field2": ...,
    }
}
```

**OR** (preferred):
```python
output_ports=[
    PortMetadata(name="field1", ...),  # ← Explicit ports
    PortMetadata(name="field2", ...),
]

return {
    "field1": ...,  # ← Keys match ports
    "field2": ...,
}
```

---

## Nodes Verified As Correct ✅

| Node | Ports | Status |
|------|-------|--------|
| TrainTestSplitNode | 4 | ✅ Perfect |
| PCANode | 4 | ✅ Perfect |
| PLSNode | 5 | ✅ Perfect |
| PCRNode | 3 | ✅ Perfect |
| SVRNode | 3 | ✅ Perfect |
| LinearRegressionNode | 3 | ✅ Perfect |
| PLSDANode | 3 | ✅ Perfect |
| KNNNode | 3 | ✅ Perfect |
| EFANode | 3 | ✅ Perfect |
| HCANode | 3 | ✅ Perfect |
| KMeansNode | 3 | ✅ Perfect |
| DBSCANNode | 2 | ✅ Perfect |
| SIMPLISMANode | 4 | ✅ Perfect |
| NMFNode | 4 | ✅ Perfect |
| FastICANode | 4 | ✅ Perfect |
| PlotNode | 1 | ✅ Perfect |
| ExportNode | 1 | ✅ Perfect |
| StatsSummaryNode | 1 | ✅ Perfect |
| ContourPlotNode | 1 | ✅ Perfect |
| DataTableNode | 1 | ✅ Perfect |
| OutlierDetectionNode | 4 | ✅ Perfect |
| CrossValidationNode | 4 | ✅ Perfect |

**Total Verified**: 22/25 nodes (88%)
**Bugs Found**: 3/25 nodes (12%)

---

## Conclusion

Out of **25 standardized nodes**, found **3 critical bugs** (12% failure rate):

1. 🔴🔴🔴 **MCRNode**: **BLOCK-RELEASE BUG** - Copy-paste error causes NameError crash (returns undefined variable `simplisma` instead of `mcr`)
2. 🔴 **SIMCANode**: Structural issue - single port pattern violation (missing "default" wrapper)
3. 🔴 **PeakFindingNode**: Structural issue - single port pattern violation (missing "default" wrapper)

**Severity Breakdown**:
- **MCRNode**: Cannot execute at all - crashes immediately with NameError
- **SIMCANode/PeakFindingNode**: Can execute but connections will fail

**Recommended Action**:
1. **URGENT**: Fix MCRNode immediately (5 min) - this is a block-release bug
2. Decide on SIMCANode/PeakFindingNode strategy: wrapper vs multi-output
3. Add unit tests to prevent future regressions:
   - Verify all nodes execute without NameError
   - Verify return dict keys match declared output_ports

---

**Report Generated**: 2026-01-24
**Reviewer**: Critical Code Review Agent
**Next Step**: Apply fixes before Phase 3 deployment
