# Read BOSCH NetCDF4 acquisitions

In **Data → Upload**, choose one `Day_*.nc` file from the record, then choose
a wafer asset. Save it to a dataset and open **My Dataset**. Select the wafer
to plot its spectra or inspect Data View. Each row is one recorded acquisition;
its label includes the wafer, source row and UTC acquisition time. Irregular
times are preserved. No etch/passivation phase is inferred.

The native reader uses the `netCDF4` package, with automatic masking/scaling
disabled for dictionary indices. Small, unmodified CC BY 4.0 dictionaries are
bundled with attribution and checksum validation, so only one measurement file
is uploaded. Metadata inventory lists the wafers before allocating a matrix;
only the selected wafer is decoded. `Process_data.nc` is also supported with
named process features rather than wavelength spectra.

The multi-file reader `spectra_sherpa.io.bosch_netcdf.read_bosch_netcdf`
imports dictionary-encoded OES and process acquisitions from
[Zenodo record 17122442](https://zenodo.org/records/17122442). Supply the matching
dictionary and one wafer group explicitly. It returns a typed `SherpaDataset`
with original timestamps, channel coordinates/names and both source-file hashes.

```python
from spectra_sherpa.io.bosch_netcdf import read_bosch_netcdf
from spectra_sherpa.io.types import ParserLimits

spectra = read_bosch_netcdf(
    "Day_2024_08_05.nc",
    dictionary_path="Dictionary_OES.nc",
    group="Wafer_01",
    rows=slice(0, 100),
    limits=ParserLimits(max_source_bytes=1024**3),
)
```

Use `Dictionary_process.nc` with `Process_data.nc`, selecting a group such as
`Day_2024_08_05_Wafer_01`. Process channels are general features; their physical
units are not inferred. Missing acquisition times are not filled, and process
phases and target measurements are not guessed or aligned automatically.

The [source example](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/tree/main/examples/bosch_oes)
contains checksum verification, a canonical smoothing/peak-finding workflow,
and independent comparisons with the raw dictionary lookups. The optional
prototype transition table supplies unverified wavelength candidates, not
validated chemical identifications.

The native registry and `sdk.data.read()` support this specific NetCDF4/HDF5
schema, not arbitrary NetCDF or NetCDF3. A source is bounded to 512 MiB in the
Workbench, and a decoded wafer to 64 million elements / 512 MiB; larger files
are refused rather than silently sampled. Collections of multiple files retain
the existing aggregate budgets.

My Dataset retrieves up to 20,000 acquisition labels within the existing 4 MiB table response bound. Sample-inclusion editing retains its existing 5,000-observation limit; full-wafer plotting and read-only inspection do not imply curation support beyond it.

## Experiment context and EPD scope

My Dataset shows initial chamber preparation, conditioning surfaces and repeat
counts, and the production lot recipe. The bundled catalog transcribes
`Readme.pdf` (§1 and Figure 1) and `Lot_status.xlsx` from the Zenodo record.
Lot-specific settings are assigned only after matching the measurement source's
published checksum. For August 5 this is lot 7, three conditioning repetitions
on a blank SiO₂ wafer, with six recorded wafers out of ten planned. Renaming an
uploaded source does not change that match.

The user-provided recipe clarification places one EPD clean before the first
wafer and EPD cleans between production wafers. Cleaning after the last wafer
remains unconfirmed. The interface retains this attribution and its conflict
with the README introduction's statement about no intermediate cleaning.
Inspection of all 96 process groups found a short final RF-powered interval
(8.59–8.81 s above a 500 W inspection threshold), including all nine available
Wafer 10 groups. This is an observation, not an independently verified EPD label.

The process file's small numeric time values conflict with its declared Unix
epoch and date-bearing wafer names. Those raw values are preserved and disclosed
as source seconds with an unverified origin. OES timestamps remain Unix UTC.
No automatic clock alignment, phase boundaries, cycle IDs or cross-day recipe-step
filter is claimed. A future separator needs event-anchored EPD boundaries and
verified production start offsets, then can use nominal fixed-duration windows.
