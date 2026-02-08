# FTIR Chemometrics Analysis Tool - Installation & Usage Guide

**Copyright © Spectra Scientific LLC**

Provided to Intel Corporation for internal research and demonstration use only under the Statement of Work (Oct 15, 2025). No redistribution, sublicensing, or commercial deployment rights are granted.

---

## Table of Contents

1. [Overview](#overview)
2. [System Requirements](#system-requirements)
3. [Installation Steps](#installation-steps)
4. [Data Preparation](#data-preparation)
5. [Running the Analysis](#running-the-analysis)
6. [Viewing Results](#viewing-results)
7. [Troubleshooting](#troubleshooting)
8. [Support](#support)

---

## Overview

This tool generates interactive HTML visualizations for FTIR spectral analysis with chemometric modeling. It analyzes multiple FTIR spectra at different concentrations and fits linear or saturation models to predict concentration from absorbance.

**Key Features:**
- Interactive wavenumber exploration
- Automatic model selection (linear vs saturation)
- Quality metrics (NRMSE, R², slope/c, eigenvectors)
- Full-spectra validation plots
- Model parameter export (JSON)

---

## System Requirements

### Required Software

- **Python**: 3.8 or higher
- **Web Browser**: Chrome, Firefox, Safari, or Edge (modern version)
- **Operating System**: Windows, macOS, or Linux

### Required Python Packages

```
pandas >= 1.3.0
numpy >= 1.20.0
plotly >= 5.0.0
scipy >= 1.7.0
```

---

## Installation Steps

### Step 1: Install Python

**Windows:**
1. Download Python from [python.org](https://www.python.org/downloads/)
2. Run installer and **check "Add Python to PATH"**
3. Verify installation:
   ```cmd
   python --version
   ```

**macOS:**
```bash
brew install python3
python3 --version
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-pip
python3 --version
```

### Step 2: Install Required Packages

Open a terminal/command prompt and run:

```bash
pip install pandas numpy plotly scipy
```

Or use a requirements file (if provided):

```bash
pip install -r requirements.txt
```

### Step 3: Download the Analysis Scripts

Copy these files to your working directory:
- `plot_ftir_spectra.py` (main analysis script)
- `ftir_controls.js` (interactive controls - embedded automatically)

---

## Data Preparation

### File Organization

Create a folder with your FTIR data organized as follows (one folder can contain one or multiple species):

```
my_ftir_data/
├── Water [H2O] [7732-18-5] (5000ppm_5-10m_150C).csv
├── Water [H2O] [7732-18-5] (12000ppm_5-10m_150C).csv
├── Carbon Dioxide [CO2] [124-38-9] (4000ppm_5-10m_150C).csv
├── Carbon Dioxide [CO2] [124-38-9] (8000ppm_5-11m_150C).csv
└── Water_EV_Intensity_20251016.xlsx  (optional; first XLSX with species prefix is used)
```

### CSV File Format (FTIR Spectra)

Each CSV file contains one spectrum with two columns:

```csv
499.96,0.0234
500.20,0.0241
500.44,0.0245
...
```

**Requirements:**
- Column headers not needed
- Wavenumber in cm⁻¹ (descending or ascending order)
- One spectrum per file
- File naming convention (parsed by the script):
  - `ChemicalName [...metadata...] (###ppm)_path1_path2.csv`
  - Chemical name: text before the first `" ["`
  - Concentration: parsed from `(###ppm)`
  - Pathlength: **second-to-last** underscore segment; hyphen → decimal; trailing letters trimmed (e.g., `_5-10m_` → 5.10)
  - At least **3 CSVs per species** are required; species with fewer files are skipped with a warning


### Optional Excel File (Eigenvector Metadata)

To overlay a legacy eigenvector in the diagnostics panel, place an Excel workbook (`.xlsx`) in the data folder. The tool picks the **first** `.xlsx` whose filename starts with the species name (alphabetical order) and reads the first worksheet as two columns of numeric pairs:

| Wavenumber | Eigenvector_Intensity |
|-------------------:|------------:|
| 499.96             | 0.014       |
| 500.20             | -0.032      |
| 500.44             | 0.021       |

Specifications:
- First worksheet only; one header row is expected (column names are not enforced).
- Column A: Wavenumber (cm⁻¹), numeric.
- Column B: Eigenvector value, numeric (unitless).
- Rows may be unsorted; the script sorts and linearly interpolates values to the golden grid.
- Blank/non‑numeric rows are ignored; out‑of‑range values are treated as 0 during interpolation.

---

## Running the Analysis

### Basic Usage

```bash
python plot_ftir_spectra.py --directory <data_folder> --output <output.html>
```

**Example:**

```bash
python plot_ftir_spectra.py --directory ./my_ftir_data --output ./results/ftir_analysis.html
```

**Parameters:**
- `--directory` (required): Path to folder containing CSV and XLSX files
- `--output` (optional): Output HTML filename; defaults to `ftir_spectra.html` (and `ftir_spectra_selector.html` when multiple species are present)

### Selecting Concentration Mode (ppm vs concentration×pathlength)

Use the `--concentration-mode` flag to pick the X-axis used for sorting, fitting, and plotting:

- **Product (concentration × pathlength, ppm·m) - RECOMMENDED:**
  `python plot_ftir_spectra.py --directory ./data --output ./results.html --concentration-mode product`

- **Concentration (ppm only) - LEGACY:**
  `python plot_ftir_spectra.py --directory ./data --output ./results.html --concentration-mode concentration`

**IMPORTANT:**
- **Always use `--concentration-mode product`** for libraries intended for MCR analysis (Project2)
- Product mode is required for cross-project compatibility
- Concentration-only mode produces libraries that will be rejected by Project2
- If pathlength is constant, product mode with pathlength=1.0m gives equivalent ppm units

When to choose:
- **Product mode (default):** Use for all new calibrations, especially when pathlength varies or for Project2 compatibility
- **Concentration mode (legacy):** Only for standalone analysis or legacy compatibility (not usable in Project2)

Filename parsing (unchanged):
- Concentration parsed from `(###ppm)` in the filename.
- Pathlength parsed from the second-to-last underscore segment (`_5-10m_` → 5.10). If missing/unparseable, defaults to 1.0 m (warning logged), so product falls back to concentration.

### Example Commands

**Windows:**
```cmd
python plot_ftir_spectra.py --directory C:\Users\YourName\ftir_data --output C:\Users\YourName\Desktop\analysis.html
```

**macOS/Linux:**
```bash
python3 plot_ftir_spectra.py --directory ~/ftir_data --output ~/Desktop/analysis.html
```

### Expected Output

When successful, you'll see species grouping and (for multi-species folders) selector + per-species pages generation. Example:

```
Scanning directory: /path/to/multi_species_folder

Species Summary:
  Including 'Carbon Dioxide': 12 files
  Including 'Water': 18 files

Building species datasets:
  Species 'Carbon Dioxide': processing 12 file(s)
    Eigenvector: found Carbon Dioxide_EV_Intensity_20251016.xlsx
    Eigenvector pairs mapped: 18669 points
  Species 'Water': processing 18 file(s)
    Eigenvector: not found (rendering empty eigenvector trace)
Species ready: Carbon Dioxide
Species ready: Water
Auto-selecting single species: Carbon Dioxide
Wrote viewer: /.../viewer.html
Wrote selector: /.../viewer_selector.html
```

---

## Viewing Results

### Opening the HTML File

- Single-species folder: open the generated species HTML (e.g., `ftir_spectra_Water.html`). The selector page is not generated when only one species exists.
- Multi-species folder: open the selector HTML (e.g., `output_selector.html`), choose a species, then continue to that per-species viewer (each species has its own HTML; no in-viewer dropdown).

### Interactive Features

**Navigation:**
- Use slider or input box to change wavenumber
- Click on diagnostic plots to jump to that wavenumber
- Vertical lines show current wavenumber across all subplots

**Controls:**
- **Species**: Use the selector page to swap species (per-species viewers contain only one species’ data; no in-viewer dropdown)
- **Saturation Level**: Adjust maximum absorbance threshold
- **Wavenumber Range**: Filter to specific spectral region
- **NRMSE Threshold**: Quality filter for model acceptance
- **Model Selection**: View parameters from linear, saturation, or winner models
- **Concentration**: Select spectrum for validation plots

**Color Legend:**
- 🟢 Green = Linear model
- 🔴 Red = Saturation model

**Exporting:**
- Click "Export Model Parameters (JSON)" to save fitted parameters
- Downloads `ftir_model_parameters.json` with all wavenumber data

---

## Multi-Species Settings Management

When working with multiple species, the selector page (`ftir_spectra_selector.html`) provides centralized settings management.

### Settings Storage Mechanisms

The tool uses two complementary storage methods:

1. **Browser Storage (Automatic)**
   - Settings automatically save to your browser's localStorage
   - Persists across browser sessions
   - Provides instant synchronization between selector and viewer pages
   - **Critical requirement:** All HTML files must remain in the same directory

2. **JSON File (Manual Export/Import)**
   - Portable backup of all species settings
   - Shareable with colleagues
   - Survives browser cache clearing
   - Click "Save Multi-Species Settings" to export

### Customizing Settings

**For individual species:**
1. Open `ftir_spectra_selector.html`
2. Find the species row in the table
3. Modify threshold values or wavenumber ranges
4. Changes save automatically to browser storage
5. Open the species viewer → settings load immediately

**For all species:**
1. Modify multiple rows in the selector table
2. Click "Save Multi-Species Settings" → exports JSON file
3. Store JSON file for backup or sharing

### Loading Saved Settings

**From browser storage:**
- Automatic on page load if HTML files are in the same directory
- No user action required

**From JSON file:**
1. Open selector page
2. Click "Load Settings from File"
3. Select your saved JSON file
4. Settings apply to all species immediately

**From clipboard:**
1. Copy JSON text from email, document, etc.
2. Click "Paste Settings from Clipboard" in selector
3. Settings import and apply automatically

### Resetting Settings

**Single species:** Click "Reset to Defaults" in the species row (selector table)

**All species:** Click "Reset All to Defaults" button at top of selector page

### Important Notes

⚠️ **File Location Matters**
- Keep all generated HTML files in the same directory
- Moving files to different folders breaks browser storage sync
- Always use "Save Multi-Species Settings" before reorganizing files

⚠️ **Browser Cache Clearing**
- Clearing browser data erases localStorage settings
- Keep JSON backups for important configurations
- JSON files are not affected by browser cache clearing

⚠️ **Sharing with Colleagues**
- Recipients must load the JSON file manually
- Browser storage does not transfer between computers
- Include the JSON file when sharing HTML files

---

## Troubleshooting

### Error: "No module named 'pandas'"

**Solution:** Install required packages:
```bash
pip install pandas numpy plotly scipy
```

### Error: "File not found" or "No CSV files found"

**Solution:**
- Check that data folder path is correct
- Verify CSV files have `.csv` extension
- At least one CSV file must be present

### Species missing or skipped

**Solution:**
- Ensure the filename follows the required pattern (`ChemicalName [...] (###ppm)_path1_path2.csv`)
- Provide at least **3 CSVs per species** or the species will be skipped
- Check logs for detailed warnings (pathlength parsing, missing files)

### Charts not displaying

**Solution:**
- HTML generated by the current script is self-contained (Plotly is embedded; works offline)
- If you are viewing an older/prebuilt HTML that references a CDN, point it to the local vendor file:
  - Replace the CDN script with `./vendor/plotly-3.2.0.min.js` (or regenerate HTML with the latest script)
- Try a different web browser
- Check browser console for errors (F12 → Console tab)

### Very slow performance

**Possible causes:**
- HTML file size too large (>20 MB)
- Too many spectra (>50) or wavenumbers (>50000)
- Old browser version

**Solutions:**
- Reduce wavenumber range with `--range` parameter (if available)
- Use fewer spectra
- Update browser to latest version

### Settings not syncing between selector and viewer

**Cause:** HTML files were moved to different directories

**Symptoms:**
- Selector shows custom settings but viewer shows defaults
- Changes in selector don't appear in viewer

**Solution:**
1. Keep all HTML files in the same directory
2. If you've already moved files:
   - Click "Save Multi-Species Settings" in selector
   - Move the JSON file to the new directory
   - Click "Load Settings from File" to restore settings

### Settings lost after closing browser

**Cause:** Browser cache was cleared or private browsing mode was used

**Prevention:**
- Regularly click "Save Multi-Species Settings" to create JSON backups
- Store JSON files with your data for long-term archival

**Recovery:**
- Load the most recent JSON backup using "Load Settings from File"

### Colleague can't see my custom settings

**Cause:** Browser storage doesn't transfer with HTML files

**Solution:**
1. Before sharing, click "Save Multi-Species Settings"
2. Send both the HTML files AND the JSON file
3. Instruct recipient to:
   - Save all files to same directory
   - Open selector page
   - Click "Load Settings from File"
   - Select the JSON file you provided

---

## File Descriptions

### Input Files

| File | Purpose | Required |
|------|---------|----------|
| `*.csv` | Individual FTIR spectra | Yes |
| `*.xlsx` | Eigenvector overlay (optional) | No |

### Output Files

| File | Description |
|------|-------------|
| `viewer.html` (name follows `--output`) | Main per-species viewer (auto-loads first species; in-viewer dropdown available) |
| `viewer_selector.html` (only when multiple species) | Lightweight dropdown to choose a species and open the main viewer |
| `ftir_model_parameters.json` | Exported model parameters (per selected species; optional) |

### Script Files

| File | Purpose |
|------|---------|
| `plot_ftir_spectra.py` | Main analysis script |
| `ftir_controls.js` | Interactive controls (embedded in HTML) |

### Vendor Files

| File | Purpose |
|------|---------|
| `vendor/plotly-3.2.0.min.js` | Offline Plotly runtime for legacy/prebuilt HTML that expects a separate Plotly script. New HTML embeds Plotly automatically. |

---

## Advanced Usage

### Batch Processing Multiple Datasets

Create a batch script to process multiple folders:

**Windows (batch.bat):**
```cmd
@echo off
python plot_ftir_spectra.py --directory data\CO2 --output output\CO2_analysis.html
python plot_ftir_spectra.py --directory data\H2O --output output\H2O_analysis.html
python plot_ftir_spectra.py --directory data\CF4 --output output\CF4_analysis.html
echo All analyses complete!
```

**macOS/Linux (batch.sh):**
```bash
#!/bin/bash
python3 plot_ftir_spectra.py --directory data/CO2 --output output/CO2_analysis.html
python3 plot_ftir_spectra.py --directory data/H2O --output output/H2O_analysis.html
python3 plot_ftir_spectra.py --directory data/CF4 --output output/CF4_analysis.html
echo "All analyses complete!"
```

### Programmatic Usage

```python
from plot_ftir_spectra import main
from pathlib import Path

# Process data
main(
    directory=Path("./my_data"),
    output_html=Path("./output.html")
)
```

---

## Support

### For Questions or Issues

Contact: Spectra Scientific LLC
Email: info@spectrascientific.ai
Reference: Intel SOW (Oct 15, 2025)

### Reporting Bugs

Please provide:
1. Python version (`python --version`)
2. Package versions (`pip list | grep -E "pandas|numpy|plotly|scipy"`)
3. Error message (full traceback)
4. Sample data (if possible)

---

## License & Intellectual Property

**Copyright © Spectra Scientific LLC**

This software is provided to Intel Corporation for internal research and demonstration use only under the Statement of Work dated Oct 15, 2025.

**Restrictions:**
- ❌ No redistribution outside Intel Corporation
- ❌ No sublicensing to third parties
- ❌ No commercial deployment or production use
- ✅ Internal research and evaluation permitted
- ✅ Modification for internal use permitted

**Deliverables included:**
- `plot_ftir_spectra.py` - Analysis script
- `ftir_controls.js` - Interactive controls
- Supporting documentation

For licensing inquiries or commercial use, contact Spectra Scientific LLC.

---

## Appendix: Quick Reference

### Command Syntax

```bash
python plot_ftir_spectra.py --directory <DATA_FOLDER> --output <OUTPUT.html>
```

### Minimum Example

```bash
# 1. Prepare data folder with CSV files (optional: add eigenvector.xlsx)
# 2. Run analysis
python plot_ftir_spectra.py --directory ./data --output ./analysis.html
# 3. Open analysis.html in browser
```

### File Size Guidelines

| Spectra Count | Wavenumbers | Expected HTML Size |
|---------------|-------------|-------------------|
| 5-10 | ~3000 | 8-12 MB |
| 10-20 | ~3000 | 12-18 MB |
| 20-50 | ~3000 | 18-30 MB |

**Note:** Files >20 MB may be slow to load. Consider reducing wavenumber range if needed.

---

**Document Version:** 1.0
**Last Updated:** 2025-11-11
**Compatible with:** plot_ftir_spectra.py v2.0+
