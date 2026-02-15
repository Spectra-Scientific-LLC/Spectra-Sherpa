# Reproduction & Verification Methodology

To ensure the Workflow Bench is a reliable scientific tool, we employ a rigorous "Dual-Implementation" verification strategy. This ensures that the GUI-based workflows produce results identical to the underlying `spectrochempy` library code.

## 1. The Verification Process

For every major algorithm (PCA, MCR-ALS, PLS), we maintain:
1.  **A "Golden" Notebook:** A Jupyter notebook (`docs/examples/*.ipynb`) running the raw Python code using `spectrochempy`.
2.  **A Test Script:** A Python script (`verify_parity.py`) that:
    *   Exports data from the Workflow Bench (CSV/JSON).
    *   Runs the equivalent logic in Python.
    *   Compares matrices element-by-element.

## 2. Methodology by Component

### A. Data Loading (DOE & Experiments)
We verify that file parsing, metadata extraction, and CSV export match exactly.

*   **Tool:** `verify_parity.py`
*   **Check:** Row counts, column names, and cell values.
*   **Tolerance:** Exact string matching.

### B. Preprocessing Algorithms
Algorithms like Smoothing and Baseline Correction are verified for numerical precision.

*   **Tool:** Unit tests (`tests/`)
*   **Check:** Output `NDDataset` data arrays.
*   **Tolerance:** Floating point epsilon (`1e-9`).

### C. Chemometrics (PCA, MCR, PLS)
Complex iterative algorithms are checked for convergence and output statistics.

*   **Tool:** Case Study Notebooks.
*   **Check:**
    *   **Eigenvalues/Variance:** Must match to 4 decimal places.
    *   **Scores/Loadings:** Must match in shape and magnitude. (Note: Sign flips are common in PCA/MCR; we check for absolute correlation).

## 3. Running Verification

You can run the verification suite locally:

```bash
# 1. Verify Examples (Runs the Python side of the case studies)
python3 verify_examples.py

# 2. Verify DOE Parity (Requires CSV export from UI)
python3 verify_parity.py
```

## 4. Current Parity Status

| Component | Status | Verified Against |
| :--- | :--- | :--- |
| **Data Loading** | ✅ Verified | SpectroChemPy 0.6.3 |
| **Savitzky-Golay** | ✅ Verified | Scipy/SpectroChemPy Implementation |
| **Baseline (ALS)** | ✅ Verified | SpectroChemPy `basc()` |
| **PCA** | ✅ Verified | SpectroChemPy `PCA` (SVD-based) |
| **MCR-ALS** | ⚠️ Beta | Validation pending for complex constraints |

**Note on Versions:** The Workflow Bench bundles `spectrochempy` version `x.x.x`. Parity is guaranteed only for this bundled version.
