# Frontend-Backend Parameter Mapping

This document maps all workflow node parameters between frontend and backend to ensure validation and execution work correctly.

## Critical Information

⚠️ **IMPORTANT**: When validation fails with "parameter X is required" even though you entered a value, check this document to see if there's a parameter name mismatch.

The frontend uses user-friendly parameter names (e.g., `window`, `components`), while the backend uses library-specific names (e.g., `size`, `n_components`). The mapping is defined in:

```
frontend/src/stores/workflow.ts → PARAM_NAME_MAP
```

## Nodes with Parameter Mappings

### 1. Smoothing Nodes

#### SMOOTH (smooth.savitzky_golay)
- **Frontend → Backend**:
  - `window` → `size` (Window size for S-G filter)
  - `poly` → `order` (Polynomial order)
- **Status**: ✅ Mapped in PARAM_NAME_MAP

#### DERIV_1 (derivative.first)
- **Frontend → Backend**:
  - `window` → `size` (Window size for derivative)
  - `poly` → `order` (Polynomial order)
- **Status**: ✅ Mapped in PARAM_NAME_MAP

#### DERIV_2 (derivative.second)
- **Frontend → Backend**:
  - `window` → `size` (Window size for derivative)
  - `poly` → `order` (Polynomial order)
- **Status**: ✅ Mapped in PARAM_NAME_MAP

### 2. Component Analysis Nodes

#### PCA (model.pca)
- **Frontend → Backend**:
  - `components` → `n_components`
- **Status**: ✅ Mapped in PARAM_NAME_MAP

#### PLS (model.pls)
- **Frontend → Backend**:
  - `components` → `n_components`
- **Status**: ✅ Mapped in PARAM_NAME_MAP

#### MCR (model.mcr_als)
- **Frontend → Backend**:
  - `components` → `n_components`
- **Status**: ✅ Mapped in PARAM_NAME_MAP

#### EFA (model.efa)
- **Frontend → Backend**:
  - `components` → `n_components`
- **Status**: ✅ Mapped in PARAM_NAME_MAP

#### SIMPLISMA (model.simplisma)
- **Frontend → Backend**:
  - `components` → `n_components`
- **Status**: ✅ Mapped in PARAM_NAME_MAP

## Nodes WITHOUT Parameter Mappings

These nodes use consistent parameter names between frontend and backend (snake_case throughout):

### Data Nodes
- **DATA** (data.source): `experiment_id`, `file_path`, `source`, `transpose_on_load`, etc.
- **FILE_LOAD** (data.file_load): `experiment_id`, `file_id`, `stage`
- **NIST_LIBRARY** (data.nist_library): `library_id`, `compound_name`
- **SYNTHETIC_CURVE** (data.synthetic_curve): `curve_type`, `n_points`, `max_concentration`, `center`, `width`

### Preprocessing Nodes
- **BASELINE** (baseline.als): `lam`, `p`
- **BASELINE_RB** (baseline.rubberband): `ranges`
- **NORMALIZE** (normalize.snv): (no parameters)
- **SCALE** (normalize.scale): `method`
- **MSC** (normalize.msc): `reference`
- **COSMIC_RAY** (preprocess.cosmic_ray): `window`, `zscore`
- **CLIP_RANGE** (preprocess.clip_range): `min_wavenumber`, `max_wavenumber`
- **CLIP_FLOOR** (preprocess.clip_floor): `floor`
- **WAVENUMBER_ALIGN** (preprocess.wavenumber_align): `method`, `merge_tolerance`
- **SCALE_MAX** (preprocess.scale_max): `target_max`
- **CENTER_MEAN** (preprocess.center_mean): (no parameters)

### Modeling Nodes
- **LINEAR_REGRESSION** (model.linear_regression): `fit_intercept`

### Synthesis/Blend Nodes
- **BLEND** (synthesis.blend): `n_timepoints`, `model_type`, `pathlength`, `noise_level`, `species_config`
- **SPECIES** (synthesis.species): `species_name`, `molar_absorptivity`
- **MERGE_SPECTRA** (synthesis.merge): `align_wavenumbers`

### Output Nodes
- **PLOT** (output.plot): `plot_type`, `x_axis`, `y_axis`
- **CONTOUR_PLOT** (output.contour): `colorscale`, `plot_type`, `reverse_x`, `transpose`
- **EXPORT** (output.export): `filename`, `format`
- **STATS** (stats.summary): `compute_outliers`, `outlier_threshold`, `max_samples`

## How Parameter Mapping Works

### 1. Validation (Frontend)
When validating node parameters, the system:
1. Takes frontend parameter names from the UI (e.g., `window`, `poly`)
2. Maps them to backend names using `PARAM_NAME_MAP` (e.g., `size`, `order`)
3. Validates against backend metadata
4. Converts any errors back to frontend parameter names for display

**Code Location**: `frontend/src/stores/workflow.ts` → `validateNodeParams()`

### 2. Execution (Backend Communication)
When sending workflow to backend for execution:
1. Frontend parameters are mapped to backend names
2. Backend receives parameters with correct names
3. Backend nodes execute with expected parameter names

**Code Location**: `frontend/src/stores/workflow.ts` → `mapParamsToBackend()`

### 3. Loading Workflows (Backend → Frontend)
When loading saved workflows from backend:
1. Backend returns parameters with backend names
2. Frontend maps them to UI names for display
3. User sees familiar parameter names in UI

**Code Location**: `frontend/src/stores/workflow.ts` → `mapParamsFromBackend()`

## Adding New Nodes with Custom Parameter Names

If you need to add a new node with different frontend/backend parameter names:

### Step 1: Add mapping to PARAM_NAME_MAP
```typescript
// In frontend/src/stores/workflow.ts
export const PARAM_NAME_MAP: Record<string, Record<string, string>> = {
  // ... existing mappings ...
  YOUR_NODE: {
    frontendParamName: "backend_param_name",
  },
};
```

### Step 2: Add parameter definitions
```typescript
// In WorkflowInspector.vue → getParamDefinitions()
const definitions: Record<string, any[]> = {
  // ... existing definitions ...
  YOUR_NODE: [
    { name: 'frontendParamName', label: 'Display Label', type: 'number', ... },
  ],
};
```

### Step 3: Test
1. Add node to workflow
2. Set parameters in UI
3. Verify validation works (no "parameter required" errors)
4. Execute workflow
5. Verify backend receives correct parameter names

## Troubleshooting

### "Parameter X is required" but I entered a value
**Cause**: Parameter name mismatch between frontend and backend.

**Solution**:
1. Find your node type in this document
2. Check if it has a parameter mapping
3. If missing, add it to `PARAM_NAME_MAP` in `workflow.ts`

### Validation passes but backend execution fails
**Cause**: Parameters not being mapped correctly during execution.

**Solution**:
1. Check `mapParamsToBackend()` is being called before sending to backend
2. Verify `NODE_TYPE_MAP` includes your node type
3. Check backend logs for actual parameter names received

### Parameters disappear when loading saved workflow
**Cause**: Reverse mapping (backend → frontend) not working.

**Solution**:
1. Verify `mapParamsFromBackend()` includes your mapping
2. Check that the reverse mapping is correctly constructed in that function

## Naming Conventions

### Backend (Python)
- **Convention**: `snake_case`
- **Example**: `n_components`, `max_wavenumber`, `fit_intercept`
- **Location**: `app/services/dag/nodes/`

### Frontend (TypeScript)
- **Convention**: Mixed (user-friendly names)
- **Example**: `components`, `window`, `poly`
- **Location**: `frontend/src/views/workflow-builder/WorkflowInspector.vue`

### Best Practice
When possible, use consistent names between frontend and backend to avoid needing mappings. Only use different names when the backend name is:
- Library-specific (e.g., `n_components` from scikit-learn)
- Too technical for end users (e.g., `size` → `window` is more intuitive)
- Mathematically notated (e.g., Greek letters)

## Validation System

The validation system ensures all required parameters are provided before execution:

1. **Real-time validation**: As you type in the UI
2. **Pre-execution validation**: Before "Run Trial" or workflow execution
3. **Error display**: Shows which parameters need fixing

**Key Files**:
- `frontend/src/stores/workflow.ts` → `validateNodeParams()`
- `frontend/src/views/workflow-builder/NodeDetailView.vue` → validation UI
- `frontend/src/views/workflow-builder/WorkflowInspector.vue` → validation UI

## Backend Node Parameter Reference

For complete backend parameter definitions, see:
- `app/services/dag/nodes/preprocessing.py`
- `app/services/dag/nodes/modeling.py`
- `app/services/dag/nodes/data.py`
- `app/services/dag/nodes/blend.py`
- `app/services/dag/nodes/output.py`

Each node class has a `metadata` property with `parameters` list defining all parameter names, types, min/max values, and defaults.
