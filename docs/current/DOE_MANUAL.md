# Design of Experiments (DOE) - Comprehensive Manual

## Overview

This manual documents the DOE capabilities implemented in the Refactored codebase, with examples paralleling the Original/Exp_loader functionality. Each section includes verification steps to test the implementation.

---

## Table of Contents

1. [Sample Database Management](#1-sample-database-management)
2. [Mixture Creation](#2-mixture-creation)
3. [96-Well Plate Mapping](#3-96-well-plate-mapping)
4. [Experimental Factors](#4-experimental-factors)
5. [Run Sequence Management](#5-run-sequence-management)
6. [Acquisition File Matching](#6-acquisition-file-matching)
7. [DOE Design Export](#7-doe-design-export)

---

## 1. Sample Database Management

### Original Implementation
**File**: `Original/Exp_loader/app/routes.py` (lines 84-226)

**Original Capability**:
```python
# Load samples.csv with columns: sample_id, name, type, brand, cas, active
# Filter samples by type, brand, active status
# Faceted search with autocomplete
```

**Sample Data Format** (Original):
```csv
sample_id,name,type,brand,cas,active
S001,Methanol,Solvent,Sigma-Aldrich,67-56-1,true
S002,Ethanol,Solvent,Fisher,64-17-5,true
S003,Acetone,Solvent,Sigma-Aldrich,67-64-1,true
S004,Benzene,Standard,Acros,71-43-2,true
S005,Toluene,Standard,Sigma-Aldrich,108-88-3,false
```

### Refactored Implementation

**Backend Endpoint**: `POST /api/v1/experiments/{experiment_id}/doe/samples/import`

**Frontend**: Experiments → DOE Tab → Sample Database → "Import CSV"

### Verification Steps

#### Test 1.1: Import Sample Database

**Step 1**: Create test CSV data
```csv
sample_id,name,type,brand,cas_number,active
S001,Methanol,Solvent,Sigma-Aldrich,67-56-1,true
S002,Ethanol,Solvent,Fisher,64-17-5,true
S003,Acetone,Solvent,Sigma-Aldrich,67-64-1,true
S004,Benzene,Standard,Acros,71-43-2,true
S005,Toluene,Standard,Sigma-Aldrich,108-88-3,false
S006,Water,Solvent,Fisher,7732-18-5,true
S007,Hexane,Solvent,Acros,110-54-3,true
S008,Naphthalene,Standard,Sigma-Aldrich,91-20-3,true
```

**Step 2**: Via GUI
1. Navigate to **Experiments** tab
2. Select or create an experiment
3. Go to **DOE** tab
4. Click **"Import CSV"** button
5. Paste the CSV data above
6. Click **"Import"**

**Expected Result**:
- ✅ Success toast: "Imported 8 samples"
- ✅ DataTable shows 8 rows
- ✅ Columns: Sample ID, Name, Type, Brand, CAS Number, Active
- ✅ Active samples show green "Active" tag
- ✅ Inactive (Toluene) shows red "Inactive" tag

**Step 3**: Via API (curl verification)
```bash
curl -X POST "http://localhost:8000/api/v1/experiments/1/doe/samples/import" \
  -H "Content-Type: application/json" \
  -d '{
    "csv_data": "sample_id,name,type,brand,cas_number,active\nS001,Methanol,Solvent,Sigma,67-56-1,true"
  }'
```

**Expected API Response**:
```json
[
  {
    "id": 1,
    "experiment_id": 1,
    "sample_id": "S001",
    "name": "Methanol",
    "type": "Solvent",
    "brand": "Sigma",
    "cas_number": "67-56-1",
    "active": true,
    "notes": null,
    "created_at": "2026-01-04T..."
  }
]
```

#### Test 1.2: List Samples

**Via API**:
```bash
curl "http://localhost:8000/api/v1/experiments/1/doe/samples"
```

**Expected**: JSON array of all imported samples

**Comparison with Original**:
- Original: `GET /api/samples?type=Solvent` filters by type
- Refactored: `GET /experiments/1/doe/samples` returns all samples (filtering on frontend)

---

## 2. Mixture Creation

### Original Implementation
**File**: `Original/Exp_loader/app/models.py` (lines 18-24)

**Original Data Model**:
```python
class RackMixture(BaseModel):
    mixture_id: str
    name: Optional[str] = None
    basis: Literal["volume", "mass"] = "volume"
    components: List[MixtureComponent]
    notes: Optional[str] = None

class MixtureComponent(BaseModel):
    sample_id: str
    amount: float
    unit: str  # volume: mL/uL/µL; mass: g/mg/ug/µg
```

### Refactored Implementation

**Backend Endpoint**: `POST /api/v1/experiments/{experiment_id}/doe/mixtures`

**Frontend**: Experiments → DOE Tab → Mixtures → "Create Mixture"

### Verification Steps

#### Test 2.1: Create Volume-Based Mixture

**Step 1**: Via GUI
1. Go to **DOE** tab → **Mixtures** section
2. Click **"Create Mixture"** button
3. Fill in form:
   - **Mixture ID**: `MIX001`
   - **Name**: `Methanol-Ethanol 50:50`
   - **Basis**: `Volume`
4. Click **"Add Component"** twice
5. Component 1: Select `Methanol`, Amount: `5.0`, Unit: `mL`
6. Component 2: Select `Ethanol`, Amount: `5.0`, Unit: `mL`
7. Click **"Create"**

**Expected Result**:
- ✅ Success toast: "Mixture created successfully"
- ✅ Mixture appears in DataTable
- ✅ Shows "2 component(s)"
- ✅ Basis tag shows "volume"

**Step 2**: Via API
```bash
curl -X POST "http://localhost:8000/api/v1/experiments/1/doe/mixtures" \
  -H "Content-Type: application/json" \
  -d '{
    "mixture_id": "MIX002",
    "name": "Acetone-Water 70:30",
    "basis": "volume",
    "components": [
      {"sample_id": 3, "amount": 7.0, "unit": "mL"},
      {"sample_id": 6, "amount": 3.0, "unit": "mL"}
    ]
  }'
```

**Expected Response**:
```json
{
  "id": 2,
  "experiment_id": 1,
  "mixture_id": "MIX002",
  "name": "Acetone-Water 70:30",
  "basis": "volume",
  "components": [
    {"id": 1, "mixture_id": 2, "sample_id": 3, "amount": 7.0, "unit": "mL"},
    {"id": 2, "mixture_id": 2, "sample_id": 6, "amount": 3.0, "unit": "mL"}
  ],
  "created_at": "..."
}
```

#### Test 2.2: Create Mass-Based Mixture

**Via GUI**:
1. Create mixture with **Basis**: `Mass`
2. Components with units: `g`, `mg`

**Expected**: Mass-basis mixtures work identically

**Comparison with Original**:
- Original: Mixtures stored in XML under `<rack>` element
- Refactored: Mixtures stored in SQL database, linked to experiment

---

## 3. 96-Well Plate Mapping

### Original Implementation
**File**: `Original/Exp_loader/app/models.py` (lines 58-69)

**Original Data Model**:
```python
class PlacementInfo(BaseModel):
    protocol: Optional[str] = None
    plate_map: Dict[str, str] = Field(default_factory=dict)  # well -> mixture_id
    # ... includes BLANK
```

**Original UI**: JavaScript-based 96-well grid with drag-drop

### Refactored Implementation

**Backend Endpoint**: `POST /api/v1/experiments/{experiment_id}/doe/plate-map`

**Frontend**: Experiments → DOE Tab → 96-Well Plate Map

### Verification Steps

#### Test 3.1: Assign Mixtures to Wells

**Step 1**: Create test mixtures (if not done)
- Create at least 3 mixtures (MIX001, MIX002, MIX003)

**Step 2**: Via GUI
1. Go to **DOE** tab → **96-Well Plate Map** section
2. Select mixture from dropdown: `MIX001`
3. Click wells: `A1`, `A2`, `A3`
4. Select mixture: `MIX002`
5. Click wells: `B1`, `B2`, `B3`
6. Select mixture: `MIX003`
7. Click wells: `C1`, `C2`, `C3`

**Expected Result**:
- ✅ Wells show blue background when assigned
- ✅ Well labels show mixture ID (e.g., "Mix 1")
- ✅ Toast confirmation: "Mixture assigned to A1"
- ✅ Stats update: "Assigned Wells: 9 / 96"
- ✅ Legend shows assigned vs empty

**Step 3**: Verify plate map layout
- Rows: A-H (8 rows)
- Columns: 1-12 (12 columns)
- Total: 96 wells
- Wells clickable with hover effect

**Step 4**: Via API
```bash
curl -X POST "http://localhost:8000/api/v1/experiments/1/doe/plate-map" \
  -H "Content-Type: application/json" \
  -d '{
    "wells": [
      {"well_position": "A1", "mixture_id": 1},
      {"well_position": "A2", "mixture_id": 1},
      {"well_position": "B1", "mixture_id": 2},
      {"well_position": "B2", "mixture_id": 2}
    ]
  }'
```

**Expected Response**: Array of plate wells with assignments

#### Test 3.2: Clear Plate Map

**Via GUI**:
1. Click **"Clear Plate"** button
2. Confirm in dialog (if prompted)

**Expected**:
- ✅ All wells return to white/empty state
- ✅ Stats show: "Assigned Wells: 0 / 96"

**Comparison with Original**:
- Original: Stores `plate_map: {"A1": "mix_01", "BLANK": "B12"}`
- Refactored: Stores in `plate_well` table with mixture foreign keys

---

## 4. Experimental Factors

### Original Implementation
**File**: `Original/Exp_loader/app/models.py` (lines 43-49)

**Original Data Model**:
```python
class FactorDef(BaseModel):
    name: str
    scope: Literal["sample", "method"]
    type: Literal["categorical", "numeric"]
    unit: Optional[str] = None
    levels: Optional[List[str]] = None
```

**Original Example**:
```json
{
  "sample_defs": [
    {"name": "Temperature", "scope": "sample", "type": "numeric", "unit": "°C", "levels": ["25", "50", "75"]},
    {"name": "Concentration", "scope": "sample", "type": "numeric", "unit": "ppm", "levels": ["100", "500", "1000"]}
  ],
  "method_defs": [
    {"name": "Scan_Type", "scope": "method", "type": "categorical", "levels": ["transmission", "ATR"]},
    {"name": "Resolution", "scope": "method", "type": "categorical", "levels": ["standard", "high"]}
  ]
}
```

### Refactored Implementation

**Backend Endpoint**: `POST /api/v1/experiments/{experiment_id}/doe/factors`

**Frontend**: Experiments → DOE Tab → Experimental Factors → "Add Factor"

### Verification Steps

#### Test 4.1: Create Sample Factor

**Step 1**: Via GUI
1. Go to **DOE** tab → **Experimental Factors** section
2. Click **"Add Factor"** button
3. Fill in form:
   - **Factor Name**: `Temperature`
   - **Scope**: `Sample`
   - **Type**: `Numeric`
   - **Unit**: `°C`
   - **Levels**: `25, 50, 75, 100`
4. Click **"Add"**

**Expected Result**:
- ✅ Factor appears in **Sample Factors** table
- ✅ Type tag shows "numeric"
- ✅ Levels column shows "4"

**Step 2**: Create another sample factor
- **Name**: `Concentration`
- **Scope**: `Sample`
- **Type**: `Numeric`
- **Unit**: `ppm`
- **Levels**: `100, 500, 1000`

#### Test 4.2: Create Method Factor

**Via GUI**:
1. Click **"Add Factor"**
2. **Name**: `Scan_Type`
3. **Scope**: `Method`
4. **Type**: `Categorical`
5. **Levels**: `transmission, ATR, reflection`

**Expected**: Appears in **Method Factors** table

**Step 3**: Via API
```bash
curl -X POST "http://localhost:8000/api/v1/experiments/1/doe/factors" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Resolution",
    "scope": "method",
    "type": "categorical",
    "levels": ["standard", "high", "ultra"]
  }'
```

**Expected Response**:
```json
{
  "id": 4,
  "experiment_id": 1,
  "name": "Resolution",
  "scope": "method",
  "type": "categorical",
  "unit": null,
  "levels": ["standard", "high", "ultra"]
}
```

#### Test 4.3: Verify Factor Separation

**Expected Display**:
- **Sample Factors** table shows: Temperature, Concentration
- **Method Factors** table shows: Scan_Type, Resolution
- Each in separate columns (two-column grid layout)

**Comparison with Original**:
- Original: Factors stored in XML under `<sample_defs>` and `<method_defs>`
- Refactored: Factors stored in `factor_definition` table with `scope` field

---

## 5. Run Sequence Management

### Original Implementation
**File**: `Original/Exp_loader/app/models.py` (lines 25-29, 62-63)

**Original Data Model**:
```python
class RunLevel(BaseModel):
    value: str
    path: Optional[str] = None
    batch: Optional[int] = None
    fileCount: Optional[int] = None

# In PlacementInfo:
run_sequence: Dict[str, List[RunLevel]] = Field(default_factory=dict)
# Example: {"Defocus": [{"value": "94", "path": "RunA", "batch": 1, "fileCount": 24}, ...]}
```

**Original Example**:
```json
{
  "run_sequence": {
    "Scan_Type": [
      {"value": "transmission", "path": "Transmission_Run", "batch": 1, "fileCount": 96},
      {"value": "ATR", "path": "ATR_Run", "batch": 2, "fileCount": 96}
    ],
    "Resolution": [
      {"value": "standard", "path": "Std_Res", "batch": 1, "fileCount": 48},
      {"value": "high", "path": "High_Res", "batch": 2, "fileCount": 48}
    ]
  }
}
```

### Refactored Implementation

**Backend Endpoint**: `POST /api/v1/experiments/{experiment_id}/doe/run-sequence`

**Frontend**: Experiments → DOE Tab → Run Sequence → "Add Run Level"

### Verification Steps

#### Test 5.1: Create Run Sequence

**Prerequisites**: Must have created method factors (Test 4.2)

**Step 1**: Add first run level via GUI
1. Go to **DOE** tab → **Run Sequence** section
2. Click **"Add Run Level"**
3. Fill in form:
   - **Factor**: Select `Scan_Type`
   - **Level Value**: `transmission`
   - **Folder Path**: `Transmission_Run`
   - **Batch Number**: `1`
   - **File Count**: `96`
   - **Sequence Order**: `0`
4. Click **"Add"**

**Expected Result**:
- ✅ Run level appears in DataTable
- ✅ Columns show: #, Level Value, Folder Path, Batch, File Count

**Step 2**: Add more run levels
```
Factor: Scan_Type, Value: ATR, Path: ATR_Run, Batch: 2, Files: 96, Order: 1
Factor: Resolution, Value: standard, Path: Std_Res, Batch: 1, Files: 48, Order: 2
Factor: Resolution, Value: high, Path: High_Res, Batch: 2, Files: 48, Order: 3
```

**Step 3**: Via API (Bulk create)
```bash
curl -X POST "http://localhost:8000/api/v1/experiments/1/doe/run-sequence" \
  -H "Content-Type: application/json" \
  -d '{
    "levels": [
      {
        "factor_definition_id": 3,
        "level_value": "transmission",
        "path": "Transmission_Run",
        "batch": 1,
        "file_count": 96,
        "sequence_order": 0
      },
      {
        "factor_definition_id": 3,
        "level_value": "ATR",
        "path": "ATR_Run",
        "batch": 2,
        "file_count": 96,
        "sequence_order": 1
      }
    ]
  }'
```

**Expected Response**: Array of created run levels

#### Test 5.2: Verify Sequence Order

**Expected**: DataTable sorted by **sequence_order** ascending (0, 1, 2, 3, ...)

**Comparison with Original**:
- Original: Run sequence grouped by factor name in dictionary
- Refactored: Run levels stored in `run_level` table with `factor_definition_id` and `sequence_order`

---

## 6. Acquisition File Matching

### Original Implementation
**File**: `Original/Exp_loader/app/models.py` (lines 32-41), `Original/Exp_loader/app/static/app_c.js` (lines 692-704)

**Original Data Model**:
```python
class MatchedRow(BaseModel):
    seq: Optional[int] = None
    filename: Optional[str] = None
    folder: Optional[str] = None
    timestamp: Optional[int] = None
    date: Optional[str] = None
    batch: Optional[int] = None
    sample_id: Optional[str] = None
    cell: Optional[str] = None
    special: Optional[str] = None
```

**Original Matching Logic**: JavaScript pattern matching on filename strings

### Refactored Implementation

**Backend Endpoint**: `POST /api/v1/experiments/{experiment_id}/doe/match-acquisitions`

**Auto-Match Algorithm** (`app/api/v1/routes/doe.py`, lines 371-408):
```python
# Pattern: extracts seq, batch, timestamp, cell from filenames
# e.g., "Batch1_A1_20240101_123456.csv" → seq=1, batch=1, cell=A1, timestamp=...
pattern = re.compile(r"(?:seq|s)?(\d+)?.*?(?:batch|b)?(\d+)?.*?(\d{6,})?", re.IGNORECASE)
cell_pattern = re.compile(r"([A-H][0-9]{1,2})", re.IGNORECASE)
```

### Verification Steps

#### Test 6.1: Auto-Match Acquisition Files

**Step 1**: Prepare test filename list
```
Batch1_A1_seq001_20260104_120000.csv
Batch1_A2_seq002_20260104_120100.csv
Batch1_A3_seq003_20260104_120200.csv
Batch1_B1_seq004_20260104_120300.csv
Batch1_B2_seq005_20260104_120400.csv
Batch2_C1_seq006_20260104_130000.csv
Batch2_C2_seq007_20260104_130100.csv
Batch2_C3_seq008_20260104_130200.csv
```

**Step 2**: Via GUI
1. Go to **DOE** tab → **Acquisition Matching** section
2. Click **"Auto-Match Files"** button
3. Paste filename list (one per line)
4. Optional: Set **First Cell**: `A1`
5. Optional: Set **Scan Orientation**: `Row-wise`
6. Click **"Match Files"**

**Expected Result**:
- ✅ Success toast: "Matched 8 acquisitions"
- ✅ DataTable shows 8 rows
- ✅ Columns populated:
  - **Seq**: 1, 2, 3, 4, 5, 6, 7, 8 (extracted from filenames)
  - **Filename**: Full filename
  - **Batch**: 1, 1, 1, 1, 1, 2, 2, 2 (extracted from "Batch1", "Batch2")
  - **Cell**: A1, A2, A3, B1, B2, C1, C2, C3 (extracted from pattern)
  - **Timestamp**: Extracted if present
  - **Date**: Derived from timestamp

#### Test 6.2: Test Different Filename Patterns

**Pattern Variations**:
```
# Seq-based
seq001_sample_A1.dat
s002_sample_A2.dat

# Batch-based
b1_well_A1_data.csv
batch2_well_A2_data.csv

# Timestamp-based
20260104120000_A1.csv
file_20260104120100_A2.csv

# Combined
Batch1_seq001_A1_20260104.csv
B2_s002_C3_timestamp.dat
```

**Via API**:
```bash
curl -X POST "http://localhost:8000/api/v1/experiments/1/doe/match-acquisitions" \
  -H "Content-Type: application/json" \
  -d '{
    "file_list": [
      "Batch1_A1_seq001.csv",
      "Batch1_A2_seq002.csv",
      "Batch2_B1_seq003.csv"
    ],
    "first_cell": "A1",
    "scan_orientation": "row"
  }'
```

**Expected Response**:
```json
[
  {
    "id": 1,
    "experiment_id": 1,
    "seq": 1,
    "filename": "Batch1_A1_seq001.csv",
    "folder": null,
    "timestamp": null,
    "date": null,
    "batch": 1,
    "sample_id": null,
    "cell": "A1",
    "special": null
  },
  ...
]
```

#### Test 6.3: Edge Cases

**Test filenames without patterns**:
```
unknown_file.csv
data.txt
measurement_001.dat
```

**Expected**: Sequential seq assignment (1, 2, 3), null values for batch/cell

**Comparison with Original**:
- Original: JavaScript regex matching in frontend
- Refactored: Python regex matching in backend with more robust pattern detection

---

## 7. DOE Design Export

### Original Implementation
**File**: `Original/Exp_loader/app/routes.py` (lines 400+)

**Original Export Formats**:
- CSV: Matched acquisitions export
- XML: Full experiment export with mixtures, factors, acquisitions
- JSON: Not implemented in Original

**Original CSV Format**:
```csv
seq,filename,folder,batch,sample_id,cell,timestamp,date
1,file1.csv,RunA,1,S001,A1,1609459200,2021-01-01
2,file2.csv,RunA,1,S002,A2,1609459300,2021-01-01
```

**Original XML Format**:
```xml
<experiment>
  <experiment_id>exp_001</experiment_id>
  <mixtures>
    <mixture>
      <mixture_id>mix_01</mixture_id>
      <components>...</components>
    </mixture>
  </mixtures>
  <factors>...</factors>
  <matched_acquisitions>...</matched_acquisitions>
</experiment>
```

### Refactored Implementation

**Backend Endpoints**:
- `GET /api/v1/experiments/{experiment_id}/doe/export/csv`
- `GET /api/v1/experiments/{experiment_id}/doe/export/json`
- `GET /api/v1/experiments/{experiment_id}/doe/export/xml`

**Frontend**: Experiments → DOE Tab → Export DOE Design → "Export CSV/JSON/XML"

### Verification Steps

#### Test 7.1: Export as CSV

**Prerequisites**: Must have matched acquisitions (Test 6.1)

**Step 1**: Via GUI
1. Go to **DOE** tab → **Export DOE Design** section
2. Click **"Export CSV"** button

**Expected Result**:
- ✅ Browser downloads file: `doe_export.csv`
- ✅ File contains matched acquisitions
- ✅ Columns: seq, filename, folder, batch, sample_id, cell, timestamp, date

**Step 2**: Verify CSV content
```bash
cat doe_export.csv
```

**Expected Output**:
```csv
seq,filename,folder,batch,sample_id,cell,timestamp,date
1,Batch1_A1_seq001_20260104_120000.csv,,1,,A1,20260104120000,2026-01-04
2,Batch1_A2_seq002_20260104_120100.csv,,1,,A2,20260104120100,2026-01-04
...
```

**Step 3**: Via API
```bash
curl "http://localhost:8000/api/v1/experiments/1/doe/export/csv" -o doe_export.csv
```

#### Test 7.2: Export as JSON

**Via GUI**:
1. Click **"Export JSON"** button

**Expected Result**:
- ✅ Downloads: `doe_export.json`
- ✅ Contains all DOE data: samples, mixtures, factors, plate_map, run_sequence, matched_acquisitions

**Verify JSON structure**:
```bash
cat doe_export.json | python -m json.tool
```

**Expected Output**:
```json
{
  "experiment_id": 1,
  "exported_at": "2026-01-04T12:00:00",
  "samples": [
    {"id": 1, "sample_id": "S001", "name": "Methanol", ...}
  ],
  "mixtures": [
    {"id": 1, "mixture_id": "MIX001", "components": [...]}
  ],
  "factors": [
    {"id": 1, "name": "Temperature", "scope": "sample", ...}
  ],
  "plate_map": [
    {"well_position": "A1", "mixture_id": 1}
  ],
  "run_sequence": [
    {"level_value": "transmission", "path": "Transmission_Run", ...}
  ],
  "matched_acquisitions": [
    {"seq": 1, "filename": "...", "batch": 1, ...}
  ]
}
```

#### Test 7.3: Export as XML

**Via GUI**:
1. Click **"Export XML"** button

**Expected Result**:
- ✅ Downloads: `doe_export.xml`
- ✅ XML structure matches Original format

**Verify XML structure**:
```bash
cat doe_export.xml
```

**Expected Output**:
```xml
<?xml version="1.0" ?>
<experiment id="1">
  <samples>
    <sample id="S001">
      <name>Methanol</name>
      <type>Solvent</type>
      <brand>Sigma-Aldrich</brand>
    </sample>
  </samples>
  <mixtures>
    <mixture id="MIX001">
      <basis>volume</basis>
      <components>
        <component>
          <amount>5.0</amount>
          <unit>mL</unit>
        </component>
      </components>
    </mixture>
  </mixtures>
  <factors>
    <factor>
      <name>Temperature</name>
      <scope>sample</scope>
      <type>numeric</type>
    </factor>
  </factors>
  <matched_acquisitions>
    <acquisition>
      <seq>1</seq>
      <filename>...</filename>
      <batch>1</batch>
    </acquisition>
  </matched_acquisitions>
</experiment>
```

#### Test 7.4: Verify Export Completeness

**Check export includes all sections**:
```bash
# JSON export should have all keys
jq 'keys' doe_export.json
# Expected: ["experiment_id", "exported_at", "samples", "mixtures", "factors", "plate_map", "run_sequence", "matched_acquisitions"]

# Count items
jq '.samples | length' doe_export.json  # Should match imported count
jq '.mixtures | length' doe_export.json
jq '.matched_acquisitions | length' doe_export.json
```

**Comparison with Original**:
- Original: CSV exports acquisitions only, XML exports full experiment
- Refactored: CSV exports acquisitions, JSON exports everything, XML exports structured data

---

## 8. DOE Summary Statistics

### Refactored Enhancement (Not in Original)

**Backend Endpoint**: `GET /api/v1/experiments/{experiment_id}/doe/summary`

**Frontend**: Experiments → DOE Tab → Export section → Summary cards

### Verification Steps

#### Test 8.1: View Summary Statistics

**Via GUI**:
1. Go to **DOE** tab → **Export DOE Design** section
2. View summary cards at bottom

**Expected Display**:
```
┌─────────────┬─────────────┬─────────────┐
│ 📊 Samples  │ 🧪 Mixtures │ 📋 Wells    │
│     8       │     3       │     9       │
├─────────────┼─────────────┼─────────────┤
│ ⚙️  Factors │ 📝 Runs     │ ✅ Matched  │
│     4       │     4       │     8       │
└─────────────┴─────────────┴─────────────┘
```

**Via API**:
```bash
curl "http://localhost:8000/api/v1/experiments/1/doe/summary"
```

**Expected Response**:
```json
{
  "sample_count": 8,
  "mixture_count": 3,
  "factor_count": 4,
  "well_count": 9,
  "run_level_count": 4,
  "matched_count": 8
}
```

---

## Complete End-to-End Workflow Test

### Scenario: Multi-Factor Solvent Study

**Objective**: Design experiment with 3 solvents, 3 temperatures, 2 scan types = 18 total measurements

#### Step 1: Import Samples
```csv
sample_id,name,type,brand,cas_number,active
S001,Methanol,Solvent,Sigma,67-56-1,true
S002,Ethanol,Solvent,Fisher,64-17-5,true
S003,Acetone,Solvent,Sigma,67-64-1,true
```

#### Step 2: Create Mixtures
- MIX001: Pure Methanol (10 mL)
- MIX002: Pure Ethanol (10 mL)
- MIX003: Pure Acetone (10 mL)

#### Step 3: Assign Plate Map
```
A1-A6: MIX001
B1-B6: MIX002
C1-C6: MIX003
```

#### Step 4: Define Factors
**Sample Factors**:
- Temperature: 25, 50, 75 (°C)

**Method Factors**:
- Scan_Type: transmission, ATR

#### Step 5: Create Run Sequence
```
Order 0: transmission, Batch 1, Files 9
Order 1: ATR, Batch 2, Files 9
```

#### Step 6: Match Files
```
Batch1_A1_25C_trans.csv
Batch1_A2_50C_trans.csv
Batch1_A3_75C_trans.csv
Batch1_B1_25C_trans.csv
... (9 transmission files)
Batch2_A1_25C_ATR.csv
Batch2_A2_50C_ATR.csv
... (9 ATR files)
```

#### Step 7: Export Design
- Export JSON with complete DOE configuration
- Use for downstream analysis

**Expected Final Summary**:
- Samples: 3
- Mixtures: 3
- Wells: 18
- Factors: 2 (1 sample + 1 method)
- Run Levels: 2
- Matched: 18

---

## Comparison Matrix: Original vs Refactored

| Feature | Original | Refactored | Status |
|---------|----------|------------|--------|
| Sample DB Import | CSV file upload | CSV paste import | ✅ |
| Sample Storage | In-memory Pandas DataFrame | SQL database | ✅ Enhanced |
| Mixture Creation | XML storage | SQL with components | ✅ |
| Plate Mapping | JSON dict in XML | SQL table (96 wells) | ✅ |
| Factor Definitions | JSON arrays in XML | SQL table with types | ✅ |
| Run Sequence | Nested dict in XML | SQL table with order | ✅ |
| File Matching | Frontend JS regex | Backend Python regex | ✅ Enhanced |
| Export CSV | Acquisitions only | Acquisitions only | ✅ |
| Export XML | Full experiment | Structured data | ✅ |
| Export JSON | Not available | Full DOE config | ✅ New |
| Summary Stats | Not available | Real-time counts | ✅ New |
| Plate Visualization | Custom JS grid | Vue component | ✅ Enhanced |
| Multi-tenancy | Single experiment | Per-experiment isolation | ✅ New |

---

## Testing Checklist

- [ ] Test 1.1: Import sample database (8 samples)
- [ ] Test 1.2: List samples via API
- [ ] Test 2.1: Create volume-based mixture
- [ ] Test 2.2: Create mass-based mixture
- [ ] Test 3.1: Assign mixtures to plate wells
- [ ] Test 3.2: Clear plate map
- [ ] Test 4.1: Create sample factor
- [ ] Test 4.2: Create method factor
- [ ] Test 4.3: Verify factor separation
- [ ] Test 5.1: Create run sequence
- [ ] Test 5.2: Verify sequence order
- [ ] Test 6.1: Auto-match acquisition files
- [ ] Test 6.2: Test different filename patterns
- [ ] Test 6.3: Test edge cases (no patterns)
- [ ] Test 7.1: Export as CSV
- [ ] Test 7.2: Export as JSON
- [ ] Test 7.3: Export as XML
- [ ] Test 7.4: Verify export completeness
- [ ] Test 8.1: View summary statistics
- [ ] Complete end-to-end workflow

---

## Troubleshooting

### Issue: "No experiment selected"
**Solution**: Select an experiment in Overview tab before accessing DOE tab

### Issue: "Import failed"
**Solution**: Check CSV format, ensure headers match: `sample_id,name,type,brand,cas_number,active`

### Issue: "Can't create mixture"
**Solution**: Import samples first before creating mixtures

### Issue: "Can't add run level"
**Solution**: Create method factors first

### Issue: "Export disabled"
**Solution**: Must have matched acquisitions before exporting

---

## API Reference Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/experiments/{id}/doe/samples/import` | POST | Import samples from CSV |
| `/experiments/{id}/doe/samples` | GET | List samples |
| `/experiments/{id}/doe/mixtures` | GET | List mixtures |
| `/experiments/{id}/doe/mixtures` | POST | Create mixture |
| `/experiments/{id}/doe/factors` | GET | List factors |
| `/experiments/{id}/doe/factors` | POST | Create factor |
| `/experiments/{id}/doe/plate-map` | GET | Get plate map |
| `/experiments/{id}/doe/plate-map` | POST | Set plate map |
| `/experiments/{id}/doe/run-sequence` | GET | Get run sequence |
| `/experiments/{id}/doe/run-sequence` | POST | Set run sequence |
| `/experiments/{id}/doe/match-acquisitions` | POST | Auto-match files |
| `/experiments/{id}/doe/matched-acquisitions` | GET | Get matched data |
| `/experiments/{id}/doe/export/csv` | GET | Export CSV |
| `/experiments/{id}/doe/export/json` | GET | Export JSON |
| `/experiments/{id}/doe/export/xml` | GET | Export XML |
| `/experiments/{id}/doe/summary` | GET | Get summary stats |
