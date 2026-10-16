"""Independent full-covariance and reconstruction checks for saved PLS review."""

from copy import deepcopy

import numpy as np
import pytest
from scipy.stats import f

from spectra_sherpa.app.services import pls_review_applicability as applicability
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import (
    FittedPLSV2Node,
    verify_fitted_pls_state_envelope,
)
from spectra_sherpa.app.services.pls_review_evidence import build_review_receipt
from tests.test_pls_sample_review import definition, run


@pytest.mark.asyncio
@pytest.mark.parametrize("responses", [1, 2])
@pytest.mark.parametrize("scale", [False, True])
async def test_saved_scores_full_covariance_q_and_signed_terms(responses, scale, monkeypatch):
    original, _, _ = await run(responses=responses, scale=scale)
    removed = original["calibration_ids"][-1]
    monkeypatch.setattr(applicability, "MAX_TERMS", 80)  # One leading term per statistic.
    receipt, dataset, results = await run([removed], responses=responses, scale=scale)
    detail = receipt["pls_applicability"]
    assert "unavailable_reason" not in detail
    state = verify_fitted_pls_state_envelope(results["pls"]["fitted_state"])
    diagnostic = state["diagnostic_state"]
    by_id = dict(zip(dataset.sample_axis.labels, dataset.X))
    n, k = 29, state["effective_n_components"]
    reference = np.asarray([by_id[row["id"]] for row in receipt["rows"] if row["role"] == "calibration"])
    offset, scale_vector = np.asarray(state["feature_offset"]).reshape(-1), np.asarray(diagnostic["x_scale"])
    z_reference = (reference - offset) / scale_vector
    projection, reconstruction = np.asarray(diagnostic["projection"]), np.asarray(diagnostic["reconstruction"])
    calibration_scores = z_reference @ projection
    mean = calibration_scores.mean(axis=0)
    covariance = np.cov(calibration_scores, rowvar=False, ddof=1)
    inverse = np.linalg.inv(covariance)
    calibration_limit = k * (n - 1) / (n - k) * f.ppf(0.95, k, n - k)
    assert detail["calibration_t2_limit"] == pytest.approx(calibration_limit)
    assert detail["application_t2_limit"] == pytest.approx(calibration_limit * (n + 1) / n)
    assert detail["score_covariance_rank"] == k
    assert detail["reference_count"] == n
    for row in receipt["rows"]:
        z = (by_id[row["id"]] - offset) / scale_vector
        scores = z @ projection
        t2 = (scores - mean) @ inverse @ (scores - mean)
        residual = z - scores @ reconstruction.T
        q_terms = residual**2
        t_terms = (z - z_reference.mean(axis=0)) * ((scores - mean) @ inverse @ projection.T)
        np.testing.assert_allclose(row["scores"], scores, atol=1e-12)
        assert row["t2"] == pytest.approx(t2)
        assert row["q"] == pytest.approx(q_terms.sum())
        chosen_limit = calibration_limit if row["role"] == "calibration" else detail["application_t2_limit"]
        assert row["outside_t2"] == (t2 > chosen_limit)
        assert row["outside_q"] == (q_terms.sum() > detail["q_limit"])
        terms = detail["rows"][row["id"]]
        indices = [item[0] for item in terms["variables"]]
        omitted = np.ones(dataset.shape[1], bool)
        omitted[indices] = False
        np.testing.assert_allclose([item[1] for item in terms["variables"]], q_terms[indices])
        np.testing.assert_allclose([item[2] for item in terms["variables"]], t_terms[indices], atol=1e-12)
        assert terms["omitted_q"] == pytest.approx(q_terms[omitted].sum())
        assert terms["omitted_t2"] == pytest.approx(t_terms[omitted].sum())
        assert terms["omitted_t2_absolute"] == pytest.approx(np.abs(t_terms[omitted]).sum())
    assert receipt["full_test_statistics"] is not None

    def never_fit(*args, **kwargs):
        raise AssertionError("Applicability replay must never fit")

    monkeypatch.setattr(FittedPLSV2Node, "_fit_model_and_state", never_fit)
    replay = await build_review_receipt(definition([removed]), results, "pls")
    assert replay["pls_applicability"] == detail
    assert replay["rows"] == receipt["rows"]


@pytest.mark.asyncio
async def test_covariance_basis_rotation_nonzero_center_and_extreme_application():
    receipt, _, results = await run(responses=2, scale=True)
    state = verify_fitted_pls_state_envelope(results["pls"]["fitted_state"])
    original = deepcopy(state["diagnostic_state"])
    d = state["diagnostic_state"]
    train, test = results["split"]["X_train"].copy(), results["split"]["X_test"].copy()
    # Equivalent nonorthogonal score basis: full covariance must preserve T²/Q.
    rotation = np.array([[2.0, 0.7], [0.0, 0.5]])
    projection = np.asarray(d["projection"]) @ rotation
    reconstruction = np.asarray(d["reconstruction"]) @ np.linalg.inv(rotation).T
    d["projection"], d["reconstruction"] = projection.tolist(), reconstruction.tolist()
    # Retained calibration mean is explicitly nonzero in this equivalent test frame.
    state["feature_offset"] = (np.asarray(state["feature_offset"]) + 0.125).tolist()
    z = (train.X - state["feature_offset"]) / d["x_scale"]
    scores = z @ projection
    center = scores.mean(axis=0)
    covariance = np.cov(scores, rowvar=False, ddof=1)
    eigenvalues = np.linalg.eigvalsh(covariance)
    d["score_center"] = center.tolist()
    d["score_covariance_inverse"] = np.linalg.inv(covariance).tolist()
    d["rank_tolerance"] = np.finfo(float).eps * 2 * eigenvalues[-1]
    test.X[:] *= 1e6
    detail, updates = applicability.build_applicability(
        state, "a" * 64, "b" * 64, [train, test], receipt["rows"], [], scores, reconstruction.T
    )
    assert detail["application_t2_limit"] == original["t2_limit"]
    assert detail["q_limit"] == original["q_limit"]
    assert abs(center).max() > 0
    assert abs(covariance[0, 1]) > 1e-6
    for identity, item in detail["rows"].items():
        assert sum(v[2] for v in item["variables"]) + item["omitted_t2"] == pytest.approx(updates[identity]["t2"])
        assert all(v[1] >= 0 for v in item["variables"])
    assert any(v[2] < 0 for item in detail["rows"].values() for v in item["variables"])
    assert all(updates[identity]["outside_t2"] for identity in test.sample_axis.labels)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["scores", "loadings", "work", "bytes"])
async def test_optional_applicability_failure_preserves_predictions_and_review(failure, monkeypatch):
    original, _, results = await run()
    if failure == "scores":
        results["pls"]["x_scores"][0, 0] += 1
    elif failure == "loadings":
        results["pls"]["x_loadings"][0, 0] += 1
    elif failure == "work":
        monkeypatch.setattr(applicability, "MAX_WORK", 1)
    else:
        monkeypatch.setattr(applicability, "MAX_BYTES", 1)
    changed = await build_review_receipt(definition(), results, "pls")
    assert "unavailable_reason" in changed["pls_applicability"]
    assert changed["full_test_statistics"] == original["full_test_statistics"]
    assert changed["heldout_ids"] == original["heldout_ids"]
    assert [r["predicted"] for r in changed["rows"]] == [r["predicted"] for r in original["rows"]]


@pytest.mark.asyncio
async def test_optional_decomposition_failure_keeps_global_diagnostics(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ValueError("Optional term reconciliation unavailable")

    monkeypatch.setattr(applicability, "_row_terms", unavailable)
    receipt, _, _ = await run()
    assert "unavailable_reason" not in receipt["pls_applicability"]
    assert all(row["scores"] and row["q"] is not None for row in receipt["rows"])
    for terms in receipt["pls_applicability"]["rows"].values():
        assert terms["variables"] == []
        assert terms["decomposition_unavailable_reason"]
        assert terms["omitted_q"] is None


@pytest.mark.asyncio
async def test_legacy_screening_is_not_relabeled_as_modern_f_limits():
    from spectra_sherpa.app.services.dag.nodes.modeling import pls_applicability

    receipt, _, results = await run()
    state = verify_fitted_pls_state_envelope(results["pls"]["fitted_state"])
    d = state["diagnostic_state"]
    d["schema_version"], d["method"] = pls_applicability.LEGACY_SCHEMA, pls_applicability.LEGACY_METHOD
    d.pop("q_residual_eigenvalues")
    d.pop("q_limit_method")
    d["q_limit"] = max(d["q_calibration_quantile"], d["q_numerical_tolerance"])
    with pytest.raises(ValueError, match="Legacy empirical"):
        applicability.build_applicability(
            state,
            "a" * 64,
            "b" * 64,
            [results["split"]["X_train"], results["split"]["X_test"]],
            receipt["rows"],
            [],
            results["pls"]["x_scores"],
            results["pls"]["x_loadings"],
        )


@pytest.mark.asyncio
async def test_rank_deficient_score_space_never_uses_pseudoinverse():
    receipt, _, results = await run()
    state = verify_fitted_pls_state_envelope(results["pls"]["fitted_state"])
    d = state["diagnostic_state"]
    projection = np.asarray(d["projection"])
    projection[:, 1] = projection[:, 0] * 1e-10
    train = results["split"]["X_train"]
    scores = ((train.X - state["feature_offset"]) / d["x_scale"]) @ projection
    d["projection"] = projection.tolist()
    d["score_center"] = scores.mean(axis=0).tolist()
    eigenvalues = np.linalg.eigvalsh(np.cov(scores, rowvar=False, ddof=1))
    d["rank_tolerance"] = np.finfo(float).eps * 2 * eigenvalues[-1]
    d["score_covariance_rank"] = 1
    d["score_covariance_inverse"] = None
    d["t2_limit"] = d["q_limit"] = None
    d["t2_unavailable_reason"] = d["q_unavailable_reason"] = "rank_deficient_score_covariance"
    detail, updates = applicability.build_applicability(
        state,
        "a" * 64,
        "b" * 64,
        [train, results["split"]["X_test"]],
        receipt["rows"],
        [],
        scores,
        results["pls"]["x_loadings"],
    )
    assert detail["calibration_t2_limit"] is None
    assert detail["application_t2_limit"] is None
    assert all(row["t2"] is None and row["outside_t2"] is None and row["outside_q"] is None for row in updates.values())
    assert all(row["screening_status"] == "unavailable" for row in updates.values())
    assert all(term[2] is None for row in detail["rows"].values() for term in row["variables"])


@pytest.mark.asyncio
async def test_combined_receipt_budget_withholds_terms_before_global_diagnostics(monkeypatch):
    import json

    from spectra_sherpa.app.services import pls_review_evidence

    original, _, results = await run()
    base = deepcopy(original)
    base.pop("pls_explanations")
    lean = deepcopy(base)
    lean["pls_applicability"] = applicability.without_decomposition(
        lean["pls_applicability"], "Optional terms exceed the retained review receipt budget."
    )
    lean_size = len(json.dumps(lean, allow_nan=False).encode())
    full_size = len(json.dumps(base, allow_nan=False).encode())
    assert lean_size < full_size
    monkeypatch.setattr(pls_review_evidence, "MAX_RECEIPT_BYTES", lean_size + 100)
    result = await build_review_receipt(definition(), results, "pls")
    assert "unavailable_reason" not in result["pls_applicability"]
    assert all(row["scores"] for row in result["rows"])
    assert all(row["decomposition_unavailable_reason"] for row in result["pls_applicability"]["rows"].values())
    assert len(json.dumps(result, allow_nan=False).encode()) <= lean_size + 100


@pytest.mark.asyncio
async def test_near_component_reference_size_keeps_scores_but_withholds_limits():
    initial, _, _ = await run()
    receipt, _, _ = await run(initial["calibration_ids"][:-3])
    detail = receipt["pls_applicability"]
    assert detail["reference_count"] == 3
    assert detail["components"] == 2
    assert detail["t2_unavailable_reason"] == "insufficient_reference_degrees_of_freedom"
    assert detail["calibration_t2_limit"] is None
    assert detail["application_t2_limit"] is None
    assert detail["q_limit"] is None
    assert all(len(row["scores"]) == 2 and row["t2"] is None and row["q"] is not None for row in receipt["rows"])
    assert all(row["screening_status"] == "unavailable" for row in receipt["rows"])


@pytest.mark.asyncio
async def test_limits_use_effective_components_not_requested_count():
    receipt, _, results = await run()
    state = verify_fitted_pls_state_envelope(results["pls"]["fitted_state"])
    state["n_components"] = 5  # A request is not authority for retained fitted dimensions.
    detail, updates = applicability.build_applicability(
        state,
        "a" * 64,
        "b" * 64,
        [results["split"]["X_train"], results["split"]["X_test"]],
        receipt["rows"],
        [],
        results["pls"]["x_scores"],
        results["pls"]["x_loadings"],
    )
    assert detail["components"] == 2
    assert detail["calibration_t2_limit"] == receipt["pls_applicability"]["calibration_t2_limit"]
    assert detail["application_t2_limit"] == receipt["pls_applicability"]["application_t2_limit"]
    assert all(len(row["scores"]) == 2 for row in updates.values())


def test_nonfinite_absolute_mass_cannot_relax_signed_reconciliation():
    diagnostic = {
        "projection": [[1.0], [-1.0]],
        "reconstruction": [[0.0], [0.0]],
        "score_center": [0.0],
        "score_covariance_inverse": [[1e308]],
    }
    # Individual signed T² terms are finite and cancel, but their absolute mass
    # overflows. An infinite tolerance must never make reconciliation succeed.
    with np.errstate(over="ignore"), pytest.raises(ValueError, match="do not reproduce"):
        applicability._row_terms(
            np.array([1.0, 1.0]), np.array([1.0]), diagnostic, np.zeros(2), {"q": 2.0, "t2": 1.0}, 1
        )
