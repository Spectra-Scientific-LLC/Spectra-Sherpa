# Optional SpectroChemPy Nodes

!!! abstract "Summary"
    Reference: optional nodes powered by SpectroChemPy (MCR-ALS, EFA, SIMPLISMA) — what they add, how to install the extra, and the current support limits.

SpectroChemPy support is optional.

> **Installation target.** These guides describe v0.6.4. Commands below install
> the latest *published* package. For source qualification, install the exact
> reviewed checkout with the required extras using
> [Local onboarding](../onboarding/local-30-minutes.md).

```bash
pip install "spectra-sherpa[scp]"
```

## What It Enables

The extra enables exactly three specialized spectral-analysis nodes. Its
matrix adapter is private to those nodes. It adds no reference datasets,
public conversion API, or file readers; ingestion availability comes only
from the native registry described in [Supported File Types](../introduction/file-types.md).

## Nodes That Currently Require SpectroChemPy

- [`model.mcr_als`](exploratory.md#registry-reference): Uses constrained curve-resolution support.
- [`model.efa`](exploratory.md#registry-reference): Uses Evolving Factor Analysis support.
- [`model.simplisma`](exploratory.md#registry-reference): Uses purity-maximization component estimation.

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

See the generated [exploratory registry reference](exploratory.md#registry-reference) for exact ports and parameters.
