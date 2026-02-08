# DOE Enhancements - Exp_loader Capability Parity

## Overview

All 4 critical gaps have been implemented to match Original/Exp_loader functionality:

✅ **Gap 1: Folder-Based Batch Mapping**
✅ **Gap 2: Scan-Path Derived Cell/Sample Assignment**
✅ **Gap 3: Factor Columns in Matched Export**
✅ **Gap 4: Enhanced Sequence Number Logic**

---

## Gap 1: Folder-Based Batch Mapping

### What Was Missing
- Original: Scans folder structure, auto-assigns batch numbers
- Refactored (before): Only accepted pasted filename list

### Implementation
**Backend** ([doe.py:410-440](app/api/v1/routes/doe.py#L410-L440)):
- Added `FolderBatch` schema with `folder_path`, `file_list`, `batch_number`
- Auto-assigns batch numbers if not provided (folder index + 1)
- Detects folder from full paths in simple mode (`08-29-2025_@05-19-55/Spectrum_0001.csv`)

**Frontend** ([DoeTab.vue:520-559](frontend/src/views/experiments/DoeTab.vue#L520-L559)):
- Tab-based UI: "Simple File List" vs "Folder-Based"
- Folder-Based tab allows multiple folders with individual file lists
- Each folder has: path input, batch number input, file list textarea

### Usage Example
```
Folder 1: 08-29-2025_@05-19-55, Batch: 1
Files:
  Spectrum_0001.csv
  Spectrum_0002.csv
  ...

Folder 2: 08-29-2025_@05-39-11, Batch: 2
Files:
  Spectrum_0025.csv
  Spectrum_0026.csv
  ...
```

---

## Gap 2: Scan-Path Derived Cell/Sample Assignment

### What Was Missing
- Original: Uses `first_cell` + `scan_orientation` + plate map to derive positions
- Refactored (before): Only extracted cell from filename patterns

### Implementation
**Backend** ([doe.py:302-367](app/api/v1/routes/doe.py#L302-L367)):

**`generate_scan_path()` function:**
- **Row-wise**: A1→A2→...→A12→B1→B2→...→H12
- **Column-wise**: A1→B1→C1→...→H1→A2→B2→...→H12
- **Serpentine**: A1→A12, B12→B1, C1→C12, D12→D1, ...

**Cell/Sample Derivation** ([doe.py:519-536](app/api/v1/routes/doe.py#L519-L536)):
1. Try extracting cell from filename pattern (`[A-H][0-9]{1,2}`)
2. If not found, use scan path based on file index
3. Look up mixture_id from plate map using derived cell
4. Extract sample_id from mixture's first component

**Frontend** ([DoeTab.vue:565-600](frontend/src/views/experiments/DoeTab.vue#L565-L600)):
- Added "Scan Path Options" section
- First Cell input (e.g., "A1")
- Scan Orientation dropdown (row/column/serpentine)
- Checkboxes to enable/disable plate map and run sequence mapping

### Usage Example
```
First Cell: A1
Scan Orientation: Row-wise
Use Plate Map: ✓

Files:
  Spectrum_0001.csv → Derived: A1 → Sample: S001 (from plate map)
  Spectrum_0002.csv → Derived: A2 → Sample: S002
  Spectrum_0003.csv → Derived: A3 → Sample: S003
  ...
```

---

## Gap 3: Factor Columns in Matched Export

### What Was Missing
- Original: CSV includes dynamic factor columns (`Defocus [mm]`, `Temperature [°C]`, etc.)
- Refactored (before): Only 8 base columns (seq, filename, folder, timestamp, cell, sample_id, batch, date)

### Implementation
**Database** ([matched_acquisition.py:27](app/models/matched_acquisition.py#L27)):
```python
factor_values: Mapped[dict | None] = mapped_column(JSON)
# Stores: {"Defocus [mm]": "94", "Temperature [°C]": "25"}
```

**Factor Mapping Logic** ([doe.py:472-547](app/api/v1/routes/doe.py#L472-L547)):
1. Load run sequence with factor definitions
2. Build lookup: `{folder_path: {factor_name: factor_value}}`
3. Match file's folder to run level path
4. Store factor values in `factor_values` JSON field

**CSV Export** ([doe.py:642-701](app/api/v1/routes/doe.py#L642-L701)):
- Collects all unique factor names across acquisitions
- Builds dynamic column headers: `base_fields + sorted(factor_fields) + batch_field`
- Writes factor values for each row

**Frontend**:
- Checkbox: "Map folders to run sequence for factor values"
- When enabled, backend automatically populates factor_values

### Usage Example

**Setup:**
```
Run Sequence:
  Factor: Defocus, Level: 94 mm, Path: 08-29-2025_@05-19-55, Batch: 1
  Factor: Defocus, Level: 100 mm, Path: 08-29-2025_@05-39-11, Batch: 2
```

**Export CSV:**
```csv
seq,filename,folder,timestamp,cell,sample_id,Defocus [mm],batch
1,Spectrum_0001.csv,08-29-2025_@05-19-55,,A1,S001,94,1
2,Spectrum_0002.csv,08-29-2025_@05-19-55,,A2,S002,94,1
25,Spectrum_0025.csv,08-29-2025_@05-39-11,,A1,S001,100,2
```

---

## Gap 4: Enhanced Sequence Number Logic

### What Was Missing
- Original: Filename-number heuristic with scan plan offsets
- Refactored (before): Simple regex or idx+1 fallback

### Implementation
**Filename Number Extraction** ([doe.py:370-388](app/api/v1/routes/doe.py#L370-L388)):
```python
def extract_filename_number(filename: str) -> int | None:
    patterns = [
        r"_(\d+)\.",   # Spectrum_0002.csv → 2
        r"_(\d+)$",    # file_0002 → 2
        r"^(\d+)_",    # 0002_data.csv → 2
        r"(\d+)",      # Any digits → first match
    ]
```

**Sequence Assignment** ([doe.py:507-512](app/api/v1/routes/doe.py#L507-L512)):
1. Extract number from filename
2. Add `seq_offset` parameter
3. Fallback to `idx + 1 + seq_offset`

**Frontend** ([DoeTab.vue:586-590](frontend/src/views/experiments/DoeTab.vue#L586-L590)):
- "Sequence Offset" input field
- Default: 0
- Use case: If files start at 0001 but you want seq to start at 1, set offset=0

### Usage Example
```
Files:
  Spectrum_0002.csv → Extracted: 2, Offset: 0 → Seq: 2
  Spectrum_0003.csv → Extracted: 3, Offset: 0 → Seq: 3

With offset=10:
  Spectrum_0002.csv → Seq: 12
  Spectrum_0003.csv → Seq: 13
```

---

## Database Migrations

### Migration 1: DOE Tables
**File**: `4724968e5531_add_doe_tables_for_design_of_experiments.py`

Created 7 tables:
- `sample` - Sample metadata
- `mixture` - Mixture definitions
- `mixture_component` - Mixture components
- `factor_definition` - Sample/method factors
- `plate_well` - 96-well plate map
- `run_level` - Run sequence
- `matched_acquisition` - Auto-matched data

### Migration 2: Factor Values Field
**File**: `e9472434d5ee_add_factor_values_json_field_to_matched_acquisition.py`

Added:
- `matched_acquisition.factor_values` - JSON column for dynamic factor storage

**Status**: ✅ Both migrations applied successfully

---

## API Changes

### Updated Endpoint
**POST** `/api/v1/experiments/{id}/doe/match-acquisitions`

**Request Schema:**
```json
{
  "file_list": ["file1.csv", "file2.csv"],  // OR
  "folders": [
    {
      "folder_path": "08-29-2025_@05-19-55",
      "batch_number": 1,
      "file_list": ["Spectrum_0001.csv", "Spectrum_0002.csv"]
    }
  ],
  "first_cell": "A1",
  "scan_orientation": "row",  // "row", "column", "serpentine"
  "seq_offset": 0,
  "use_plate_map": true,
  "use_run_sequence": true
}
```

**Response:**
```json
[
  {
    "id": 1,
    "seq": 1,
    "filename": "Spectrum_0001.csv",
    "folder": "08-29-2025_@05-19-55",
    "batch": 1,
    "cell": "A1",
    "sample_id": "S001",
    "timestamp": null,
    "date": null,
    "special": null,
    "factor_values": {
      "Defocus [mm]": "94",
      "Temperature [°C]": "25"
    }
  }
]
```

### Updated Export
**GET** `/api/v1/experiments/{id}/doe/export/csv`

**Dynamic Columns:**
- Base: seq, filename, folder, timestamp, cell, sample_id
- Factor columns (sorted alphabetically)
- Batch column

**Example:**
```csv
seq,filename,folder,timestamp,cell,sample_id,Defocus [mm],Temperature [°C],batch
1,Spectrum_0001.csv,08-29-2025_@05-19-55,,A1,S001,94,25,1
```

---

## Frontend UI Changes

### Match Dialog Enhancements
**Location**: [DoeTab.vue:499-614](frontend/src/views/experiments/DoeTab.vue#L499-L614)

**New Tabs:**
1. **Simple File List** - Paste filenames, auto-detect folders from paths
2. **Folder-Based** - Define multiple folders with individual file lists

**New Options Section:**
- **First Cell** - Starting position (e.g., A1)
- **Scan Orientation** - Dropdown (row/column/serpentine)
- **Sequence Offset** - Number input (default: 0)
- **Use Plate Map** - Checkbox (default: ✓)
- **Map Folders to Run Sequence** - Checkbox (default: ✓)

---

## Comparison: Before vs After

### Before (Basic Implementation)
```python
# Only simple pattern matching
pattern = re.compile(r"(?:seq|s)?(\d+)?.*?(?:batch|b)?(\d+)?")
for filename in file_list:
    seq = extract_from_pattern(filename) or idx+1
    batch = extract_batch(filename) or None
    cell = extract_cell(filename) or None
    # factor_values = None (not supported)
    # folder = None (not supported)
    # sample_id = None (not derived)
```

### After (Exp_loader Parity)
```python
# Comprehensive matching with all enhancements
for folder_data in folders:
    for filename in folder_data.files:
        # Gap 1: Folder-based batch mapping
        batch = folder_data.batch_number

        # Gap 4: Enhanced seq extraction
        seq = extract_filename_number(filename) + seq_offset

        # Gap 2: Scan-path derived cell/sample
        cell = scan_path[idx] if use_plate_map else extract_cell(filename)
        sample_id = plate_map[cell].sample_id if cell in plate_map else None

        # Gap 3: Factor values from run sequence
        factor_values = run_sequence_map[folder_data.path]
```

---

## Verification Steps

### Test with Spike_DOE_082925 Data

1. **Import Samples** (if not already done)
2. **Create Mixtures** and assign to plate map
3. **Define Run Sequence**:
   - Factor: Defocus [mm]
   - Levels: 94, 100, 106 (map to 3 folders)

4. **Match Files** (Folder-Based):
```
Folder: 08-29-2025_@05-19-55, Batch: 1
Files: Spectrum_0001.csv → Spectrum_0024.csv

Folder: 08-29-2025_@05-39-11, Batch: 2
Files: Spectrum_0025.csv → Spectrum_0048.csv

Folder: 08-29-2025_@05-57-09, Batch: 3
Files: Spectrum_0049.csv → Spectrum_0072.csv
```

Options:
- First Cell: A1
- Scan Orientation: Row-wise
- ✓ Use Plate Map
- ✓ Map to Run Sequence

5. **Export CSV** and verify:
   - Folder column populated
   - Batch numbers: 1, 2, 3
   - Cell positions: A1-H12 pattern
   - Sample IDs from plate map
   - Defocus [mm] column with values: 94, 100, 106

---

## Files Modified

### Backend
- `models/matched_acquisition.py` - Added factor_values JSON field
- `schemas/doe.py` - Added FolderBatch, updated MatchAcquisitionsRequest
- `api/v1/routes/doe.py` - Complete rewrite of matching logic + export

### Frontend
- `views/experiments/DoeTab.vue` - Enhanced match dialog with tabs, folder support, all options

### Database
- Migration: `e9472434d5ee_add_factor_values_json_field_to_matched_acquisition.py`

---

## Summary

The Refactored DOE implementation now has **full capability parity** with Original/Exp_loader:

✅ Folder-based batch organization
✅ Scan-path cell derivation with plate map lookup
✅ Factor values in matched data and CSV export
✅ Intelligent sequence number extraction

**Result**: Can now process Spike_DOE_082925 data exactly like Exp_loader, with matching CSV output format including all factor columns.
