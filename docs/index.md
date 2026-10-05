# SpectraSherpa

SpectraSherpa is a free open-source spectroscopy workbench for building reproducible analysis workflows. The current release is centered on **FTIR, NIR, Raman, and UV-VIS spectroscopy**: import files, inspect the data matrix, track provenance, preprocess spectra, run chemometrics, save models, and export results.

<figure class="ss-hero-figure">
  <img src="assets/workflow-canvas-hero.png" alt="SpectraSherpa workflow canvas showing connected data, model, plot, comparison, and table nodes." />
</figure>

## Choose Your Path

| Goal | Start Here |
| --- | --- |
| Install and run on your computer | [10 Minutes to Local Compute](onboarding/local-30-minutes.md) |
| Bring in your first dataset | [Import Your First Dataset](onboarding/import-first-dataset.md) |
| Compare cloud and local OSS | [Cloud vs Local OSS](introduction/cloud-vs-local.md) |
| Check supported formats | [Supported File Types](introduction/file-types.md) |
| See what is built today | [Current Capabilities](introduction/capabilities.md) |
| Contribute a canonical node | [Contributing](developers/contributing.md) and [Developer Setup](developers/setup.md) |

## Two Ways to Run

- **Local OSS** runs on your own machine with no login. You can inspect and modify the source, load your own data without hosted demo limits, and add optional extras for specialized algorithms, reference data, or HITRAN/HAPI synthesis.
- **SpectraSherpa Cloud** is the hosted enterprise/demo experience. It adds managed accounts, demo policy, Sherpa Advisor, and Ambient Guidance for users who want to evaluate the workflow in a browser.

## What Is Built Today

SpectraSherpa combines a visual workflow builder, spectroscopy-aware data handling, import transparency, preprocessing, PCA, PLS, classification, SIMCA QC, MCR-ALS, peak/library workflows, model artifacts, reports, exports, NIST reference data, and optional HITRAN/HAPI synthesis. Vendor readers are exposed only after native qualification; the detailed scope is maintained in [Current Capabilities](introduction/capabilities.md).

The v0.6.0 validation baseline also keeps grouped and repeated validation,
retained evidence, report figures, recorded independence evidence, and
analytical qualification claims visibly separate. Start with [Validation and
Model Application](chemometrics/validation-application.md) and [Reports and
Exports](workflows/reports-exports.md) when a result needs more than an
exploratory interpretation.

## Scientific Foundations

SpectraSherpa builds on scientific software and data resources maintained by the broader community, including [SpectroChemPy](attributions/spectrochempy.md), [NIST](attributions/nist.md), [HITRAN/HAPI](attributions/hitran.md), NumPy, SciPy, pandas, and scikit-learn. Cite upstream resources when they contribute to your analysis, and review [License](introduction/license.md) before redistribution or hosted use.
