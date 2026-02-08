# DOE Implementation Verification Procedure

This document outlines how to verify that the refactored DOE implementation produces identical results to the original Exp_loader.

## Prerequisites

1. **Test Data**: Use `Spike_DOE_082925` folder with known ground truth
2. **Original Exp_loader**: Have the original implementation available for comparison
3. **Reference CSV**: Keep the original `EXP_20250909_6ZJBX_matched.csv` for comparison

## Test 1: Folder Picker & File Loading

### Steps:
1. Start the refactored frontend:
   ```bash
   cd Refactored/frontend
   npm run dev
   ```

2. Navigate to an experiment → DOE tab

3. Click "Match Files" → Select "Folder-Based" tab

4. Click "Select Folders" button

5. Select the `Spike_DOE_082925` folder (contains 3 subfolders with 40 files each)

### Expected Results:
- ✅ All 3 folders should appear with batch numbers 1, 2, 3
- ✅ Each folder should show "40 files" tag
- ✅ File preview should show first 5 filenames
- ✅ No manual copy-paste required

### Verification:
```bash
# The matchFolders array should contain:
[
  { folder_path: "08-29-2025_@05-19-55", batch_number: 1, file_list: ["Spectrum_0001.csv", ...] },
  { folder_path: "08-29-2025_@05-39-11", batch_number: 2, file_list: ["Spectrum_0041.csv", ...] },
  { folder_path: "08-29-2025_@05-59-01", batch_number: 3, file_list: ["Spectrum_0081.csv", ...] }
]
```

---

## Test 2: Auto-Match with Plate Map

### Steps:
1. Set up DOE factors (same as original):
   - **Sample Factor "Cells"**: 2 levels (Cell1, Cell2)
   - **Method Factor "Defocus"**: 5 levels (-200, -100, 0, 100, 200)

2. Create plate map (10 unique mixtures, A1-E2)

3. Create run sequence:
   - Map batch 1 → Defocus: -200
   - Map batch 2 → Defocus: -100
   - Map batch 3 → Defocus: 0

4. Match files with these settings:
   - First Cell: `A1`
   - Scan Orientation: `serpentine_column`
   - ✅ Use plate map for cells
   - ✅ Use run sequence for factors

### Expected Results:
- ✅ 120 matched acquisitions (40 files × 3 batches)
- ✅ Sequence numbers: 1-120 (continuous, NOT restarting per batch)
- ✅ Each acquisition has correct cell assignment (A1-H12 pattern)
- ✅ Each acquisition has `factor_values` with "Cells" and "Defocus"

### Verification Script:
```python
# Run this to verify matching
cd Refactored
python test_spike_doe.py
```

Expected output:
```
Creating experiment...
Creating sample factor (Cells)...
Creating method factor (Defocus)...
Creating mixtures and plate map...
Creating run sequence...
Matching files...
Matched 120 acquisitions

Comparing first 10 rows with original...
✓ All first 10 rows match!
```

---

## Test 3: Dynamic Factor Columns in Table

### Steps:
1. After matching (from Test 2), scroll to "Matched Acquisitions" section

2. Check the DataTable columns

### Expected Results:
- ✅ Base columns: Seq, Filename, Folder, Batch, Cell, Sample ID
- ✅ **Dynamic factor columns**: "Cells" and "Defocus [mm]" (or whatever you named them)
- ✅ Factor values populated for each row
- ✅ Table is scrollable with frozen Seq/Filename columns

### Manual Verification:
Look at row 1:
- Seq: 1
- Filename: Spectrum_0001.csv
- Folder: 08-29-2025_@05-19-55
- Batch: 1
- Cell: A1
- Sample ID: mixture_1 (or actual mixture name)
- **Cells**: Cell1 (from plate map)
- **Defocus [mm]**: -200 (from run sequence)

---

## Test 4: CSV Export with Factor Columns

### Steps:
1. Click "Export CSV" button

2. Save the file as `refactored_matched.csv`

3. Compare with original `EXP_20250909_6ZJBX_matched.csv`

### Expected CSV Structure:
```csv
seq,filename,folder,timestamp,cell,sample_id,Cells,Defocus [mm],batch
1,Spectrum_0001.csv,08-29-2025_@05-19-55,,A1,mixture_1,Cell1,-200,1
2,Spectrum_0002.csv,08-29-2025_@05-19-55,,B1,mixture_2,Cell2,-200,1
...
```

### Automated Comparison:
```python
import pandas as pd

# Load both CSVs
original = pd.read_csv("Original/EXP_20250909_6ZJBX_matched.csv")
refactored = pd.read_csv("Refactored/refactored_matched.csv")

# Compare key columns
key_cols = ["seq", "filename", "cell", "sample_id"]
factor_cols = ["Cells", "Defocus [mm]"]  # Adjust to your factor names

print("Checking key columns...")
for col in key_cols:
    matches = (original[col] == refactored[col]).all()
    print(f"  {col}: {'✓ MATCH' if matches else '✗ MISMATCH'}")

print("\nChecking factor columns...")
for col in factor_cols:
    if col in original.columns and col in refactored.columns:
        matches = (original[col] == refactored[col]).all()
        print(f"  {col}: {'✓ MATCH' if matches else '✗ MISMATCH'}")
    else:
        print(f"  {col}: ✗ MISSING")

print(f"\nRow count: Original={len(original)}, Refactored={len(refactored)}")
```

### Expected Results:
- ✅ seq: MATCH
- ✅ filename: MATCH
- ✅ cell: MATCH
- ✅ sample_id: MATCH
- ✅ Factor columns (Cells, Defocus): MATCH
- ✅ Row count: 120 (or 121 if original has duplicate)

---

## Test 5: Run Sequence Auto-Population

### Steps:
1. Create a new experiment

2. Create a method factor (e.g., "Temperature")

3. Go to Match Files → Folder-Based tab

4. Select 3 folders using folder picker

5. **Check if run sequence is auto-created**

### Expected Results:
- ✅ Run sequence automatically created with 3 levels
- ✅ Each level mapped to a folder/batch
- ✅ Level values default to batch numbers (1, 2, 3)
- ✅ Toast notification: "Run Sequence Auto-Created"

### Verification:
```bash
# Check the API response
curl http://localhost:8000/api/v1/experiments/{exp_id}/doe/run-sequence
```

Expected:
```json
[
  {
    "factor_definition_id": 1,
    "path": "folder1",
    "batch": 1,
    "level_value": "1",
    "sequence_order": 0
  },
  ...
]
```

---

## Test 6: Performance & Query Efficiency

### Steps:
1. Start backend with query logging:
   ```bash
   cd Refactored/backend
   # Add to .env: DATABASE_ECHO=true
   poetry run uvicorn app.main:app --reload
   ```

2. Match 120 files using the folder picker

3. Watch the SQL queries in the terminal

### Expected Results:
- ✅ **No N+1 queries**: Should see batched `SELECT` with `JOIN` for mixtures
- ✅ Plate wells loaded with eager loading: `selectinload(PlateWell.mixture)`
- ✅ Total queries < 10 (not 100+)

### Query Pattern Should Look Like:
```sql
-- Single query with JOIN, NOT one query per well
SELECT plate_well.*, mixture.*
FROM plate_well
LEFT OUTER JOIN mixture ON mixture.id = plate_well.mixture_id
WHERE plate_well.experiment_id = ?
```

---

## Test 7: End-to-End Workflow

### Complete Workflow Test:
1. ✅ Create experiment
2. ✅ Define 2 sample factors (Cells, Method)
3. ✅ Define 1 method factor (Defocus)
4. ✅ Create 10 mixtures
5. ✅ Generate plate map (A1-E2)
6. ✅ Use folder picker to select 3 folders → Auto-creates run sequence
7. ✅ Match files with plate map + run sequence
8. ✅ View table with dynamic factor columns
9. ✅ Export CSV with all factor columns
10. ✅ Compare CSV with original Exp_loader output

### Success Criteria:
- ✅ No manual file pasting required
- ✅ Factor columns visible in table
- ✅ Factor columns in CSV export
- ✅ Run sequence tied to folder selection
- ✅ Output matches original Exp_loader

---

## Troubleshooting

### Issue: "Folder picker not showing"
**Solution**: Rebuild frontend
```bash
cd Refactored/frontend
npm run build
# Or restart dev server
npm run dev
```

### Issue: "Factor columns not appearing in table"
**Check**:
1. Are `factor_values` populated in matched acquisitions?
2. Is `factorColumnNames` computed property defined?
3. Browser console for errors

**Debug**:
```javascript
// In browser console
console.log(matchedAcquisitions.value[0]?.factor_values)
// Should show: { "Cells": "Cell1", "Defocus [mm]": -200 }
```

### Issue: "CSV missing factor columns"
**Check**: Backend route at `/api/v1/experiments/{id}/doe/export/csv`
```python
# In doe.py:675-679, verify:
all_factor_names = set()
for acq in acquisitions:
    if acq.factor_values:
        all_factor_names.update(acq.factor_values.keys())
```

### Issue: "Sequence numbers restart per batch"
**Fixed in**: `doe.py:510` - uses global index not batch-local index

---

## Automated Test Suite

Run the full automated test:
```bash
# Backend tests
cd Refactored/backend
poetry install
poetry run pytest tests/

# Frontend tests
cd Refactored/frontend
npm install
npm test

# Integration test
cd Refactored
python test_spike_doe.py
```

---

## Acceptance Criteria Summary

| Feature | Status | Location |
|---------|--------|----------|
| Folder picker (no manual paste) | ✅ Implemented | DoeTab.vue:543-599 |
| Factor columns in table | ✅ Implemented | DoeTab.vue:206-210 |
| Factor columns in CSV | ✅ Implemented | doe.py:675-706 |
| Run sequence auto-populate | ✅ Implemented | DoeTab.vue:1080-1096 |
| N+1 query prevention | ✅ Implemented | doe.py:473-477 |
| Eager loading | ✅ Implemented | experiments.py:84-88 |

**All must-fix items are implemented and ready for verification.**
