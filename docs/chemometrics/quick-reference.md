# Chemometrics Quick Reference

!!! abstract "Summary"
    One table from the analysis you want to the **Analysis Starter** that
    builds it, the nodes it adds, the settings it starts with, what it
    reports, and the guide that explains it. Starter settings are starting
    points: review them for your data before you trust a result.

Open **Workflow → Analysis Starter**, pick the starter named in the second
column, and bind your dataset. The nodes then appear on the canvas, where you
can change any setting in the Inspector. See
[Build a Workflow on the Canvas](../workflows/build-a-workflow.md) for the
clicks.

## Find your task

| I want to… | Analysis Starter | Nodes it adds | Starter settings | What you get | Read |
| --- | --- | --- | --- | --- | --- |
| See sample structure, groups and outliers | **PCA Exploration & Outlier Diagnostics** | Filter → Fit PCA Transform → Detect Outliers | Scaling inside PCA: mean-centred spectra, autoscaled feature tables; 3 components; outlier limits at 95 % | Scores, loadings, explained variance, Hotelling T² and Q residuals | [PCA](pca.md) |
| Clean up spectra before modeling | **Preprocessing Pipeline** | Filter → Baseline (Penalized LS) → Smooth → Normalize | ALS baseline; Savitzky–Golay window 15, order 2; SNV | Corrected spectra for downstream nodes | [Preprocessing Spectra](../workflows/preprocessing.md) |
| Clean up Raman spectra | **Raman Processing Pipeline** | Cosmic Ray Removal → Baseline (Penalized LS) → Smooth → Scale / Center | Cosmic rays at z-score 5; ALS baseline; Whittaker smoothing; mean-centred | Corrected Raman spectra | [Preprocessing Spectra](../workflows/preprocessing.md) |
| Correct scatter against a reference | **MSC Reference Correction**, **EMSC Reference Correction**, **Target-Orthogonal Signal Correction** | Multiplicative Scatter Correction (MSC); EMSC; Orthogonal Signal Correction | MSC to the mean spectrum; EMSC requires explicit reference and known-interferent spectra, polynomial order 2; OSC with 1 component | Scatter-corrected spectra | [Preprocessing Nodes](../nodes/preprocessing.md) |
| Predict a property or concentration | **PLS Regression Calibration** | Train/Test Split → Fit PLS1 / PLS2 Regression (SIMPLS) → Predict Regression → Held-out Regression with Source Labels | Kennard–Stone split, 25 % test; **3 latent variables, fixed** (not chosen by cross-validation) | Held-out RMSE, MAE, bias, R², SEP, slope, intercept and RER; predicted-vs-measured plot | [PLS Calibration](pls.md) |
| Build a calibration on a representative training set | **Representative Calibration (Kennard-Stone)** | Smooth → Train/Test Split → Fit PLS → Predict Regression → Reference Regression Evaluator (v2) | Savitzky–Golay 15/2; Kennard–Stone, 25 % test; 4 latent variables | Held-out regression metrics | [Designing Validation](validation-design.md) |
| Calibrate on selected variables | **Variable Selection + PLS Calibration**, **VIP-Assisted PLS**, **Peak-Guided PLS** | Fit PLS → Variable Selection Rule → refit PLS on the selected variables | VIP threshold 1.0 (Peak-Guided PLS selects windows around peaks instead) | Selected variables and held-out regression metrics | [Selection and Validation Nodes](../nodes/selection-validation.md) |
| Compare variable-selection methods | **Variable Selection Comparison** | VIP rule, CARS, MC-UVE, SPA-MLR, Stability Selection → Compare Feature Selections | Each method's own defaults; 0.5 consensus threshold | Selected variables per method and their agreement | [Selection and Validation Nodes](../nodes/selection-validation.md) |
| Validate without selection leakage | **Nested CV (Leakage-Safe Validation)** | Smooth → Evaluate Nested CV Selection (with and without VIP selection) | 5 folds; 5 components | Outer-fold estimates for both designs | [Designing Validation](validation-design.md) |
| Assign samples to known classes | **Classification (PLS-DA)**, **KNN Classification**, **SIMCA Classification** | Train/Test Split → Train … Classifier → Apply Fitted … → Reference Classification Evaluator (v2) | Stratified split, 25 % test; PLS-DA 2 components; KNN k = 5; SIMCA 2 components, 95 %, data-driven (DD-SIMCA) limits | Confusion matrix, accuracy, sensitivity/recall, specificity where applicable, per-class results. SIMCA can return *unassigned* | [Classification](classification.md) |
| Accept or reject samples against one class (QC) | **Quality Control (SIMCA)**, *pending qualification* | Scale / Center → Train SIMCA Classifier | Autoscaled; 3 components; 95 % | Class acceptance diagnostics | [SIMCA QC](simca.md) |
| Find groups without labels | **Partition Clustering Comparison**, **Hierarchical Clustering** | Fit K-Means Clustering and Fit DBSCAN Clustering; Fit HCA Clustering | Autoscaled, k = 3, DBSCAN eps 0.45; mean-centred, Ward linkage, 3 clusters | Cluster assignments | [Exploratory Nodes](../nodes/exploratory.md) |
| Resolve mixtures into pure components | **MCR-ALS Curve Resolution**, **SIMPLISMA Pure Variables**, **Evolving Factor Analysis** (all need the optional SpectroChemPy extra); **NMF Mixture Decomposition**, **FastICA Blind Source Separation** | Fit MCR-ALS Decomposition; Fit SIMPLISMA Pure Components; Fit EFA Decomposition; Fit NMF Decomposition; Fit FastICA Decomposition | MCR-ALS 3 components, non-negative concentrations and spectra; SIMPLISMA 3 components; NMF 3 components | Resolved spectra and concentration-like profiles; MCR-ALS lack-of-fit | [MCR-ALS](mcr-als.md) |
| Find peaks and compare with a library | **Peak Detection** (add **Compare vs. Library** for reference matching) | Baseline (Penalized LS) → Smooth → Peak Finding | ALS baseline; Savitzky–Golay window 11, order 3; prominence 0.1 | Peak positions, prominence, widths and areas; HQI/cosine library ranking | [Peak Finding and Library Comparison](peaks-library.md) |
| Transfer a calibration between instruments | **Calibration Transfer Method Comparison** | Piecewise Direct Standardization, Direct Standardization, Single-Wavelength Standardization → Apply Fitted Spectral Transfer | Sequential split, 25 %; PDS half-window 3 | Transferred spectra for each method | [Preprocessing Nodes](../nodes/preprocessing.md) |
| Decompose genuinely multiway data | **PARAFAC Multiway Decomposition** (expert) | Fit PARAFAC Decomposition | 3 components | Mode loadings | [Exploratory Nodes](../nodes/exploratory.md) |

Pending starters are shown only when enabled in the picker. Their availability
and qualification status are distinct; a pending label is not a qualified result.
Starters that need the SpectroChemPy extra stop before running and say how to
install it; see [Optional SpectroChemPy Nodes](../nodes/spectrochempy.md).

## Metrics at a glance

The NMF starter explicitly clips negative intensities to zero before fitting;
review that transformation for baseline-corrected spectra. The PARAFAC starter
requires a declared hyperspectral cube, not an ordinary sample-by-wavelength table.

| Metric | Meaning in SpectraSherpa |
| --- | --- |
| RMSE | Root-mean-square prediction error, in target units. It describes the population it was computed on: calibration fit, cross-validation or a held-out test set. |
| MAE | Mean absolute prediction error, in target units. |
| Bias | Mean of predicted minus reference values; positive means predictions run high. |
| R² | 1 − (residual sum of squares ÷ reference sum of squares). It can be negative when predictions are worse than the reference mean, and is undefined for a constant reference. |
| SEP | Standard deviation of the residuals after removing the mean bias (n − 1 denominator); undefined for one sample. |
| Slope, intercept | Ordinary least-squares line of predicted on reference values. |
| RER | Reference-value range divided by SEP; undefined when SEP is zero or cannot be estimated. |
| Hotelling T² | Distance of a sample *inside* the PCA model plane: unusual but explained. |
| Q residual | Distance of a sample *from* the model plane: structure the model does not capture. |
| Confusion matrix, accuracy, sensitivity, specificity | Classification results against reference classes; SIMCA may also leave samples unassigned. |

A metric is only as meaningful as its population. Keep the evaluated
population, units, preprocessing and validation design with every number you
report; [Validation and Model Application](validation-application.md) gives
the full definitions and [Designing Validation](validation-design.md) explains
which design answers which question.

## Where to look next

- Every node's exact ports and parameters: [Node Library](../nodes/index.md).
- What each starter assumes about your data: [Templates](../workflow-templates/index.md).
- Terms used across the app: [Glossary](../concepts/glossary.md).
