# Read BOSCH NetCDF4 acquisitions

In **Data → Upload**, add one or more `Day_*.nc` files and their shared
`Process_data.nc` companion to the same dataset. Native files upload sequentially.
In **My Dataset**, select the companion, check days/wafers, select processing
steps, and click **Compare selected steps**. Every plotted group is labeled by
day, wafer and phase. The preview uses up to four evenly spaced original
acquisitions per group, without averaging; it is not an exhaustive plot of all
selected acquisitions. At most 50 wafer/step groups can be compared at once.

Expand a file and wafer to see UTC start/end times and 1-based acquisition ranges.
Each repeating phase retains its separate intervals. **Inspect all acquisitions
and experiment metadata** opens the original wafer's Data View; expand its
**Active dataset** section to inspect the complete acquisition table and protocol
context. Sample values, identities and irregular source times remain unchanged.

The native reader uses the `netCDF4` package, with automatic masking/scaling
disabled for dictionary indices. Small, unmodified CC BY 4.0 dictionaries are
bundled with attribution and checksum validation, so dictionary files need not be uploaded. Metadata inventory lists the wafers before allocating a matrix;
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
target measurements are not inferred. Phase comparison requires the explicit
companion and the conservative alignment described below.

The [source example](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/tree/main/examples/bosch_oes)
contains checksum verification, a canonical smoothing/peak-finding workflow,
and independent comparisons with the raw dictionary lookups. The optional
prototype transition table supplies unverified wavelength candidates, not
validated chemical identifications.

The native registry and `sdk.data.read()` support this specific NetCDF4/HDF5
schema, not arbitrary NetCDF or NetCDF3. A native BOSCH source is bounded to 1 GiB in the
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
The canonical `preprocess.bosch_phase_labels` node estimates the clock offset
from correlation between Gas5 flow and the strongest mean OES channel. It searches
the feasible overlap, requires at least 90% coverage, correlation ≥0.8, and an
alias margin ≥0.025. Ambiguous wafers are refused. One process sampling interval
around transitions is excluded from etch/passivation groups; gaps remain unmapped.
Use this node on native wafer data before attaching sample-table supervision.

Gas4 → C₄F₈ and Gas5 → SF₆ remain tentative feed assignments supported by the
alternating recipe and phase-associated C₂/fluorine emissions. Gas1 → O₂ is not
confirmed: the investigated Gas1-only spectra are argon-rich. The interface keeps
that group chemically unassigned. OES line matching also indicates an approximately
1.2 nm wavelength offset; this diagnostic observation does not alter source axes.
Fluorine emission alone cannot distinguish the two fluorinated feed gases.

The daily groups do not cover the complete chamber preparation and conditioning
sequence. Recipe context is not presented as observed phase boundaries. A final
Gas1-only RF interval is selectable, but neither EPD control nor cleaning purpose
is inferred from its duration. BOSCH cycle numbers are not generated.
