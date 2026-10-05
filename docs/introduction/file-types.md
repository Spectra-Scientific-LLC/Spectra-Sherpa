# Supported File Types

File support is determined by the installed native ingestion registry. Optional
algorithm extras do not change which source files can be parsed.

## Base Install

These formats are handled without SpectroChemPy:

| Extension | Typical Use | Notes |
| --- | --- | --- |
| `.csv` | tabular spectra, feature matrices, or one unheaded X/Y spectrum | Headered and unheaded layouts support comma, semicolon, or tab delimiters plus decimal-point or decimal-comma numbers. Ambiguous unheaded X/Y files require one visible, persisted interpretation. Keep sample IDs and target columns explicit for tables. |
| `.jdx`, `.dx` | JCAMP-DX spectra | Open spectroscopy interchange format. |
| `.npy`, `.npz` | NumPy arrays or SpectraSherpa synthetic datasets | `.npz` is also used for SpectraSherpa synthetic benchmark datasets. |
| `.mat` | MATLAB arrays and Eigenvector PLS_Toolbox DataSet Objects | MATLAB v4/v5 and v7.3/HDF5 numeric workspaces are supported. The qualified DSO contract preserves n-D data, per-mode scales, labels, titles, class sets, include masks, image layout, history, and descriptive metadata across both storage families. A two-dimensional pixels-by-features image DSO exposes both its ordinary unfolded table and an explicitly named, column-major image-cube view; the source inclusion mask is retained on both. Arbitrary MATLAB classes, executable objects, sparse/complex arrays, and ragged batch DSOs refuse. |
| `.opus`, numeric suffixes such as `.0` | Bruker OPUS one-dimensional measurements | Every typed result is inventoried; select the exact scientific result for multi-result files. |
| `.spc` | Galactic/Thermo GRAMS SPC spectra and multifiles | Common-axis multifiles become one sample matrix; independent XYXY records remain explicit assets. |
| `.txt` with `#Wave` / `#Intensity` tab header | Renishaw WiRE single-spectrum text export | The exact two-column export is supported; other `.txt` tables, series, and maps are not guessed. Prefer WDF when acquisition metadata or topology is required. |

## Native Bruker OPUS

One-dimensional Bruker OPUS (`.opus` and numeric suffixes such as `.0`) is
read natively. A file can contain absorbance, transmittance, reflectance,
interferogram, phase, or other typed results; the Workbench inventories them
and saves the scientist's exact result choice in the canonical DAG. Series and
3-D OPUS blocks are recognized and refused rather than flattened.

The always-running bundled corpus contains one licensed real acquisition.
Additional qualified multi-asset layouts are exact-hash external references
because their source corpus does not grant redistribution permission; those
bytes must be acquired and executed during release qualification. Support is
limited to the explicitly qualified grammar and is not inferred from the
numeric filename alone. The optional SpectroChemPy differential job compares
the retained OMNIC and WDF readers; it is not an OPUS or SPC variant oracle.

## Missing spectral values

Ingestion preserves an empty numeric cell or an explicit supplier missing token
such as `#NaN` as missing data so source identity is not silently rewritten.
Binary missing values are narrower: the qualified OMNIC SPA reader preserves
them only for the retained code-23 profile when the missing-value mask exactly
matches one explicit processing-history `Blank ... From ... to ...` interval.
An arbitrary SPA NaN, a mismatched blank interval, or any infinite coordinate
or intensity is refused.

The admitted file remains inspectable and carries a visible missing-data
warning, but numerical preprocessing, variable selection, transfer, fitting,
and prediction remain fail-closed: SpectraSherpa does not invent replacement
intensities. For a terminal vendor-declared blank interval, apply the canonical
`preprocess.clip_range` operation to retain only the measured region before any
numerical preprocessing. Otherwise exclude identified affected samples or
variables, or repair the source. Automatic or fitted imputation is not a 0.6
capability; it requires a separately reviewed preprocessing contract with
training-only fit semantics and explicit provenance.

## Native Galactic SPC

Galactic/Thermo GRAMS SPC (`.spc`) is read through the native bounded parser.
Qualified 0x4B little-endian files cover generated, common explicit, and
independent XYXY axes; qualified 0x4D files cover the old word-swapped data
layout. Common-axis multifiles become one chemometric sample matrix. XYXY
files retain every independent record as a named asset and require an exact
selection. Big-endian 0x4C remains fail-closed until an independent scientific
conformance fixture is available.

## Native Thermo OMNIC and Renishaw WiRE

Qualified legacy Thermo OMNIC SPA single spectra, SPG compatible groups, and
SRS time series (`.spa`, `.spg`, `.srs`) are read by the native registry. SRS
coverage includes the qualified rapid-scan, high-speed, GC/TGA, and extended-
directory Kinetics layouts; it is not a claim that every historical SRS layout
is interchangeable. SPA projection retains the declared ordinate type, axis,
acquisition timestamp and scan fields, plus bounded comments, processing
history, experiment information, accessory text, and the identity—not the raw
values—of a qualified embedded linked source when those records are present.
For the retained Nicolet Apex code-23 profile, OMNIC displays **Transmittance**
while processing history separately records `Final format: Single Beam`.
SpectraSherpa preserves both statements, assigns no ratio units, and therefore
does not offer transmittance-to-absorbance conversion for that profile: a
display label alone does not establish an `I/I0` ratio. The declared blanked
interval is preserved as missing in SPA and CSV, omitted by the corresponding
JDX export, and filled by the corresponding SPC export. Cross-format signal
parity for those sources is claimed only over their common measured finite
region.
Metadata-poor CSV, JCAMP-DX, or SPC exports are not used to invent fields that
the export discarded.
Qualified Renishaw WiRE WDF (`.wdf`) single spectra, depth series, XY lines,
StreamLine acquisitions, and rectangular maps are also native. Map spectra
remain one sample-by-Raman-shift matrix with exact X/Y/Z/time origin columns
and explicit topology. The exact tab-separated WiRE single-spectrum text
export headed by `#Wave` and `#Intensity` is also native; it retains only the
Raman-shift axis and intensity, so its result warns scientists to use WDF when
acquisition settings, coordinates, or map topology are required. Thermo
Paradigm/OMNICxi containers (`.srsx`,
`.session`, `.map`, `.mapx`) still require an upstream spectrum export.

The Workbench lists recognized pending families as unavailable and shows the
same export remediation before a file is stored. It never sends them through
a generic parser or silently guesses other `.txt`/`.dat` content.

All admitted source formats—CSV, JCAMP-DX, NumPy, MATLAB v4/v5 and v7.3,
the qualified Eigenvector PLS_Toolbox DataSet Object contract, Galactic SPC,
one-dimensional Bruker OPUS, qualified legacy OMNIC SPA/SPG/SRS, and Renishaw
WiRE WDF and exact single-spectrum text exports—are parsed by bounded native
readers with no SpectroChemPy import or fallback, proven per PR by a clean-room
no-SpectroChemPy profile.
SpectroChemPy remains an optional runtime for exactly three scientific
operations: EFA, MCR-ALS, and SIMPLISMA.

This is SpectroChemPy-independent ingestion complete for the qualified format
set, not complete spectroscopic ingestion. Additional vendor and interchange
families remain demand-gated, and Thermo Paradigm/OMNICxi containers (`.srsx`,
`.session`, `.map`, `.mapx`) remain pending with the export guidance above.

## Optional SpectroChemPy Algorithms

> **0.6.0 release lifecycle.** Install 0.6.0 from PyPI only after the public
> index reports that exact version. Before the public tag exists, use only the
> exact monorepo commit named by the qualification record. After the tag exists
> but before PyPI reports 0.6.0, use the exact `spectra-sherpa-v0.6.0` source
> tag. Source version text alone is not publication evidence.

After 0.6 publication, install with:

```bash
pip install "spectra-sherpa[scp]==0.6.0"
```

This enables the three [SpectroChemPy](https://www.spectrochempy.fr/)-backed
operations retained by SpectraSherpa—EFA, MCR-ALS, and SIMPLISMA. It does not
install a SpectraSherpa reference-data catalog. SpectraSherpa itself currently
supports Python `>=3.11,<3.13`; the optional dependency is pinned to exactly
[SpectroChemPy 0.8.1](https://www.spectrochempy.fr/0.8.1/). Installing this
extra does not add source-file readers.

## Optional HITRAN/HAPI Extra

Install with:

```bash
pip install "spectra-sherpa[hitran]==0.6.0"
```

This enables HITRAN/HAPI synthesis support. The current package supports [hitran-api](https://pypi.org/project/hitran-api/) `>=1.3.0.0,<2` and [hitran-api2](https://pypi.org/project/hitran-api2/) `>=0.2.2,<1`. See the official [HITRAN HAPI page](https://hitran.org/hapi/) and [HAPI manual](https://hitran.org/static/hapi/hapi_manual.pdf) for upstream API details.

## Practical Guidance

For a first demo, prefer CSV, JCAMP-DX, NPY/NPZ, a qualified MATLAB/DSO
workspace, qualified SPC,
qualified one-dimensional OPUS, qualified legacy OMNIC, qualified WDF, or the
exact Renishaw `#Wave`/`#Intensity` text export. For a pending native instrument
format, export a representative source to an admitted format and verify its
dimensions, axis, and units before converting a large calibration library.

After import, check the **Files**, **Metadata**, and **Data Matrix** panels to confirm the file names, extensions, sample count, spectral axis, and target values.
For an n-dimensional DSO, the Data Matrix panel instead shows the full native
shape and dimension roles. Inspect every axis, class, and include set. Use
**Dimension Projection** before a two-dimensional node. For a qualified image
DSO, select its explicitly named **image-cube** result before manually adding
PARAFAC; masked PARAFAC honors the source's spatial exclusions and records that
decision. The Workbench never silently flattens or refolds a DSO.
