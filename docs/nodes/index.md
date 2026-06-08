# Node Library

Workflow nodes are the building blocks of SpectraSherpa analyses. They are grouped by what they do rather than by implementation package.

This section documents the built-in nodes from the current workflow registry. Each category page lists the node's expected inputs, outputs, and configuration knobs so you can decide whether it belongs in a workflow before wiring it.

## Reading Node Tables

The node tables use semantic port types. The most common one is `SpectralDataset`: a spectral matrix with sample rows, spectral-variable columns, axis metadata, and processing history. In the Python SDK and DAG engine, that payload is represented by the concrete `SherpaDataset` class. Put another way, `SpectralDataset` is the workflow contract and `SherpaDataset` is the runtime object that satisfies it.

For typical FTIR, NIR, Raman, or UV-Vis work, a `SpectralDataset` port expects a `SherpaDataset` whose feature axis is a spectral axis such as wavenumber, wavelength, or Raman shift. Supervised nodes may also consume targets such as concentrations or class labels, either attached to the dataset or passed through a separate target port.

| Term | Meaning |
| --- | --- |
| `SherpaDataset` | Concrete Python/SDK data object passed by the DAG engine. It carries the numeric matrix, axes, metadata, provenance, data role, and optional target context. |
| `SpectralDataset` | Node-port contract for a `SherpaDataset` that represents spectra, usually samples by wavenumbers, wavelengths, or Raman shifts. |
| `TargetMatrix` | Continuous target values such as concentration, property value, or response matrix. |
| `Categorical` | Class labels, sample groups, or QC categories. |
| `ScoreMatrix` | Scores from PCA, PLS, PCR, clustering embeddings, or similar latent-variable methods. |
| `LoadingMatrix` | Loadings or component vectors associated with latent-variable models. |
| `FittedModel` | Generic trained model object. |
| `RegressionModel` | Trained model that predicts continuous targets. |
| `ClassificationModel` | Trained model that predicts class labels or class distances. |
| `Visualization` | Plot-ready payload consumed by output nodes and the report view. |
| `ValidationResult` | Metrics, limits, diagnostics, or validation tables. |

Optional inputs are marked with `?` in the tables. The `default` port is the normal single input or output when a node does not need a named port.

## Choosing Nodes

- Start with [Data Nodes](data.md) to load files, project datasets, library references, synthetic curves, or saved datasets.
- Use [Preprocessing Nodes](preprocessing.md) to correct baseline, smooth, crop, align, normalize, or transfer spectra before modeling.
- Use [Exploratory Nodes](exploratory.md) for PCA, clustering, MCR-ALS, EFA, SIMPLISMA, peak finding, and library comparison.
- Use [Regression Nodes](regression.md) when the target is quantitative.
- Use [Classification Nodes](classification.md) when the target is a class or QC decision.
- Use [Selection and Validation Nodes](selection-validation.md) for sample splitting, variable selection, CV, holdout metrics, and outlier flags.
- Use [Output Nodes](output.md) to make results visible or exportable.
- Check [Optional SpectroChemPy Nodes](spectrochempy.md) when a node or file reader requires `spectra-sherpa[scp]`, including Thermo OMNIC/OMNICxi `.spa`, `.spg`, `.srs`, Bruker `.opus`, Galactic `.spc`, Renishaw `.wdf`, and vendor `.txt`/`.dat`.

## Categories

- data, synthesis, and deployment helpers
- preprocessing and calibration transfer
- exploratory, clustering, and decomposition
- regression
- classification
- selection and validation
- output
- SpectroChemPy-backed vendor readers and optional nodes
