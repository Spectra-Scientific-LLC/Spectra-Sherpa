# SpectraSherpa User Manual

## Overview

SpectraSherpa is an integrated platform for spectroscopic data analysis, synthesis, and workflow automation. This manual covers how to load different data sources and synthesize spectral data.

---

## Table of Contents

1. [Loading SpectroChemPy Data (Experiments)](#1-loading-spectrochempy-data-experiments)
2. [Loading NIST Reference Spectra](#2-loading-nist-reference-spectra)
3. [Loading 96-Well Essential Oil Data](#3-loading-96-well-essential-oil-data)
4. [Loading DOE Calibration Data (Project 1)](#4-loading-doe-calibration-data-project-1)
5. [Synthesizing Data with the Builder](#5-synthesizing-data-with-the-builder)
6. [Workflow Builder](#6-workflow-builder)
7. [Status Indicators](#7-status-indicators)

---

## 1. Loading SpectroChemPy Data (Experiments)

The **Experiments** module manages experimental spectra with versioning and metadata tracking.

### Creating a New Experiment

1. Navigate to **Experiments** in the sidebar
2. Click the **Create** tab
3. Fill in the experiment details:
   - **Name**: Descriptive name for your experiment
   - **Description**: Purpose and notes
   - **Hardware**: Spectrometer used (optional)
   - **DOE Setup**: Link to Design of Experiments configuration (optional)
4. Click **Create Experiment**

### Uploading Spectra Files

1. Select an experiment from the **Overview** tab
2. Switch to the **Files** tab
3. Choose the file stage:
   - **Raw**: Original unprocessed spectra
   - **Preprocessed**: Cleaned/corrected spectra
   - **Synthetic**: Generated/blended spectra
4. Drag and drop files or click to browse
5. Supported formats:
   - CSV (wavenumber, absorbance columns)
   - JCAMP-DX (.jdx, .dx)
   - SPC files
   - SpectroChemPy native formats

### Version Management

1. Go to the **Versions** tab
2. Click **Create Version** to snapshot current state
3. Enter version name and description
4. To restore: click the restore icon on any version

### Loading Experiment Data in Builder

Once files are uploaded, they become available in the **Synthesis** module:
1. Go to **Synthesis** > **Preprocess** tab
2. Select your experiment from the dropdown
3. Choose files to preprocess

---

## 2. Loading NIST Reference Spectra

The **Library** module provides access to NIST WebBook reference spectra.

### Searching NIST Database

1. Navigate to **Library** in the sidebar
2. Use the **Search** tab
3. Type a compound name (e.g., "ethanol", "limonene")
4. Results show:
   - Compound name
   - CAS number
   - NIST identifier

### Downloading Spectra

1. From search results, click **Download** for standard resolution
2. Or click **High-Res** for higher resolution data
3. Download progress appears in the right panel
4. Downloads are queued and processed in background

### Viewing Library Entries

1. Switch to the **Library** tab
2. Browse all downloaded spectra
3. Click any entry to view:
   - Interactive spectrum plot
   - Wavenumber range
   - Resolution details
   - Download date

### Using Library Spectra in Synthesis

1. In the **Library** tab, select spectra for blending
2. Click **Add to Builder**
3. Navigate to **Synthesis** to use them

---

## 3. Loading 96-Well Essential Oil Data

The **DOE** (Design of Experiments) tab in Experiments manages 96-well plate configurations for essential oil analysis.

### Setting Up the Sample Database

1. Navigate to **Experiments** > select your experiment
2. Go to the **DOE** tab
3. In the **Sample Database** section:
   - Click **Import CSV** to bulk import samples
   - Or manually add samples with:
     - Sample ID
     - Name (e.g., "Lavender EO", "Peppermint EO")
     - Type (essential_oil, carrier, standard)
     - Brand/Source
     - CAS Number (if applicable)

### Creating Mixtures

1. In the **Mixtures** section, click **New Mixture**
2. Select component samples from the database
3. Specify composition:
   - **Weight %**: Mass-based percentages
   - **Mole %**: Molar percentages
   - **Volume %**: Volume-based percentages
4. Name the mixture (e.g., "Blend A - 50% Lavender, 50% Peppermint")

### Assigning Wells on the 96-Well Plate

1. In the **96-Well Plate Map** section:
   - Visual grid shows all 96 wells (A1-H12)
   - Select a mixture from the dropdown
   - Click wells to assign that mixture
   - Color coding shows different mixtures
2. **Plate Statistics** show:
   - Assigned wells count
   - Empty wells count
   - Mixture distribution

### Matching Acquisition Files to Wells

1. Upload your spectra files in the **Files** tab
2. Return to **DOE** > **Acquisition Matching** section
3. Click **Auto-Match** to automatically match files to wells
4. Matching uses filename patterns to identify:
   - Well position (e.g., "A1", "B12")
   - Sequence number
   - Replicate information
5. Review and manually correct any mismatches

### Loading 96-Well Data in Builder

1. Go to **Synthesis** > **Preprocess** tab
2. Select your 96-well experiment
3. Files are organized by well position
4. Select wells/files to preprocess together

---

## 4. Loading DOE Calibration Data (Project 1)

DOE Configurations store structured experimental designs for calibration studies.

### Creating a DOE Configuration

1. Navigate to **Experiments** > **DOE** tab
2. Or access **DOE Configs** directly

### Defining Experimental Factors

1. In the **Experimental Factors** section:
2. Add **Sample Factors**:
   - Concentration levels
   - Component ratios
   - Sample types
3. Add **Method Factors**:
   - Temperature
   - Integration time
   - Number of scans
4. For each factor, specify:
   - Name
   - Type (categorical or continuous)
   - Levels (e.g., [0, 25, 50, 75, 100] for concentration %)

### Setting Up Run Sequences

1. In the **Run Sequence** section:
2. Define the order of experimental runs
3. Each run includes:
   - Sequence order
   - Factor level values
   - Folder path for data files
   - Batch identifier

### Loading Calibration Data

1. Upload calibration spectra files to the experiment
2. Match files to run sequences in **Acquisition Matching**
3. The system links:
   - Spectra files
   - Well positions (if applicable)
   - Factor values (concentrations, conditions)

### Using Calibration Data in Builder

1. Go to **Synthesis** > **Preprocess** tab
2. Select the calibration experiment
3. Files are available with their associated metadata
4. Use for:
   - Building calibration curves
   - Creating synthetic mixtures
   - Validating models

---

## 5. Synthesizing Data with the Builder

The **Synthesis** module creates synthetic spectra by blending reference species.

### Preprocess Tab

**Purpose**: Clean and prepare spectra before blending.

#### Loading Spectra
1. **From Experiments**: Select experiment and files
2. **From Library**: Add NIST reference spectra
3. Both sources can be combined

#### Preprocessing Settings

| Setting | Description | Default |
|---------|-------------|---------|
| **Alignment Method** | Wavenumber interpolation (pchip, linear, sinc) | pchip |
| **Apply Range Limit** | Clip to wavenumber range | Off |
| **Min/Max Wavenumber** | Range bounds (cm^-1) | 400-4000 |
| **Cosmic Ray Removal** | Remove spike artifacts | On |
| **Savitzky-Golay Smoothing** | Noise reduction filter | On |
| **Clip Floor** | Set minimum absorbance value | Off |

#### Running Preprocessing
1. Configure settings
2. Click **Run Preprocessing**
3. View results in the plot panel
4. Each spectrum shows as a separate trace

### Blend Tab

**Purpose**: Combine species spectra with concentration profiles.

#### Selecting Species
1. Preprocessed spectra appear as available species
2. Check species to include in blend
3. Each species represents a pure component

#### Defining Concentration Profiles

Create time-series concentrations for each species:

```
Species A: [100, 80, 60, 40, 20, 0]    (decreasing)
Species B: [0, 20, 40, 60, 80, 100]    (increasing)
Species C: [50, 50, 50, 50, 50, 50]    (constant)
```

**Concentration Curve Editor**:
1. Select a species
2. Draw curve points on the canvas
3. Or enter values numerically
4. Curves are interpolated between points

#### Blending Options

| Option | Description |
|--------|-------------|
| **Pathlength (m)** | Optical pathlength for Beer's Law |
| **Absorption Coefficient** | Molar absorptivity |
| **Time Steps** | Number of blend time points |

#### Running the Blend
1. Configure concentrations for all species
2. Click **Blend Spectra**
3. Result shows:
   - Time-series of blended spectra
   - 3D surface plot (wavenumber x time x absorbance)
   - Individual time slices

### Export Tab

**Purpose**: Save synthetic data for external use.

#### Export Formats

| Format | Use Case |
|--------|----------|
| **CSV** | Spreadsheet analysis, simple import |
| **JSON** | Web applications, metadata preservation |
| **NetCDF** | Scientific computing, large datasets |
| **Python Script** | Reproducibility, automation |

#### Export Options
1. Select output format
2. Choose data to include:
   - Preprocessed spectra
   - Blended results
   - Concentration profiles
   - Full metadata
3. Click **Export**
4. File downloads to your system

---

## 6. Workflow Builder

The **Workflow Builder** creates visual analysis pipelines.

### Adding Nodes

From the left toolbar, click to add nodes:

| Category | Nodes |
|----------|-------|
| **Data** | Load Data |
| **Preprocess** | Normalize, Scale, Baseline, Smooth |
| **Analysis** | PCA, PLS, MCR-ALS |
| **Stats** | Statistics |
| **Visualize** | Scatter Plot |
| **Export** | Export |

### Connecting Nodes

1. Click **Connect** on a source node
2. Click **Connect Here** on the target node
3. Arrow shows data flow direction

### Configuring Nodes

1. Click a node to select it
2. Inspector panel shows parameters
3. Adjust settings as needed:
   - Normalization method
   - Number of components
   - Output format

### Executing Workflows

1. Click **Execute Workflow**
2. Nodes process in topological order
3. Status shows:
   - Pending (gray circle)
   - Processing (yellow, animated)
   - Complete (green checkmark)
4. Results display in inspector panel

### Exporting Python Code

1. Click **Export Python**
2. Downloads executable Python script
3. Uses SpectroChemPy for full compatibility

---

## 7. Status Indicators

The top bar shows four status lights:

| Position | Indicator | Colors |
|----------|-----------|--------|
| 1st | **Data** | Green: Sources available / Gray: No experiments |
| 2nd | **Workflow** | Green: Ready / Yellow: Unsaved changes / Gray: Empty |
| 3rd | **LLM** | Green: Connected / Yellow: Connecting / Red: Disconnected |
| 4th | **Compute** | Blue: Local |

Hover over any indicator for detailed status.

---

## Quick Start Workflow

### Example: Essential Oil Blend Analysis

1. **Create Experiment**
   - Experiments > Create > "Essential Oil Study"

2. **Set Up 96-Well Plate**
   - DOE tab > Import samples
   - Create mixtures
   - Assign wells

3. **Upload Spectra**
   - Files tab > Upload raw spectra
   - Match to wells in DOE > Acquisition Matching

4. **Add Reference Spectra**
   - Library > Search "limonene", "linalool"
   - Download reference spectra

5. **Preprocess**
   - Synthesis > Preprocess tab
   - Select experiment files + library references
   - Apply smoothing, baseline correction
   - Run Preprocessing

6. **Blend**
   - Blend tab > Select species
   - Define concentration profiles
   - Run Blend

7. **Analyze**
   - Workflow Builder > Add PCA node
   - Connect to data
   - Execute and view results

8. **Export**
   - Export tab > Download CSV/Python script

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+S` | Save current work |
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z` | Redo |
| `Delete` | Remove selected node |
| `Escape` | Cancel current operation |

---

## Troubleshooting

### Common Issues

**"No experiments loaded"**
- Create an experiment first
- Check that files are uploaded

**"LLM Disconnected"**
- Check backend server is running
- Verify WebSocket connection

**"Workflow execution failed"**
- Check node connections
- Verify data node has valid source
- Review error message in toast

**"NIST download stuck"**
- Check internet connection
- NIST may rate-limit requests
- Try again after a few minutes

---

## Support

For issues and feature requests, visit:
https://github.com/anthropics/claude-code/issues
