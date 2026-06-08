# SherpaDataset Foundation

`SherpaDataset` is the concrete data object passed through workflow nodes and exposed through the Python SDK. It is the runtime container for spectroscopy data, targets, axes, metadata, provenance, and domain context.

The node library often says `SpectralDataset` in input and output tables. That name is a semantic port contract, not a separate Python class. A `SpectralDataset` port expects a `SherpaDataset` whose data role and feature axis describe spectra, such as FTIR/NIR wavenumbers, Raman shifts, or UV-Vis wavelengths.

This distinction is intentional:

| Name | Layer | Meaning |
| --- | --- | --- |
| `SherpaDataset` | Runtime and SDK | Concrete Python object used by nodes, plugins, exports, and tests. |
| `SpectralDataset` | Workflow type registry | Contract for ports that require spectral data carried inside a `SherpaDataset`. |
| `SpectralAxis` | Axis metadata | Axis object for wavenumber, wavelength, Raman shift, units, labels, and coordinate values. |

## What It Carries

- numeric data matrix
- sample and feature axes
- data role such as spectra or features
- units and labels when known
- metadata and provenance
- target values when available

## Why It Matters

Chemometrics depends on shape, axis, and target meaning. A dataset is not just an array; it also carries the scientific contract that lets nodes decide whether an operation is appropriate.

For example, a preprocessing node that lists `default: SpectralDataset` is saying: "send me a `SherpaDataset` containing spectra." A PCA scores output may also be a `SherpaDataset`, but it is not a `SpectralDataset` in the chemometric sense because its columns are latent variables rather than spectral coordinates.
