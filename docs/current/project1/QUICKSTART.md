# FTIR Analysis Tool - Quick Start Guide

**Copyright © Spectra Scientific LLC** | Intel SOW (Oct 15, 2025)

---

## ⚡ 5-Minute Setup

### 1. Install Python & Dependencies

```bash
pip install pandas numpy plotly scipy
```

### 2. Organize Your Data

```
my_data/
├── spectrum1.csv    # wavenumber, absorbance
├── spectrum2.csv
├── spectrum3.csv
└── eigenvector.xlsx  # OPTIONAL: for eigenvector overlay
```

### 3. Run Analysis

```bash
python plot_ftir_spectra.py --directory ./my_data --output ./output.html
# --output is optional; defaults to ftir_spectra.html (and ftir_spectra_selector.html when multiple species)
```

### 4. View Results

- Single species in folder: open the generated species HTML (e.g., `ftir_spectra_Species.html`). Selector is not generated when only one species exists.
- Multiple species: open `output_selector.html`, pick a species, then click through to its per-species viewer (each species has its own HTML; no in-viewer dropdown).

---

## 📦 Deliverables Package

Intel users receive:

1. **`plot_ftir_spectra.py`** - Main analysis script
2. **`ftir_controls.js`** - Interactive controls (auto-embedded)
3. **`INSTALLATION_GUIDE.md`** - Complete documentation
4. **`QUICKSTART.md`** - This file

---

## 📊 Data Format

### CSV Files (Spectra)
```csv
wavenumber,absorbance
499.96,0.0234
500.20,0.0241
...
```

### Excel File (Eigenvector, optional)
Two numeric columns on the first worksheet:

```
Wavenumber, Eigenvector
499.96, 0.014
500.20, -0.032
...
```
Notes: header row optional; rows may be unsorted; values are interpolated to the golden grid; out-of-range treated as 0.

### Filename Pattern (Multi-Species)

`ChemicalName [...metadata...] (###ppm)_path1_path2.csv`

- Chemical name: everything before the first ` [`
- Concentration: extracted from `(###ppm)`
- Pathlength: second-to-last underscore segment; `5-10m` → 5.10 (letters trimmed)
- If pathlength is missing/unparseable, the tool defaults to 1.0 m (and logs a warning) so the product becomes the concentration value.
- Eigenvector: first `.xlsx` whose filename starts with the species name (alphabetical pick); if absent, the eigenvector plot renders empty on the left axis while the right-axis slope/c still show.

---

## 🎯 Example Usage

```bash
# Basic
python plot_ftir_spectra.py --directory ./data --output ./results.html

# With different paths
python plot_ftir_spectra.py --directory ~/ftir_data --output ~/Desktop/analysis.html

# Product mode (uses concentration × pathlength as X)
python plot_ftir_spectra.py --directory ./data --output ./results.html --concentration-mode product
# Use this when pathlength varies between spectra. Default remains concentration-only (ppm).
```

---

## 🔍 Interactive Features

Once HTML is generated:

- **Species selection**: Use the selector page to open a per-species viewer (no in-viewer dropdown)
- **Slider**: Navigate through wavenumbers
- **Color Code**: 🟢 Green = Linear, 🔴 Red = Saturation
- **Validation**: Select concentration for full-spectra comparison
- **Export**: Download model parameters as JSON
- **Tooltips**: Hover for detailed metrics

### Quality Control Thresholds

Two independent thresholds control data quality:

1. **Absorbance Outlier Rejection Threshold** (default: 4.0)
   - Filters individual concentration points where absorbance exceeds this value
   - Applied **before** model fitting (per-wavenumber, per-concentration)
   - Wavenumbers with < 4 valid points after outlier removal are completely rejected
   - Rejected points shown as hollow gray circles on scatter plot
   - Statistics display shows count of affected wavenumbers

2. **NRMSE Max Threshold** (default: 0.05)
   - Filters wavenumbers where **both** linear and saturation models have poor fit quality
   - Applied **after** model fitting
   - Lower NRMSE = better fit (closer to zero is ideal)
   - Affects winner selection for validation/export; doesn't change model computation

Click **"Update Settings"** to apply threshold changes and see summary statistics.

**Understanding the Statistics:**

The system applies a two-stage filtering process:

**Stage 1: Absorbance Outlier Filtering** (applied BEFORE model fitting)
- Individual concentration points where absorbance exceeds threshold are rejected
- If a wavenumber has < 4 valid points remaining → wavenumber is completely rejected (not fitted)

**Stage 2: NRMSE Quality Filtering** (applied AFTER model fitting)
- For wavenumbers that were fitted, check if NRMSE ≤ threshold
- Both models must pass NRMSE threshold for wavenumber to be used in production

**Statistics Display:**
- **Total Wavenumbers in Range**: Number of wavenumbers in selected range
- **Quality Breakdown** (percentages add to 100%):
  - **Insufficient data (<4 valid pts)**: Rejected before fitting due to outlier threshold
  - **Both models failed NRMSE**: Fitted but both had poor quality
  - **Linear model winners**: Passed all filters, linear had better/only valid NRMSE
  - **Saturation model winners**: Passed all filters, saturation had better/only valid NRMSE
- **Wavenumbers with ≥1 outlier point**: Count (not %) of wavenumbers where at least one concentration point exceeded outlier threshold but still had enough points (≥4) to attempt fitting

### Winner Selection

The system uses two different winner selection approaches:

**Diagnostic Winner** (First 4 plots: NRMSE, Slope/c, p-parameter, s-parameter)
- Selects model with lower NRMSE for comparison purposes
- Shows color-coded winners: 🟢 Green = Linear, 🔴 Red = Saturation
- Points above threshold shown in gray
- Allows toggling between winner view and baseline comparison

**Quality-Filtered Winner** (Eigenvector right axis, Validation, Export)
- Only selects models that pass NRMSE threshold
- Ensures production use only includes quality models
- If both pass: picks lower NRMSE
- If one passes: picks that one
- If neither passes: wavenumber excluded

### Full-Spectra Validation

<details>
<summary><strong>📖 Quick Reference Guide</strong> (click to expand)</summary>

#### Purpose
Compare measured spectra against model predictions across the entire wavenumber range for a selected concentration.

#### Plot Components

**Top Plot: Spectrum Comparison**
- **Raw measured spectrum** (markers): Original FTIR measurements at instrument wavenumber positions
- **Clipped spectrum (model input)** (line): Interpolated data on golden grid with outlier filtering applied
- **Modeled prediction** (line): Model output using fitted parameters (linear, saturation, or winner)

**Bottom Plot: Residuals**
- Shows difference between clipped spectrum and model prediction
- Helps identify systematic fitting errors or outlier regions

#### Understanding Clipped Spectrum Gaps

You may notice gaps in the clipped line where raw spectrum points are visible. This is expected behavior:

**Why it happens:**
- Raw spectrum shows measured data at instrument positions (e.g., 679.05 cm⁻¹)
- Clipped line uses golden grid positions (e.g., 679.25 cm⁻¹)
- Linear interpolation between measured points can produce values above threshold
- Example: Point A = 3.9, Point B = 4.8 → interpolated midpoint = 4.3 (rejected)

**What this means:**
- **Visual only** - This is a plotting artifact, not a computational problem
- **Models unaffected** - Fitting uses concentration-dependent behavior across all valid points
- **Residuals confirm** - If you see residuals at a wavenumber, the model was fitted correctly
- **Export includes** - Wavenumbers with passing NRMSE are exported regardless of clipped line gaps

**Key insight:** Gaps in the clipped line do NOT indicate missing analysis. The models are fitted using all valid concentration points, and residuals prove the fitting was successful.

See [INTERPOLATION_OUTLIER_BEHAVIOR.md](../../INTERPOLATION_OUTLIER_BEHAVIOR.md) for detailed technical explanation.

#### Model Selection Options
- **Linear**: Uses linear model (slope × concentration + intercept)
- **Saturation**: Uses saturation model (c × concentration^p + intercept)
- **Winner (lowest NRMSE)**: Uses quality-filtered winner (must pass NRMSE threshold)

#### Controls
- **Concentration dropdown**: Select which concentration to validate
- **Model toggle**: Switch between Linear, Saturation, and Winner views
- **Hover tooltips**: View wavenumber-specific metrics and values

</details>

### Wavenumber-Specific s-Parameter

The saturation model automatically optimizes three parameters per wavenumber:
- **s-parameter**: Saturation level (optimized individually for each wavenumber)
- **p-parameter**: Shape parameter
- **c-parameter**: Concentration scaling factor

The s-parameter plot (7th panel) shows optimized saturation levels:
- 🟢 Green circles: Linear model winners
- 🔴 Red diamonds: Saturation model winners
- Only wavenumbers passing NRMSE threshold are displayed
- Each wavenumber has its own s-value; no global saturation level setting

Note: HTML generated by the current script embeds Plotly and works offline. For legacy/prebuilt pages that rely on an external Plotly script, use `./vendor/plotly-3.2.0.min.js`.

---

## 🔧 Multi-Species Settings Management

### Settings Storage

The selector page manages settings for all species using two storage mechanisms:

1. **Browser Storage (Primary)**: Settings auto-save to your browser's localStorage
   - Persists across sessions
   - Instant sync between selector and viewer pages
   - **Important:** All HTML files must stay in the same directory for settings to sync

2. **JSON File (Backup/Sharing)**: Export settings to `ftir_spectra_settings.json`
   - Portable across computers
   - Shareable with colleagues
   - Click "Save Multi-Species Settings" to export

### Settings Workflow

**To customize settings:**
1. Open `ftir_spectra_selector.html`
2. Modify thresholds/ranges in the table for any species
3. Settings auto-save to browser storage
4. Open any species viewer → settings load automatically

**To share settings with others:**
1. Click "Save Multi-Species Settings" → downloads JSON file
2. Send JSON file to colleague
3. They click "Load Settings from File" in their selector
4. Settings apply to all their viewer pages

**To reset:**
- Single species: Click "Reset to Defaults" in selector row
- All species: Click "Reset All to Defaults" button

### Important Notes

- **Keep files together:** Moving HTML files to different folders breaks settings sync
- **Browser cache:** Clearing browser data erases stored settings (use JSON backup)
- **File sharing:** Recipients need to load the JSON file; browser storage won't transfer

---

## 🆘 Common Issues

| Problem | Solution |
|---------|----------|
| "Module not found" | Run `pip install pandas numpy plotly scipy` |
| "No CSV files" | Check folder path and `.csv` extension |
| "Data error" in HTML | Regenerate with latest script |
| Slow performance | Use fewer spectra or smaller range |
| Settings not syncing | Ensure all HTML files are in the same directory |
| Settings lost after moving files | Use "Save Multi-Species Settings" to create portable JSON backup |

---

## 📚 Full Documentation

See **`INSTALLATION_GUIDE.md`** for:
- Detailed installation steps
- Advanced usage
- Troubleshooting guide
- Batch processing examples

---

## 📧 Support

Questions? Contact Spectra Scientific LLC
Reference: Intel SOW (Oct 15, 2025)

---

## 📜 License

**Internal Use Only** - Intel Corporation
No redistribution or commercial deployment permitted.

For full licensing terms, see INSTALLATION_GUIDE.md § License & Intellectual Property.
