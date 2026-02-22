# Node Updates Required for New Axis Types

## Summary

For new axis types (TimeAxis, MZAxis, PotentialAxis) to work in workflows, several nodes need updates to use **generic accessors** instead of type-specific ones.

## ✅ Already Fixed

### 1. `io_contracts.py` - `build_dataset_like()` ✅

**Status**: FIXED

**Change**: Updated to use `get_feature_axis()` and `get_observation_axis()` to preserve ANY axis type through transformations.

**Before**:
```python
spectral_axis = src.spectral_axis.copy()  # Loses TimeAxis, MZAxis, etc.
sample_axis = src.sample_axis.copy()      # Loses TimeAxis in dimension 0
```

**After**:
```python
feature_axis = src.get_feature_axis()     # Preserves ANY FeatureAxis
obs_axis = src.get_observation_axis()     # Preserves ANY axis type
```

**Impact**: This is the **most critical fix** - without it, new axis types would be lost after any transformation.

---

## ⚠️ Nodes That Need Updates

### Priority 1: Critical for Time-Resolved Data

#### 1. `modeling.py` - MCRNode (MCR-ALS) ⚠️

**Status**: NEEDS UPDATE

**Location**: `src/spectra_sherpa/app/services/dag/nodes/modeling.py` lines ~1637-1638

**Issue**:
```python
_x_coord = input_ds.spectral_axis  # ✓ Works for spectroscopy
_y_coord = input_ds.sample_axis    # ✗ Returns None for time-resolved data!
```

**Fix**:
```python
_x_coord = input_ds.get_feature_axis()      # Works for any FeatureAxis
_y_coord = input_ds.get_observation_axis()  # Works for TimeAxis, SampleAxis, etc.
```

**Impact**: **HIGH** - MCR-ALS is specifically designed for time-resolved spectroscopy, so this breaks its primary use case.

**Test Case**:
```python
# Time-resolved spectroscopy (reaction monitoring)
time_axis = TimeAxis(values=np.linspace(0, 30, 50), units="min")
spec_axis = SpectralAxis(values=np.linspace(400, 4000, 200), units="cm-1")
ds = SherpaDataset(X, feature_axis=spec_axis)
ds._axes[ds._SAMPLE_DIM] = time_axis.copy()

# Run MCR-ALS - should preserve time axis in outputs
result = mcr_node.execute(input_data=ds)
```

---

#### 2. `meta_helpers.py` - Metadata Extraction Functions ⚠️

**Status**: NEEDS UPDATE (if used for axis info)

**Files to Check**:
- `get_spectral_info()` - May assume spectral_axis
- Other metadata extractors

**Fix**: Use `get_feature_axis()` for generic feature axis info.

---

### Priority 2: Important for Correctness

#### 3. `output.py` - Visualization and Export Nodes ⚠️

**Status**: NEEDS REVIEW

**Potential Issues**:
- Plots may assume `spectral_axis` for x-axis labels
- Exports may not handle TimeAxis, MZAxis labels

**Fix**: Check axis type and use appropriate labels:
```python
feature_ax = dataset.get_feature_axis()
if feature_ax:
    if isinstance(feature_ax, SpectralAxis):
        x_label = "Wavenumber (cm⁻¹)"
    elif isinstance(feature_ax, TimeAxis):
        x_label = f"Time ({feature_ax.units})"
    elif isinstance(feature_ax, MZAxis):
        x_label = "m/z"
    # etc.
```

---

#### 4. `preprocessing.py` - Preprocessing Nodes ⚠️

**Status**: SHOULD WORK (via build_dataset_like)

**Reason**: Most preprocessing nodes use `build_dataset_like()` which now preserves axes correctly.

**Verification Needed**: Test that preprocessing works with:
- TimeAxis data (chromatography smoothing)
- MZAxis data (mass spec baseline correction)

---

#### 5. `classification.py`, `custom.py`, `blend.py` ⚠️

**Status**: NEEDS REVIEW

**Action**: Search for uses of `.spectral_axis` or `.sample_axis` and evaluate if they should be generic.

---

### Priority 3: Data Loading Nodes

#### 6. `data.py` - Data Loading Nodes 📝

**Status**: NEEDS NEW NODES

**Current State**: Existing loaders create `SpectralAxis` by default.

**Needed**:
- Chromatography loader → Creates `TimeAxis`
- Mass spec loader → Creates `MZAxis`
- Electrochemistry loader → Creates `PotentialAxis`

**Example New Node**:
```python
class LoadChromatogramNode(Node):
    """Load HPLC/GC chromatogram data."""

    async def execute(self, file_path: str, **kwargs):
        # Load data
        data, retention_times, wavelengths = load_hplc_file(file_path)

        # Create axes
        time_axis = TimeAxis(
            values=retention_times,
            units="min",
            title="Retention Time"
        )
        spec_axis = SpectralAxis(
            values=wavelengths,
            units="nm",
            title="Wavelength"
        )

        # Create dataset
        ds = SherpaDataset(
            X=data,
            feature_axis=spec_axis
        )
        # Set time axis in dimension 0
        time_copy = time_axis.copy()
        time_copy.bind_expected_length(data.shape[0])
        ds._axes[ds._SAMPLE_DIM] = time_copy

        return ds
```

---

## Files Summary

| File | Priority | Status | Lines to Update |
|------|----------|--------|-----------------|
| `io_contracts.py` | P0 | ✅ FIXED | ~254-255 |
| `modeling.py` (MCRNode) | P1 | ⚠️ NEEDS UPDATE | ~1637-1638 |
| `meta_helpers.py` | P2 | ⚠️ NEEDS REVIEW | TBD |
| `output.py` | P2 | ⚠️ NEEDS REVIEW | TBD |
| `preprocessing.py` | P2 | ✓ SHOULD WORK | 0 (uses build_dataset_like) |
| `classification.py` | P3 | ⚠️ NEEDS REVIEW | TBD |
| `custom.py` | P3 | ⚠️ NEEDS REVIEW | TBD |
| `blend.py` | P3 | ⚠️ NEEDS REVIEW | TBD |
| `data.py` | P3 | 📝 NEW NODES | New code needed |

---

## Testing Strategy

### Test 1: Verify build_dataset_like Preserves Axes ✅

```python
def test_build_dataset_like_preserves_time_axis():
    """Test that build_dataset_like preserves TimeAxis."""
    # Create source with TimeAxis
    time_axis = TimeAxis(values=np.linspace(0, 30, 50), units="min")
    spec_axis = SpectralAxis(values=np.linspace(400, 4000, 200), units="cm-1")

    source = SherpaDataset(X=np.random.rand(50, 200), feature_axis=spec_axis)
    source._axes[source._SAMPLE_DIM] = time_axis.copy()

    # Transform data (e.g., normalize)
    transformed_data = source.X * 2.0

    # Build new dataset
    result = build_dataset_like(transformed_data, source)

    # Verify axes preserved
    assert result.get_observation_axis() is not None
    assert isinstance(result.get_observation_axis(), TimeAxis)
    assert result.get_feature_axis() is not None
    assert isinstance(result.get_feature_axis(), SpectralAxis)
```

### Test 2: MCR-ALS with Time-Resolved Data ⚠️

```python
def test_mcr_als_with_time_resolved():
    """Test MCR-ALS node with time-resolved spectroscopy data."""
    # Create time-resolved data
    n_time = 50
    n_wavelengths = 200
    X = np.random.rand(n_time, n_wavelengths)

    time_axis = TimeAxis(values=np.linspace(0, 30, n_time), units="min")
    spec_axis = SpectralAxis(values=np.linspace(400, 4000, n_wavelengths), units="cm-1")

    ds = SherpaDataset(X, feature_axis=spec_axis)
    ds._axes[ds._SAMPLE_DIM] = time_axis.copy()

    # Run MCR-ALS
    mcr_node = MCRNode(parameters={"n_components": 3})
    result = await mcr_node.execute(input_data=ds)

    # Verify outputs preserve axes
    C = result["C"]  # Concentration profiles
    St = result["St"]  # Pure spectra

    # C should have time axis in y-coord
    assert C.get_observation_axis() is not None
    # St should have spectral axis in x-coord
    assert St.get_feature_axis() is not None
```

### Test 3: Chromatography Workflow 📝

```python
def test_chromatography_workflow():
    """Test full chromatography workflow (load → preprocess → analyze)."""
    # Load HPLC data
    hplc_ds = load_hplc_data("test.csv")  # Creates TimeAxis + SpectralAxis

    # Preprocess (baseline correction)
    baseline_node = BaselineNode(parameters={"method": "als"})
    corrected = await baseline_node.execute(input_data=hplc_ds)

    # Verify axes preserved through preprocessing
    assert isinstance(corrected.get_observation_axis(), TimeAxis)
    assert isinstance(corrected.get_feature_axis(), SpectralAxis)

    # Peak detection
    peaks_node = FindPeaksNode()
    peaks = await peaks_node.execute(input_data=corrected)

    # Peaks should have time positions
    assert "retention_times" in peaks
```

---

## Implementation Checklist

### Immediate (This Session)

- [x] Fix `build_dataset_like()` to use generic accessors
- [x] Add `get_feature_axis()` and `get_observation_axis()` to SherpaDataset
- [x] Document multi-dimensional data support
- [ ] Update MCRNode to use generic accessors
- [ ] Test MCR-ALS with time-resolved data

### Short Term (Next Session)

- [ ] Review and update visualization nodes
- [ ] Review and update metadata helpers
- [ ] Add unit tests for all new axis types in workflows
- [ ] Update classification nodes if needed

### Medium Term

- [ ] Create chromatography data loader
- [ ] Create mass spec data loader
- [ ] Create electrochemistry data loader
- [ ] Add comprehensive workflow examples for each domain
- [ ] Update documentation with domain-specific examples

---

## Key Insights

### Why This Matters

**Without these updates**:
- ✗ TimeAxis data works for input, but is LOST after first transformation
- ✗ MCR-ALS fails on time-resolved data (its primary use case!)
- ✗ Users can't build chromatography or mass spec workflows

**With these updates**:
- ✓ Any axis type propagates through entire workflow
- ✓ MCR-ALS works with time-resolved spectroscopy
- ✓ Same preprocessing nodes work for spectroscopy, chromatography, mass spec
- ✓ True multi-domain analytical chemistry platform

### Design Pattern

**Old Pattern** (domain-specific):
```python
x = dataset.spectral_axis  # Only works for spectroscopy
y = dataset.sample_axis    # Only works for sample-based data
```

**New Pattern** (domain-agnostic):
```python
x = dataset.get_feature_axis()      # Works for any domain
y = dataset.get_observation_axis()  # Works for any observation type
```

**When to use which**:
- Use **type-specific** (`spectral_axis`, `sample_axis`) only when you specifically need that type and its methods
- Use **generic** (`get_feature_axis()`, `get_observation_axis()`) for code that should work across domains

---

## Backward Compatibility

All updates maintain **100% backward compatibility**:

- Type-specific accessors still work for their types
- `build_dataset_like()` still works with old code
- Nodes using generic accessors work with both old and new data
- No breaking changes to existing workflows

---

## Next Steps

1. **Immediate**: Update MCRNode (15 minutes)
2. **Test**: Verify MCR-ALS with time-resolved data (30 minutes)
3. **Review**: Check visualization nodes (30 minutes)
4. **Document**: Add examples to docs (1 hour)
5. **Long-term**: Create domain-specific data loaders (ongoing)
