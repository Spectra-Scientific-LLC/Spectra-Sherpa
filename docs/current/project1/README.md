# FTIR Spectral Analysis & Calibration Tool v1.0.0

**Copyright © Spectra Scientific LLC** | Intel SOW (Oct 15, 2025)

---

## Overview

This tool analyzes FTIR (Fourier Transform Infrared) spectroscopy data to create calibrated spectral signatures for chemical species. It fits linear and saturation models to concentration-dependent absorbance data, producing interactive HTML visualizations and exportable calibration parameters.

**Use Case:** Generate calibration models from controlled laboratory measurements for use in multi-component analysis (see [Project2](../Project2_release/)).

---

## Key Features

- **Automatic Model Selection**: Compares linear vs. saturation models per wavenumber, selects best fit based on NRMSE
- **Interactive Visualization**: Explore spectra, model parameters, and fit quality across the full wavenumber range
- **Quality Control**: Filter by absorbance outliers and NRMSE thresholds to ensure production-ready models
- **Multi-Species Support**: Process multiple chemical species in one run with centralized settings management
- **JSON Export**: Export calibrated model parameters for downstream MCR-ALS analysis
- **Validation Plots**: Full-spectrum reconstruction with residuals to verify model quality

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Or manually:
```bash
pip install pandas numpy plotly scipy
```

### 2. Prepare Your Data

Organize FTIR CSV files with concentration/pathlength metadata in filenames:

```
my_data/
├── Water [metadata] (100ppm)_5m_001.csv
├── Water [metadata] (200ppm)_5m_002.csv
├── CO2 [metadata] (50ppm)_10m_001.csv
└── eigenvector.xlsx  # Optional
```

**CSV Format:**
```csv
wavenumber,absorbance
499.96,0.0234
500.20,0.0241
...
```

### 3. Run Analysis

```bash
python plot_ftir_spectra.py --directory ./my_data --output ./results.html
```

### 4. View Results

- **Single species**: Opens species-specific HTML automatically
- **Multiple species**: Opens `results_selector.html` → click species name → explore calibration

---

## Documentation

📖 **[QUICKSTART.md](QUICKSTART.md)** - 5-minute setup guide with examples

📖 **[INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md)** - Comprehensive reference (17 KB)
- Detailed data format specifications
- Filename parsing rules (concentration, pathlength extraction)
- Model selection algorithms (linear vs. saturation)
- Quality control parameters (outlier thresholds, NRMSE)
- Interactive features guide
- Multi-species workflow

📖 **[EXPORT_FEATURE.md](EXPORT_FEATURE.md)** - JSON export format for calibrated models

📖 **[NRMSE_IMPLEMENTATION.md](NRMSE_IMPLEMENTATION.md)** - Fit quality metric details

📖 **[MULTI_SPECIES_IMPLEMENTATION_PLAN.md](MULTI_SPECIES_IMPLEMENTATION_PLAN.md)** - Multi-species architecture

---

## Workflow Integration

This tool is **Project1** in a two-stage analysis pipeline:

1. **Project1** (this tool): Calibrate spectral signatures from pure-component lab data
2. **[Project2](../Project2_release/)**: Analyze field measurements using MCR-ALS to unmix components

See [Project2 WORKFLOW.md](../Project2_release/WORKFLOW.md) for the complete pipeline.

---

## Output Files

### HTML Visualizations
- **Per-species viewer**: Interactive plots with wavenumber navigation
  - Scatter plots (concentration vs. absorbance)
  - Model comparison (linear vs. saturation)
  - Eigenvector overlay (if provided)
  - Fit quality diagnostics (NRMSE, slope/c, s/p parameters)
  - Full-spectrum validation with residuals

- **Multi-species selector**: Centralized settings manager
  - Set quality thresholds per species
  - Manage wavenumber ranges
  - Save/load settings as JSON

### Exported Data
- **`*_model.json`**: Calibrated model parameters (slope, intercept, s, p, c per wavenumber)
  - Used as input for Project2 MCR analysis
  - Includes only wavenumbers passing NRMSE threshold
  - Hybrid format: mix of linear and saturation models per wavenumber

---

## Example Command Line Usage

```bash
# Single species (product mode - RECOMMENDED)
python plot_ftir_spectra.py \
  --directory ./water_data \
  --output water.html \
  --concentration-mode product

# Multi-species (product mode - REQUIRED for Project2 compatibility)
python plot_ftir_spectra.py \
  --directory ./multi_species \
  --output calibration.html \
  --concentration-mode product

# Legacy concentration-only mode (NOT compatible with Project2)
python plot_ftir_spectra.py \
  --directory ./water_data \
  --output water.html \
  --concentration-mode concentration

# Custom output location
python plot_ftir_spectra.py \
  --directory ~/ftir_data \
  --output ~/Desktop/analysis.html \
  --concentration-mode product
```

**IMPORTANT:** Always use `--concentration-mode product` for libraries that will be used in downstream MCR analysis (Project2).

---

## System Requirements

- **Python**: 3.8 or higher
- **Dependencies**: See [requirements.txt](requirements.txt)
- **Data**: Minimum 3 CSV files per species for model fitting
- **Memory**: ~100 MB per 1000 wavenumbers × 20 concentrations

---

## Scientific Attribution

This software implements spectral analysis methodology based on:

- Jaumot, J., de Juan, A., & Tauler, R. (2015). MCR-ALS GUI 2.0: New features and applications. *Chemometrics and Intelligent Laboratory Systems*, 140, 1-12.

- de Juan, A., Jaumot, J., & Tauler, R. (2014). Multivariate Curve Resolution (MCR). Solving the mixture analysis problem. *Analytical Methods*, 6(14), 4964-4976.

- Pomerantsev, A. L., Zontov, Y. V., & Rodionova, O. Y. (2014). Nonlinear multivariate curve resolution alternating least squares (NL-MCR-ALS). *Journal of Chemometrics*, 28(10), 740-748.

---

## Support

For questions, bug reports, or feature requests:

**Email**: info@spectrascientific.ai

Please include:
- Brief description of your issue
- Sample data files (if applicable)
- Error messages or screenshots
- Python version and OS

---

## License

**Proprietary Software** - Internal Use Only

This software was developed by Spectra Scientific LLC under contract with Intel Corporation (SOW dated Oct 15, 2025). All rights reserved.

**Restrictions**:
- No redistribution without written permission
- For use by authorized Intel personnel only
- Source code modifications require approval

For licensing inquiries, contact: info@spectrascientific.ai

---

## Version History

**v1.0.0** (2025-12-10)
- Initial production release
- Multi-species support with centralized settings
- Linear and saturation model fitting
- NRMSE-based quality control
- Interactive HTML visualization
- JSON model export for Project2 integration

---

## Related Projects

- **[Project2_release](../Project2_release/)**: Multi-component MCR-ALS analysis tool
  - Consumes calibrated models from Project1
  - Analyzes field measurements with unknown mixtures
  - Estimates component concentrations over time/space

---

**Developed by Spectra Scientific LLC** | info@spectrascientific.ai
