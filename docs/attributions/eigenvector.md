# Eigenvector Research Example Datasets

Eigenvector Research hosts several classic chemometrics datasets that are useful for learning SpectraSherpa and for checking NIR/OES workflow behavior:

- Diesel NIR calibration data
- Corn NIR instrument-standardization data
- CGL NIR data
- IDRC 2002 NIR Shootout data
- SEMATECH/Texas Instruments metal-etch OES and process-monitoring data

These are excellent datasets for PCA, PLS calibration, classification, process monitoring, calibration transfer, and workflow export checks. SpectraSherpa strongly recommends downloading and caching them during local onboarding because they are well known in the chemometrics community and exercise realistic spectral shapes, targets, missing values, and instrument differences.

## User-Acquired Import Model

SpectraSherpa catalogs these datasets but does **not** redistribute the raw Eigenvector files in the Python wheel or source distribution.

The **Reference Datasets** card links to the provider. The user's browser—not
SpectraSherpa—downloads the file. **Import downloaded file** then admits only a
registered byte identity by exact size and SHA-256. Filename and directory are
not authorities. A nonmatching file is refused without retention.

This reference admission slot is not the ordinary paid/local data path. Local
OSS, desktop, paid cloud, and Enterprise Hybrid continue to process generic
supported files through their normal upload/import surfaces.

## Attribution

The datasets remain Eigenvector Research and contributor data. Cite the original source and contributor guidance when using them in reports, publications, teaching material, or validation records:

- Eigenvector Research data sets: <https://eigenvector.com/resources/data-sets/>
- Original contributors include Cargill, Southwest Research Institute, IDRC participants, SEMATECH, and Texas Instruments depending on the dataset.
