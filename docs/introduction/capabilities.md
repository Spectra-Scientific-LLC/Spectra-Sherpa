# Current Capabilities

This page describes the **SpectraSherpa OSS v0.6.4 candidate (unreleased)**.
Source availability, Python-package publication and desktop-installer publication
are separate. See [installation](../onboarding/local-30-minutes.md).

## Scientific work

| Task | Available path | Check before interpreting |
| --- | --- | --- |
| Import and inspect | Qualified native readers, matrix preview, axes, source metadata and sample tables | Format variant, row order, missing values, axis quantity and units |
| Preprocess spectra | Smoothing/derivatives, baseline correction, normalization, scatter correction, scaling and region selection | Whether each transform is appropriate and where its fitted state was learned |
| Explore data | PCA, clustering, peak finding and library comparison | Sample structure, residuals and chemical plausibility; similarity is not identification |
| Calibrate | PLS regression, variable selection, calibration transfer and saved-model application | Target alignment, component selection, instrument compatibility and validation design |
| Classify or screen | KNN, PLS-DA and SIMCA | Class order, class balance, rejection behavior and held-out evidence |
| Resolve mixtures | EFA, MCR-ALS and SIMPLISMA with the optional SCP extra | Rank, constraints, initialization and solution ambiguity |
| Analyze multiway data | Native PARAFAC on explicitly modeled supported multiway inputs | Mode meaning and missing-data contract; no guided imaging/ROI workflow is included |
| Record and share | Saved runs, short/detailed reports, table/plot exports, supported Python/notebook exports and project packages | Retained result scope, source availability and recipient runtime requirements |

Use the [scientific guides](../chemometrics/index.md) for interpretation and the
[node reference](../nodes/index.md) for the source version's exact parameters
and ports. A template is a starting recipe, not a validated analytical method.

## Data and optional capabilities

The base installation includes the local Workbench, Python SDK and native
readers listed in [Supported file types](file-types.md). Reader support is
limited to documented variants, not every file with the same extension.

- **SCP extra:** EFA, MCR-ALS and SIMPLISMA. It adds no file readers or dataset catalog.
- **NIST extra:** configured WebBook acquisition; previously acquired local data
  can be used without a new network request.
- **HITRAN extra:** configured line-data acquisition and gas-phase synthesis.
  A personal key and permitted network access are also required.
- **Provider teaching data:** obtain files such as Corn directly from the
  provider, then import them. A catalog listing does not redistribute the data.

## Validation and reports

Calibration, cross-validation, held-out evaluation and application are distinct
result populations. Read the retained split/fold evidence and target units
alongside the metrics. Repeated validation measures sensitivity to partitions
of the same data; it does not create additional independent specimens.

Reports present saved results. They do not fit a missing model, invent missing
units or establish regulatory compliance. See
[Validation and model application](../chemometrics/validation-application.md)
and [Reports and exports](../workflows/reports-exports.md).

## AI and hosted-product boundary

Local OSS offers optional basic chat through a configured provider. It is not
the project-aware managed Advisor or hosted Optimize service. Computation does
not require AI, a subscription, or a hosted account. See
[Product boundaries](cloud-vs-local.md) and
[Scientific assistance](../onboarding/scientific-assistance.md).

## Limits

The installed Workbench executes its shipped canonical nodes; it does not load
drop-in plugins or arbitrary workflow code. Export support is contract-specific,
not a promise that every graph becomes a standalone script.

General hyperspectral-image analysis, unlisted vendor formats, laboratory
certification, and guaranteed predictive performance are not implied by the
available numerical methods. Check a representative file and a small workflow
before committing a full study.
