# Spectra Platform - Information Architecture

**Version**: 1.0
**Date**: January 2025
**Status**: Approved for Implementation

---

## Executive Summary

This document defines the high-level information architecture for the Spectra Platform - the navigation structure, tab organization, and LLM integration strategy.

### Core Principles
1. **Project as Global Context** - Scientists think "I'm working on Project X"
2. **3-Tab Navigation** - Data | Operations | Workflows (low cognitive load)
3. **AnalysisDataset Throughout** - All data flows as `AnalysisDataset` (the DAG's canonical runtime container). NDDataset (SpectroChemPy) is used only by SCP-only nodes via adapters. Provenance in `meta["processing_history"]`, serialization at API boundary via `serialize_for_api()`.
4. **LLM as Technical Assistant** - Code generation and guidance, not scientific conclusions

---

## Navigation Structure

### Header (Always Visible - Global Context)
```
┌─────────────────────────────────────────────────────────────────────┐
│ [Logo] Spectra Platform                                             │
│                                                                     │
│ Project: [Spike_DOE_082925 ▼]  [+ New] [Save] [⚙ Settings]         │
└─────────────────────────────────────────────────────────────────────┘
```

**Project Dropdown Features:**
- Recently opened projects
- Create new project
- Open from file
- Save current project
- Project properties/metadata

**Rationale**: Scientists think in terms of "I'm working on Project X" - the project is the mental frame, not a navigation destination.

### Main Navigation (3 Tabs)
```
┌─────────────────────────────────────────────────────────────────────┐
│         Data          |       Operations       |      Workflows     │
│  ─────────────────────────────────────────────────────────────────  │
│  Experiments          |       Calibration      |      Builder       │
│  Library              |       Process          |      Templates     │
│  Synthesis            |       Analysis         |                    │
└─────────────────────────────────────────────────────────────────────┘
```

**Rationale**: 3 clear categories reduces cognitive load compared to 7-8 separate tabs.

---

## Tab 1: Data (Data Ingestion)

**Purpose**: Get NDDatasets into the project from various sources.

### 1.1 Experiments Sub-tab
**Purpose**: Capture real lab data with proper metadata organization.

**Features:**
- File upload supporting all SpectrochemPy formats:
  - `read_csv()` - CSV files
  - `read_jcamp()` - JCAMP-DX files
  - `read_opus()` - Bruker OPUS files
  - `read_omnic()` - Thermo OMNIC files
  - `read_labspec()` - Horiba LabSpec files
  - `read_srs()` - SRS format
  - `read_matlab()` - MATLAB files
- **DOE Configuration**:
  - Factor definitions (sample factors, method factors)
  - Plate mapping (96-well)
  - Run sequences
  - File matching with metadata capture
  - Folder-based batch organization
- Metadata editor
- Version control for raw data
- Preview loaded datasets

**Design Decision**: DOE stays in Experiments because it's about **organizing experimental metadata**, not analyzing results.

### 1.2 Library Sub-tab
**Purpose**: Access validated reference and standard spectra.

**Features:**
- NIST spectral database browser
- JCAMP-DX imports
- Compound search:
  - By CAS number
  - By chemical formula
  - By compound name
- Reference spectra collections
- User-uploaded standards
- Tag and categorize library entries
- Preview spectra before adding to project

### 1.3 Synthesis Sub-tab (renamed from "Builder")
**Purpose**: Generate synthetic data for training, testing, or simulation.

**Features:**
- Mix/blend existing datasets
- Concentration profiles:
  - Linear gradients
  - Random sampling
  - Custom curves
- Noise models:
  - Gaussian noise
  - Baseline drift
  - Cosmic ray simulation
- Spectral simulation
- Export as new NDDataset to project

---

## Tab 2: Operations (Data Transformation)

**Purpose**: Transform NDDatasets through calibration, processing, and analysis.

### 2.1 Calibration Sub-tab
**Purpose**: Correct systematic instrumental errors.

**Features:**
- **Wavelength Calibration**:
  - Using reference peak positions
  - Polynomial correction
  - Apply to datasets
- **Intensity Calibration**:
  - Background correction
  - Sensitivity correction
- Fit/transform operations
- Save calibration models to project
- Apply saved calibrations to new data

### 2.2 Process Sub-tab
**Purpose**: Essential preprocessing only (minimal, focused).

**Features** (Only these four categories):

| Category | Methods |
|----------|---------|
| **Baseline Correction** | Polynomial, ALS, airPLS, SNIP |
| **Smoothing** | Savitzky-Golay, Moving average, Gaussian |
| **Alignment** | Peak alignment, COW, Shift correction |
| **Interpolation** | Common wavenumber grid, Resampling |

**Design Decision**: Simple math operations (add, subtract, multiply, normalize) are NOT separate menu items - they're available within workflows as needed.

### 2.3 Analysis Sub-tab
**Purpose**: Extract insights from processed data (comprehensive).

**Features** (All SpectrochemPy analysis methods):

| Category | Methods |
|----------|---------|
| **Peak Analysis** | Detection, Fitting (Gaussian, Lorentzian, Voigt), Integration, Assignment |
| **Multivariate** | PCA, PLS, MCR-ALS, NMF |
| **RSM** | Response surface fitting, Optimization, Interaction effects |
| **Classification** | LDA, PLS-DA, SVM |
| **Clustering** | K-means, Hierarchical, DBSCAN |
| **Curve Fitting** | Linear regression, Nonlinear fitting, Custom models |

**Design Decision**: RSM (Response Surface Methodology) lives in Analysis because it **analyzes DOE results**. DOE setup lives in Experiments because it **organizes experimental metadata**.

---

## Tab 3: Workflows

**Purpose**: Automate multi-step analyses and provide reusable patterns.

### 3.1 Builder Sub-tab (Visual Workflow)
**Purpose**: Drag-and-drop workflow construction.

**Features:**
- Node-based visual editor
- Nodes from ALL categories:
  - **Data nodes**: Load from Experiments, Library, Synthesis
  - **Calibration nodes**: Apply wavelength/intensity calibration
  - **Process nodes**: Baseline, smooth, align, interpolate
  - **Analysis nodes**: PCA, MCR, peak detection, RSM, etc.
  - **Export nodes**: Save results, generate reports
- Connect nodes to define data flow
- Execute entire workflow
- Save workflows to project
- **LLM Assistant panel** (collapsible, resizable, 30% default width)

### 3.2 Templates Sub-tab
**Purpose**: Pre-built workflows for common analysis patterns.

#### Template: Project1 - Wavenumber-Specific Calibration
```
Purpose: Extract wavenumber-specific absorption vs. concentration
         models per species from skew data.

Flow:
[Load Experiments]
    → [Calibrate Wavelength]
    → [Process: Baseline + Smooth]
    → [Analysis: Fit Absorption vs Concentration per Wavenumber]
    → [Save Calibration Model]

Output: Wavenumber-specific absorption coefficients per species
```

#### Template: Project2 - MCR with Nonlinear Models
```
Purpose: Specialized MCR implementation with nonlinear models
         for complex mixture analysis.

Flow:
[Load Data]
    → [Process: Align + Smooth + Baseline]
    → [Analysis: MCR-ALS with Constraints]
    → [Nonlinear Fitting for Pure Components]
    → [Save Resolved Components]

Output: Pure component spectra and concentration profiles
```

#### Template: DOE Analysis Pipeline
```
Purpose: Analyze factorial experimental designs.

Flow:
[Load DOE Experiment]
    → [Process: Standard Preprocessing]
    → [Analysis: Extract Response Variable]
    → [Analysis: RSM - Response Surface]
    → [Visualize + Optimize]

Output: Response surface model, optimal conditions
```

#### Template: Routine QC Analysis
```
Purpose: Quick quality control check on new samples.

Flow:
[Load Sample]
    → [Apply Saved Calibration]
    → [Process: Standard Pipeline]
    → [Compare to Reference Specs]
    → [Generate QC Report]

Output: Pass/fail determination, comparison charts
```

#### Template: Library Matching
```
Purpose: Identify unknown spectra by library comparison.

Flow:
[Load Unknown Sample]
    → [Process: Baseline + Normalize]
    → [Analysis: Library Search]
    → [Rank Matches by Similarity]
    → [Generate Match Report]

Output: Top library matches with confidence scores
```

---

## LLM Assistant - Realistic Capabilities

### Design Philosophy

The LLM is a **technical assistant**, not a scientific advisor. It helps with code, workflows, and documentation - not scientific interpretation.

**Target Users**: Scientists who already know spectroscopy. They don't need the LLM to teach them science - they need it to help them use the software efficiently.

### What the LLM CAN Do (Technical Assistance)

#### 1. Code Generation
```
User: "Create a baseline correction using ALS with lambda=1e5"
LLM:  [Generates SpectrochemPy Python code]

User: "Write a loop to process all datasets in batch"
LLM:  [Generates batch processing script]
```
- Generate SpectrochemPy Python code from natural language
- Export workflows as executable Python scripts
- Translate user intent into correct API calls

#### 2. Workflow Construction Assistance
```
User: "What should I add after baseline correction?"
LLM:  "Based on your noisy data, consider adding Savitzky-Golay
       smoothing next. Drag the 'Smooth' node from Process category."
```
- Suggest next nodes based on current workflow state
- Recommend node parameters based on data characteristics
- Identify missing connections or incomplete flows

#### 3. Parameter Guidance
```
User: "What's a good window size for Savitzky-Golay?"
LLM:  "For your data with ~2 cm⁻¹ resolution, try window=15
       (covers ~30 cm⁻¹). Start with order=3 for smoothing
       without distorting peak shapes."
```
- Explain what parameters do in plain language
- Suggest reasonable starting values based on data
- Flag potentially problematic parameter combinations

#### 4. Error Interpretation
```
Error: "ValueError: Wavenumber ranges do not overlap"
LLM:   "This means your spectra have different x-axis ranges.
        Add an 'Interpolate' node before merging to create a
        common wavenumber grid."
```
- Parse Python/SpectrochemPy error messages
- Suggest fixes for common errors
- Point to relevant documentation

#### 5. Documentation Lookup
```
User: "How do I use MCR-ALS?"
LLM:  [Explains MCR-ALS parameters, shows example code,
       links to SpectrochemPy docs]
```
- Answer "How do I..." questions about SpectrochemPy
- Explain method differences (ALS vs airPLS baseline)
- Provide syntax examples

#### 6. Data Quality Checks
```
LLM: "Warning: Your spectrum has negative values after baseline
     correction. This might indicate over-correction. Consider
     adjusting the ALS smoothness parameter."
```
- Flag suspicious patterns in data
- Suggest preprocessing steps based on data characteristics
- Identify potential cosmic rays or artifacts

#### 7. Result Summarization
```
LLM: "PCA Results Summary:
      - 3 components explain 95.2% of variance
      - PC1 (67%): Correlates with concentration
      - PC2 (21%): Correlates with temperature
      - Outlier detected: Sample #47"
```
- Generate plain-language summaries of analysis results
- Create formatted reports for export
- Summarize workflow execution results

#### 8. Template Recommendations
```
User: "I want to calibrate my instrument for CF4"
LLM:  "For concentration calibration, the 'Project1' template
       is designed exactly for this. It will:
       1. Load your reference spectra
       2. Apply wavelength calibration
       3. Fit absorption vs concentration at each wavenumber
       Would you like me to load it?"
```
- Suggest which workflow template to use based on user's goal
- Explain differences between templates
- Help customize templates for specific needs

#### 9. Context-Aware Responses
The LLM has access to:
- Current project name and contents
- Datasets loaded in current session
- Current workflow state (nodes, connections)
- Selected node and its parameters
- Previous conversation history

### What the LLM Should NOT Do

#### 1. Make Scientific Conclusions
```
❌ "This peak at 1650 cm⁻¹ is definitely amide I"
✅ "The peak at 1650 cm⁻¹ is in the typical amide I region (1600-1700 cm⁻¹)"
```

#### 2. Replace Domain Expertise
```
❌ "Your sample contains 45% protein based on this spectrum"
✅ "Here's how to set up a quantitative model for protein content using
   the amide I band. You'll need reference samples with known concentrations."
```

#### 3. Claim Certainty About Assignments
```
❌ "This is contamination"
✅ "This unexpected peak at 2350 cm⁻¹ might be CO₂ from the atmosphere.
   If it's not expected, you may want to investigate."
```

#### 4. Make Decisions About Experimental Validity
```
❌ "This data is bad, discard it"
✅ "This dataset shows unusually high noise (SNR=15, typical is >50).
   Consider repeating the measurement or applying stronger smoothing."
```

#### 5. Provide Medical/Safety Conclusions
```
❌ "This sample is safe for consumption"
✅ "I can help you compare your spectrum against regulatory reference
   values. You'll need to interpret the results according to your
   organization's safety protocols."
```

### LLM Integration Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Workflows Tab                                 │
│  ┌─────────────────────────────┬─────────────────────────────┐  │
│  │                             │   LLM Assistant Panel       │  │
│  │    Visual Workflow          │   ─────────────────────     │  │
│  │    Builder                  │   [Collapsible]             │  │
│  │                             │   [Resizable: 30% default]  │  │
│  │    ┌───┐    ┌───┐    ┌───┐ │                             │  │
│  │    │ A │───▶│ B │───▶│ C │ │   User: "Add MCR analysis"  │  │
│  │    └───┘    └───┘    └───┘ │                             │  │
│  │                             │   🤖 Drag the MCR-ALS node  │  │
│  │                             │   from Analysis → Multi-    │  │
│  │                             │   variate. Connect it to    │  │
│  │                             │   your preprocessed data.   │  │
│  │                             │                             │  │
│  │                             │   [Generate Code] [Explain] │  │
│  └─────────────────────────────┴─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Context Passed to LLM

```python
llm_context = {
    "project": {
        "name": "DOE_Spike_Analysis",
        "datasets": ["raw_batch1", "raw_batch2", "nist_co2"],
        "calibrations": ["wavelength_cal_v1"],
    },
    "workflow": {
        "nodes": [
            {"id": "n1", "type": "load", "data": "raw_batch1"},
            {"id": "n2", "type": "baseline", "method": "als"},
        ],
        "edges": [{"from": "n1", "to": "n2"}],
        "selected_node": "n2",
    },
    "selected_node_params": {
        "method": "als",
        "lam": 1e5,
        "p": 0.001,
    },
}
```

---

## Data Flow Diagram

```
                    ┌─────────────────────────────────────────────┐
                    │               PROJECT CONTEXT                │
                    │         (Always Active in Header)            │
                    └─────────────────────────────────────────────┘
                                         │
            ┌────────────────────────────┼────────────────────────────┐
            │                            │                            │
            ▼                            ▼                            ▼
    ┌───────────────┐           ┌───────────────┐           ┌───────────────┐
    │     DATA      │           │  OPERATIONS   │           │   WORKFLOWS   │
    │───────────────│           │───────────────│           │───────────────│
    │ • Experiments │           │ • Calibration │           │ • Builder     │
    │ • Library     │──────────▶│ • Process     │──────────▶│ • Templates   │
    │ • Synthesis   │           │ • Analysis    │           │ • LLM Assist  │
    └───────────────┘           └───────────────┘           └───────────────┘
            │                            │                            │
            │         NDDataset          │         NDDataset          │
            └────────────────────────────┼────────────────────────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   PROJECT STORAGE   │
                              │  (Parquet + JSON)   │
                              └─────────────────────┘
```

---

## Project Structure (SpectrochemPy-Aligned)

```python
from spectrochempy import Project, NDDataset

project = Project(
    name="DOE_Spike_Analysis",

    # Datasets from all sources
    datasets={
        # From Experiments
        "raw_batch1": NDDataset(...),
        "raw_batch2": NDDataset(...),

        # From Library
        "nist_co2_reference": NDDataset(...),

        # From Synthesis
        "synthetic_training_set": NDDataset(...),

        # Processed
        "processed_batch1": NDDataset(...),
    },

    # Calibrations
    calibrations={
        "wavelength_cal_20250105": Calibration(...),
    },

    # Saved workflows
    scripts={
        "project1_workflow": Workflow(...),
        "project2_mcr": Workflow(...),
    },

    # Analysis results
    results={
        "pca_model": PCAResult(...),
        "rsm_surface": RSMResult(...),
    },

    metadata={
        "created": "2025-01-05",
        "author": "User",
        "description": "DOE analysis of spike samples",
    }
)
```

---

## Key Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Project context | Global (header dropdown) | Scientists think "I'm working on X" |
| Main navigation | 3 tabs | Lower cognitive load |
| DOE location | Experiments tab | DOE is metadata organization |
| RSM location | Analysis tab | RSM analyzes DOE results |
| Project1/2 | Workflow templates | Span multiple operations |
| Process scope | 4 categories only | Essential preprocessing only |
| LLM role | Technical assistant | Code gen, not scientific conclusions |
| Data structure | AnalysisDataset (NDDataset-compatible) | Provenance in `meta["processing_history"]`; NDDataset used only by SCP-only nodes via adapters |

---

## Navigation Flow Examples

### Example 1: New DOE Experiment
1. **Header**: Select or create project "New_DOE_Study"
2. **Data → Experiments**: Upload files, set up DOE metadata
3. **Operations → Process**: Baseline correction, smoothing
4. **Operations → Analysis → RSM**: Fit response surface
5. Save results to project

### Example 2: Using Project1 Template
1. **Header**: Select project "Calibration_Study"
2. **Workflows → Templates**: Click "Project1 - Wavenumber Calibration"
3. Configure input datasets
4. Click "Run Workflow"
5. Review results, save model to project

### Example 3: Building Custom Workflow
1. **Header**: Select project
2. **Workflows → Builder**: Drag nodes
   - Add "Load Experiment" node (from Data)
   - Add "Baseline Correction" node (from Process)
   - Add "PCA" node (from Analysis)
   - Add "Export" node
3. Connect nodes
4. Ask LLM: "What parameters for baseline?"
5. Save as "My Custom Pipeline"
6. Execute

---

## Implementation Phases

### Phase 1: Core Structure
- [ ] Implement global project context in header
- [ ] Restructure Vue Router to 3 main tabs
- [ ] Create sub-tab navigation components
- [ ] Move existing views to correct locations
- [ ] Rename "Builder" to "Synthesis"

### Phase 2: Data Tab
- [ ] Experiments sub-tab (DOE functionality exists)
- [ ] Library sub-tab (NIST browser, compound search)
- [ ] Synthesis sub-tab (move current Builder here)
- [ ] Unify file upload with all SpectrochemPy readers

### Phase 3: Operations Tab
- [ ] Calibration sub-tab (new implementation)
- [ ] Process sub-tab (baseline, smooth, align, interpolate only)
- [ ] Analysis sub-tab (PCA, PLS, MCR, RSM, peak detection)

### Phase 4: Workflows Tab
- [ ] Visual workflow builder (exists, needs restructuring)
- [ ] Workflow template system
- [ ] Project1 template implementation
- [ ] Project2 template implementation
- [ ] LLM assistant enhancement (base already implemented)

### Phase 5: Project Management
- [ ] Project CRUD operations
- [ ] SpectrochemPy Project format save/load
- [ ] Project history and versioning
- [ ] Project export/import

---

## Appendix: SpectrochemPy Integration Points

### Data Ingestion (Data Tab)
```python
scp.read()           # Generic reader (auto-detect format)
scp.read_csv()       # CSV files
scp.read_jcamp()     # JCAMP-DX
scp.read_opus()      # Bruker OPUS
scp.read_omnic()     # Thermo OMNIC
scp.read_matlab()    # MATLAB files
```

### Processing (Operations Tab)
```python
dataset.baseline()      # Baseline correction
dataset.smooth()        # Smoothing
dataset.align()         # Alignment
dataset.interpolate()   # Interpolation
```

### Analysis (Operations Tab)
```python
scp.PCA()              # Principal Component Analysis
scp.PLS()              # Partial Least Squares
scp.MCR_ALS()          # Multivariate Curve Resolution
scp.find_peaks()       # Peak detection
scp.fit()              # Curve fitting
```

### Project Management
```python
scp.Project()          # Create project
project.save()         # Save to file
Project.load()         # Load from file
```

---

*This document represents the approved information architecture for the Spectra Platform. All implementation should follow this structure.*

**Document Version:** 1.0
**Last Updated:** January 2025
**Status:** Approved for Implementation
