# Chemometric Implementation Plan: Critical Bug Fixes
**Date**: 2026-01-24
**Discipline**: Spectroscopy & Chemometrics
**Context**: 2D Spectral Data (n_samples × n_wavenumbers)

---

## Executive Summary

Three critical bugs threaten the scientific integrity of spectral data workflows:

1. 🔴🔴🔴 **MCRNode**: Copy-paste error breaks mixture resolution (BLOCK-RELEASE)
2. 🔴 **SIMCANode**: Port architecture loses semantic meaning of classification outputs
3. 🔴 **PeakFindingNode**: Port structure incompatible with multi-modal peak analysis

**All fixes must preserve**:
- NDDataset coordinate systems (wavenumbers, time, sample labels)
- Spectral metadata (units, acquisition parameters)
- Chemometric model objects for downstream analysis
- Scientific traceability and reproducibility

---

## Chemometric Data Context

### Spectral Data Structure (2D)

```
Input: NDDataset (n_samples × n_wavenumbers)
├── Rows (dim 0): Time series, sample index, or replicates
├── Cols (dim 1): Spectral features (wavenumbers, wavelengths, m/z)
├── X-axis: Coordinate values (e.g., 4000-400 cm⁻¹)
└── Y-axis: Sample metadata (time points, temperature, labels)
```

**Example**: FTIR time-series data
- Shape: `(100 samples, 1868 wavenumbers)`
- X-coords: `[3999.5, 3997.6, ..., 650.1] cm⁻¹`
- Y-coords: `[0, 5, 10, ..., 495] seconds`
- Labels: `['baseline', 'reaction', 'reaction', ..., 'product']`

### Chemometric Decomposition Outputs

**MCR-ALS** decomposes mixture spectra:
```
D (n×m) = C (n×k) @ St (k×m) + E
where:
  n = samples (time points)
  m = features (wavenumbers)
  k = pure components

C:  Concentration profiles over time
St: Pure component spectra
E:  Residuals (unexplained variance)
```

**SIMCA** builds class-specific PCA models:
```
For each class j:
  Model_j = PCA(X_class_j)
  Distance_ij = ||x_i - x̂_i,j||  (Mahalanobis or Q-residuals)

Classification: Assign x_i to class with min(Distance_ij)
```

**Peak Finding** identifies spectral features:
```
Spectrum → [Peak Detection] → {
  positions: [1650, 1540, 1450] cm⁻¹
  heights: [0.85, 0.62, 0.41] A.U.
  widths: [15, 12, 18] cm⁻¹
  areas: [12.3, 7.8, 9.2] integrated absorbance
}
```

---

## Bug #1: MCRNode - Mixture Resolution Failure 🔴🔴🔴

### Scientific Impact

**Severity**: BLOCK-RELEASE - Node crashes on execution

**Use Case**: Process monitoring of chemical reactions
- Input: Time-series FTIR spectra (100 samples × 1868 wavenumbers)
- Goal: Resolve pure reactant/product spectra + concentration profiles
- Current state: **Crashes with NameError**

### Root Cause Analysis

```python
# Line 1403: Model correctly created and fitted
mcr = scp.MCRALS(max_iter=max_iter, tol=tol)
mcr.fit(input_data, C0)

# Lines 1407-1408: Results correctly extracted
C_data = np.array(mcr.C.data)   # Concentration profiles
St_data = np.array(mcr.St.data)  # Pure spectra

# Lines 1484-1488: ❌ COPY-PASTE ERROR FROM SIMPLISMA
if hasattr(simplisma, "purities"):  # ← 'simplisma' undefined!
    purities = np.array(simplisma.purities).tolist()

return {
    "model": simplisma,  # ← Should be 'mcr'
    "purity_values": purities,  # ← Concept doesn't apply to MCR
    # ...
}
```

**Scientific Error**:
- SIMPLISMA computes "purity spectra" (most dissimilar spectra from dataset)
- MCR-ALS computes "resolved spectra" (via alternating least squares optimization)
- These are **different chemometric concepts** - code was copied without adaptation

### Implementation Fix

**File**: `backend/app/services/dag/nodes/modeling.py`
**Lines**: 1484-1520 (MCRNode.execute return statement)

#### Step 1: Remove SIMPLISMA-specific code

```python
# DELETE lines 1484-1485 (purity check doesn't apply to MCR)
# if hasattr(simplisma, "purities"):
#     purities = np.array(simplisma.purities).tolist()
```

#### Step 2: Correct model variable name

```python
# Line 1488: Change variable reference
return {
    "model": mcr,  # ← CRITICAL: Change from 'simplisma' to 'mcr'
    "C": C_data.tolist(),
    "St": St_data.tolist(),
    # ... rest unchanged ...
}
```

#### Step 3: Remove purity_values from return dict

```python
# Line 1491: DELETE this line (not applicable to MCR-ALS)
# "purity_values": purities if purities is not None else [],
```

### Validation Tests

```python
# Test 1: Node executes without error
async def test_mcr_node_executes():
    # Synthetic mixture: 2 Gaussian peaks
    X = create_mixture_spectra(n_samples=50, n_components=2)
    node = MCRNode(parameters={"n_components": 2})
    result = await node.execute(X)

    assert "model" in result
    assert isinstance(result["model"], scp.MCRALS)  # Correct type
    assert result["model"] is not None  # Not undefined variable

# Test 2: C matrix has correct shape (samples × components)
async def test_mcr_concentration_shape():
    X = create_mixture_spectra(n_samples=50, n_components=2)
    node = MCRNode(parameters={"n_components": 2})
    result = await node.execute(X)

    C = np.array(result["C"])
    assert C.shape == (50, 2)  # n_samples × n_components

# Test 3: St matrix has correct shape (components × features)
async def test_mcr_spectra_shape():
    X = create_mixture_spectra(n_samples=50, n_components=2, n_features=100)
    node = MCRNode(parameters={"n_components": 2})
    result = await node.execute(X)

    St = np.array(result["St"])
    assert St.shape == (2, 100)  # n_components × n_wavenumbers

# Test 4: Model can be used for predictions
async def test_mcr_model_predict():
    X = create_mixture_spectra(n_samples=50, n_components=2)
    node = MCRNode(parameters={"n_components": 2})
    result = await node.execute(X)

    # Model should have transform method for new data
    model = result["model"]
    X_new = create_mixture_spectra(n_samples=10, n_components=2)
    C_new = model.transform(X_new)  # Should not crash
    assert C_new.shape == (10, 2)
```

### Downstream Impact

**Affected Workflows**:
1. MCR → Plot Concentration Profiles
2. MCR → Residual Analysis → Outlier Detection
3. MCR → Export Pure Spectra → Library Matching

**Fix ensures**:
- Model object available for residual computation
- Concentration profiles maintain time/sample coordinates
- Pure spectra retain wavenumber axis for plotting

---

## Bug #2: SIMCANode - Classification Output Architecture 🔴

### Scientific Impact

**Severity**: CRITICAL - Connections fail, semantic meaning lost

**Use Case**: Supervised classification of process states
- Input: Labeled spectra (3 classes: 'baseline', 'transition', 'steady-state')
- Goal: Build class-specific models + predict new spectra
- Current state: **Connections fail** - cannot access individual outputs

### Root Cause Analysis

```python
# Declared port (Line 1212-1220)
output_ports=[
    PortMetadata(
        name="default",  # ← Generic wrapper loses meaning
        port_type="model",
        label="SIMCA Model",
    ),
]

# Actual return (Lines 1454-1488)
return {
    "class_models": serializable_models,  # ❌ No "default" key
    "predictions": predictions.tolist(),
    "distances": {
        "Q_residuals": Q_distances,
        "T2_scores": T2_distances,
    },
    # ... 10+ additional fields ...
}
```

**Scientific Problem**:
- Users need to **selectively connect outputs** (e.g., distances → heatmap, predictions → confusion matrix)
- Single "default" port forces entire dict through one connection
- Downstream nodes can't declare port-level type requirements

### Implementation Fix (Recommended: Multi-Output Ports)

**File**: `backend/app/services/dag/nodes/classification.py`
**Lines**: 1212-1220 (output_ports), 1454-1488 (return statement)

#### Step 1: Declare semantic output ports

```python
output_ports=[
    # Primary outputs (REQUIRED)
    PortMetadata(
        name="class_models",
        port_type="model",
        required=True,
        label="Class Models",
        description="Dictionary of PCA models (one per class)"
    ),
    PortMetadata(
        name="predictions",
        port_type="array",
        required=True,
        label="Predictions",
        description="Predicted class labels for training data"
    ),

    # Distance metrics (REQUIRED for interpretation)
    PortMetadata(
        name="Q_residuals",
        port_type="array",
        required=True,
        label="Q Residuals",
        description="Distance to class model hyperplane (SPE)"
    ),
    PortMetadata(
        name="T2_scores",
        port_type="array",
        required=True,
        label="Hotelling T²",
        description="Distance within class model (score space)"
    ),

    # Optional diagnostic outputs
    PortMetadata(
        name="train_accuracy",
        port_type="number",
        required=False,
        label="Training Accuracy",
        description="Classification accuracy on training set"
    ),
]
```

#### Step 2: Restructure return dictionary

```python
# No changes needed to return dict structure!
# Keys already match new port names:
return {
    "class_models": serializable_models,  # ✅ Matches port
    "predictions": predictions.tolist(),   # ✅ Matches port
    "Q_residuals": Q_distances,            # ✅ Matches port
    "T2_scores": T2_distances,             # ✅ Matches port
    "train_accuracy": train_accuracy,      # ✅ Matches port

    # Additional metadata (not ports, but allowed)
    "classes": classes.tolist(),
    "n_classes": n_classes,
    "n_components": n_components,
    # ...
}
```

**Why this works**:
- Return dict can contain **more keys than declared ports** (metadata, internal fields)
- Executor only extracts **named port keys** for connections
- Additional fields available for introspection but not connectable

### Scientific Workflow Examples

#### Example 1: SIMCA → Confusion Matrix
```
[SIMCA Node] ──predictions──→ [Confusion Matrix]
             └──classes──────→ [class labels]
```

#### Example 2: SIMCA → Distance Heatmap
```
[SIMCA Node] ──Q_residuals──→ [Heatmap Plot]
             └──T2_scores────→ [Overlay scatter]
```

#### Example 3: SIMCA → Model Export
```
[SIMCA Node] ──class_models──→ [Model Serializer]
             └──train_accuracy→ [Report Generator]
```

### Validation Tests

```python
# Test 1: All required ports present in return dict
async def test_simca_output_ports():
    X, y = create_labeled_spectra(n_samples=150, n_classes=3)
    node = SIMCANode(parameters={"n_components": 3})
    result = await node.execute(X, y)

    # Check required ports
    required_ports = ["class_models", "predictions", "Q_residuals", "T2_scores"]
    for port in required_ports:
        assert port in result, f"Missing required port: {port}"

# Test 2: Port extraction works in executor
async def test_simca_port_extraction():
    workflow = {
        "nodes": [
            {"id": 1, "type": "data.source"},
            {"id": 2, "type": "classification.simca"},
            {"id": 3, "type": "output.plot"},
        ],
        "edges": [
            {"from": 1, "to": 2},
            {"from": 2, "to": 3, "fromPort": "predictions"},  # Extract specific port
        ]
    }

    result = await execute_workflow(workflow)
    assert result.success

    # Node 3 should receive predictions array, not entire dict
    node3_input = result.node_results[3]["input_data"]
    assert isinstance(node3_input, list)  # predictions is a list
    assert len(node3_input) == 150  # One prediction per sample

# Test 3: Distance metrics have correct shape
async def test_simca_distance_shapes():
    X, y = create_labeled_spectra(n_samples=150, n_classes=3)
    node = SIMCANode(parameters={"n_components": 3})
    result = await node.execute(X, y)

    Q = np.array(result["Q_residuals"])
    T2 = np.array(result["T2_scores"])

    # Distance to each class for each sample
    assert Q.shape == (150, 3)   # n_samples × n_classes
    assert T2.shape == (150, 3)
```

---

## Bug #3: PeakFindingNode - Multi-Modal Output Architecture 🔴

### Scientific Impact

**Severity**: CRITICAL - Type mismatch, connection failures

**Use Case**: Automated peak identification in IR spectra
- Input: FTIR spectrum (1868 wavenumbers)
- Goal: Identify characteristic peaks (C=O stretch, N-H bend, etc.)
- Current state: **Port type mismatch** - declares "dataset" but returns analysis dict

### Root Cause Analysis

```python
# Declared port (Lines 2272-2280)
output_ports=[
    PortMetadata(
        name="default",
        port_type="dataset",  # ❌ Semantic mismatch
        label="Peak Data",
    ),
]

# Actual return (Lines 2364-2402)
return {
    "peaks": {  # ❌ Not a dataset - it's an analysis dict
        "count": len(peak_indices),
        "positions": peak_positions,  # Wavenumbers
        "heights": peak_heights,       # Absorbance values
        "widths": peak_widths,         # cm⁻¹
        "prominences": prominences,    # Relative intensity
    },
    "spectrum": spectrum.tolist(),           # Original data
    "annotated_spectrum": annotated.tolist(), # With peak markers
    # ...
}
```

**Scientific Problems**:
1. **Type confusion**: `port_type="dataset"` expects NDDataset, but returns analysis dict
2. **No "default" wrapper**: Executor cannot extract port
3. **Lost modularity**: Can't separately connect peak table vs. annotated spectrum

### Implementation Fix (Recommended: Multi-Output Ports)

**File**: `backend/app/services/dag/nodes/modeling.py`
**Lines**: 2272-2280 (output_ports), 2364-2402 (return statement)

#### Step 1: Declare analysis-specific output ports

```python
output_ports=[
    # Peak analysis data (for tables, export)
    PortMetadata(
        name="peaks",
        port_type="array",  # ← NOT "dataset" - it's tabular peak data
        required=True,
        label="Peak List",
        description="Detected peaks with positions, heights, widths, areas"
    ),

    # Visualization outputs
    PortMetadata(
        name="annotated_spectrum",
        port_type="array",
        required=True,
        label="Annotated Spectrum",
        description="Spectrum with peak markers and labels"
    ),
    PortMetadata(
        name="spectrum",
        port_type="array",
        required=False,
        label="Original Spectrum",
        description="Input spectrum (for comparison)"
    ),

    # Metadata output (optional)
    PortMetadata(
        name="peak_assignments",
        port_type="array",
        required=False,
        label="Peak Assignments",
        description="Functional group assignments (if library matching enabled)"
    ),
]
```

#### Step 2: Return dict already matches!

```python
# No changes needed - return dict already has correct keys:
return {
    "peaks": {  # ✅ Matches port name
        "count": len(peak_indices),
        "positions": peak_positions,
        "heights": peak_heights,
        "widths": peak_widths,
        "prominences": prominences,
        "areas": peak_areas,
    },
    "spectrum": spectrum.tolist(),           # ✅ Matches port
    "annotated_spectrum": annotated.tolist(), # ✅ Matches port

    # Additional fields (not ports, but useful for frontend)
    "x_axis": wavenumbers,
    "peak_count": len(peak_indices),
    "detection_params": {
        "height_threshold": height,
        "prominence": prominence,
        "distance": distance,
    },
}
```

### Scientific Workflow Examples

#### Example 1: Peak Table Export
```
[Peak Finding] ──peaks──→ [Data Table] → [CSV Export]
```

Output table:
```
Position (cm⁻¹) | Height (A.U.) | Width (cm⁻¹) | Area | Assignment
1650.2          | 0.85          | 12.4          | 10.5 | C=O stretch (amide I)
1540.8          | 0.62          | 15.1          | 9.3  | N-H bend (amide II)
1450.3          | 0.41          | 10.8          | 4.4  | CH₂ bend
```

#### Example 2: Annotated Spectrum Plot
```
[Peak Finding] ──annotated_spectrum──→ [Line Plot]
                                        └─ Show peak markers
```

#### Example 3: Peak Tracking Over Time
```
[Time Series Data] → [Peak Finding] ──peaks──→ [Peak Tracker]
                                                └─ Track position shifts
                                                └─ Detect peak emergence/disappearance
```

### Validation Tests

```python
# Test 1: Peak detection finds expected peaks
async def test_peak_finding_accuracy():
    # Synthetic spectrum with 3 Gaussian peaks
    spectrum = create_gaussian_spectrum(
        positions=[1650, 1540, 1450],
        heights=[0.8, 0.6, 0.4],
        widths=[12, 15, 10]
    )

    node = PeakFindingNode(parameters={
        "height_threshold": 0.3,
        "prominence": 0.1
    })
    result = await node.execute(spectrum)

    peaks = result["peaks"]
    assert peaks["count"] == 3
    assert np.allclose(peaks["positions"], [1650, 1540, 1450], atol=2)

# Test 2: Port structure matches declaration
async def test_peak_finding_ports():
    spectrum = create_gaussian_spectrum(positions=[1650, 1540])
    node = PeakFindingNode(parameters={})
    result = await node.execute(spectrum)

    # Check required ports
    assert "peaks" in result
    assert "annotated_spectrum" in result
    assert "spectrum" in result

# Test 3: Peak data structure is correct
async def test_peak_data_structure():
    spectrum = create_gaussian_spectrum(positions=[1650])
    node = PeakFindingNode(parameters={})
    result = await node.execute(spectrum)

    peaks = result["peaks"]
    assert "count" in peaks
    assert "positions" in peaks
    assert "heights" in peaks
    assert "widths" in peaks
    assert "areas" in peaks

    # All arrays should have same length
    n_peaks = peaks["count"]
    assert len(peaks["positions"]) == n_peaks
    assert len(peaks["heights"]) == n_peaks
    assert len(peaks["widths"]) == n_peaks

# Test 4: Annotated spectrum preserves coordinates
async def test_annotated_spectrum_coordinates():
    spectrum = create_gaussian_spectrum(positions=[1650])
    node = PeakFindingNode(parameters={})
    result = await node.execute(spectrum)

    original = np.array(result["spectrum"])
    annotated = np.array(result["annotated_spectrum"])

    # Same length (same wavenumber axis)
    assert len(original) == len(annotated)

    # X-axis coordinates preserved
    assert "x_axis" in result
    assert len(result["x_axis"]) == len(annotated)
```

---

## Implementation Sequence

### Phase 1: Emergency Fix (BLOCK-RELEASE) ⏰ 5 minutes

**Priority**: IMMEDIATE - MCRNode crashes on execution

**File**: `modeling.py` lines 1484-1520

**Changes**:
1. Delete lines 1484-1485 (SIMPLISMA purity check)
2. Line 1488: Change `"model": simplisma,` → `"model": mcr,`
3. Line 1491: Delete `"purity_values": purities if purities is not None else [],`

**Validation**:
```bash
# Run MCR integration test
pytest tests/nodes/test_mcr_node.py::test_mcr_executes -v
```

**Deploy**: Push to staging immediately

---

### Phase 2: SIMCA Multi-Output Refactor ⏰ 30 minutes

**File**: `classification.py` lines 1212-1220, 1454-1488

**Changes**:
1. Replace single "default" port with 5 semantic ports (see Bug #2 fix above)
2. Return dict: **No changes needed** (already has correct keys)
3. Update frontend port metadata cache

**Validation**:
```bash
# Test port extraction
pytest tests/nodes/test_simca_node.py::test_output_ports -v

# Test workflow connections
pytest tests/workflows/test_simca_connections.py -v
```

**Frontend update**: Clear node metadata cache
```javascript
// workflow.ts
nodeRegistry.refreshMetadata('classification.simca')
```

---

### Phase 3: PeakFinding Multi-Output Refactor ⏰ 30 minutes

**File**: `modeling.py` lines 2272-2280, 2364-2402

**Changes**:
1. Replace single "default" port with 4 semantic ports (see Bug #3 fix above)
2. Return dict: **No changes needed** (already has correct keys)
3. Update frontend port metadata cache

**Validation**:
```bash
# Test peak detection accuracy
pytest tests/nodes/test_peak_finding.py::test_peak_accuracy -v

# Test port structure
pytest tests/nodes/test_peak_finding.py::test_output_ports -v
```

---

### Phase 4: Regression Testing ⏰ 2 hours

**Scope**: All 25 standardized nodes

**Test Suite**:
```python
# tests/nodes/test_output_port_compliance.py

import pytest
from app.services.dag.node_registry import get_all_nodes

@pytest.mark.parametrize("node_class", get_all_nodes())
async def test_node_output_ports_match_return(node_class):
    """Verify all declared output ports are present in return dict."""

    # Get test data for this node type
    test_data = get_test_data_for_node(node_class)

    # Execute node
    node = node_class(parameters=get_default_params(node_class))
    result = await node.execute(**test_data)

    # Get required port names
    required_ports = [
        p.name for p in node.metadata.output_ports
        if p.required
    ]

    # Verify all required ports present
    for port_name in required_ports:
        assert port_name in result, (
            f"{node_class.__name__}: Missing required port '{port_name}'\n"
            f"Declared: {required_ports}\n"
            f"Returned: {list(result.keys())}"
        )

@pytest.mark.parametrize("node_class", get_all_nodes())
async def test_node_executes_without_undefined_vars(node_class):
    """Verify no NameError from undefined variables."""

    test_data = get_test_data_for_node(node_class)
    node = node_class(parameters=get_default_params(node_class))

    # Should not raise NameError
    result = await node.execute(**test_data)
    assert result is not None
```

**Run tests**:
```bash
pytest tests/nodes/test_output_port_compliance.py -v --tb=short
```

---

## Scientific Validation Checklist

### ✅ Data Integrity Preserved

- [ ] MCR C matrix preserves sample/time coordinates
- [ ] MCR St matrix preserves wavenumber coordinates
- [ ] SIMCA class models retain original class labels
- [ ] Peak finding preserves spectrum x-axis (wavenumbers)

### ✅ Chemometric Model Objects Accessible

- [ ] MCR model object can be used for `transform()` on new data
- [ ] SIMCA class models can compute distances for new samples
- [ ] Peak positions can be used for functional group assignment

### ✅ Downstream Workflow Compatibility

- [ ] MCR → Residual Analysis → Outlier Detection (end-to-end)
- [ ] SIMCA → Confusion Matrix → Model Report (end-to-end)
- [ ] Peak Finding → Peak Table → CSV Export (end-to-end)

### ✅ Type System Consistency

- [ ] `port_type="dataset"` only for NDDataset objects
- [ ] `port_type="array"` for numerical arrays (C, St, predictions)
- [ ] `port_type="model"` for fitted model objects

---

## Risk Mitigation

### Risk 1: Breaking Existing Workflows

**Mitigation**: Multi-output nodes are **backward compatible**
- Executor falls back to entire dict if no `fromPort` specified
- Existing workflows without explicit port selection continue working
- Users can opt-in to port-level connections incrementally

### Risk 2: Data Coordinate Loss

**Mitigation**: All fixes preserve NDDataset metadata
- MCR fix doesn't touch coordinate extraction logic
- SIMCA refactor only changes port declarations
- Peak finding only changes port types, not data structure

### Risk 3: Scientific Validity

**Mitigation**: Chemometrician review before deployment
- MCR: Verify C and St matrices are correct (use test mixture)
- SIMCA: Verify Q-residuals and T² calculations (compare to PyCaret/sklearn)
- Peak Finding: Verify against manual peak picking on standard spectra

---

## Deployment Strategy

### Staging Deployment (Week 1)

**Day 1**:
- Deploy MCR emergency fix
- Run integration tests with real FTIR data
- Verify no NameError crashes

**Day 2-3**:
- Deploy SIMCA + PeakFinding multi-output refactors
- Test all connection patterns (port selection UI)
- Verify frontend metadata cache updates

**Day 4-5**:
- Full regression testing (all 25 nodes)
- User acceptance testing with chemometricians
- Document new port architecture in user guide

### Production Deployment (Week 2)

**Pre-deployment**:
- Database backup (workflows, user data)
- Announce breaking changes (if any) to users
- Prepare rollback plan

**Deployment**:
- Blue-green deployment (zero downtime)
- Monitor error logs for NameError, KeyError
- Check Sentry for connection failures

**Post-deployment**:
- Verify key workflows: MCR, SIMCA, Peak Finding
- User feedback collection
- Performance monitoring (no regressions)

---

## Success Criteria

### Immediate (Phase 1)
- ✅ MCRNode executes without NameError
- ✅ Returns correct `mcr` model object
- ✅ No "purity_values" in MCR output

### Short-term (Phases 2-3)
- ✅ SIMCANode supports port-level connections
- ✅ PeakFindingNode exposes semantic outputs
- ✅ All 25 nodes pass compliance tests

### Long-term (Phase 4)
- ✅ Zero NameError crashes in production
- ✅ Zero KeyError from missing ports
- ✅ Users successfully build complex multi-output workflows
- ✅ Chemometric integrity verified on real datasets

---

**Next Actions**:
1. Review this plan with lead chemometrician
2. Approve fix strategy (multi-output vs. wrapper)
3. Execute Phase 1 (MCR emergency fix) immediately
4. Schedule Phases 2-4 for next sprint

**Document Owner**: AI Reviewer
**Approvers**: [Lead Chemometrician], [Software Architect], [QA Lead]
**Target Completion**: 2026-01-31
