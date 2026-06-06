# Current Capabilities

This page describes the documented production path for the current release.

## What Is Built

SpectraSherpa is already a full spectroscopy workbench for first-pass method development, exploratory chemometrics, calibration review, and guided reporting. It is not just a Python package wrapped in a UI. The product combines spectroscopy-aware data handling, a visual workflow engine, model artifacts, reporting/export, optional scientific reference data, and Cloud Advisor/Guidance assistance in one place.

Key capabilities built today:

- **GUI-first workflow building** for importing, inspecting, preprocessing, modeling, validating, reporting, and exporting without notebooks for the common path.
- **Data transparency at import** with file names, extensions, metadata, spectral axis, and data-matrix shape shown before users commit to modeling.
- **Spectroscopy-aware dataset model** where wavenumber/wavelength axes, spectral matrices, sample metadata, processing history, reference libraries, and data-role semantics are first-class concepts.
- **Reproducible workflow DAG builder** with connected nodes for data, preprocessing, modeling, validation, plots, tables, reports, exports, parameters, inputs, outputs, and artifacts.
- **Template library** for PCA, PLS calibration, classification, SIMCA QC, MCR-ALS, peak workflows, and spectroscopy-specific starters.
- **Core chemometrics** for PCA, PLS regression, KNN, PLS-DA, SIMCA-style classification/QC, MCR-ALS, peak finding, variable selection, and validation.
- **Model and validation outputs** where PLS, classification, SIMCA, PCA, and MCR workflows surface interpretable plots, metrics, and saved artifacts.
- **Report and export path** for carrying exploratory analyses into shareable scientific records and portable outputs.
- **Reference and synthesis workflows** around NIST data and optional HITRAN/HAPI line-by-line synthesis.
- **Recommended Eigenvector Research example catalogs** for realistic NIR and OES chemometrics workflows, with runtime/local download rather than redistribution in the wheel.
- **SpectroChemPy extra support** for Thermo OMNIC/OMNICxi `.spa`, `.spg`, `.srs`, Bruker `.opus`, Galactic `.spc`, Renishaw `.wdf`, vendor `.txt`/`.dat`, example datasets, and coordinate-aware algorithms.
- **Cloud Advisor and Ambient Guidance** for onboarding, interpretation drafts, scientific review, and contextual next-step suggestions.
- **Extension surfaces** for OSS users and developers to add nodes, providers, export behavior, and deployment-specific policy without rewriting the workbench.

## Spectroscopy Focus

SpectraSherpa is currently documented for **FTIR, NIR, Raman, and UV-VIS spectroscopy**. The strongest path is:

1. Import spectra from user files, example datasets, or reference libraries.
2. Inspect file names, extensions, metadata, and the data matrix.
3. Apply spectral preprocessing.
4. Run PCA, PLS calibration, classification, SIMCA QC, MCR-ALS, or peak/library workflows.
5. Review plots, tables, metrics, and reports.
6. Save models or export results.

## Fit and Boundaries

SpectraSherpa is strongest when the goal is quantitative calibration, reproducible spectroscopy workflow review, and a browser-based workbench that can move from local OSS evaluation to managed Cloud deployment.

| Current fit | Confirm before relying on SpectraSherpa |
| --- | --- |
| Quantitative calibration: PLS regression with variable selection, calibration transfer, and applicability-domain checks on saved models | Hyperspectral **imaging** workflows that need image-cube exploration, ROI tools, or linked image/spectra views |
| Browser-based, multi-user evaluation that can deploy from local OSS to managed Cloud | Modalities outside the documented FTIR/NIR/Raman/UV-VIS scope |
| File provenance, spectral axes, workflow templates, scientific reporting, and Python export as first-class concepts | Instrument formats outside the current base readers and SpectroChemPy-backed `.spa`, `.spg`, `.srs`, `.opus`, `.spc`, `.wdf`, `.txt`, and `.dat` matrix |
| Optional AI assistance for plot explanation, preprocessing choices, report wording, and contextual guidance | Fully offline desktop operation with no server component |

The goal is fit, not feature count. SpectraSherpa's product layer is centered on spectroscopy provenance, spectral axes, templates, chemometrics node contracts, reporting, and deployment for calibration and method-development workflows.

## Documented Scientific Scope

The public docs cover the following current capabilities:

- CSV, JCAMP-DX, NumPy, MAT, and SpectroChemPy-backed vendor formats: Thermo OMNIC/OMNICxi `.spa`, `.spg`, `.srs`, Bruker `.opus`, Galactic `.spc`, Renishaw `.wdf`, and vendor `.txt`/`.dat`
- FTIR, NIR, Raman, and UV-VIS data import and preprocessing
- PCA exploratory analysis and diagnostics
- PLS regression calibration, VIP scores, coefficients, and CV predictions
- KNN, PLS-DA, and SIMCA classification
- SIMCA-style acceptance/QC concepts
- MCR-ALS and self-modeling curve-resolution workflows
- peak finding with positions, prominence, FWHM-like widths, areas, and consensus across spectra; Peak ID assistance; and library comparison with HQI/cosine similarity scores
- Eigenvector Research NIR/OES example catalog support via user-local runtime download/cache
- NIST reference workflows and synthetic FTIR examples
- HITRAN/HAPI synthesis when the optional extra and API key are configured
- workflow templates, model artifacts, reports, and exports

## Reference Foundations

NIST and HITRAN are both important spectroscopy foundations, but they enter SpectraSherpa differently.

- **NIST** supports reference-library and quantitative infrared workflows around public scientific data resources such as the NIST Chemistry WebBook and NIST Quantitative Infrared data.
- **HITRAN/HAPI** supports line-by-line gas-phase spectral synthesis when the optional extra, API key, and network access are configured.

SpectroChemPy is an optional software foundation for additional readers, example datasets, and coordinate-aware spectroscopy algorithms. NumPy, SciPy, pandas, and scikit-learn provide much of the numerical computing base.

## Out of Scope for First-Run Onboarding

The production documentation does not teach exploratory modality stories that lack a verified data source, template, plots, metrics, and user story. For a first evaluation, stay with the documented FTIR, NIR, Raman, and UV-VIS paths above.
