from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.modeling.mcr_nodes import _compare_mcr_spectra_to_truth


def test_mcr_spectra_recovery_scores_recovered_st_against_ground_truth_s() -> None:
    x = np.linspace(600.0, 700.0, 101)
    water = np.exp(-((x - 630.0) ** 2) / 20.0)
    methane = np.exp(-((x - 670.0) ** 2) / 30.0)
    truth_s = np.vstack([water, methane])
    recovered_st = np.vstack([3.0 * methane, 2.0 * water])

    dataset = SherpaDataset(
        X=np.zeros((5, x.size)),
        feature_axis=SpectralAxis(values=x, title="Wavenumber", units="cm^-1"),
        sample_axis=SampleAxis(labels=[f"sample_{i + 1}" for i in range(5)]),
        extra={
            "ground_truth.spectra": truth_s.tolist(),
            "ground_truth.spectra_names": ["Water", "Methane"],
            "ground_truth.spectra_units": ["ppm^-1 m^-1"],
            "ground_truth.spectra_x": x.tolist(),
            "ground_truth.spectra_x_title": "Wavenumber",
            "ground_truth.spectra_x_units": "cm^-1",
        },
    )

    comparison = _compare_mcr_spectra_to_truth(
        recovered_st,
        dataset,
        selected_target_index=0,
        selected_component_index=1,
        component_labels=["Recovered methane", "Recovered water"],
    )

    assert comparison is not None
    assert comparison["selected_match"]["truth_name"] == "Water"
    assert comparison["selected_match"]["component_name"] == "Recovered water"
    assert comparison["selected_match"]["correlation"] == pytest.approx(1.0)
    assert comparison["selected_match"]["r2"] == pytest.approx(1.0)
    assert comparison["truth_spectra"] == truth_s.tolist()
    assert comparison["truth_spectra_x"] == x.tolist()
    assert comparison["truth_spectra_x_title"] == "Wavenumber"
    assert comparison["truth_spectra_x_units"] == "cm^-1"

    suggested = {(item["component_name"], item["truth_name"]): item for item in comparison["suggested_matches"]}
    assert suggested[("Recovered water", "Water")]["correlation"] == pytest.approx(1.0)
    assert suggested[("Recovered methane", "Methane")]["correlation"] == pytest.approx(1.0)
