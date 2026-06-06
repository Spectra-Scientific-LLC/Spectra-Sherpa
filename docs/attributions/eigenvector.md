# Eigenvector Research Example Datasets

Eigenvector Research hosts several classic chemometrics datasets that are useful for learning SpectraSherpa and for checking NIR/OES workflow behavior:

- Diesel NIR calibration data
- Corn NIR instrument-standardization data
- CGL NIR data
- IDRC 2002 NIR Shootout data
- SEMATECH/Texas Instruments metal-etch OES and process-monitoring data

These are excellent datasets for PCA, PLS calibration, classification, process monitoring, calibration transfer, and workflow export checks. SpectraSherpa strongly recommends downloading and caching them during local onboarding because they are well known in the chemometrics community and exercise realistic spectral shapes, targets, missing values, and instrument differences.

## Download Model

SpectraSherpa catalogs these datasets but does **not** redistribute the raw Eigenvector files in the Python wheel or source distribution.

When a user selects an Eigenvector dataset, SpectraSherpa will use a local cache if the files are already present. If runtime download is enabled, SpectraSherpa can download the upstream archive from Eigenvector Research and cache only the user's local copy.

For local OSS use, we recommend enabling runtime download before the first serious workflow exercise with either:

```bash
EGRESS_ENABLED=true
```

or, for only these examples:

```bash
SPECTRASHERPA_EIGENVECTOR_DOWNLOADS=true
```

If downloads are disabled, SpectraSherpa leaves the catalog visible and reports the exact source files needed. Download the datasets from [Eigenvector Research data sets](https://eigenvector.com/resources/data-sets/) and place them under the local SpectraSherpa reference cache shown in the error message.

## Attribution

The datasets remain Eigenvector Research and contributor data. Cite the original source and contributor guidance when using them in reports, publications, teaching material, or validation records:

- Eigenvector Research data sets: <https://eigenvector.com/resources/data-sets/>
- Original contributors include Cargill, Southwest Research Institute, IDRC participants, SEMATECH, and Texas Instruments depending on the dataset.
