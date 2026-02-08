# Workflow Bench vs. SpectrochemPy Gap Analysis

This report identifies potential issues when trying to reproduce SpectrochemPy scripts in the Workflow Bench.

## 1. Data Loading Parity
- **Notebook:** `scp.read("irdata/CO@Mo_Al2O3.SPG")`
- **Workflow Bench:** `DataSourceNode` supports loading specific example files via the `Example File` parameter.
- **Verification:** Ensure the `CO@Mo_Al2O3.SPG` file exists in the user's `~/.spectrochempy/data/irdata/` directory or the system's `datadir`. If missing, the node will fail.

## 2. Parameter Mapping
- **Baseline:**
  - Notebook: `basc(method="rubberband")`
  - Node: `BaselineRubberbandNode`. Matches exactly.

- **PCA:**
  - Notebook: `scp.PCA(n_components=3)`
  - Node `PCANode`: Parameters `n_components`, `standardized`, `scaled`.
  - **Gap:** SpectroChemPy's `PCA` defaults to `centered=True`. The Node implementation performs `scp.PCA(..., standardized=standardized, scaled=scaled)`.
  - **Risk:** If `standardized=False` and `scaled=False` are set (default in Node), SpectroChemPy might *still* mean center by default.
  - **Mitigation:** If results differ (e.g., PC1 looks like the mean spectrum), verify if explicit Mean Centering (`CenterMeanNode`) is required before PCA in the workflow.

## 3. Visualization
- **Notebook:** Can plot any arbitrary slice or overlay.
- **Workflow Bench:** Limited to pre-defined node outputs (Scores plot, Loadings plot).
- **Mitigation:** The UI's "Data View" or "Table" tab in the results pane allows inspecting specific values.

## Summary
The updated case study uses real data (`CO@Mo_Al2O3.SPG`). The key to reproducibility is ensuring the local SpectroChemPy data directory is populated (usually via `scp.download_data()` in Python if missing) and that the Workflow Bench has access to it.