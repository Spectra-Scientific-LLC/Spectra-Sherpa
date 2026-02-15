# Original → Refactored Functional Mapping

## Tab Structure Overview

```
┌─────────────────────────────────────────────────────────────┐
│ LEFT SIDEBAR (Collapsible)                                 │
├─────────────────────────────────────────────────────────────┤
│ 📊 Experiments    → Load & Check My Data                   │
│ 📚 NIST Library   → Load & Check Public Data               │
│ 🧼 Analysis       → Clean & Compare Spectra (DAG)          │
│ 🔧 Builder        → Create Synthetic Datasets              │
│ 📏 Calibrations   → Calibrate + Build Prediction Models    │
│ 🧪 DOE            → Map Process → Spectra (NEW)            │
│ 📤 Deploy         → Streaming Report (NEW)                 │
│ ⚙️  Settings       → API Keys, Preferences                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Experiments (📊 Load & Check My Data)

### Original Code
- **Location**: `Original/Exp_loader/`
- **Files**:
  - `app/routes.py` - Experiment CRUD, file upload
  - `app/models.py` - ExperimentData, MixtureComponent, RackMixture
  - `app/storage.py` - File storage management

### Refactored Implementation
- **Models**: `app/models/experiment.py`, `experiment_file.py`
- **Routes**: `app/api/v1/routes/experiments.py`
- **Services**: `app/services/experiments.py`

### Tab Structure
```
┌─────────────────────────────────────────────────────────────┐
│ Experiments                                                 │
├─────────────────────────────────────────────────────────────┤
│ [Overview] [Create] [Files] [Versions]                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Overview Tab:                                              │
│  - DataTable with all experiments                          │
│  - Quick actions (view, edit, delete)                      │
│  - Filters (date, hardware, status)                        │
│                                                             │
│  Create Tab:                                                │
│  1. Basic Info (name, description)                         │
│  2. Hardware Config (instrument, detector, etc.)           │
│  3. DOE Setup (optional - design of experiments)           │
│  4. Mixtures Setup (optional - component definitions)      │
│                                                             │
│  Files Tab:                                                 │
│  - Upload spectral files (.spa, .csv)                      │
│  - File list with metadata                                 │
│  - Quick preview/plot                                       │
│                                                             │
│  Versions Tab:                                              │
│  - Version history (content-addressed storage)             │
│  - Export to CSV/JSON                                       │
│  - Compare versions                                         │
└─────────────────────────────────────────────────────────────┘
```

### Key Features
- Hardware configuration tracking
- DOE (Design of Experiments) integration
- Mixture component definitions
- Version control with content-addressable storage
- File upload and validation

---

## 2. NIST Library (📚 Load & Check Public Data)

### Original Code
- **Location**: `Original/Pull_FTIR_from_NIST/`
- **Files**:
  - `pull_data_from_NIST.py` - Downloads JCAMP-DX files from NIST
  - `convert_plot_NIST_spectra.py` - Converts and plots NIST spectra

### Refactored Implementation
- **Models**: `app/models/nist_library.py`
- **Routes**: `app/api/v1/routes/nist.py`
- **Frontend**: `frontend/src/views/NistView.vue`

### Tab Structure
```
┌─────────────────────────────────────────────────────────────┐
│ NIST Library                                                │
├─────────────────────────────────────────────────────────────┤
│ [Search] [Library] [Blend with Experiments]                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Search Tab:                                                │
│  - AutoComplete search (compound names)                    │
│  - Results table (CAS#, formula, MW)                       │
│  - Download queue (right sidebar, 30%)                     │
│  - Bulk download actions                                    │
│                                                             │
│  Library Tab:                                               │
│  - Downloaded entries table                                │
│  - Bulk operations (select multiple, delete)               │
│  - Load into experiments                                    │
│  - Plot/preview spectra                                     │
│                                                             │
│  Blend with Experiments Tab: (NEW)                         │
│  - Select NIST spectra                                      │
│  - Select experiment data                                   │
│  - Blending controls (ratios, mixing)                      │
│  - Output: Combined AnalysisDataset for analysis            │
└─────────────────────────────────────────────────────────────┘
```

### Key Features
- Search NIST database by compound name
- Download JCAMP-DX files
- Convert to AnalysisDataset format
- Blend NIST reference data with experimental spectra
- Create "spiked" datasets for validation

---

## 3. Analysis (🧼 Clean & Compare Spectra)

### Original Code
- **Location**: `Original/MCR_ICA_exploration/`
- **Files**:
  - `mcr_als_comparison.py` - MCR-ALS analysis
  - `mcr_als_pymcr_standalone.py` - Standalone MCR
  - `efa_analysis.py` - Evolving Factor Analysis
  - `efa_for_pyMCR.py` - EFA for MCR initialization
  - `plot_fast_ica.py` - Independent Component Analysis
  - `syn_data_gen.py` - Synthetic data for testing

### Refactored Implementation ✅ **COMPLETE**
- **DAG Engine**: `app/services/dag/`
- **Nodes**: `app/services/dag/nodes/preprocessing.py`, `modeling.py`
- **Frontend**: `frontend/src/views/analysis/AnalysisContent.vue`

### Current Node Library (10 nodes)
**Preprocessing (7)**:
- Baseline (ALS, Rubberband)
- Smooth (Savitzky-Golay)
- Normalize (SNV, MSC)
- Derivative (1st, 2nd)

**Modeling (3)**:
- PCA
- PLS
- Linear Regression

### **TODO**: Add Missing Nodes from Original
- **MCR-ALS** node (`mcr_als_comparison.py`)
- **ICA** node (`plot_fast_ica.py`)
- **EFA** node (`efa_analysis.py`)

---

## 4. Builder (🔧 Create Synthetic Datasets)

### Original Code
- **Location**: `Original/Synthetic_Spectra_Builder_py/`
- **Files**:
  - `Project0/blend.py` - Multi-species spectral blending (Beer's Law)
  - `Project0/curves.py` - Concentration curve generation
  - `Project0/preprocess.py` - Preprocessing utilities
  - `Project0/models.py` - SpectrumRecord, calibration models
  - `Project0/exporter.py` - Export to various formats
  - `launch.py` - Server launcher

### Refactored Implementation
- **Routes**: `app/api/v1/routes/builder.py`
- **Frontend**: `frontend/src/views/BuilderView.vue` (needs reorganization)

### Tab Structure
```
┌─────────────────────────────────────────────────────────────┐
│ Builder (Synthetic Data Generator)                         │
├─────────────────────────────────────────────────────────────┤
│ [Library] [Curves] [Blend] [Export]                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Library Tab:                                               │
│  - Load spectral signatures (NIST or experimental)         │
│  - Manage library of pure components                       │
│  - Upload custom signatures                                │
│  - Preview individual spectra                              │
│                                                             │
│  Curves Tab:                                                │
│  - Define concentration profiles over time                 │
│  - Curve types: linear, exponential, sinusoidal, etc.      │
│  - Multi-species curves (independent or linked)            │
│  - Visual curve editor                                      │
│                                                             │
│  Blend Tab:                                                 │
│  - Blending algorithm (Beer's Law superposition)           │
│  - Model selection:                                         │
│    • Linear: A = α(ν) × C + β(ν)                           │
│    • Saturation: A = c(ν) × C^p / (s^p + C^p)             │
│    • Hybrid: Per-wavenumber model selection                │
│  - System-level saturation controls                        │
│  - Live preview plot (spectra evolving over time)          │
│                                                             │
│  Export Tab:                                                │
│  - Export formats: CSV, SPA, AnalysisDataset               │
│  - Metadata tagging                                         │
│  - Batch generation (parameter sweeps)                     │
└─────────────────────────────────────────────────────────────┘
```

### Key Features
- Multi-species spectral blending (Beer's Law)
- Concentration curve design (linear, saturation, hybrid)
- Calibration model support (linear, saturation, hybrid)
- System-level saturation effects
- Export to multiple formats

---

## 5. Calibrations (📏 Calibrate + Build Prediction Models)

### Original Code
- Partially in refactored code already
- Missing: Advanced calibration curve fitting from Original

### Refactored Implementation
- **Models**: `app/models/calibration.py`, `cal_model.py`
- **Routes**: `app/api/v1/routes/calibrations.py`
- **Frontend**: `frontend/src/views/CalibrationsView.vue` (needs reorganization)

### Tab Structure
```
┌─────────────────────────────────────────────────────────────┐
│ Calibrations                                                │
├─────────────────────────────────────────────────────────────┤
│ [Overview] [Create] [Fit Model] [Evaluate]                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Overview Tab:                                              │
│  - Table of all calibrations                               │
│  - Filter by analyte, method, status                       │
│  - Quick actions (activate, archive, delete)               │
│                                                             │
│  Create Tab:                                                │
│  1. Calibration Info (name, analyte, units)                │
│  2. Select Data Source (experiments or NIST)               │
│  3. Reference Values (lab measurements)                    │
│  4. Spectral Range Selection                               │
│                                                             │
│  Fit Model Tab:                                             │
│  - Model type selection (PLS, PCR, Linear, etc.)           │
│  - Hyperparameter tuning                                    │
│  - Cross-validation settings                               │
│  - Live fit plot (predicted vs actual)                     │
│  - Residuals plot                                           │
│                                                             │
│  Evaluate Tab:                                              │
│  - Metrics (R², RMSE, MAE, etc.)                           │
│  - Outlier detection (Hotelling T², Q-residuals)          │
│  - Model comparison (different versions)                   │
│  - Export model (Python, ONNX, etc.)                       │
└─────────────────────────────────────────────────────────────┘
```

### Key Features
- Multi-method calibration (PLS, PCR, Linear)
- Cross-validation and hyperparameter tuning
- Outlier detection
- Model versioning
- Export to production formats

---

## 6. DOE (🧪 Map Process → Spectra) - NEW

### Purpose
Design of Experiments to understand process variables → spectral changes

### Tab Structure
```
┌─────────────────────────────────────────────────────────────┐
│ DOE (Design of Experiments)                                │
├─────────────────────────────────────────────────────────────┤
│ [Designs] [Plan] [Execute] [Analyze]                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Designs Tab:                                               │
│  - DOE templates (factorial, response surface, etc.)       │
│  - Create custom designs                                    │
│  - Import from software (JMP, Design-Expert)               │
│                                                             │
│  Plan Tab:                                                  │
│  - Define factors (temperature, pressure, time, etc.)      │
│  - Factor ranges and levels                                │
│  - Response variables (spectral features)                  │
│  - Randomization and blocking                              │
│                                                             │
│  Execute Tab:                                               │
│  - Run order table                                          │
│  - Data collection checklist                               │
│  - Link to experiments (executed runs)                     │
│                                                             │
│  Analyze Tab:                                               │
│  - ANOVA (factor significance)                             │
│  - Response surface plots                                   │
│  - Interaction plots                                        │
│  - Spectral feature extraction                             │
└─────────────────────────────────────────────────────────────┘
```

### Key Features
- DOE design templates
- Factor and response definition
- Execution tracking
- Statistical analysis (ANOVA, response surfaces)

---

## 7. Deploy (📤 Streaming Report) - NEW

### Purpose
Real-time prediction from streaming spectral data

### Tab Structure
```
┌─────────────────────────────────────────────────────────────┐
│ Deploy (Streaming Report)                                  │
├─────────────────────────────────────────────────────────────┤
│ [Models] [Stream] [Monitor] [Report]                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Models Tab:                                                │
│  - Select calibration model                                │
│  - Model status (active, idle)                             │
│  - Model metadata (accuracy, range, etc.)                  │
│                                                             │
│  Stream Tab:                                                │
│  - Data source configuration (file, API, instrument)       │
│  - Streaming rate (Hz)                                      │
│  - Buffer settings                                          │
│  - Start/Stop controls                                      │
│                                                             │
│  Monitor Tab:                                               │
│  - Live predictions (real-time chart)                      │
│  - Alert thresholds                                         │
│  - Quality metrics (confidence intervals)                  │
│  - System health (latency, errors)                         │
│                                                             │
│  Report Tab:                                                │
│  - Auto-generated reports (PDF, HTML)                      │
│  - Report templates                                         │
│  - Scheduled reports (hourly, daily, etc.)                 │
│  - Export prediction history                               │
└─────────────────────────────────────────────────────────────┘
```

### Key Features
- Load streaming spectral data
- Apply calibration model in real-time
- Generate reports automatically
- Alert on out-of-spec predictions

---

## Implementation Priority

### Phase 1: Core Functionality (Current Sprint)
1. ✅ Analysis (DAG system) - **COMPLETE**
2. 🚧 Experiments - Reorganize tabs
3. 🚧 NIST Library - Add blending tab
4. 🚧 Builder - Reorganize tabs
5. 🚧 Calibrations - Reorganize tabs

### Phase 2: Advanced Features
6. ⏳ DOE - New section
7. ⏳ Deploy - New section

### Phase 3: Missing Nodes
- Add MCR-ALS, ICA, EFA nodes to Analysis DAG

---

## Data Flow

```
┌─────────────────┐     ┌─────────────────┐
│   Experiments   │────▶│  NIST Library   │
│  (My spectra)   │     │ (Public spectra)│
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     │
                     ▼
         ┌──────────────────────────────┐
         │      "Loaded Data"          │
         │     (AnalysisDataset)       │
         └───────────┬────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│    Analysis     │     │     Builder     │
│  (Clean/Model)  │     │   (Synthetic)   │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │   Calibrations        │
         │  (Build predictors)   │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │      Deploy           │
         │  (Real-time predict)  │
         └───────────────────────┘
```

---

## Next Steps

1. Reorganize Experiments view with 4 tabs
2. Add Blend tab to NIST Library
3. Reorganize Builder view with 4 tabs
4. Reorganize Calibrations view with 4 tabs
5. Create DOE section stub (Phase 2)
6. Create Deploy section stub (Phase 2)
