"""Run the Sherpa-native canonical PCA journey."""

from __future__ import annotations

import json

import numpy as np

import spectra_sherpa.sdk as ss


def run() -> dict[str, object]:
    """Fit PCA through the canonical registry and return its summary."""

    rng = np.random.default_rng(23)
    X = rng.normal(size=(12, 32))
    X[:, 10:16] += np.linspace(-1.0, 1.0, X.shape[0])[:, None]
    dataset = ss.data.from_array(X, x=np.linspace(800.0, 2400.0, X.shape[1]), units="cm-1")
    return ss.explore.pca(dataset, n_components=2).summary()


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
