# SherpaDataset Foundation

`SherpaDataset` is the concrete data object passed through workflow nodes and exposed through the Python SDK. It is the runtime container for spectroscopy data, targets, axes, metadata, provenance, and domain context.

The node library often says `SpectralDataset` in input and output tables. That name is a semantic port contract, not a separate Python class. A `SpectralDataset` port expects a `SherpaDataset` whose data role and feature axis describe spectra, such as FTIR/NIR wavenumbers, Raman shifts, or UV-Vis wavelengths.

This distinction is intentional:

| Name | Layer | Meaning |
| --- | --- | --- |
| `SherpaDataset` | Runtime and SDK | Concrete Python object used by canonical nodes, exports, and tests. |
| `SpectralDataset` | Workflow type registry | Contract for ports that require spectral data carried inside a `SherpaDataset`. |
| `SpectralAxis` | Axis metadata | Axis object for a canonical physical quantity (wavenumber, wavelength, or Raman shift), canonical units, original display units, labels, and coordinate values. |

## What It Carries

- numeric data matrix
- sample and feature axes
- data role such as spectra or features
- units and labels when known
- metadata and provenance
- target values when available

## Why It Matters

Chemometrics depends on shape, axis, and target meaning. A dataset is not just an array; it also carries the scientific contract that lets nodes decide whether an operation is appropriate.

Readers normalize equivalent unit spellings such as `cm-1`, `cm⁻¹`, `cm^-1`,
and `1/cm` to canonical `cm-1` while retaining the source spelling for
display. Units do not determine physical meaning by themselves: absolute
wavenumber and Raman shift remain distinct quantities even though both use
inverse centimetres. Collection assembly, calibration transfer, library
comparison, and saved-model application refuse missing or incompatible axis
meaning instead of treating a numerically similar grid as sufficient.

For example, a preprocessing node that lists `default: SpectralDataset` is saying: "send me a `SherpaDataset` containing spectra." A PCA scores output may also be a `SherpaDataset`, but it is not a `SpectralDataset` in the chemometric sense because its columns are latent variables rather than spectral coordinates.

## Computational admission and identity

The [scientific contract](../developers/scientific-result-surface-contract.md#computational-boundary-obligations)
requires identity checks before metadata is removed for numerical computation.
Separate labeled predictor/response datasets require ordered sample agreement or
an explicit recorded join. A feature axis identifies coordinates; signal quantity
and signal units are separate authorities used by fitted-state application.

Supported missing targets and optional metadata must survive the reader, scientific
digest, result and serialization boundaries consistently. Invalid nonfinite predictors
are not interchangeable with missing optional metadata. A node that filters rows
must preserve the row mapping and reasons; dataset copying alone is insufficient.
