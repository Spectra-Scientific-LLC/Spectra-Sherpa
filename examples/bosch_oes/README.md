# BOSCH NetCDF4 ingestion

This example uses the source checkout of SpectraSherpa OSS. The tested public
baseline is `2a6e70062663cc436226d98a4347740958bc2c3c` (main, package 0.6.3),
plus the new reader and example in this change. It does not require the private
server or SpectroChemPy. The reader uses the existing h5py dependency.

The supported source is [Zenodo record 17122442](https://zenodo.org/records/17122442),
version 1. It is NetCDF4/HDF5 with uint16 dictionary indices, not an ordinary
matrix of intensities. The record's README describes `decoder[encoded]` for
both OES and process files. This importer implements that decoding once.

## Read one wafer

Run from the OSS repository root. Use your environment's `python`; explicit
`PYTHONPATH=src` selects this checkout rather than an older editable install.
First obtain the files independently, or use the checksum-verifying helper:

```sh
python examples/bosch_oes/download_data.py /absolute/path/to/bosch-data
```

The helper fetches one OES day and the complete process file, with their two
companion dictionaries (about 485 MB). Existing files are checked and never
silently replaced. Raw NetCDF files and the prototype's spectral-reference CSV
are not bundled with this example.

```python
from spectra_sherpa.io.bosch_netcdf import read_bosch_netcdf
from spectra_sherpa.io.types import ParserLimits

spectra = read_bosch_netcdf(
    "/absolute/path/to/bosch-data/Day_2024_08_05.nc",
    dictionary_path="/absolute/path/to/bosch-data/Dictionary_OES.nc",
    group="Wafer_01",
    rows=slice(0, 100),       # omit to read all acquisitions of this wafer
    limits=ParserLimits(max_source_bytes=1024**3),
)
print(spectra.shape, spectra.feature_axis.units)
print(spectra.sample_axis.values)  # original Unix UTC seconds, including gaps
print(spectra.get_extra("ingestion.authority"))

process = read_bosch_netcdf(
    "/absolute/path/to/bosch-data/Process_data.nc",
    dictionary_path="/absolute/path/to/bosch-data/Dictionary_process.nc",
    group="Day_2024_08_05_Wafer_01",
)
print(process.shape, process.feature_axis.labels)
# Process source seconds have an unverified origin; inspect authority warnings.
```

Select one group explicitly. Wafer groups remain separate; they are not
silently stacked. OES channels retain their measured wavelength coordinates in
nm. Process channels retain their names as general features. Undocumented
intensity/channel units are left unknown. No targets, specimen independence,
process phase, calibration or chemical identity are inferred.

The matching companion dictionary must be supplied explicitly; use the
record's published checksums to establish correct pairing. Both file SHA-256s,
parser identity and group identity are attached to the typed dataset. Every
row has a stable `sample_id` bound to those sources, the wafer and original row
index. Timestamps are on the sample axis, not substituted with uniform spacing.

## Run the canonical OSS workflow

```sh
PYTHONPATH=src python examples/bosch_oes/run_oes_workflow.py \
  /absolute/path/to/bosch-data/Day_2024_08_05.nc \
  --dictionary /absolute/path/to/bosch-data/Dictionary_OES.nc \
  --group Wafer_01 --rows 20 --output /tmp/bosch-peaks.csv
```

This executes `deploy.input → preprocess.smooth → analysis.peak_finding`, plus
the existing spectral plot branch. It reads `peaks.data`, without requesting an
undeclared `salient_features` port. CSV uses standard quoting and reports the
actual half-prominence width rather than claiming FWHM.

`--rows` selects the first N real acquisitions, not N summary statistics.
The compatibility facade supports `all` and `time_series_sample` (the first N
acquisitions). The old `etch_mean`/`passivation_mean` requests now fail with an
explanation: the prototype's middle-60% window did not establish either phase.
A phase-specific analysis needs independently established boundaries followed
by explicit selection and a separate scientific aggregation operation.

An optional `--reference-csv /path/to/common_spectral_lines.csv` adds local
wavelength candidates. The retained prototype transition table is unverified;
this is not a live NIST lookup or a validated chemical identification. Transition
candidates are restricted to the same species as the selected local reference.
Omit this argument to export only measured peak results.

## Verification and scope

```sh
PYTHONPATH=src python examples/bosch_oes/verify_ingestion.py \
  /absolute/path/to/bosch-data --report /tmp/bosch-verification.json
python -m pytest tests/test_bosch_netcdf.py tests/test_bosch_oes_example.py --no-cov
```

The verifier checks published file MD5s, then independently compares every
returned value with the source dictionary lookup, every timestamp, channel
coordinate/name and source SHA-256. It covers all six wafers in the available
August 5 OES file and all 96 process groups. Other OES days are not claimed as
tested. Regression tests cover the original seven P2 issues, malformed sources,
row selection, missing values, links, and resource limits.

Workbench Upload supports one measurement `.nc` file using the bundled,
checksum-pinned dictionaries and explicit wafer selection. The native reader
uses `h5py` for structural preflight and dictionary decoding. See [the reader guide](../../docs/developers/bosch-netcdf.md).

The Workbench bounds each source to 512 MiB and selected decoded wafer to
64 million elements / 512 MiB. Other daily files beyond that bound are
explicitly refused. Classic NetCDF3 and unrelated NetCDF schemas are unsupported.
The SDK companion-dictionary entry point allows explicit caller resource limits.

The reader also retains source-attributed experiment context. OES timestamps are Unix UTC; process time values conflict with their epoch metadata and are preserved as source seconds with a warning. See the reader guide for EPD scope and the conditioning/lot mapping.
