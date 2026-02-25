# Applications Guide

Chemometric methods were born in spectroscopy, but the same multivariate math — PCA, PLS, MCR-ALS, classification — applies wherever you have a matrix of samples versus measured variables. SpectraSherpa's algorithm library covers the full analytical lifecycle: preprocessing, decomposition, calibration, classification, and deployment.

This guide maps specific analytical techniques to the SpectraSherpa nodes that support them.

---

## Analytical Chemistry

### Vibrational Spectroscopy (NIR, FTIR, Raman)

The backbone of chemometrics. Whether you are building a NIR moisture calibration, resolving mid-IR reaction intermediates with MCR-ALS, or classifying polymers by Raman fingerprint, the workflow is the same:

| Step | Algorithms | SpectraSherpa Nodes |
|------|-----------|-------------------|
| Scatter correction | SNV, MSC, EMSC | Preprocessing |
| Baseline removal | Polynomial, ALS, SNIP, rubberband | Preprocessing |
| Smoothing / derivatives | Savitzky-Golay, Whittaker, Gaussian | Preprocessing |
| Exploratory analysis | PCA, HCA | PCA, HCA |
| Quantitative calibration | PLS, PCR, SVR, linear regression | PLS, PCR, SVR, Linear Regression |
| Mixture resolution | MCR-ALS, EFA, SIMPLISMA, NMF, ICA | MCR-ALS, EFA, SIMPLISMA, NMF, Fast ICA |
| Classification | PLS-DA, KNN, K-Means, DBSCAN | Classification nodes |
| Validation | Cross-validation (K-fold), outlier detection (T², Q) | Diagnostics nodes |
| Deployment | Batch prediction, folder watching | Deploy Input/Output, Load & Apply Model |

### Terahertz (THz) Spectroscopy

THz spectra exhibit the same Beer-Lambert linearity and scattering effects as mid-IR. The identical preprocessing (baseline correction, SNV) and modeling (PLS, PCA) pipeline applies. SpectraSherpa treats THz data as any other spectral matrix — load, preprocess, model.

### UV-Vis Spectroscopy

UV-Vis measurements often have fewer spectral channels but the same calibration needs: quantitation via PLS/PCR, mixture unmixing via MCR-ALS, and sample screening via PCA. The preprocessing emphasis shifts to normalization and baseline correction rather than scatter correction.

### Fluorescence Spectroscopy (including EEM)

Excitation-Emission Matrix (EEM) data is inherently three-way (excitation × emission × samples). SpectraSherpa handles the unfolded two-way case today:

| Algorithm | Application |
|-----------|------------|
| PCA | Exploratory analysis of emission profiles |
| MCR-ALS | Unmixing overlapping fluorophores |
| NMF | Non-negative component extraction (physically meaningful for emission) |
| PLS | Quantitative analysis from emission spectra |

Three-way methods (PARAFAC, Tucker3, N-PLS) are planned for future releases.

### LIBS (Laser-Induced Breakdown Spectroscopy)

LIBS produces emission spectra virtually identical in structure to OES data. The main preprocessing challenge is shot-to-shot variability, addressed by normalization (area, L2, SNV) and averaging. After preprocessing, PCA for screening, PLS for elemental quantification, and PLS-DA / KNN for material classification follow the standard pipeline.

### X-ray Methods

**XRF / TXRF** — Elemental fluorescence spectra. PCA for sample fingerprinting, PLS/PCR for quantitative elemental analysis, HCA for provenance studies.

**XRD / HRXRD** — Diffraction patterns. PCA for phase mixture analysis, PLS for quantitative phase determination, KNN for phase classification.

**XPS** — Binding energy spectra from surface analysis. PCA for compositional screening, MCR-ALS for chemical state decomposition, PLS for quantitative surface stoichiometry.

### Mass Spectrometry

**GC-MS / LC-MS** — Mass spectral matrices are treated the same as any spectral dataset. PCA and PLS-DA are the workhorses for metabolomics and biomarker discovery. MCR-ALS resolves co-eluting chromatographic peaks. HCA groups samples by spectral similarity.

**TOF-SIMS** — Surface mass spectra and images. PCA for spatial composition mapping, NMF for component extraction (naturally non-negative), MCR-ALS for chemical phase identification, K-Means for pixel-wise segmentation.

**ICP-MS** — Multi-element concentration profiles rather than continuous spectra, but the same multivariate classification applies. PCA and HCA for geographic origin / provenance studies, PLS-DA and KNN for sample classification by elemental fingerprint.

### Atomic Emission Spectroscopy

**ICP-OES** — Optical emission spectra from inductively coupled plasma. PCA for multi-element fingerprinting, PLS for quantitative elemental analysis, HCA and PLS-DA for provenance and classification studies. Shares its chemometric toolkit with other emission techniques (OES, LIBS) rather than with mass spectrometry.

### NMR Spectroscopy (Benchtop / Low-Field)

Low-field and benchtop NMR spectra respond well to PCA for mixture profiling, PLS/PLS-DA for quantification and classification, and MCR-ALS for deconvolution. Preprocessing emphasis is on baseline correction and smoothing.

Specialized NMR alignment methods (COW, icoshift) and statistical correlation methods (STOCSY, OPLS) are planned for future releases.

### Hyperspectral Imaging (HSI)

Hyperspectral images unfold to (pixels × wavelengths) — a standard spectral matrix. SpectraSherpa's nD array support (`SherpaDataset` with inner spatial dimensions) handles the unfolding. PCA for dimensionality reduction, MCR-ALS for endmember extraction, K-Means/DBSCAN for pixel classification, and PLS for property prediction all apply directly.

### Sensor Arrays (Electronic Nose / Tongue)

Electronic nose and electronic tongue instruments produce sensor response matrices rather than continuous spectra, but the pattern recognition pipeline is identical: PCA for visualization, PLS for concentration prediction, KNN/PLS-DA for classification, and K-Means/HCA for unsupervised grouping.

---

## Semiconductor Metrology

SpectraSherpa's chemometric toolkit maps directly to semiconductor fab metrology. Spectral and multi-sensor data from process tools drive fault detection, process control, and virtual metrology — applications where data privacy, reproducibility, and inline deployment are non-negotiable.

### Metrology Tools and Algorithms

| Tool | Data Type | Preprocessing | Modeling | Classification |
|------|-----------|--------------|----------|---------------|
| **OES** (plasma etch / deposition) | Emission spectra (200–900 nm) | SNV, normalization, baseline | PCA, PLS, PCR | PLS-DA, KNN, outlier detection |
| **FTIR** (thin film, contamination) | Absorption / transmission spectra | Baseline, derivatives, SNV | PCA, PLS, MCR-ALS | KNN |
| **Raman** (stress, composition) | Raman shift spectra | Baseline, cosmic ray removal | PCA, PLS, MCR-ALS | K-Means |
| **XRF / TXRF** (elemental composition) | Fluorescence spectra | Normalization | PCA, PLS | KNN |
| **XRD / HRXRD / CD-SAXS** (crystal structure, CD) | Diffraction patterns | Baseline, normalization | PCA, PLS | HCA, KNN |
| **XPS** (surface chemistry) | Binding energy spectra | Baseline | PCA, MCR-ALS, PLS | — |
| **TOF-SIMS** (surface contamination) | Mass spectra / images | Normalization | PCA, MCR-ALS, NMF | PLS-DA, K-Means |
| **Virtual metrology** (multi-sensor) | Mixed sensor + spectral feeds | Normalization, outlier removal | PCA, PLS, SVR | Outlier detection |

### Typical Semiconductor Workflows

**Fault Detection & Classification (FDC)**

```
OES Data Source → SNV Normalization → PCA → Outlier Detection (T², Q)
                                       ↓
                                    PLS-DA → Fault Classification
```

Monitor plasma etch emission spectra in real time. PCA captures the normal operating space; T² and Q residuals flag process excursions. PLS-DA classifies the fault type for root cause analysis.

**Virtual Metrology**

```
Multi-Sensor Input → Normalization → PLS → Predicted CD / Thickness / Etch Rate
                                      ↓
                                Model Artifact → Deploy for inline prediction
```

Replace or supplement physical metrology (SEM, ellipsometry) with PLS models trained on sensor data. SpectraSherpa's batch prediction and folder watching features enable the model to run continuously against tool data feeds.

**Thin Film Composition Monitoring**

```
XRF Spectra → Baseline Correction → PLS Calibration → Composition Prediction
                                      ↓
                              Cross-Validation (K-fold)
```

Build and validate PLS calibrations for elemental composition from XRF or TXRF. Export the trained model artifact and deploy for inline monitoring of deposition processes.

**Contamination Screening (TOF-SIMS)**

```
TOF-SIMS Spectra → Normalization → PCA → Score Plot → K-Means Clustering
                                    ↓
                               NMF → Component Identification
```

Screen wafer surfaces for organic or metallic contamination. PCA separates clean from contaminated sites; NMF extracts physically meaningful (non-negative) mass spectral components for identification.

---

## Common Workflow Pattern

Regardless of the technique, the SpectraSherpa workflow follows the same structure:

```
1. Load data          →  Data Source node (CSV, instrument file, reference dataset)
2. Preprocess         →  Baseline, smoothing, normalization, scatter correction
3. Explore            →  PCA, HCA for sample grouping and outlier screening
4. Model              →  PLS, MCR-ALS, NMF for quantitation or resolution
5. Classify           →  PLS-DA, KNN for sample identification
6. Validate           →  Cross-validation, outlier detection (T², Q)
7. Deploy             →  Save model artifact → Load & Apply on new data
```

This universality is by design. The same pipeline that builds a NIR moisture calibration also builds a virtual metrology model for semiconductor etch — only the data source and preprocessing choices differ.
