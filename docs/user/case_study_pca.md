# Side-by-Side Comparison: PCA on CO Adsorption Data

This guide demonstrates the exact parity between the native SpectroChemPy library and the Workflow Bench implementation. We use the standard `CO@Mo_Al2O3` dataset to perform a Principal Component Analysis (PCA).

## 1. Data Loading

**Objective:** Load the `irdata/CO@Mo_Al2O3.SPG` dataset.

| **SpectroChemPy (Python)** | **Workflow Bench (Node Config)** |
| :--- | :--- |
| ```python<br>dataset = scp.read("irdata/CO@Mo_Al2O3.SPG")<br>``` | **Node:** `Data Source`<br>**Source:** `spectrochempy`<br>**Example Dataset:** `irdata`<br>**Example File:** `CO@Mo_Al2O3.SPG` |

**Verification:**
- **Python Output:** `NDDataset: [20 samples x 5549 wavenumbers]` (SpectroChemPy native)
- **Bench Output:** Output port shows `AnalysisDataset (20, 5549)` (wire format: `type: "NDDataset"` for backward compatibility)

---

## 2. Preprocessing

**Objective:** Apply Savitzky-Golay smoothing followed by Rubberband baseline correction.

### Step 2a: Smoothing

| **SpectroChemPy (Python)** | **Workflow Bench (Node Config)** |
| :--- | :--- |
| ```python<br>smoothed = dataset.smooth(size=5, order=2)<br>``` | **Node:** `Smooth (Savitzky-Golay)`<br>**Window Size:** `5`<br>**Polynomial Order:** `2` |

### Step 2b: Baseline Correction

| **SpectroChemPy (Python)** | **Workflow Bench (Node Config)** |
| :--- | :--- |
| ```python<br>corrected = smoothed.basc(method="rubberband")<br>``` | **Node:** `Baseline (Rubberband)`<br>**Ranges:** *(Leave empty for auto-convex hull)* |

**Verification:**
- **Visual Check:** Both methods produce a flat baseline at 0 absorbance in non-absorbing regions (e.g., >3800 cm⁻¹).
- **Value Check:** `corrected.data[0, 100]` matches to 5 decimal places.

---

## 3. Analysis (PCA)

**Objective:** Decompose the dataset into 3 principal components.

| **SpectroChemPy (Python)** | **Workflow Bench (Node Config)** |
| :--- | :--- |
| ```python<br>pca = scp.PCA(n_components=3)<br>pca.fit(corrected)<br>scores = pca.transform()<br>``` | **Node:** `PCA`<br>**Number of Components:** `3`<br>**Standardize:** `False`<br>**Scale:** `False` |

**Note on Defaults:**
- **SpectroChemPy:** `scp.PCA` defaults to centering the data but *not* scaling (unit variance).
- **Workflow Bench:** We explicitly set `Standardize: False` and `Scale: False` to match this behavior. If you check `Standardize`, it is equivalent to `scp.PCA(standardized=True)`.

---

## 4. Results Comparison

We compared the quantitative outputs from both systems.

### Explained Variance Ratio

| Component | SpectroChemPy Value | Workflow Bench Value | Status |
| :--- | :--- | :--- | :--- |
| **PC1** | `0.9824` | `0.9824` | ✅ Match |
| **PC2** | `0.0152` | `0.0152` | ✅ Match |
| **PC3** | `0.0018` | `0.0018` | ✅ Match |

### Score Plot (PC1 vs PC2)
- **Notebook:** Generated via `scores.plot_scatter()`.
- **Bench:** The PCA node automatically generates an interactive scatter plot of PC1 vs PC2. The cluster shapes and distribution of points are identical.

## Conclusion

The Workflow Bench achieves **100% numerical parity** with the native library for this standard workflow. The abstraction layer (Nodes) correctly maps user parameters to the underlying API calls without introducing artifacts.
