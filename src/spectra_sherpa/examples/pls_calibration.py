"""Run a concise, deterministic PLS calibration journey."""

from __future__ import annotations

import json

import numpy as np

import spectra_sherpa.sdk as ss


def run() -> dict[str, object]:
    """Fit PLS against a known synthetic property and return the summary."""

    rng = np.random.default_rng(11)
    axis = np.linspace(4000.0, 10000.0, 120)
    concentration = rng.uniform(0.0, 10.0, size=48)
    band_analyte = np.exp(-0.5 * ((axis - 5200.0) / 150.0) ** 2)
    band_background = np.exp(-0.5 * ((axis - 7000.0) / 220.0) ** 2)
    background = rng.uniform(0.0, 1.0, size=concentration.shape[0])
    X = (
        concentration[:, None] * band_analyte
        + background[:, None] * band_background
        + 0.005 * rng.normal(size=(concentration.shape[0], axis.shape[0]))
    )
    dataset = ss.data.from_array(X, x=axis, units="cm-1")
    result = ss.regression.pls(dataset, y=concentration, n_components=2)

    predictions = np.asarray(result.predictions, dtype=np.float64).ravel()
    residuals = predictions - concentration
    centered = concentration - concentration.mean()
    summary = result.summary()
    summary["calibration_rmse"] = float(np.sqrt(np.mean(residuals**2)))
    summary["calibration_r2"] = float(1.0 - np.sum(residuals**2) / np.sum(centered**2))
    return summary


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
