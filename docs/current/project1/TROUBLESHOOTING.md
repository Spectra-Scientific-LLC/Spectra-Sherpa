# Troubleshooting Guide - FTIR Analysis Tool (Project1)

**Copyright © Spectra Scientific LLC** | Intel SOW (Oct 15, 2025)

---

## Quick Problem Solving

### 1. No HTML Output Generated

**Symptom:** Command runs but no HTML file appears

**Checks:**
1. **Look for error messages** in terminal output
2. **Check output directory** - Default is `ftir_spectra.html` in current directory
3. **Verify CSV files exist** in input directory

**Common causes:**
- No CSV files found in specified directory
- Insufficient data (< 3 files per species)
- Invalid CSV format
- File permission issues

**Solution:**
```bash
# Run with explicit output path
python plot_ftir_spectra.py \
  --directory ./my_data \
  --output ./Desktop/results.html \
  --concentration-mode product

# Check for errors in output
```

---

### 2. "Insufficient data for fitting" Error

**Symptom:** Script exits with error about insufficient data points

**Cause:** Need minimum 3 CSV files per species for model fitting

**Solution:**
1. **Check file count:**
   ```bash
   ls my_data/*.csv | wc -l  # Linux/Mac
   dir /b my_data\*.csv | find /c /v ""  # Windows
   ```

2. **Ensure files are valid:**
   - Each CSV has wavenumber + absorbance columns
   - At least 3 different concentration values
   - Concentration extracted from filename `(###ppm)`

3. **Add more measurement files** if below minimum

---

### 3. Concentration/Pathlength Parsing Issues

**Symptom:** Warning: "Could not parse concentration from filename" or "Pathlength parsing failed"

**Cause:** Filename doesn't match expected pattern

**Expected format:**
```
ChemicalName [metadata] (###ppm)_pathlength_###.csv
```

**Examples:**
- `Water [lab] (100ppm)_5m_001.csv` → conc=100, pathlength=5.0
- `CO2 [field] (50ppm)_10-5m_002.csv` → conc=50, pathlength=10.5
- `CH4 (200ppm)_001.csv` → conc=200, pathlength=1.0 (default)

**Fix:**
1. **Rename files** to match pattern
2. **Concentration:** Must be `(###ppm)` - digits + "ppm" in parentheses
3. **Pathlength:** Second-to-last underscore segment, digits+optional decimal+'m'
   - `_5m_` → 5.0 meters
   - `_10-5m_` → 10.5 meters
   - Missing → defaults to 1.0m (warning logged)

---

### 4. Multi-Species: Wrong Species Detected

**Symptom:** Species name extracted incorrectly from filenames

**Cause:** Species name is everything BEFORE the first `[` bracket

**Examples:**
- ✓ `Water [lab] (100ppm)_5m_001.csv` → species="Water"
- ✓ `Carbon Dioxide [field] (50ppm)_10m_002.csv` → species="Carbon Dioxide"
- ✗ `Water_sample_1_(100ppm)_5m_001.csv` → species="Water_sample_1_" (no bracket)

**Fix:**
- Add `[metadata]` bracket in filename before concentration
- Or accept that species name includes underscores up to first `(`

---

### 5. No Eigenvector Plot Showing

**Symptom:** Eigenvector plot is empty (right Y-axis shows nothing)

**Causes:**
1. No XLSX file provided
2. XLSX filename doesn't match species name
3. XLSX file is corrupt or wrong format

**Solution:**

1. **Provide eigenvector XLSX** (optional, for reference only):
   - Filename must START with species name (case-insensitive)
   - Example: `Water_eigenvector.xlsx` for species "Water"
   - If multiple species, first alphabetically is chosen

2. **XLSX format:**
   ```
   | Wavenumber | Eigenvector |
   |------------|-------------|
   | 499.96     | 0.014       |
   | 500.20     | -0.032      |
   ```
   - Two numeric columns on first worksheet
   - Header row optional (auto-detected)
   - Rows can be unsorted (will be interpolated to golden grid)

3. **Check XLSX is valid:**
   ```bash
   python -c "import pandas as pd; df=pd.read_excel('Water_eigenvector.xlsx'); print(df.head())"
   ```

---

### 6. Model Export (JSON) Not Working

**Symptom:** Click "Export Model Parameters (JSON)" but nothing happens or error shown

**Checks:**
1. **Browser console** (F12) for JavaScript errors
2. **Downloaded file** in browser's download folder (may have auto-downloaded)
3. **NRMSE threshold** - If too strict, no wavenumbers pass, export is empty

**Solution:**

1. **Check NRMSE threshold:**
   - Default: 0.05 (5% normalized error)
   - If too few wavenumbers pass, increase threshold temporarily
   - Update settings and re-check fit quality

2. **Manually verify export:**
   - Export should create `species_name_model.json`
   - Open in text editor to verify structure
   - Should contain: `wavenumbers`, `model_at_wavenumber`, `slope`, `s`, `p`, `c` arrays

3. **Check file size:**
   - Typical size: 50-500 KB depending on wavenumber count
   - If < 1 KB, likely no wavenumbers passed NRMSE filter

---

### 7. Settings Not Saving/Loading

**Symptom:** Changed settings in HTML viewer but lost on page reload

**Cause:** Settings saved to browser localStorage and/or `_settings.json` file

**How it works:**
1. **Adjust settings** in species viewer (outlier threshold, NRMSE, wavenumber range)
2. **Click "Update Settings"** to apply
3. **Settings auto-save** to browser localStorage
4. **Export settings** to JSON for sharing/backup:
   - Multi-species: Click "Save Multi-Species Settings" in selector page
   - Creates `ftir_spectra_settings.json` in downloads folder
5. **Load settings** from JSON:
   - Click "Load Multi-Species Settings"
   - Select previously saved JSON file

**Fix:**
- Settings are per-browser, per-machine
- To share between machines: Export → Download → Load on other machine
- Keep `_settings.json` file in same directory as HTML for auto-load

---

### 8. Product Mode Not Working as Expected

**Symptom:** Used `--concentration-mode product` but results don't look right

**Checks:**

1. **Pathlength parsing:**
   - Check terminal output for pathlength parse warnings
   - Verify pathlengths extracted correctly from filenames
   - If missing, defaults to 1.0m → product = concentration

2. **X-axis units:**
   - Product mode: ppm·m (concentration × pathlength)
   - Concentration mode: ppm only
   - Check HTML plot axis labels

3. **Verification:**
   ```
   If:
     Concentration = 100 ppm
     Pathlength = 5.0 m
   Then:
     Product = 500 ppm·m
   ```

**Fix:**
- Ensure filenames have pathlength: `_5m_` or `_10-5m_`
- Check terminal output for "Pathlength: X.X m" confirmations
- Regenerate if pathlengths were missed

---

## Reporting Issues to Support

### Information to Include:

1. **Command used:**
   ```bash
   python plot_ftir_spectra.py --directory ./data --output ./results.html --concentration-mode product
   ```

2. **Terminal output:**
   - Copy ENTIRE output (including any warnings)
   - Or screenshot the terminal window

3. **File structure:**
   ```bash
   ls -la my_data/  # Linux/Mac
   dir my_data\     # Windows
   ```

4. **Sample filenames:**
   - List 2-3 example CSV filenames
   - This helps diagnose parsing issues

5. **Python version:**
   ```bash
   python --version
   ```

6. **Dependencies:**
   ```bash
   pip list | grep -E 'pandas|numpy|plotly|scipy'  # Linux/Mac
   pip list | findstr "pandas numpy plotly scipy"  # Windows
   ```

### Email Template:

```
To: info@spectrascientific.ai
Subject: FTIR Analysis Issue - [Brief Description]

Problem description:
[What happened? What did you expect?]

Command used:
[Paste command here]

Terminal output:
[Paste full output here]

Sample filenames:
- Water [lab] (100ppm)_5m_001.csv
- Water [lab] (200ppm)_5m_002.csv
- ...

System info:
- OS: [Windows 10 / macOS 14 / Ubuntu 22.04]
- Python version: [from python --version]
- Package versions:
  pandas: X.X.X
  numpy: X.X.X
  plotly: X.X.X
  scipy: X.X.X

[Attach sample CSV file if possible]
```

---

## Advanced Diagnostics

### 1. Validate CSV Files

```bash
# Check CSV format (first 5 lines)
head -5 data/sample.csv  # Linux/Mac
type data\sample.csv | more  # Windows

# Expected:
# wavenumber,absorbance
# 499.96,0.0234
# 500.20,0.0241
```

### 2. Test Dependencies

```bash
python -c "import pandas, numpy, plotly, scipy; print('All OK')"
```

**Expected:** "All OK"
**If error:** Missing dependency, run `pip install -r requirements.txt`

### 3. Check File Permissions

```bash
# Ensure output directory is writable
touch test.txt && rm test.txt && echo "Writable" || echo "Not writable"
```

### 4. Run with Debug Output

```bash
# Python verbose mode
python -v plot_ftir_spectra.py --directory ./data --output ./out.html --concentration-mode product 2>&1 | tee debug.log

# Redirect all output to log file for inspection
```

---

## Known Limitations

1. **Minimum data requirement:**
   - Need ≥3 CSV files per species for fitting
   - Models cannot be fitted with fewer points

2. **Filename parsing strict:**
   - Concentration: Must be `(###ppm)` format
   - Pathlength: Second-to-last underscore segment
   - Deviations cause parse warnings/failures

3. **Browser limitations:**
   - HTML file size can be large (10-50 MB) for many wavenumbers
   - Older browsers may struggle with interactive plots
   - Use Chrome/Edge for best performance

4. **NRMSE threshold sensitivity:**
   - Too strict (< 0.01): Very few wavenumbers pass filter
   - Too loose (> 0.10): Poor-quality models included
   - Default 0.05 works for most cases

5. **Eigenvector optional:**
   - If no XLSX provided, eigenvector plot is empty
   - Does not affect model fitting - purely visual reference

---

## FAQ

**Q: Do I need product mode for Project2 compatibility?**
A: YES. Always use `--concentration-mode product` when generating libraries for MCR analysis (Project2). Concentration-mode libraries will be rejected by Project2 v1.0.0.

**Q: What if all my pathlengths are the same?**
A: Still use product mode! Even if pathlength=1.0m (constant), product mode ensures correct metadata is included in JSON exports. With constant pathlength, ppm and ppm·m are numerically equivalent.

**Q: Can I mix species with different concentration modes?**
A: No. All species in a single run must use the same mode (either all product or all concentration). This is enforced by the `--concentration-mode` flag.

**Q: How do I know if my models are good quality?**
A: Check NRMSE values in the diagnostic plots:
- NRMSE < 0.05: Excellent fit
- NRMSE 0.05-0.10: Acceptable fit
- NRMSE > 0.10: Poor fit, may need more data or different model

**Q: What's the difference between linear and saturation models?**
A: Linear model assumes absorbance ∝ concentration (Beer's Law). Saturation model accounts for detector saturation at high concentrations. The tool automatically selects the best model per wavenumber based on fit quality.

**Q: Can I edit the HTML files to change settings?**
A: Yes, the HTML files are standalone and editable. However, it's easier to use the interactive controls in the browser and export new settings JSON.

---

## Getting Help

**Email:** info@spectrascientific.ai

**Include:**
- Full terminal output
- Sample CSV filenames
- Command used
- Python and package versions

**Response time:** 1-2 business days

---

**Still having issues?** Email us at info@spectrascientific.ai with the diagnostic information above.
