# Optional SpectroChemPy Nodes

SpectroChemPy support is optional.

> **0.6.0 release lifecycle.** Install 0.6.0 from PyPI only after the public
> index reports that exact version. Before the public tag exists, use only the
> exact monorepo commit named by the qualification record. After the tag exists
> but before PyPI reports 0.6.0, use the exact `spectra-sherpa-v0.6.0` source
> tag. Source version text alone is not publication evidence.

```bash
pip install "spectra-sherpa[scp]==0.6.0"
```

## What It Enables

The extra enables exactly three specialized spectral-analysis nodes. Its
matrix adapter is private to those nodes. It adds no reference datasets,
public conversion API, or file readers; ingestion availability comes only
from the native registry described in [Supported File Types](../introduction/file-types.md).

## Nodes That Currently Require SpectroChemPy

| Node | Why It Needs the Extra | Main Inputs | Main Outputs | Main Configuration |
| --- | --- | --- | --- | --- |
| MCR-ALS (`model.mcr_als`) | Uses constrained curve-resolution support. | `SpectralDataset` | concentration profiles, pure spectra, residuals, model | `n_components`; non-negativity flags; `max_iter`; `tol`. |
| EFA (`model.efa`) | Uses Evolving Factor Analysis support. | `SpectralDataset` | forward/backward eigenvalues, model | `n_components`. |
| SIMPLISMA (`model.simplisma`) | Uses purity-maximization component estimation. | `SpectralDataset` | concentrations, spectra, purity values, model | `n_components`; `tol`; `noise`. |

If the extra is missing, these nodes should fail early with the install message rather than fail deep in workflow execution.

## Why Optional

Keeping SpectroChemPy optional preserves a clean license and dependency
boundary. Base SpectraSherpa remains installable without it, while users who
need these three algorithms can opt in explicitly.

## User-Facing Expectation

The app discloses when one of the three nodes requires the extra and fails
early with a clear installation message if it is missing. File formats never
recommend this extra; pending vendor formats instead give native-reader/export
guidance.
