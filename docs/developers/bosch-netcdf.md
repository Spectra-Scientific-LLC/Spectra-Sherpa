# Read BOSCH NetCDF4 acquisitions

The following integration targets **v0.6.5 only**.

In **Data → Upload**, add one or more `Day_*.nc` files and their shared
`Process_data.nc` companion to the same named dataset. Prepare the alignment
there before adding the dataset to My Dataset. Native files upload sequentially.

My Dataset preserves its shared layout. Its sequential filters are Packaged
Datasets → Data Views → **Steps Selection** → Comparison preview. The expanded,
collapsible Steps Selection panel sits immediately above the plot and reads
retained Upload catalogs. No step groups are selected initially. Clicking wafer
boxes adds/removes groups automatically; the selected box fill matches all
preview curves in that group, the border retains recipe color, and hover/focus
shows acquisition metadata. The comparison has no legend. Explanations and the
bounded preview sampling disclosure live in the panel's question-mark help.

The old whole-container inspection path is not invoked for daily OES filtering:
Process_data.nc and daily wafer groups cannot share one observation matrix.
No OES-specific portfolio/Workflow controls or recipe panels are inserted into
Active dataset. Those placements remain pending user review. The separate
prototype and canonical backend operations remain available for v0.6.5 review.

The native reader uses `h5py` and reads dictionary indices without CF masking/scaling. Small, unmodified CC BY 4.0 dictionaries are
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

The retained experiment-context metadata describes initial chamber preparation,
conditioning surfaces and repeat counts, and the production lot recipe. Its
placement in My Dataset is pending review. The bundled catalog transcribes
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
is inferred from its duration. The legacy phase preview does not retain cycle indices.


## v0.6.5 portfolio review workflow

This feature is isolated to the v0.6.5 integration branch. The development-only
`/preview/oes-v065` matrix saves named, immutable selections. Saving binds exact
acquisition intervals, source and process hashes, both decoding dictionary hashes,
and segmentation identity. Names cannot be overwritten; save a new portfolio to
change membership. Every execution re-admits access and verifies these bindings.

Select individual day/wafer/step boxes, name the selection, then save it. Select
saved portfolios to create independent canonical workflow branches:
Load Data · Portfolio → Average · Portfolio → Smooth → optional Normalize →
Find peaks · Partitioned → Combine peak columns → Export wide peak CSV.
Reference wavelengths and matching tolerance are explicit user settings, shared
initially but independently editable on each branch.

Averaging uses equal acquisition weights and never combines wafers:

- **Step:** one spectrum per day × wafer × selected step.
- **Phase across cycles:** one spectrum per day × wafer × step × phase.
- **Cycle phase:** one spectrum per day × wafer × step × phase × cycle.

Cycle indices derive from aligned process etch onsets. Transition acquisitions
and intervals without an assigned cycle remain explicit; they are not silently
dropped. The default includes all acquisitions. Optional transition trimming
removes a declared duration from each retained interval's ends; it is relative
to the OES interval timestamps, not a calibrated gas transport delay.

Raw decoding uses h5py in bounded acquisition batches, without netCDF4. Averaged
outputs have a 16-million-value bound; peak detection runs in bounded batches.
The combined table retains independent measurement columns, with peak references
as rows and date/wafer/step/phase/cycle identity in column labels. Missing peaks
export as blank cells, distinct from measured zero. The CSV is a verified
canonical ExportArtifact downloadable through the workflow Inspector.

Large finite two-dimensional spectral outputs are retained as bounded, lossless
float64 byte-shuffled zlib partitions, each protected by the existing SHA-256
content-addressed store. The manifest binds every partition and records its
additional storage bytes. Large JSON outputs also use bounded, lossless compressed
envelopes; existing uncompressed retained files remain readable. Original sample
identity, coordinates, provenance and
values survive reload. Garbage collection retains manifest children; partial
runs charge them against the same quota. There is no increase to the 16 MiB
per-file or 64 MiB per-run storage limit. Partitioned datasets have a separate
16-million-value decoded bound. HTTP inspection uses the canonical bounded
preview and owner-scoped dataset handle, not an unlimited JSON response.

The real two-day cycle-phase workflow retains all three 598 × 3,648 intermediate
arrays and its peak outputs. Larger selections can still exhaust the configured
quota and are reported explicitly. Missing peak detections remain NaN internally
and null in retained JSON (declared reduced evidence), then blank in CSV; this is
distinct from missing retention or lost acquisitions.

The standalone example uses the canonical local executor's named deployment
admission to retain native acquisition annotations. It does not strip the sample
table or widen the managed spectral capability. Shared runtime qualification
identities remain unchanged. This draft remains local review work for v0.6.5;
passing public tests does not qualify new nodes for managed execution.
