# Node Standardization Effort Estimate
**Date**: 2026-01-24
**Purpose**: Convert all 53 nodes to unified modern port-based pattern
**Target Standard**: DataSourceNode pattern (explicit input_ports/output_ports)

---

## Recommended Standard

### Pattern Definition

**Modern Port-Based Pattern** (Based on DataSourceNode):

```python
@register_node
class ExampleNode(Node):
    metadata = NodeMetadata(
        node_type="category.example",
        category="modeling",
        label="Example Node",

        # INPUT PORTS (if multi-input or named inputs)
        input_ports=[
            PortMetadata(
                name="X",
                port_type="dataset",      # Semantic type
                required=True,
                label="Input Dataset",
                description="Primary input data",
            ),
            PortMetadata(
                name="y",
                port_type="target",
                required=False,
                label="Target Values",
                description="Optional target values",
            ),
        ],

        # OUTPUT PORTS (if multi-output)
        output_type="dict",  # Must be "dict" for multi-output
        output_ports=[
            PortMetadata(
                name="model",
                port_type="model",
                required=True,
                label="Trained Model",
                description="The fitted model object",
            ),
            PortMetadata(
                name="predictions",
                port_type="array",
                required=True,
                label="Predictions",
                description="Model predictions on training data",
            ),
        ],

        # OR for single-input/single-output:
        input_types=["NDDataset"],     # Legacy pattern OK for simple cases
        output_type="NDDataset",       # Single value
        # output_ports=None             # No ports needed
    )

    async def execute(self, X: NDDataset = None, y: Any = None, **kwargs) -> dict:
        # ... implementation ...

        # RETURN: Dict with keys matching output_port names
        return {
            "model": fitted_model,
            "predictions": predictions_array,
        }
```

**Key Rules**:
1. **Multi-input nodes**: Use `input_ports` (e.g., X + y)
2. **Multi-output nodes**: Use `output_ports` + return dict with matching keys
3. **Single-input/single-output**: Use `input_types`/`output_type` (legacy pattern OK)
4. **Port types**: Use semantic names ("dataset", "target", "model", "array") not class names
5. **Dict keys must match port names** exactly

---

## Effort Breakdown by Category

### Category 1: Already Compliant ✅ (3 nodes)
**No changes needed**

| Node | Status |
|------|--------|
| DataSourceNode | ✅ Gold standard |
| PLSDAPredictNode | ✅ Already modern |
| KNNPredictNode | ✅ Already modern |

**Effort**: 0 hours

---

### Category 2: Simple Single-Value Nodes ✅ (26 nodes)
**Keep legacy pattern - no changes needed**

These nodes have single input → single output, no multi-port benefits:

**Preprocessing (18 nodes)**:
- BaselineALSNode, BaselineRubberbandNode
- SmoothSavitzkyGolayNode
- NormalizeSNVNode, NormalizeScaleNode, NormalizeMSCNode
- DerivativeFirstNode, DerivativeSecondNode, SGDerivativeNode
- CosmicRayRemovalNode, ClipRangeNode, ClipFloorNode
- WavenumberAlignNode, ScaleMaxNode, CenterMeanNode
- ParetoScalingNode, AutoscalingNode, EMSCNode

**Synthesis/Blend (3 nodes)**:
- BlendNode, SpeciesSelectorNode, MergeSpectraNode

**Time Series (2 nodes)**:
- MovingWindowNode, TrendRemovalNode

**Prediction/Transform (2 nodes)**:
- PLSPredictNode, PCATransformNode

**Specialized (1 node)**:
- PeakFindingNode

**Effort**: 0 hours (intentionally keep simple)

**Rationale**: These nodes are pure transformations. Adding ports adds complexity without benefit.

---

### Category 3: Add Input Ports Only 🟡 (1 node)
**Moderate effort - update input side only**

| Node | Current | Target | Changes |
|------|---------|--------|---------|
| **OSCNode** | Has input_ports ✅ | Keep as-is | None (already modern) |

**Effort**: 0 hours (already done)

---

### Category 4: Add Output Ports - Low Complexity 🟡 (6 nodes)
**Update output_ports metadata + standardize return keys**

**Output/Display Nodes** (5 nodes):
- PlotNode
- ExportNode
- StatsSummaryNode
- ContourPlotNode
- DataTableNode

**Specialized** (1 node):
- NISTLibraryNode

**Current State**: Return dicts, but only single logical output (visualization/export data)

**Target State**: Formalize as single `output_port` with clear type

```python
# Example: PlotNode
output_ports=[
    PortMetadata(
        name="default",
        port_type="plot",
        label="Plot Data",
        description="Plotly-formatted visualization data",
    ),
]

# Return unchanged (already returns dict)
return plot_data
```

**Changes per node**:
1. Add `output_ports` metadata (1 port each)
2. Verify return dict has consistent structure
3. Update docstring
4. Test

**Effort per node**: 20 minutes
**Total**: 6 nodes × 20 min = **2 hours**

---

### Category 5: Add Multi-Output Ports - Medium Complexity 🟠 (10 nodes)
**Declare multiple output_ports + restructure return dict**

**Modeling Nodes** (10 nodes):
- PCANode → 4 ports (model, scores, loadings, explained_variance)
- PLSNode → 5 ports (model, X_scores, Y_scores, X_loadings, Y_loadings)
- PCRNode → 4 ports (model, scores, loadings, predictions)
- SVRNode → 3 ports (model, predictions, residuals)
- LinearRegressionNode → 3 ports (model, predictions, coefficients)
- MCRNode → 4 ports (model, concentrations, spectra, residuals)
- EFANode → 3 ports (model, forward_spectra, backward_spectra)
- NMFNode → 4 ports (model, W, H, residuals)
- FastICANode → 3 ports (model, S, A)
- SIMPLISMANode → 2 ports (model, pure_variables)

**Changes per node**:
1. Add `output_ports` metadata (3-5 ports)
2. Update execute() to return dict with standardized keys
3. Move visualization data to metadata or separate "plots" port
4. Update docstring
5. Test with executor
6. Update frontend type mapping (if new types introduced)

**Example - PCANode**:

**Before**:
```python
output_type="PCAModel"
output_ports=[PortMetadata(name="default", port_type="model")]

return {
    "model": pca_result,
    "scores": X_scores,
    "loadings": pca.get_loadings(),
    "explained_variance": explained_var,
    "data": {...},  # Visualization
    "metadata": {...},
}
```

**After**:
```python
output_type="dict"
output_ports=[
    PortMetadata(name="model", port_type="model", label="PCA Model"),
    PortMetadata(name="scores", port_type="array", label="Scores Matrix"),
    PortMetadata(name="loadings", port_type="array", label="Loadings Matrix"),
    PortMetadata(name="explained_variance", port_type="array", label="Explained Variance"),
]

return {
    "model": pca_result,              # Matches port name
    "scores": X_scores,                # Matches port name
    "loadings": pca.get_loadings(),    # Matches port name
    "explained_variance": explained_var,  # Matches port name
    # "data" and "metadata" embedded in model object or dropped
}
```

**Effort per node**: 45 minutes
- Metadata declaration: 15 min
- Refactor return structure: 20 min
- Testing: 10 min

**Total**: 10 nodes × 45 min = **7.5 hours**

---

### Category 6: Add Multi-Input + Multi-Output Ports - High Complexity 🔴 (3 nodes)
**Require both input_ports and output_ports + significant refactoring**

**Classification Training Nodes** (3 nodes):
- PLSDANode → 2 inputs (X, y), 3 outputs (model, predictions, probabilities)
- KNNNode → 2 inputs (X, y), 3 outputs (model, predictions, probabilities)
- SIMCANode → 2 inputs (X, y), 3 outputs (class_models, predictions, distances)

**Current State**: Already have `input_ports` ✅, but only 1 output_port

**Changes per node**:
1. Add multiple `output_ports` (3 ports)
2. Decide what to do with confusion matrices (embed in model? separate port?)
3. Restructure return dict
4. Update visualization data handling
5. Update docstring
6. Comprehensive testing (train + CV flows)

**Example - PLSDANode**:

**Before**:
```python
input_ports=[
    PortMetadata(name="X", ...),
    PortMetadata(name="y", ...),
]
output_ports=[PortMetadata(name="default", port_type="model")]

return {
    "model": pls_model,
    "predictions_train": ...,
    "predictions_cv": ...,
    "probabilities_train": ...,
    "probabilities_cv": ...,
    "confusion_matrix_train": ...,
    "confusion_matrix_cv": ...,
    "data": {...},
}
```

**After**:
```python
input_ports=[
    PortMetadata(name="X", ...),
    PortMetadata(name="y", ...),
]
output_ports=[
    PortMetadata(name="model", port_type="model", label="Trained Classifier"),
    PortMetadata(name="predictions", port_type="array", label="CV Predictions"),
    PortMetadata(name="probabilities", port_type="array", label="Class Probabilities"),
]

return {
    "model": pls_model,           # Contains embedded cm_train, cm_cv, metrics
    "predictions": y_pred_cv,     # Primary predictions
    "probabilities": y_proba_cv,  # Primary probabilities
}
```

**Decision needed**: Where to put confusion matrices?
- Option A: Embed in model object (recommended)
- Option B: Separate ports (adds 2 more ports)

**Effort per node**: 60 minutes
- Metadata declaration: 15 min
- Refactor return structure: 25 min
- Testing (train + CV + plots): 20 min

**Total**: 3 nodes × 60 min = **3 hours**

---

### Category 7: Special Cases - High Complexity 🔴 (4 nodes)
**Unique requirements**

**TrainTestSplitNode** (1 node):
- **Target**: 4 output_ports (X_train, X_test, y_train, y_test)
- **Effort**: 45 minutes
  - Metadata: 15 min
  - Return restructure: 15 min (minimal - already returns correct dict)
  - Testing: 15 min

**Clustering Nodes** (3 nodes):
- HCANode → 3 ports (model, labels, linkage_matrix)
- KMeansNode → 4 ports (model, labels, centers, inertia)
- DBSCANNode → 3 ports (model, labels, core_samples)

**Effort per clustering node**: 45 minutes
**Total**: 3 nodes × 45 min = **2.25 hours**

**TrainTestSplitNode**: 0.75 hours

**Category Total**: **3 hours**

---

### Category 8: Diagnostic Nodes - Input Modernization 🟡 (2 nodes)

**OutlierDetectionNode**:
- **Current**: Legacy `input_types`
- **Target**: Modern `input_ports`
- **Effort**: 30 minutes
  - Add input_ports metadata: 10 min
  - Update execute() signature: 10 min
  - Testing: 10 min

**CrossValidationNode**:
- **Current**: Has `input_ports` ✅, missing `output_ports`
- **Target**: Add `output_ports`
- **Effort**: 20 minutes
  - Add output_ports metadata: 10 min
  - Verify return structure: 5 min
  - Testing: 5 min

**Total**: **0.83 hours**

---

## Total Effort Summary

| Category | Nodes | Effort | Notes |
|----------|-------|--------|-------|
| 1. Already Compliant | 3 | 0 hrs | DataSourceNode, prediction nodes |
| 2. Keep Simple (Legacy OK) | 26 | 0 hrs | Single-value transforms |
| 3. Input Ports Only | 1 | 0 hrs | OSCNode already modern |
| 4. Output Ports - Low | 6 | 2 hrs | Display/output nodes |
| 5. Multi-Output - Medium | 10 | 7.5 hrs | Modeling nodes |
| 6. Multi-I/O - High | 3 | 3 hrs | Classification training |
| 7. Special Cases | 4 | 3 hrs | TrainTestSplit + clustering |
| 8. Diagnostic Nodes | 2 | 0.83 hrs | Input/output modernization |
| **TOTAL** | **55*** | **16.33 hrs** | ~2 working days |

*Note: 53 unique nodes + 2 counting adjustments

---

## Additional Effort (One-Time)

### Frontend Updates

**Required Changes**:
1. **Port Selection UI** (when connecting multi-output nodes)
   - Add dropdown/menu to select which output port to connect
   - Display port labels and descriptions
   - **Effort**: 3-4 hours

2. **Type Mapping Extension**
   - Update `portTypeToClassNames` in workflow.ts
   - Add new semantic types if introduced
   - **Effort**: 1 hour

3. **Edge Rendering**
   - Optional: Color-code edges by port type
   - Optional: Show port labels on hover
   - **Effort**: 2 hours (optional)

**Frontend Total**: **4-7 hours** (required: 4, optional: +3)

---

### Documentation

**Required**:
1. **Node Development Guide**
   - Document standard patterns
   - Provide templates for new nodes
   - **Effort**: 2 hours

2. **Migration Guide**
   - Document what changed per node
   - Provide upgrade path for workflows
   - **Effort**: 2 hours

3. **Type System Documentation**
   - Define all semantic port types
   - Document type compatibility rules
   - **Effort**: 1 hour

**Documentation Total**: **5 hours**

---

### Testing

**Required**:
1. **Unit Tests per Node**
   - Verify execute() returns match port definitions
   - Test executor extraction
   - **Effort**: 10 min per changed node × 24 nodes = 4 hours

2. **Integration Tests**
   - Test multi-output connections
   - Test legacy → modern compatibility
   - Test end-to-end workflows
   - **Effort**: 3 hours

3. **Frontend Tests**
   - Test port selection UI
   - Test edge validation
   - **Effort**: 2 hours

**Testing Total**: **9 hours**

---

## Grand Total Effort Estimate

| Component | Effort | Percentage |
|-----------|--------|------------|
| Backend Node Updates | 16.33 hrs | 48% |
| Frontend Updates | 4-7 hrs | 12-20% |
| Documentation | 5 hrs | 15% |
| Testing | 9 hrs | 26% |
| **TOTAL** | **34-37 hours** | 100% |

**Realistic Estimate with Buffer (+20%)**: **41-44 hours** (~1 week for 1 developer)

---

## Phased Implementation Plan

### Phase 1: Foundation (1 day, 8 hours)
**Goal**: Establish standards and tooling

1. ✅ Document standard pattern (already done - this document)
2. Create node template/generator script (2 hrs)
3. Update frontend port selection UI (3 hrs)
4. Write integration test framework (2 hrs)
5. Update type mapping (1 hr)

**Deliverable**: Infrastructure ready for node updates

---

### Phase 2: High-Value Nodes (1.5 days, 12 hours)
**Goal**: Update nodes with clearest multi-output use cases

**Nodes** (Priority order):
1. **TrainTestSplitNode** (0.75 hr) - Enables train/test routing
2. **PCANode** (0.75 hr) - Most commonly used decomposition
3. **PLSNode** (0.75 hr) - Critical for regression workflows
4. **PLSDANode** (1 hr) - Classification workflows
5. **KNNNode** (1 hr) - Alternative classifier
6. **MCRNode** (0.75 hr) - Concentration/spectra separation

**Testing**: 3 hours
**Documentation**: 2 hours

**Deliverable**: Core modeling nodes standardized

---

### Phase 3: Remaining Modeling Nodes (1 day, 8 hours)
**Goal**: Complete all modeling nodes

**Nodes**:
1. PCRNode, SVRNode, LinearRegressionNode (regression)
2. HCANode, KMeansNode, DBSCANNode (clustering)
3. EFANode, NMFNode, FastICANode, SIMPLISMANode (decomposition)
4. SIMCANode (classification)

**Testing**: 3 hours
**Documentation**: 1 hour

**Deliverable**: All modeling nodes standardized

---

### Phase 4: Remaining Nodes (0.5 days, 4 hours)
**Goal**: Finish diagnostic and output nodes

**Nodes**:
1. OutlierDetectionNode, CrossValidationNode (diagnostic)
2. PlotNode, ExportNode, StatsSummaryNode, ContourPlotNode, DataTableNode (output)
3. NISTLibraryNode (data)

**Testing**: 2 hours
**Documentation**: 1 hour

**Deliverable**: 100% standardization complete

---

### Phase 5: Polish & Documentation (0.5 days, 4 hours)
**Goal**: Finalize package release

1. Comprehensive testing (2 hrs)
2. Update API documentation (1 hr)
3. Create migration guide for existing workflows (1 hr)

**Deliverable**: Production-ready standardized node system

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Breaking existing workflows | Medium | High | Executor already handles both patterns; test compatibility |
| Frontend UI complexity | Medium | Medium | Start with simple dropdown; iterate based on feedback |
| Unexpected edge cases | Low | Medium | Comprehensive testing in Phase 1 |
| Performance regression | Very Low | Low | Return structure changes are minimal |
| Developer confusion | Low | Medium | Clear documentation and templates |

---

## Recommended Decision

### Option A: Full Standardization (Recommended)
**Timeline**: 1 week
**Effort**: 41-44 hours
**Benefits**:
- Clean, consistent API for package release
- Self-documenting node contracts
- Better type safety and composability
- Future-proof architecture

**When**: Before first public release

---

### Option B: Hybrid (Keep Simple Nodes Simple)
**Timeline**: 3-4 days
**Effort**: ~25 hours
**Approach**:
- Update only multi-output nodes (Categories 4-8)
- Keep single-value nodes with legacy pattern
- Document both patterns as official

**Benefits**:
- Faster implementation
- No unnecessary complexity for simple nodes
- Still achieves main goal (multi-output standardization)

**When**: If time-constrained

---

### Option C: Minimal (Critical Nodes Only)
**Timeline**: 1-2 days
**Effort**: ~12 hours
**Approach**:
- Update only Phase 2 nodes (TrainTestSplit + core modeling)
- Leave rest as-is

**Benefits**:
- Minimal disruption
- Fastest time to release

**Drawbacks**:
- Inconsistent API
- Technical debt remains

**When**: Only if extremely time-constrained

---

## Recommendation for New Package

**Choose Option A (Full Standardization)**

**Rationale**:
1. You're creating a NEW package - this is the time to set standards
2. 1 week of effort now saves years of maintenance
3. Comparable to Orange Data Mining's consistency
4. Professional, production-ready API
5. Easier to document and teach to users

**ROI**: 1 week investment → clean architecture for package lifetime

---

## Next Steps

1. **Approve standardization approach** (Option A, B, or C)
2. **Prioritize phase order** (recommend sequential 1→5)
3. **Assign resources** (1 developer for 1 week, or 2 developers for 3 days)
4. **Start with Phase 1** (foundation + tooling)
5. **Review after Phase 2** (ensure approach works before continuing)

---

**Document Prepared**: 2026-01-24
**Estimate Confidence**: 85% (±10 hours contingency recommended)
**Recommended Start**: Before first package release
**Estimated Completion**: 5-7 working days
