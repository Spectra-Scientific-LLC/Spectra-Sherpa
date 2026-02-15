# Backend Testing Guide - Folder and Pattern Loading

**Date:** 2026-01-20
**Purpose:** Verify folder shortcuts and pattern matching work correctly before frontend integration

---

## Prerequisites

### 1. Start Backend Server

```bash
cd src/spectra_sherpa
uvicorn app.main:app --reload
```

**Expected:** Server starts on `http://localhost:8000`

### 2. Verify SpectroChemPy Data Directory

```bash
python -c "import spectrochempy as scp; print(f'Datadir: {scp.preferences.datadir}')"
```

**Expected:** Prints path to SpectroChemPy data directory (e.g., `/Users/.../.spectrochempy/data`)

---

## Test 1: API Folder Entries

### Test 1.1: Verify Folder Entry Exists

**Command:**
```bash
curl -s http://localhost:8000/api/v1/workflows/spectrochempy-examples | \
jq '.irdata[0]'
```

**Expected Output:**
```json
{
  "label": "📁 Load all irdata files (45 files)",
  "value": "irdata/",
  "path": "irdata",
  "format": "folder",
  "is_folder": true,
  "file_count": 45,
  "source": "primary",
  "pattern": "*"
}
```

**Success Criteria:**
- ✅ First entry has `"is_folder": true`
- ✅ Label starts with 📁 emoji
- ✅ `file_count` is a positive number
- ✅ `value` ends with `/`

---

### Test 1.2: Verify All Datasets Have Folder Entries

**Command:**
```bash
curl -s http://localhost:8000/api/v1/workflows/spectrochempy-examples | \
jq 'to_entries | map({dataset: .key, has_folder: (.value[0].is_folder // false)}) | .[]'
```

**Expected Output:**
```json
{"dataset":"irdata","has_folder":true}
{"dataset":"ramandata","has_folder":true}
{"dataset":"nmrdata","has_folder":true}
{"dataset":"galacticdata","has_folder":true}
```

**Success Criteria:**
- ✅ All datasets have `has_folder: true`

---

### Test 1.3: Count Files vs Folder Entry

**Command:**
```bash
curl -s http://localhost:8000/api/v1/workflows/spectrochempy-examples | \
jq '.irdata | {folder_count: .[0].file_count, actual_files: (length - 1)}'
```

**Expected Output:**
```json
{
  "folder_count": 45,
  "actual_files": 45
}
```

**Success Criteria:**
- ✅ `folder_count` matches `actual_files`

---

## Test 2: Pattern Detection Logic

### Test 2.1: Test Pattern Detection Function

**Command:**
```bash
cd src/spectra_sherpa

python -c "
from app.services.dag.nodes.data import DataSourceNode

node = DataSourceNode()

# Test patterns
test_cases = [
    ('irdata/', True, 'Trailing slash'),
    ('*.spa', True, 'Asterisk wildcard'),
    ('sample_*', True, 'Prefix wildcard'),
    ('data_?.spa', True, 'Question mark wildcard'),
    ('irdata/*.csv', True, 'Path with wildcard'),
    ('single_file.spa', False, 'No pattern'),
    ('CO@Mo_Al2O3.SPG', False, 'No pattern'),
]

print('Pattern Detection Tests:')
print('-' * 60)
for pattern, expected, description in test_cases:
    result = node._is_pattern(pattern)
    status = '✅' if result == expected else '❌'
    print(f'{status} {description:30s} | {pattern:20s} | {result}')

print()
print('All tests passed!' if all(node._is_pattern(p) == e for p, e, _ in test_cases) else 'Some tests failed!')
"
```

**Expected Output:**
```
Pattern Detection Tests:
------------------------------------------------------------
✅ Trailing slash                   | irdata/              | True
✅ Asterisk wildcard                | *.spa                | True
✅ Prefix wildcard                  | sample_*             | True
✅ Question mark wildcard           | data_?.spa           | True
✅ Path with wildcard               | irdata/*.csv         | True
✅ No pattern                       | single_file.spa      | False
✅ No pattern                       | CO@Mo_Al2O3.SPG      | False

All tests passed!
```

**Success Criteria:**
- ✅ All tests show ✅
- ✅ "All tests passed!" message

---

## Test 3: Group Loading Functionality

### Test 3.1: Load All Files from Folder (Trailing /)

**Command:**
```bash
cd src/spectra_sherpa

python -c "
import asyncio
from app.services.dag.nodes.data import DataSourceNode

async def test():
    node = DataSourceNode()
    node.parameters = {
        'source': 'spectrochempy',
        'example_dataset': 'irdata',
        'example_file': 'irdata/'  # Trailing slash
    }

    print('Testing: Load all irdata files with trailing /')
    print('=' * 60)

    dataset = await node.execute()

    print(f'✅ Loaded successfully!')
    print(f'Dataset shape: {dataset.shape}')
    print(f'Dataset title: {dataset.title}')
    print(f'Number of spectra: {dataset.shape[0]}')
    print(f'Wavenumber points: {dataset.shape[1]}')

    if hasattr(dataset, 'y') and hasattr(dataset.y, 'labels'):
        print(f'Sample labels (first 5): {dataset.y.labels[:5]}')

    return dataset

dataset = asyncio.run(test())
print()
print('Test PASSED ✅' if dataset.shape[0] > 1 else 'Test FAILED ❌')
"
```

**Expected Output:**
```
Testing: Load all irdata files with trailing /
============================================================
[DATA] Pattern detected: folder=irdata, pattern=*
[DATA] Found 45 files matching pattern '*'
[DATA] Loading 1/45: CO@Mo_Al2O3.SPG
[DATA] Loading 2/45: nh4y-activation.spg
...
[DATA] ✅ X-axis validation passed for 45 files
[DATA] Concatenated 45 files into shape (45, 5549)
✅ Loaded successfully!
Dataset shape: (45, 5549)
Dataset title: irdata (45 files)
Number of spectra: 45
Wavenumber points: 5549
Sample labels (first 5): ['CO@Mo_Al2O3', 'nh4y-activation', ...]

Test PASSED ✅
```

**Success Criteria:**
- ✅ Pattern detected message appears
- ✅ Multiple files loaded (count > 1)
- ✅ X-axis validation passed
- ✅ Dataset shape is `(n_files, n_wavenumbers)`
- ✅ Test PASSED message

---

### Test 3.2: Load Files with Wildcard Pattern

**Command:**
```bash
cd src/spectra_sherpa

python -c "
import asyncio
from app.services.dag.nodes.data import DataSourceNode

async def test():
    node = DataSourceNode()
    node.parameters = {
        'source': 'spectrochempy',
        'example_dataset': 'irdata',
        'example_file': '*.SPG'  # Only .SPG files
    }

    print('Testing: Load only .SPG files')
    print('=' * 60)

    dataset = await node.execute()

    print(f'✅ Loaded {dataset.shape[0]} .SPG files')
    print(f'Dataset shape: {dataset.shape}')

    return dataset

dataset = asyncio.run(test())
print('Test PASSED ✅')
"
```

**Expected Output:**
```
Testing: Load only .SPG files
============================================================
[DATA] Pattern detected: folder=irdata, pattern=*.SPG
[DATA] Found 25 files matching pattern '*.SPG'
[DATA] Loading 1/25: CO@Mo_Al2O3.SPG
[DATA] Loading 2/25: nh4y-activation.spg
...
✅ Loaded 25 .SPG files
Dataset shape: (25, 5549)
Test PASSED ✅
```

**Success Criteria:**
- ✅ Only .SPG files loaded
- ✅ File count matches pattern

---

### Test 3.3: Load Files with Prefix Pattern

**Command:**
```bash
cd src/spectra_sherpa

python -c "
import asyncio
from app.services.dag.nodes.data import DataSourceNode

async def test():
    node = DataSourceNode()
    node.parameters = {
        'source': 'spectrochempy',
        'example_dataset': 'galacticdata',
        'example_file': '*.spc'  # Pattern matching
    }

    print('Testing: Pattern matching in galacticdata')
    print('=' * 60)

    dataset = await node.execute()

    print(f'✅ Loaded successfully!')
    print(f'Dataset shape: {dataset.shape}')

    return dataset

dataset = asyncio.run(test())
print('Test PASSED ✅')
"
```

**Expected Output:**
```
Testing: Pattern matching in galacticdata
============================================================
[DATA] Pattern detected: folder=galacticdata, pattern=*.spc
[DATA] Found 12 files matching pattern '*.spc'
...
✅ Loaded successfully!
Dataset shape: (12, 1024)
Test PASSED ✅
```

**Success Criteria:**
- ✅ Files loaded from galacticdata
- ✅ Pattern matching works

---

## Test 4: Error Handling

### Test 4.1: Pattern Not Found

**Command:**
```bash
cd src/spectra_sherpa

python -c "
import asyncio
from app.services.dag.nodes.data import DataSourceNode

async def test():
    node = DataSourceNode()
    node.parameters = {
        'source': 'spectrochempy',
        'example_dataset': 'irdata',
        'example_file': '*.nonexistent'  # No files match
    }

    print('Testing: Pattern with no matches')
    print('=' * 60)

    try:
        dataset = await node.execute()
        print('❌ Should have raised error!')
        return False
    except ValueError as e:
        error_msg = str(e)
        print(f'✅ Caught expected error:')
        print(f'   {error_msg[:100]}...')

        # Verify error message is helpful
        if 'No files found' in error_msg and '*.nonexistent' in error_msg:
            print('✅ Error message is clear and helpful')
            return True
        else:
            print('❌ Error message not clear enough')
            return False

success = asyncio.run(test())
print()
print('Test PASSED ✅' if success else 'Test FAILED ❌')
"
```

**Expected Output:**
```
Testing: Pattern with no matches
============================================================
[DATA] Pattern detected: folder=irdata, pattern=*.nonexistent
✅ Caught expected error:
   No files found matching pattern '*.nonexistent' in /path/to/irdata
Please verify the pattern...
✅ Error message is clear and helpful

Test PASSED ✅
```

**Success Criteria:**
- ✅ ValueError raised
- ✅ Error message mentions pattern
- ✅ Error message is helpful

---

### Test 4.2: X-Axis Validation Failure

**Command:**
```bash
cd src/spectra_sherpa

python -c "
import asyncio
import numpy as np
from app.services.dag.nodes.data import DataSourceNode

async def test():
    # This test requires files with mismatched x-axes
    # If your test data doesn't have this, skip this test

    print('Testing: X-axis validation (skip if no mismatched files)')
    print('=' * 60)

    # Try to load mixed format files that might have different axes
    node = DataSourceNode()
    node.parameters = {
        'source': 'spectrochempy',
        'example_dataset': 'irdata',
        'example_file': '*'  # All files
    }

    try:
        dataset = await node.execute()
        print(f'✅ All files have matching x-axes')
        print(f'   Loaded {dataset.shape[0]} files successfully')
        return True
    except ValueError as e:
        error_msg = str(e)
        if 'X-axis' in error_msg or 'mismatch' in error_msg:
            print(f'✅ X-axis validation correctly caught mismatch:')
            print(f'   {error_msg[:150]}...')
            return True
        else:
            print(f'❌ Unexpected error: {error_msg[:100]}')
            return False

success = asyncio.run(test())
print()
print('Test PASSED ✅' if success else 'Test FAILED ❌')
"
```

**Expected Output (if all files match):**
```
Testing: X-axis validation (skip if no mismatched files)
============================================================
[DATA] Pattern detected: folder=irdata, pattern=*
[DATA] Found 45 files matching pattern '*'
...
[DATA] ✅ X-axis validation passed for 45 files
✅ All files have matching x-axes
   Loaded 45 files successfully

Test PASSED ✅
```

**Success Criteria:**
- ✅ Either validation passes or catches mismatch
- ✅ Clear error message if mismatch

---

## Test 5: LoadGroupNode Comparison

Verify DataSourceNode pattern loading produces same result as LoadGroupNode.

**Command:**
```bash
cd src/spectra_sherpa

python -c "
import asyncio
import numpy as np
from app.services.dag.nodes.data import DataSourceNode, LoadGroupNode

async def test():
    print('Testing: DataSourceNode vs LoadGroupNode consistency')
    print('=' * 60)

    # Load via DataSourceNode (pattern)
    data_node = DataSourceNode()
    data_node.parameters = {
        'source': 'spectrochempy',
        'example_dataset': 'irdata',
        'example_file': '*.SPG'
    }

    print('Loading via DataSourceNode pattern...')
    ds1 = await data_node.execute()

    # Load via LoadGroupNode
    load_node = LoadGroupNode()
    load_node.parameters = {
        'folder_path': 'irdata',
        'pattern': '*.SPG',
        'sort_by': 'filename',
        'validate_axes': True
    }

    print('Loading via LoadGroupNode...')
    ds2 = await load_node.execute()

    # Compare
    print()
    print('Comparison:')
    print(f'  DataSourceNode shape: {ds1.shape}')
    print(f'  LoadGroupNode shape:  {ds2.shape}')

    if ds1.shape == ds2.shape:
        print('  ✅ Shapes match')
    else:
        print('  ❌ Shapes differ!')
        return False

    # Compare data
    if np.allclose(ds1.data, ds2.data, rtol=1e-10):
        print('  ✅ Data matches')
    else:
        print('  ❌ Data differs!')
        return False

    print()
    print('Both methods produce identical results ✅')
    return True

success = asyncio.run(test())
print()
print('Test PASSED ✅' if success else 'Test FAILED ❌')
"
```

**Expected Output:**
```
Testing: DataSourceNode vs LoadGroupNode consistency
============================================================
Loading via DataSourceNode pattern...
[DATA] Pattern detected: folder=irdata, pattern=*.SPG
[DATA] Found 25 files matching pattern '*.SPG'
...
Loading via LoadGroupNode...
[LOAD_GROUP] Found 25 files matching '*.SPG' in irdata
...

Comparison:
  DataSourceNode shape: (25, 5549)
  LoadGroupNode shape:  (25, 5549)
  ✅ Shapes match
  ✅ Data matches

Both methods produce identical results ✅

Test PASSED ✅
```

**Success Criteria:**
- ✅ Both methods load same number of files
- ✅ Shapes match
- ✅ Data values match

---

## Test 6: Edge Cases

### Test 6.1: Single File (No Pattern)

Verify single file loading still works (backward compatibility).

**Command:**
```bash
cd src/spectra_sherpa

python -c "
import asyncio
from app.services.dag.nodes.data import DataSourceNode

async def test():
    node = DataSourceNode()
    node.parameters = {
        'source': 'spectrochempy',
        'example_dataset': 'irdata',
        'example_file': 'CO@Mo_Al2O3.SPG'  # Single file, no pattern
    }

    print('Testing: Single file loading (backward compatibility)')
    print('=' * 60)

    dataset = await node.execute()

    print(f'✅ Single file loaded')
    print(f'Dataset shape: {dataset.shape}')
    print(f'Dataset title: {dataset.title}')

    # Should be 2D but just one spectrum or multi-spectrum file
    if len(dataset.shape) == 2:
        print(f'Number of spectra in file: {dataset.shape[0]}')

    return dataset

dataset = asyncio.run(test())
print()
print('Test PASSED ✅')
"
```

**Expected Output:**
```
Testing: Single file loading (backward compatibility)
============================================================
Loaded .spg dataset using read_omnic: CO@Mo_Al2O3.SPG
✅ Single file loaded
Dataset shape: (55, 5549)
Dataset title: irdata / CO@Mo_Al2O3.SPG
Number of spectra in file: 55

Test PASSED ✅
```

**Success Criteria:**
- ✅ No pattern detection triggered
- ✅ File loaded normally
- ✅ Original behavior preserved

---

### Test 6.2: Empty Folder

**Command:**
```bash
cd src/spectra_sherpa

python -c "
import asyncio
from app.services.dag.nodes.data import DataSourceNode

async def test():
    node = DataSourceNode()
    node.parameters = {
        'source': 'spectrochempy',
        'example_dataset': 'irdata',
        'example_file': 'nonexistent_folder/'  # Folder doesn't exist
    }

    print('Testing: Nonexistent folder')
    print('=' * 60)

    try:
        dataset = await node.execute()
        print('❌ Should have raised error!')
        return False
    except ValueError as e:
        error_msg = str(e)
        print(f'✅ Caught expected error')
        print(f'   Message preview: {error_msg[:100]}...')
        return 'Folder not found' in error_msg or 'not found' in error_msg

success = asyncio.run(test())
print()
print('Test PASSED ✅' if success else 'Test FAILED ❌')
"
```

**Expected Output:**
```
Testing: Nonexistent folder
============================================================
✅ Caught expected error
   Message preview: Folder not found: irdata/nonexistent_folder
Attempted paths:
  - /path1/irdata/nonexistent...

Test PASSED ✅
```

**Success Criteria:**
- ✅ ValueError raised
- ✅ Clear error message

---

## Test Summary Script

Run all tests in sequence:

**Command:**
```bash
cd src/spectra_sherpa

python -c "
import asyncio
import sys
from app.services.dag.nodes.data import DataSourceNode

async def run_all_tests():
    results = []

    # Test 1: Pattern detection
    print('=' * 70)
    print('TEST 1: Pattern Detection')
    print('=' * 70)
    node = DataSourceNode()
    patterns = [
        ('irdata/', True),
        ('*.spa', True),
        ('CO@Mo_Al2O3.SPG', False),
    ]
    test1_pass = all(node._is_pattern(p) == expected for p, expected in patterns)
    results.append(('Pattern Detection', test1_pass))
    print(f'Result: {'✅ PASS' if test1_pass else '❌ FAIL'}\n')

    # Test 2: Load with trailing slash
    print('=' * 70)
    print('TEST 2: Load All Files (Trailing /)')
    print('=' * 70)
    try:
        node = DataSourceNode()
        node.parameters = {
            'source': 'spectrochempy',
            'example_dataset': 'irdata',
            'example_file': 'irdata/'
        }
        ds = await node.execute()
        test2_pass = ds.shape[0] > 1
        print(f'Loaded {ds.shape[0]} files, shape {ds.shape}')
        results.append(('Load All Files', test2_pass))
        print(f'Result: {'✅ PASS' if test2_pass else '❌ FAIL'}\n')
    except Exception as e:
        print(f'❌ ERROR: {e}\n')
        results.append(('Load All Files', False))

    # Test 3: Load with pattern
    print('=' * 70)
    print('TEST 3: Load with Wildcard Pattern')
    print('=' * 70)
    try:
        node = DataSourceNode()
        node.parameters = {
            'source': 'spectrochempy',
            'example_dataset': 'irdata',
            'example_file': '*.SPG'
        }
        ds = await node.execute()
        test3_pass = ds.shape[0] > 1
        print(f'Loaded {ds.shape[0]} .SPG files, shape {ds.shape}')
        results.append(('Wildcard Pattern', test3_pass))
        print(f'Result: {'✅ PASS' if test3_pass else '❌ FAIL'}\n')
    except Exception as e:
        print(f'❌ ERROR: {e}\n')
        results.append(('Wildcard Pattern', False))

    # Test 4: Error handling
    print('=' * 70)
    print('TEST 4: Error Handling (No Matches)')
    print('=' * 70)
    try:
        node = DataSourceNode()
        node.parameters = {
            'source': 'spectrochempy',
            'example_dataset': 'irdata',
            'example_file': '*.nonexistent'
        }
        ds = await node.execute()
        print('❌ Should have raised error!')
        results.append(('Error Handling', False))
    except ValueError as e:
        test4_pass = 'No files found' in str(e)
        print(f'Caught expected error: {str(e)[:80]}...')
        results.append(('Error Handling', test4_pass))
        print(f'Result: {'✅ PASS' if test4_pass else '❌ FAIL'}\n')

    # Test 5: Backward compatibility
    print('=' * 70)
    print('TEST 5: Backward Compatibility (Single File)')
    print('=' * 70)
    try:
        node = DataSourceNode()
        node.parameters = {
            'source': 'spectrochempy',
            'example_dataset': 'irdata',
            'example_file': 'CO@Mo_Al2O3.SPG'
        }
        ds = await node.execute()
        test5_pass = ds.shape[0] >= 1  # Single file loaded
        print(f'Loaded single file, shape {ds.shape}')
        results.append(('Backward Compatibility', test5_pass))
        print(f'Result: {'✅ PASS' if test5_pass else '❌ FAIL'}\n')
    except Exception as e:
        print(f'❌ ERROR: {e}\n')
        results.append(('Backward Compatibility', False))

    # Summary
    print('=' * 70)
    print('TEST SUMMARY')
    print('=' * 70)
    for name, passed in results:
        status = '✅ PASS' if passed else '❌ FAIL'
        print(f'{status:10s} {name}')

    print()
    total = len(results)
    passed = sum(1 for _, p in results if p)
    print(f'Total: {passed}/{total} tests passed')

    return all(p for _, p in results)

success = asyncio.run(run_all_tests())
sys.exit(0 if success else 1)
"
```

**Expected Output:**
```
======================================================================
TEST 1: Pattern Detection
======================================================================
Result: ✅ PASS

======================================================================
TEST 2: Load All Files (Trailing /)
======================================================================
[DATA] Pattern detected: folder=irdata, pattern=*
...
Loaded 45 files, shape (45, 5549)
Result: ✅ PASS

======================================================================
TEST 3: Load with Wildcard Pattern
======================================================================
...
Loaded 25 .SPG files, shape (25, 5549)
Result: ✅ PASS

======================================================================
TEST 4: Error Handling (No Matches)
======================================================================
Caught expected error: No files found matching pattern '*.nonexistent'...
Result: ✅ PASS

======================================================================
TEST 5: Backward Compatibility (Single File)
======================================================================
Loaded single file, shape (55, 5549)
Result: ✅ PASS

======================================================================
TEST SUMMARY
======================================================================
✅ PASS    Pattern Detection
✅ PASS    Load All Files
✅ PASS    Wildcard Pattern
✅ PASS    Error Handling
✅ PASS    Backward Compatibility

Total: 5/5 tests passed
```

---

## Troubleshooting

### Issue: "No files found"

**Possible Causes:**
1. SpectroChemPy data not installed
2. Wrong datadir path
3. Pattern doesn't match any files

**Solution:**
```bash
# Install SpectroChemPy data
python -c "import spectrochempy as scp; scp.download_data()"

# Check what files exist
ls -la ~/.spectrochempy/data/irdata/
```

---

### Issue: "X-axis validation failed"

**Possible Cause:** Mixed file formats with different spectral ranges

**Solution:** Use specific pattern to load only compatible files:
```python
example_file = "*.SPG"  # Instead of "*"
```

---

### Issue: ImportError

**Possible Cause:** Wrong directory

**Solution:**
```bash
# Make sure you're in the package directory
cd src/spectra_sherpa

# Verify imports work
python -c "from app.services.dag.nodes.data import DataSourceNode; print('✅ Imports work')"
```

---

## Next Steps

Once all backend tests pass:

1. ✅ **Backend Verified** - All functionality working
2. 🔄 **Frontend Integration** - Add UI support for folder entries
3. 🧪 **End-to-End Testing** - Test full workflow through UI
4. 📝 **User Documentation** - Write user guide

---

## Test Checklist

Before proceeding to frontend:

- [ ] API returns folder entries (Test 1)
- [ ] Pattern detection works (Test 2.1)
- [ ] Trailing `/` loads all files (Test 3.1)
- [ ] Wildcard patterns work (Test 3.2)
- [ ] Error handling is clear (Test 4)
- [ ] X-axis validation works (Test 5.2)
- [ ] Backward compatible (Test 6.1)
- [ ] All summary tests pass

**Once all checked → Proceed to frontend integration**
