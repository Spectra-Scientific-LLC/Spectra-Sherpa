# Supported File Types

File support depends on whether you are using the base install or optional extras.

## Base Install

These formats are handled without SpectroChemPy:

| Extension | Typical Use | Notes |
| --- | --- | --- |
| `.csv` | tabular spectra or feature matrices | Best default for known data. Keep sample IDs and target columns explicit. |
| `.jdx`, `.dx` | JCAMP-DX spectra | Open spectroscopy interchange format. |
| `.npy`, `.npz` | NumPy arrays or SpectraSherpa synthetic datasets | `.npz` is also used for first-party synthetic datasets. |
| `.mat` | MATLAB-style matrices | Supported for matrix-style imports; confirm axis and target metadata after loading. |

## Optional SpectroChemPy Extra

Install with:

```bash
pip install "spectra-sherpa[scp]"
```

This enables [SpectroChemPy](https://www.spectrochempy.fr/)-backed readers and nodes. SpectraSherpa itself currently supports Python `>=3.11,<3.13`; the optional dependency is `spectrochempy >=0.8.1,<0.9.0`, and the current lockfile pins [SpectroChemPy 0.8.1](https://www.spectrochempy.fr/0.8.1/). It is the path to use for Thermo OMNIC/OMNICxi, Bruker OPUS, Galactic SPC, Renishaw WiRE, and other spectroscopy-native files supported by the installed SpectroChemPy version.

| Extension | Typical Source | Notes |
| --- | --- | --- |
| `.spa`, `.spg`, `.srs` | Thermo OMNIC / OMNICxi spectra, groups, and legacy time series | Use exported spectra or legacy time-series files. |
| `.spc` | Galactic SPC and related spectroscopy files | Requires `spectra-sherpa[scp]`. |
| `.wdf` | Renishaw WiRE Raman files | Requires `spectra-sherpa[scp]`. |
| `.opus` | Bruker OPUS files | Requires `spectra-sherpa[scp]`. |
| `.txt`, `.dat` | vendor text handled by SpectroChemPy | Requires `spectra-sherpa[scp]`. |

Some newer vendor containers are not directly readable today. Thermo OMNIC Paradigm / OMNICxi container files such as `.srsx`, `.session`, `.map`, and `.mapx` should be exported to readable spectra such as `.spa`, `.spg`, or legacy `.srs` before upload.

The UI should disclose when a selected format requires `spectra-sherpa[scp]`. If a base install cannot read a selected file, the expected message is to install the optional extra rather than silently failing later in a workflow.

## Optional HITRAN/HAPI Extra

Install with:

```bash
pip install "spectra-sherpa[hitran]"
```

This enables HITRAN/HAPI synthesis support. The current package supports [hitran-api](https://pypi.org/project/hitran-api/) `>=1.3.0.0,<2` and [hitran-api2](https://pypi.org/project/hitran-api2/) `>=0.2.2,<1`. See the official [HITRAN HAPI page](https://hitran.org/hapi/) and [HAPI manual](https://hitran.org/static/hapi/hapi_manual.pdf) for upstream API details.

## Practical Guidance

For a first demo, prefer CSV or JCAMP-DX when possible. For Thermo/Nicolet or Raman instrument files, install the SpectroChemPy extra and validate with a small representative file set before importing a large calibration library.

After import, check the **Files**, **Metadata**, and **Data Matrix** panels to confirm the file names, extensions, sample count, spectral axis, and target values.
