"""Run a concise, deterministic iPLS selection journey."""

from __future__ import annotations

import json

import numpy as np

import spectra_sherpa.sdk as ss


def run() -> dict[str, object]:
    """Select an informative interval and return the scientific summary."""

    rng = np.random.default_rng(17)
    X = rng.normal(size=(36, 24))
    y = 2.5 * X[:, 8] - 1.4 * X[:, 9] + 0.03 * rng.normal(size=X.shape[0])
    dataset = ss.data.from_array(X, x=np.linspace(900.0, 2100.0, X.shape[1]), units="cm-1")
    result = ss.selection.ipls(
        dataset,
        y,
        n_intervals=6,
        max_components=3,
        cv_folds=4,
    )
    return result.summary()


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
