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

## Metadata-driven plot styling

When a node plot represents samples one-for-one and its output retains an
aligned typed sample table, the Workbench exposes the same **Color by metadata**
and **Style by metadata** controls. Any safe, low-cardinality sample-table field
can be selected without rerunning the node. Point plots use marker symbols;
spectral overlays use line styles. PCA, PLS-DA, SIMCA, KNN, data, and
preprocessing score/overlay views all use this one authority.

The controls are intentionally absent from plots whose marks are not samples,
such as loadings, scree curves, confusion matrices, and spectral-variable
plots. A present but malformed or misaligned sample table is visibly refused;
the Workbench does not infer groups from filenames or row positions.

## Choosing Nodes

- Start with [Data Nodes](data.md) to load files, project datasets, library references, synthetic curves, or saved datasets.
- Use [Preprocessing Nodes](preprocessing.md) to correct baseline, smooth, crop, align, or normalize spectra before modeling. Calibration transfer has its own Workbench family for paired-instrument standardization and fitted transfer application.
- Use [Exploratory Nodes](exploratory.md) for PCA, clustering, MCR-ALS, EFA, SIMPLISMA, peak finding, and library comparison.
- Use [Regression Nodes](regression.md) when the target is quantitative.
- Use [Classification Nodes](classification.md) when the target is a class or QC decision.
- Use [Selection and Validation Nodes](selection-validation.md) for sample splitting, variable selection, CV, holdout metrics, and outlier flags.
- Use [Output Nodes](output.md) to make results visible or exportable.
- Check [Optional SpectroChemPy Nodes](spectrochempy.md) for the three specialized operations that require `spectra-sherpa[scp]`: EFA, MCR-ALS, and SIMPLISMA. File ingestion is governed separately by the native registry.

## Workbench Families

The Add and Catalog views, and Sherpa's canonical-node tools, use the same ordered families:

| Family | Purpose |
| --- | --- |
| Data | Load or bind datasets, targets, filters, and train/test partitions. |
| Simulation & Synthesis | Generate species responses, mixtures, concentration profiles, perturbations, and explicit simulated instrument effects. |
| Preprocessing | Correct or transform spectra before analysis, including baseline, scatter, smoothing, derivative, scaling, and axis alignment operations. |
| Calibration Transfer | Fit and apply DS, PDS, SWS, and portable transfer states between instruments. |
| Time Series | Transform ordered samples with moving windows or trend removal. |
| Feature Selection & Design | Select variables, compare selections, project dimensions, and evaluate nested selection. |
| Exploration & Decomposition | Explore latent structure, pure components, peaks, and library similarity. |
| Regression | Fit or apply quantitative models. PLS1 and PLS2 use the same SIMPLS node and differ by response dimensionality. |
| Classification | Fit or apply categorical models, including PLS-DA, SIMCA, and KNN. |
| Clustering | Fit unsupervised sample groupings. |
| Validation & Diagnostics | Evaluate held-out or out-of-fold predictions, summarize data, and detect outliers. |
| Results & Export | Render tables and plots or prepare an export. |
| Deployment & Model Application | Define deployment boundaries and apply a saved generic model artifact. |

EFA, MCR-ALS, and SIMPLISMA remain in Exploration & Decomposition while declaring their optional SpectroChemPy runtime requirement in the Catalog.
