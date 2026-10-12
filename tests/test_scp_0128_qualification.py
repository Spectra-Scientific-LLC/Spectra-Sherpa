"""Numerical acceptance checks for the current optional scientific runtime.

These synthetic mixtures test matrix reconstruction rather than component
identity: MCR and SIMPLISMA factors have permutation/scaling ambiguity.
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from tests._optional_scp import HAS_SCP

pytestmark = pytest.mark.skipif(not HAS_SCP, reason="requires the qualified SCP runtime")


def _mixture() -> SherpaDataset:
    # Include pure-variable anchors and pure-sample anchors in a rank-three,
    # nonnegative mixture with well-conditioned independent components.
    rng = np.random.default_rng(1208)
    concentrations = np.vstack((np.eye(3), rng.uniform(0.1, 1.0, (21, 3))))
    spectra = np.hstack((np.eye(3), rng.uniform(0.1, 1.0, (3, 21))))
    return SherpaDataset(
        X=concentrations @ spectra,
        feature_axis=FeatureAxis(values=np.arange(24, dtype=float)),
        data_role="X_spectra",
        is_time_series=True,
    )


@pytest.mark.asyncio
async def test_efa_matches_uncentered_svd_in_both_sample_directions() -> None:
    source = _mixture()
    result = await node_registry.create_node("model.efa", "efa-proof", {"n_components": 3}).execute(input_data=source)
    for port, reverse in (("forward_eigenvalues", False), ("backward_eigenvalues", True)):
        expected = np.zeros((len(source.X), 3))
        for row in range(len(source.X)):
            block = source.X[row:] if reverse else source.X[: row + 1]
            values = np.linalg.svd(block, compute_uv=False)[:3] ** 2
            expected[row, : len(values)] = values
        np.testing.assert_allclose(result.outputs[port].X, expected, rtol=1e-10, atol=1e-12)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,nonnegative", [("model.mcr_als", True), ("model.mcr_als", False), ("model.simplisma", False)]
)
async def test_unmixing_reconstruction_and_repeatability(operation: str, nonnegative: bool) -> None:
    source = _mixture()
    original = source.X.copy()
    parameters = {"n_components": 3}
    if operation == "model.mcr_als":
        parameters.update(max_iter=200, tol=1e-8, non_negative_C=nonnegative, non_negative_St=nonnegative)
    results = []
    for repeat in range(2):
        node = node_registry.create_node(operation, f"proof-{repeat}", parameters)
        results.append((await node.execute(input_data=source)).outputs)
    c_key, s_key = ("C", "St") if operation == "model.mcr_als" else ("concentrations", "spectra")
    for output in results:
        concentrations, spectra = output[c_key].X, output[s_key].X
        assert concentrations.shape == (24, 3)
        assert spectra.shape == (3, 24)
        assert np.isfinite(concentrations).all() and np.isfinite(spectra).all()
        if nonnegative:
            assert np.min(concentrations) >= -1e-12 and np.min(spectra) >= -1e-12
        relative_error = np.linalg.norm(original - concentrations @ spectra) / np.linalg.norm(original)
        assert relative_error < 1e-6
        if operation == "model.mcr_als":
            np.testing.assert_allclose(output["residuals"].X, original - concentrations @ spectra, atol=1e-12)
    for key in (c_key, s_key):
        np.testing.assert_allclose(results[0][key].X, results[1][key].X, rtol=1e-10, atol=1e-12)
    np.testing.assert_array_equal(source.X, original)
