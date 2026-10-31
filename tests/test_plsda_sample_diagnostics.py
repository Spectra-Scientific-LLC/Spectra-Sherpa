"""Selected PLS-DA variable terms reconcile with the fitted global screen."""

from __future__ import annotations

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import _plsda_scientific_core
from spectra_sherpa.app.services.dag.nodes.classification.plsda_sample_diagnostics import build_sample_diagnostics


def _core(per_class: int = 12):
    rng = np.random.default_rng(1203)
    labels = np.repeat(["a", "b", "c"], per_class)
    matrix = rng.normal(size=(len(labels), 8))
    matrix[labels == "a", :3] += [1.0, 0.3, 0.2]
    matrix[labels == "b", :3] += [0.1, 1.0, 0.4]
    matrix[labels == "c", :3] += [0.2, 0.4, 1.0]
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.linspace(1000, 1700, 8), units="cm-1"),
        sample_axis=SampleAxis(
            labels=[f"Display {i}" for i in range(len(labels))],
            sample_table={"sample_id": [f"obs-{i}" for i in range(len(labels))]},
        ),
        target=labels,
        target_context=TargetContext(target_type="categorical", target_names=["class"]),
    )
    return _plsda_scientific_core(dataset, labels, parameters={"n_components": 2, "scale": True})


def test_selected_terms_reconstruct_fitted_sample_t2_and_q() -> None:
    result = build_sample_diagnostics(_core())
    assert result["model_kind"] == "plsda"
    assert result["reference_count"] == 36
    assert result["feature_units"] == "cm-1"
    assert result["screening_method"] == "prediction_f_and_residual_spectrum_0.95_strict_greater"
    assert result["score_covariance_rank"] == result["components"]
    assert len(result["rows"]) == 36
    for row in result["rows"]:
        terms = row["terms"]
        q = sum(variable[1] for variable in terms["variables"]) + terms["omitted_q"]
        t2 = sum(variable[2] for variable in terms["variables"]) + terms["omitted_t2"]
        np.testing.assert_allclose(q, row["q"], rtol=1e-10, atol=1e-12)
        np.testing.assert_allclose(t2, row["t2"], rtol=1e-10, atol=1e-12)
        assert row["outside_t2"] == (row["t2"] > result["t2_limit"])
        assert row["outside_q"] == (row["q"] > result["q_limit"])
        assert row["role"] == "calibration"


def test_duplicate_observation_identity_is_refused() -> None:
    core = _core()
    axis = core["dataset"].sample_axis
    ids = list(axis.sample_table["sample_id"])
    ids[1] = ids[0]
    axis.sample_table = {"sample_id": ids}
    core["dataset"].sample_axis = axis
    try:
        build_sample_diagnostics(core)
    except ValueError as exc:
        assert "sample_id" in str(exc) and "unique" in str(exc)
    else:
        raise AssertionError("Duplicate observation identity was admitted")


def test_chunked_diagnostics_keep_observation_order_across_64_row_boundary() -> None:
    result = build_sample_diagnostics(_core(per_class=24))
    assert result["reference_count"] == 72
    assert [row["id"] for row in result["rows"]] == [f"obs-{i}" for i in range(72)]
    for row in result["rows"][63:66]:
        assert np.isclose(
            sum(term[1] for term in row["terms"]["variables"]) + row["terms"]["omitted_q"],
            row["q"],
        )
        assert np.isclose(
            sum(term[2] for term in row["terms"]["variables"]) + row["terms"]["omitted_t2"],
            row["t2"],
        )


def test_small_reference_fit_keeps_unavailable_screens_unknown_to_advisor() -> None:
    from spectra_sherpa.app.services.diagnostic_review_summary import build_summary

    matrix = np.array([[1.0, 2.0, 3.0, 4.0], [2.0, 0.0, 4.0, 5.0], [4.0, 3.0, 1.0, 0.0], [3.0, 5.0, 2.0, 1.0]])
    labels = np.array(["a", "b", "a", "b"])
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.arange(4), units="cm-1"),
        sample_axis=SampleAxis(
            labels=["Display 1", "Display 2", "Display 3", "Display 4"],
            sample_table={"sample_id": ["a1", "b1", "a2", "b2"]},
        ),
        target=labels,
        target_context=TargetContext(target_type="categorical", target_names=["class"]),
    )
    core = _plsda_scientific_core(dataset, labels, parameters={"n_components": 3, "scale": True})
    receipt = build_sample_diagnostics(core)
    assert receipt["components"] == 3
    assert receipt["t2_limit"] is None and receipt["q_limit"] is None
    assert receipt["t2_unavailable_reason"] == "insufficient_reference_degrees_of_freedom"
    assert receipt["q_unavailable_reason"] == "insufficient_reference_degrees_of_freedom"
    assert all(row["t2"] is None and row["outside_t2"] is None and row["outside_q"] is None for row in receipt["rows"])
    packet = build_summary(receipt, selected_ids=["a1"], variable_ids=[])
    facts = packet["facts"]
    assert facts["selection.t2.unknown"]["value"] == 1
    assert facts["selection.q.unknown"]["value"] == 1
    assert facts["selection.q.valid"]["value"] == 1
