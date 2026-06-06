# Data Import

The **Data** tab is where spectra enter SpectraSherpa. It turns your files, reference entries, examples, or generated spectra into a dataset that a workflow can analyze — and it makes the contents of that dataset visible before you commit to modeling.

## The Data Tab at a Glance

The Data tab has five areas. Four of them bring data in; the fifth is where everything lands.

| Area | What it does |
| --- | --- |
| **Upload** | Bring in your own files (CSV, JCAMP-DX, NumPy, MAT, and vendor formats with the optional extra). |
| **Import** | Add bundled reference and example datasets from curated catalogs. |
| **Synthesis** | Generate first-party synthetic spectra (Beer–Lambert mixtures from NIST or HITRAN). |
| **Library** | Search and import NIST and HITRAN reference spectra. |
| **My Dataset** | The reusable store of everything you have brought into the current project. |

## Everything Packages into My Dataset

Upload, Import, Synthesis, and Library all save their result into the same place — **My Dataset**, the project's reusable dataset store. Whichever path you use, the result is a named entry there.

You package data once and reuse it. A workflow does not read a file directly — its **Data Source** node selects a **My Dataset** entry. So the common pattern is:

> bring data in once → it lands in **My Dataset** → point one or more workflows at it.

Duplicate a workflow and keep the same dataset, or swap in a different My Dataset entry, without re-importing.

## Upload Your Own Files

Open **Data > Upload**, choose a file, set how it should be read, then add it to My Dataset. Stage one or more files before committing them in a batch.

**Formats.** The base install reads `.csv`, JCAMP-DX (`.jdx`, `.dx`), NumPy (`.npy`, `.npz`), and `.mat`. The optional `spectra-sherpa[scp]` extra adds vendor readers — `.spa`, `.spg`, `.srs` (Thermo OMNIC), `.opus` (Bruker), `.spc` (Galactic), `.wdf` (Renishaw WiRE), and vendor `.txt`/`.dat`. See [Supported File Types](../introduction/file-types.md) for the full matrix. If you select a format that needs the extra, the app tells you to install it rather than failing later.

**Options you set at upload.** For CSV especially, these determine how the numbers are interpreted:

- **Stage** — `raw`, `preprocessed`, or `synthetic`. This labels where the data sits in the analysis lifecycle.
- **CSV data shape** — choose **spectra** when the columns are ordered wavelengths or wavenumbers, or **feature table** when the columns are independent variables (for example, lab measurements). This sets the dataset's [data role](#data-semantics-that-matter) and changes how plots and axes are interpreted.
- **Target column** — the column holding reference values for supervised models (concentration, property, class).
- **Target type** — **continuous** for regression targets or **categorical** for class labels.

After upload, always open the inspection panels (below) to confirm the file read the way you intended.

!!! note "Using your own data"
    Running [Local OSS](../introduction/cloud-vs-local.md) places no limits on uploads, and your data stays on your machine. The hosted demo rate-limits and caps uploads.

## Import Reference and Example Datasets

**Data > Import** lists curated catalogs you can add with a click — ideal for learning a workflow before using your own data:

- **Spectra Scientific Synthetic Benchmarks** — first-party synthetic FTIR and atmospheric-gas sets with known ground truth.
- **Eigenvector Research (NIR)** — well-known NIR calibration benchmarks (for example, corn).
- **OES Datasets** — optical-emission process-monitoring data.
- **SpectroChemPy Datasets** — example spectra bundled with the optional extra, organized by category.
- **Scikit-learn Datasets** — tabular feature-table datasets for non-spectroscopic examples.

Select one or more entries, give the dataset a name, and add it to My Dataset.

## Generate Synthetic Spectra

**Data > Synthesis** builds synthetic FTIR datasets from line-by-line or reference data, which is useful for method development and benchmarking when ground truth is known. You choose components, define concentration profiles, and set acquisition parameters:

- **Source** — NIST Quantitative IR (with a resolution and apodization choice) or HITRAN/HAPI (with wavenumber range, temperature, and pressure).
- **Components** — search by name, formula, or CAS and add the species in the mixture.
- **Concentration profiles** — shape each component's concentration across the generated samples.
- **Generation** — number of samples, path length, and added noise.

HITRAN sources fetch live and need your own API key and egress permission. See [Reference Libraries and Synthesis](references-synthesis.md) for the scientific detail and citation guidance.

## Import from the NIST and HITRAN Libraries

**Data > Library** searches reference spectra and imports them into My Dataset.

- **NIST** spectra read from the local library — search by compound, formula, or CAS, **Load Spectrum** to preview, and add entries to a basket. **Add All** adds every visible row at once, with compound-level de-duplication that keeps the highest-resolution entry.
- **HITRAN** spectra are fetched live and require a HITRAN API key (Settings > API Keys) and egress permission; requests are queued as background jobs with progress status.

When importing several spectra onto one grid, the default range mode keeps the **widest** span; very large combined grids are bounded for performance.

## My Dataset: The Reusable Store

A **My Dataset** entry is a named dataset scoped to your project. It collects the files from every ingestion path and carries the metadata a workflow needs — sample and variable counts, spectral axis and units, data role, and any target values.

Because datasets live in the project, not inside a single workflow:

- one dataset can feed **multiple workflows (sheets)** in the same project;
- you can **duplicate a workflow** and keep the same dataset, or point its Data Source node at a different My Dataset entry;
- your data stays scoped to you (and your project) — it is not shared implicitly.

## Inspect Before You Model

Three panels make a dataset's contents visible **before** it enters a workflow. Reviewing them is the cheapest way to catch a bad import:

- **Files** — the file names, extensions, and reader path used, plus the data-matrix shape per file and its stage.
- **Metadata** — sample count, variable count, technique, and the spectral **axis title and units**. Axis title/units and the data quantity are editable here when a file did not declare them.
- **Data Matrix** — a preview of the matrix with per-column statistics (min/max/mean/std, missing fraction) and, when a target is present, its type and class breakdown. Spectra render as an overlay; feature tables render as distributions.

## Data Semantics That Matter

A dataset is more than a grid of numbers. A few properties decide whether a model is meaningful:

- **Data role.** *Spectra* (`X_spectra`) means the columns are ordered points on a physical axis — wavenumber, wavelength, time, or m/z — and are plotted as continuous spectra. *Feature table* (`X_features`) means the columns are independent variables and are summarized as distributions. The role is set at upload (CSV data shape) or inferred from the axis, and you can correct it.
- **Spectral axis and units.** For spectra, the feature axis carries values plus a title and units. SpectraSherpa maps `nm`/`µm` to **Wavelength** and otherwise treats the axis as **Wavenumber** (cm⁻¹); confirm or override this in **Metadata** so downstream steps (derivatives, alignment) behave correctly.
- **Sample identity.** Sample IDs travel with the dataset (from a CSV's first column, file metadata, or auto-generated). They are what lets spectra and reference values from **separate files** be joined by identity rather than by row order.
- **Targets.** A target can be embedded as a column in the same file (set the target column at upload) or attached from a separate source in the workflow using the **Attach Target** node. Either way, confirm the target type — continuous for regression, categorical for classification.

## Calibration Caution

When spectra and reference values arrive from **separate files**, align by stable sample identity whenever possible. A row-order join can train a model that looks numerically successful while quietly learning mismatched targets — one of the most common and most costly calibration mistakes. The inspection panels and matching sample counts are your first checks; sample IDs are the reliable one.
