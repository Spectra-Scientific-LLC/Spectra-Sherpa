# Import Your First Dataset

Start with a small, representative FTIR, NIR, Raman, or UV-VIS dataset. Ten to fifty spectra are enough to verify file reading, axes, metadata, and plots before you import a full calibration set.

## Recommended First Files

Use one of:

- `.csv` with one row per sample and spectral variables as columns
- `.jdx` or `.dx` JCAMP-DX spectra
- `.npy` or `.npz` arrays
- `.mat` matrix data
- Thermo OMNIC/OMNICxi `.spa`, `.spg`, `.srs`, Bruker `.opus`, Galactic `.spc`, Renishaw `.wdf`, and vendor `.txt`/`.dat` after installing `spectra-sherpa[scp]`

See [Supported File Types](../introduction/file-types.md) for the full matrix, SpectroChemPy version notes, HITRAN/HAPI extra, and currently unsupported vendor containers.

## Import Checklist

1. Open **Data > Upload**.
2. Select the file or files.
3. Check **Files** for the exact names and extensions received by SpectraSherpa.
4. Check **Metadata** for inferred labels, units, and source information.
5. Check **Data Matrix** for row count, column count, and axis direction.
6. Save the dataset to **My Dataset** if you want to reuse it in workflows.

## Calibration Data

For PLS or classification, make target values explicit. Prefer a CSV or metadata file with stable sample IDs rather than relying on row order alone.

Before training, confirm:

- samples line up with reference values
- replicate spectra are either grouped intentionally or separated intentionally
- units are recorded
- target columns are named clearly

## Common First Workflow

Run a PCA template first. PCA quickly shows whether spectra cluster, whether preprocessing is needed, and whether any sample looks obviously misaligned or outlying.

After PCA looks reasonable, move to the workflow that matches your scientific question: [PLS Calibration](../chemometrics/pls.md), [Classification](../chemometrics/classification.md), [SIMCA QC](../chemometrics/simca.md), or [Peak Finding and Library Comparison](../chemometrics/peaks-library.md).
