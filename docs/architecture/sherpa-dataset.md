# SherpaDataset Foundation

SherpaDataset is the common data object passed through workflow nodes.

## What It Carries

- numeric data matrix
- sample and feature axes
- data role such as spectra or features
- units and labels when known
- metadata and provenance
- target values when available

## Why It Matters

Chemometrics depends on shape, axis, and target meaning. A dataset is not just an array; it also carries the scientific contract that lets nodes decide whether an operation is appropriate.
