# Current Capabilities

This page describes implemented capabilities and their product boundaries.
Availability depends on the published release and the deployment profile.

For the v0.6.0 deployment candidate, the validation and reporting surfaces
described below are part of the current capability baseline. They preserve
claim limits explicitly: a repeat, a recorded identity comparison, or a
qualification dossier is evidence with a declared scope, not an automatic
independent-validation or regulatory claim.

## What Is Built

SpectraSherpa is already a full spectroscopy workbench for first-pass method development, exploratory chemometrics, calibration review, and guided reporting. It is not just a Python package wrapped in a UI. The product combines spectroscopy-aware data handling, a visual workflow engine, model artifacts, reporting/export, optional scientific reference data, and Cloud Advisor/Guidance assistance in one place.

Key capabilities built today:

- **GUI-first workflow building** for importing, inspecting, preprocessing, modeling, validating, reporting, and exporting without notebooks for the common path.
- **Data transparency at import** with file names, extensions, metadata, spectral axis, and data-matrix shape shown before users commit to modeling.
- **Spectroscopy-aware dataset model** where wavenumber/wavelength axes, spectral matrices, sample metadata, processing history, reference libraries, and data-role semantics are first-class concepts.
- **Reproducible workflow DAG builder** with connected nodes for data, preprocessing, modeling, validation, plots, tables, reports, exports, parameters, inputs, outputs, and artifacts.
- **Template library** for PCA, PLS calibration, classification, SIMCA QC, MCR-ALS, peak workflows, and spectroscopy-specific starters.
- **Core chemometrics** for PCA, PLS regression, KNN, PLS-DA, SIMCA-style classification/QC, MCR-ALS, PARAFAC, peak finding, variable selection, and validation.
- **Model and validation outputs** where PLS, classification, SIMCA, PCA, and MCR workflows surface interpretable plots, metrics, and saved artifacts.
- **Leakage-aware validation** with explicit train/test group authority, nested
  inner tuning, grouped outer and inner folds, deterministic split receipts,
  and refusal of row-ranking split methods when they cannot preserve groups.
- **Repeated validation evidence** that keeps repeat, fold, seed, selected
  component, and selection-stability identities. Repeated results report
  partition sensitivity for the same dataset; they never inflate the specimen
  count or turn repeat spread into a confidence interval.
- **Evidence-bound reporting** for saved runs and campaign verification. Reports
  retain population, preprocessing, tuning, exclusions, target units, metric
  definitions, and claim limitations. Row-level reference/prediction/residual
  values and SVG figures are opt-in and are refused or marked unavailable when
  the retained evidence is missing or exceeds the 5,000-row figure limit.
- **Recorded independence evidence** that distinguishes comparison with
  operator-supplied specimen/batch lists from declared sampling independence
  and unknown evidence. Matching IDs do not authenticate a register or prove
  population independence.
- **Report and export path** for carrying exploratory analyses into shareable scientific records and portable outputs.
- **Reference and synthesis workflows** around NIST data and optional HITRAN/HAPI line-by-line synthesis.
- **Recommended Eigenvector Research example catalogs** for realistic NIR and
  OES chemometrics workflows. The scientist obtains each source directly from
  Eigenvector; Sherpa does not retrieve or redistribute it.
- **SpectroChemPy extra support** for exactly EFA, MCR-ALS, and SIMPLISMA through a private matrix-only adapter. It adds no datasets, public conversion API, or file readers.
- **Managed Cloud Advisor and Ambient Guidance** for onboarding, interpretation drafts, scientific review, and contextual next-step suggestions.
- **Extension surfaces** for OSS users and developers to add nodes, providers, export behavior, and deployment-specific policy without rewriting the workbench.

## AI assistance by product

Local OSS (pip and desktop) supports basic chat through a user-configured model
endpoint and key. It is useful for scientific methods and help using the
workbench. Configure the provider before using AI; an unavailable provider is
reported instead of silently sending the request elsewhere. Local scientific
workflows do not require an AI key or a paid account.

Demo and Pro provide managed Sherpa Advisor: project-aware scientific help,
workflow proposals, and eligible optimization campaigns within the applicable
access and usage limits. Advisor can use permitted workflow and retained-result
context and the active window or plot. A proposed workflow is a reviewable draft,
and campaign execution follows its own admission and approval process.

An eligible selected fitted application can be exported from managed Cloud,
verified and imported locally, and used for folder-watch inference without a
subscription. Optimize retains its source-run/workflow links and signed package
and publisher-key downloads, and can open the selected result as a separate
workflow for inspection. Review package support does not make the managed
optimization service part of OSS.

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
| Quantitative calibration: PLS regression with variable selection, calibration transfer, and applicability-domain checks on saved models | Guided hyperspectral **imaging** workflows that need ROI tools, linked image/spectra views, or analysis starters; 0.6 has only an expert, manually constructed native DSO image-cube → masked PARAFAC path |
| Browser-based, multi-user evaluation that can deploy from local OSS to managed Cloud | Modalities outside the documented FTIR/NIR/Raman/UV-VIS scope |
| File provenance, spectral axes, workflow templates, scientific reporting, and Python export as first-class concepts | Unqualified vendor variants and container families outside the closed native-reader grammars |
| Local scientific workflows and folder-watch inference; optional BYOK or managed AI assistance according to product | AI and remote reference requests need their configured provider; offline scientific execution still uses the bundled or locally installed backend |

The goal is fit, not feature count. SpectraSherpa's product layer is centered on spectroscopy provenance, spectral axes, templates, chemometrics node contracts, reporting, and deployment for calibration and method-development workflows.

## Documented Scientific Scope

The public docs cover the following current capabilities:

- CSV, JCAMP-DX, NumPy, MATLAB v4/v5 and v7.3/HDF5, the qualified Eigenvector PLS_Toolbox DSO contract, qualified Galactic SPC, one-dimensional Bruker OPUS, qualified legacy OMNIC SPA/SPG/SRS, and qualified Renishaw WiRE WDF native ingestion
- FTIR, NIR, Raman, and UV-VIS data import and preprocessing
- PCA exploratory analysis and diagnostics
- PLS regression calibration, VIP scores, coefficients, and CV predictions
- KNN, PLS-DA, and SIMCA classification
- SIMCA-style acceptance/QC concepts
- MCR-ALS and self-modeling curve-resolution workflows
- native deterministic PARAFAC for explicitly modeled multiway data, including
  a privately qualified masked image-cube path for the exact registered IASIM16
  Test 1 DSO; no PARAFAC analysis starter or general HSI workflow is claimed
- peak finding with positions, prominence, FWHM-like widths, areas, and consensus across spectra; Peak ID assistance; and library comparison with HQI/cosine similarity scores
- Eigenvector Research NIR/OES catalog guidance plus user-selected local or
  registered-reference admission
- NIST reference workflows and synthetic FTIR examples
- HITRAN/HAPI synthesis when the optional extra and API key are configured
- workflow templates, model artifacts, reports, and exports

## Validation and evidence boundary

The v0.6.0 validation path has five separate authorities:

1. the executed workflow and its retained split/fold evidence;
2. the metric registry and the population it evaluates;
3. recorded specimen or batch identity comparisons;
4. operator declarations about sampling, chronology, and intended use; and
5. an explicit human qualification decision.

The product keeps these authorities separate in the Workbench, SDK, saved-run
reports, campaign verification reports, and analytical qualification dossiers.
No one of them silently upgrades another. In particular, repeated validation
is not external validation, identity comparison is not laboratory
independence, and deploy readiness is not qualification for a laboratory use.

## Reference Foundations

NIST and HITRAN are both important spectroscopy foundations, but they enter SpectraSherpa differently.

- **NIST** supports reference-library and quantitative infrared workflows around public scientific data resources such as the NIST Chemistry WebBook and NIST Quantitative Infrared data.
- **HITRAN/HAPI** supports line-by-line gas-phase spectral synthesis when the optional extra, API key, and network access are configured.

SpectroChemPy is an optional software foundation for EFA, MCR-ALS, and
SIMPLISMA through a private matrix adapter. It adds no reference-data catalog,
public conversion API, or native-ingestion capability. NumPy, SciPy, pandas,
and scikit-learn provide much of the numerical computing base.

## Out of Scope for First-Run Onboarding

The production documentation does not teach exploratory modality stories that lack a verified data source, template, plots, metrics, and user story. For a first evaluation, stay with the documented FTIR, NIR, Raman, and UV-VIS paths above.
