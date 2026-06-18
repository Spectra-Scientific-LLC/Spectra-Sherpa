from __future__ import annotations

import numpy as np
import pytest

import spectra_sherpa.sdk as ss
from spectra_sherpa.app.lib.scp_compat import HAS_SCP


def _calibration_dataset() -> ss.SherpaDataset:
    x = np.linspace(1000.0, 1005.0, 6)
    base = np.array(
        [
            [1.0, 1.4, 2.0, 2.7, 3.1, 3.5],
            [1.2, 1.7, 2.2, 2.9, 3.4, 3.8],
            [1.5, 1.9, 2.5, 3.2, 3.7, 4.2],
            [1.7, 2.2, 2.8, 3.5, 4.0, 4.6],
            [2.0, 2.5, 3.1, 3.9, 4.4, 5.0],
            [2.2, 2.8, 3.4, 4.2, 4.8, 5.4],
        ],
        dtype=float,
    )
    y = np.array([0.8, 1.1, 1.5, 1.9, 2.4, 2.8], dtype=float)
    return ss.data.from_array(
        base,
        x=x,
        samples=[f"s{i}" for i in range(base.shape[0])],
        y=y,
        y_name="assay",
        target_type="continuous",
        technique="NIR",
        units="cm-1",
    )


@pytest.mark.skipif(not HAS_SCP, reason="PCA execution requires SpectroChemPy (to_nddataset/SCP runtime)")
def test_pca_result_exposes_summary_manifest_and_ports() -> None:
    result = ss.explore.pca(_calibration_dataset(), n_components=2)

    assert result.scores.shape == (6, 2)
    assert result.loadings.shape == (2, 6)
    assert result["scores"] is result.scores
    assert result["X_loadings"] is result.loadings

    summary = result.summary()
    assert summary["model_type"] == "PCA"
    assert summary["n_components"] == 2
    assert len(summary["explained_variance_ratio"]) == 2

    manifest = result.manifest()
    assert manifest["sdk_function"] == "ss.explore.pca"
    assert manifest["node_type"] == "model.pca"
    assert "scores" in manifest["outputs"]


@pytest.mark.skipif(not HAS_SCP, reason="PLS execution requires SpectroChemPy (to_nddataset/SCP runtime)")
def test_pls_result_resolves_named_target_and_exposes_manifest() -> None:
    result = ss.regression.pls(
        _calibration_dataset(),
        y="assay",
        n_components=2,
        cv_method="none",
    )

    assert result.X_scores.shape == (6, 2)
    assert result.X_loadings.shape == (2, 6)
    assert result.y_pred is not None
    assert result.y_pred.shape == (6, 1)
    assert result["X_scores"] is result.X_scores

    summary = result.summary()
    assert summary["model_type"] == "PLS"
    assert summary["n_components"] == 2
    assert summary["n_targets"] == 1
    assert summary["target_names"] == ["assay"]

    manifest = result.manifest()
    assert manifest["sdk_function"] == "ss.regression.pls"
    assert manifest["node_type"] == "model.pls"
    assert "X_scores" in manifest["outputs"]
