# Model Artifacts

!!! abstract "Summary"
    How trained models are saved, versioned, reviewed, and reapplied — the bridge from a good run to a reusable calibration.

Model artifacts persist trained models. They are the bridge between "this workflow run looked good" and "this calibration or classifier can be reviewed, versioned, reapplied, or handed to another system."

## What a Model Artifact Is

For a PLS calibration, the artifact should answer practical questions such as:

- What dataset and target was used?
- What preprocessing and parameters were applied?
- What spectral axis and feature count does the model expect?
- Which fitted arrays are needed to predict new spectra?
- What validation metrics justified saving it?
- Which run, user, project, and timestamp produced it?

## Stored Form

SpectraSherpa stores model artifacts as **readable metadata plus numeric state**.

The readable part is a manifest. The schematic below illustrates the kinds of
context it records; it is not the actual serializer schema or a valid artifact
to construct by hand:

```json
{
  "artifact_type": "pls_regression",
  "created_from_run": "run_2026_06_05_001",
  "target": {"name": "moisture", "units": "%"},
  "spectral_axis": {"units": "cm^-1", "n_features": 1557},
  "preprocessing": ["snv", "savgol_derivative"],
  "metrics": {"rmsep": 0.18, "r2": 0.94, "bias": -0.02},
  "arrays": ["x_mean.npy", "x_scale.npy", "coef.npy", "loadings.npy"]
}
```

The numeric state files hold values that should not be hand-edited: regression coefficients, loadings, scaling vectors, class centers, or other fitted arrays. Keeping this fitted state alongside a readable manifest makes the artifact both reviewable by humans and precise enough for later application.

```mermaid
flowchart LR
    R[Workflow run] --> M[Manifest JSON]
    R --> A[Array files]
    M --> C[Compatibility review]
    A --> P[Prediction/application]
    C --> P
```

## Why They Matter

A calibration or classifier is useful only if it can be reapplied to compatible spectra. The artifact should carry enough contract information to explain what the model expects, why it was saved, and what has to match at apply time.

## Publication custody

Application-owned model files have a private ownership claim before publication.
That claim is not a saved model or evidence of a successful run. It remains if
execution fails or times out, and transfers to the completed model record in the
same database transaction that registers the artifact. Startup cleanup must not
discard a claimed file merely because it is old.

Publication rechecks the live owner under a short database lock; fitting does
not hold that lock. Cancellation waits for the actual file writer to stop before
releasing custody. File publication uses separate bounded thread capacity from
computation to avoid deadlock under concurrent runs. An uncertain claim commit
does not authorize writing files.

SDK callers that supply their own storage capability remain responsible for its
ownership and cleanup. These safeguards do not retroactively identify historical
orphan files or certify deletion of backups.

## Apply-Time Review

Before applying a model, confirm spectral axis, preprocessing, feature count, and units match the training data.

Training exclusions select the fitted cohort; they are not replayed as row
exclusions on new observations. Applying a curated PCA or PLS artifact processes
the new dataset's eligible rows, not the training dataset's row positions.

For example, a PLS model trained on absorbance spectra from 4000-650 cm^-1 should not be applied blindly to transmittance spectra, truncated axes, different resolution, or spectra preprocessed outside the saved workflow contract.
