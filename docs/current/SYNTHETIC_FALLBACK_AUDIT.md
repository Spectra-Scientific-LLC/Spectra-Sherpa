# Synthetic Data Fallback Audit

## Problem Statement

The system currently generates synthetic/fallback data when real data files cannot be loaded. This is dangerous because:

1. **Scientific Integrity**: Users may unknowingly analyze fabricated data thinking it's real
2. **Hidden Failures**: File path errors, missing files, and format issues are masked
3. **Loss of Trust**: Discovery of silent fallbacks destroys confidence in the system
4. **Incorrect Conclusions**: Analysis on fake data leads to meaningless results

## Example of the Problem

```
File not found: /Users/fe2val/.spectrochempy/testdata/matlabdata/als2004dataset.MAT
[DATA] Transposed data: 50 samples × 1000 wavenumbers → 1000 samples × 50 wavenumbers
```

The file doesn't exist, but the system **silently generated synthetic data** and proceeded as if everything was fine.

---

## All Synthetic Data Generation Methods

### 1. `_generate_synthetic()` (Lines 471-528)
**Purpose**: Generic fallback synthetic data
**Generates**: 50 samples × 1000 wavenumbers, FTIR-like peaks at [3400, 2900, 1700, 1500, 1000] cm⁻¹

### 2. `_generate_ftir_synthetic()` (Lines 244-313)
**Purpose**: Realistic FTIR fallback data simulating NH4Y zeolite activation
**Generates**: 55 samples × 5549 wavenumbers, temperature series 25-300°C

### 3. `_generate_raman_synthetic()` (Lines 315-366)
**Purpose**: Raman spectroscopy fallback data
**Generates**: 30 samples × 1024 wavenumbers, concentration series

---

## All Fallback Locations in DataSourceNode

### In `_load_spectrochempy_example()` method:

| Line | Condition | Fallback Method |
|------|-----------|-----------------|
| 216 | OMNIC IR data load exception | `_generate_ftir_synthetic()` |
| 226 | Raman example load exception | `_generate_raman_synthetic()` |
| 236 | NMR example load exception | `_generate_synthetic()` |
| 238 | Default case (unknown example) | `_generate_synthetic()` |
| 242 | Any exception in method | `_generate_synthetic()` |

### In `_load_from_experiment()` method:

| Line | Condition | Fallback Method |
|------|-----------|-----------------|
| 385 | No files found in experiment | `_generate_synthetic()` |
| 394 | No valid file paths exist | `_generate_synthetic()` |
| 397 | Exception loading from DB | `_generate_synthetic()` |

### In `_load_from_file()` method:

| Line | Condition | Fallback Method |
|------|-----------|-----------------|
| 404 | **File not found** ⚠️ | `_generate_synthetic()` |
| 428 | Exception reading file | `_generate_synthetic()` |

**Total Fallback Locations: 10**

---

## Nodes That Do It RIGHT

These nodes **properly raise exceptions** instead of silently falling back:

### ✅ FileLoadNode (Lines 538-694)
- Line 630: `raise ValueError(f"Error loading file: {e}")`
- Line 636: `raise ValueError(f"File not found: {file_path}")`
- Line 674: `raise ValueError(f"No datasets found in {file_path}")`

### ✅ NISTLibraryNode (Lines 697-796)
- Line 750: `raise ValueError(f"Library entry {library_id} not found")`
- Line 796: `raise ValueError(f"Error loading NIST library entry: {e}")`

---

## Recommended Changes

### Phase 1: Remove All Silent Fallbacks

Replace all `return self._generate_*()` with proper exceptions:

```python
# BEFORE (Line 404):
if not os.path.exists(file_path):
    print(f"File not found: {file_path}")
    return self._generate_synthetic()

# AFTER:
if not os.path.exists(file_path):
    raise FileNotFoundError(f"File not found: {file_path}")
```

### Phase 2: Remove Synthetic Generation Methods

Once all fallbacks are removed, delete these methods entirely:
- `_generate_synthetic()` (Lines 471-528)
- `_generate_ftir_synthetic()` (Lines 244-313)
- `_generate_raman_synthetic()` (Lines 315-366)

### Phase 3: Keep Only Legitimate Synthetic Generation

The **SyntheticCurveNode** (Lines 799-932) is legitimate because:
- User explicitly selects "synthetic" source
- It's for generating concentration curves, not masking failures
- No silent fallbacks involved

---

## Files to Modify

### Primary File
- `app/services/dag/nodes/data.py`

### Other Files with Synthetic Data (from grep results)
May contain test data or legitimate synthetic generation:
- `app/services/dag/nodes/blend.py` (blending synthetic spectra)
- `libs/project0/curves.py` (curve generation utilities)
- `tests/test_*.py` files (test fixtures - OK to keep)

---

## Testing After Changes

After removing fallbacks, these should **fail with clear error messages**:

1. Missing file path → `FileNotFoundError: File not found: /path/to/file`
2. Invalid experiment ID → `ValueError: File X not found in experiment Y`
3. Corrupted file → `ValueError: Error loading file: [specific error]`
4. Missing example data → `FileNotFoundError: SpectroChemPy example 'X' not found`

Users should see **explicit errors**, not silent synthetic data.

---

## Risk Assessment

### Before (Current State)
- **Risk Level**: 🔴 **CRITICAL**
- **Issue**: Users unknowingly analyze fake data
- **Impact**: Complete loss of scientific integrity

### After (With Changes)
- **Risk Level**: 🟢 **LOW**
- **Issue**: Users see clear error messages
- **Impact**: Users fix actual problems (file paths, permissions, format issues)

---

## Implementation Plan

1. **Backup**: Commit current state before changes
2. **Replace Fallbacks**: Convert all `return self._generate_*()` to `raise` statements
3. **Delete Methods**: Remove the 3 synthetic generation methods
4. **Test**: Verify all error paths work correctly
5. **Document**: Update user docs to explain error messages

---

## Code Locations Summary

**File**: `app/services/dag/nodes/data.py`

**Methods to Delete** (279 lines total):
- Lines 244-313: `_generate_ftir_synthetic()`
- Lines 315-366: `_generate_raman_synthetic()`
- Lines 471-528: `_generate_synthetic()`

**Fallback Calls to Replace with Exceptions** (10 locations):
- Lines: 216, 226, 236, 238, 242, 385, 394, 397, 404, 428

**Keep As-Is**:
- Lines 799-932: `SyntheticCurveNode` (legitimate synthetic curve generation)
- Lines 538-694: `FileLoadNode` (already raises proper exceptions)
- Lines 697-796: `NISTLibraryNode` (already raises proper exceptions)
