"""Independent additive prediction checks and custody for the PLS workbench."""

from copy import deepcopy

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.services import pls_review_explanations as explanations
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import (
    FittedPLSV2Node,
    verify_fitted_pls_state_envelope,
)
from spectra_sherpa.app.services.pca_review_evidence import filter_id
from spectra_sherpa.app.services.pls_review_evidence import build_review_receipt
from tests.test_pls_sample_review import definition, run


@pytest.mark.asyncio
@pytest.mark.parametrize("responses", [1, 2])
@pytest.mark.parametrize("scale", [False, True])
async def test_exact_affine_explanations_for_calibration_excluded_and_test(responses, scale, monkeypatch):
    # Keep only one variable per target so the test checks signed/absolute omission.
    monkeypatch.setattr(explanations, "MAX_RECORDS", 40 * responses)
    original, _, _ = await run(responses=responses, scale=scale)
    excluded = [original["calibration_ids"][-1]]
    review, ds, results = await run(excluded, responses=responses, scale=scale)
    detail = review["pls_explanations"]
    state = verify_fitted_pls_state_envelope(results["pls"]["fitted_state"])
    assert detail["reference_count"] == 29
    assert detail["top_per_response"] == 1
    assert detail["response_identity"] == state["response_identity"]
    assert len(detail["rows"]) == 40
    coefficients = np.asarray(state["coefficients"])
    offset = np.asarray(state["feature_offset"])[0]
    baseline = np.asarray(state["prediction_offset"])[0]
    np.testing.assert_array_equal(offset, results[filter_id("pls")].X.mean(axis=0))
    by_id = dict(zip(ds.sample_axis.labels, ds.X))
    for row in review["rows"]:
        independent = (by_id[row["id"]] - offset)[:, None] * coefficients
        np.testing.assert_allclose(independent.sum(axis=0) + baseline, row["predicted"], atol=1e-10)
        for t, response in enumerate(detail["rows"][row["id"]]):
            columns = [v[0] for v in response["variables"]]
            omitted = np.ones(ds.shape[1], dtype=bool)
            omitted[columns] = False
            np.testing.assert_allclose([v[1] for v in response["variables"]], independent[columns, t])
            assert response["omitted_signed"] == pytest.approx(independent[omitted, t].sum())
            assert response["omitted_absolute"] == pytest.approx(np.abs(independent[omitted, t]).sum())
            assert response["prediction"] == row["predicted"][t]
    np.testing.assert_array_equal(detail["coefficients"], coefficients.T)
    np.testing.assert_array_equal(detail["loadings"], results["pls"]["x_loadings"])
    assert review["full_test_statistics"]["targets"][0]["metrics"]["n_samples"] == 10
    restored, _, _ = await run(responses=responses, scale=scale)
    for key in original["pls_explanations"]:
        if key != "input_digests":
            assert restored["pls_explanations"][key] == original["pls_explanations"][key]

    def no_fit(*args, **kwargs):
        raise AssertionError("Explanations must never refit")

    monkeypatch.setattr(FittedPLSV2Node, "_fit_model_and_state", no_fit)
    replay = await build_review_receipt(definition(excluded), results, "pls")
    for key in detail:
        if key != "input_digests":
            assert replay["pls_explanations"][key] == detail[key]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["work", "bytes", "profiles", "prediction", "axis", "labels", "loadings"])
async def test_optional_failure_keeps_core_review_and_test_metrics(failure, monkeypatch):
    original, _, results = await run(responses=2)
    if failure == "work":
        monkeypatch.setattr(explanations, "MAX_WORK", 1)
    elif failure == "bytes":
        monkeypatch.setattr(explanations, "MAX_BYTES", 100)
    elif failure == "profiles":
        monkeypatch.setattr(explanations, "MAX_PROFILE_CELLS", 1)
    elif failure == "prediction":
        results["pls"]["default"][0, 0] += 1
    elif failure == "axis":
        results["split"]["X_test"].feature_axis = SpectralAxis(values=np.arange(8.0), units="nm")
    elif failure == "labels":
        results["split"]["X_test"].feature_axis = SpectralAxis(
            values=np.arange(8.0), units="cm^-1", labels=["duplicate"] * 8
        )
    elif failure == "loadings":
        results["pls"]["x_loadings"][0, 0] += 1
    reviewed = await build_review_receipt(definition(), results, "pls")
    assert reviewed["full_test_statistics"] == original["full_test_statistics"]
    assert reviewed["calibration_ids"] == original["calibration_ids"]
    if failure == "profiles":
        assert len(reviewed["pls_explanations"]["rows"]) == 40
        assert reviewed["pls_explanations"]["coefficients"] is None
    else:
        assert "unavailable_reason" in reviewed["pls_explanations"]


@pytest.mark.asyncio
async def test_unavailable_excluded_projection_does_not_invent_terms(monkeypatch):
    from spectra_sherpa.app.services import pls_review_evidence

    original, _, _ = await run()
    excluded = original["calibration_ids"][-1]

    async def unavailable(*args, **kwargs):
        raise ValueError("Exact transform unavailable")

    monkeypatch.setattr(pls_review_evidence, "project_excluded", unavailable)
    review, _, _ = await run([excluded])
    assert excluded not in review["pls_explanations"]["rows"]
    assert len(review["pls_explanations"]["rows"]) == 39
    assert next(r for r in review["rows"] if r["id"] == excluded)["projection_error"] == "Exact transform unavailable"


@pytest.mark.asyncio
async def test_response_reorder_and_duplicate_population_refused():
    review, _, results = await run(responses=2)
    state = verify_fitted_pls_state_envelope(results["pls"]["fitted_state"])
    populations = [results["split"]["X_train"], results["split"]["X_test"]]
    rows = deepcopy(review["rows"])
    rows[-1]["predicted"].reverse()
    with pytest.raises(ValueError, match="exact retained predictions"):
        explanations.build_explanations(state, "model", "contract", populations, rows, [], results["pls"]["x_loadings"])
    with pytest.raises(ValueError, match="identity"):
        explanations.build_explanations(
            state, "model", "contract", populations + populations[1:], review["rows"], [], results["pls"]["x_loadings"]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["large_offset", "rank_one", "constant_feature"])
async def test_affine_reference_cancellation_and_effective_rank(mode):
    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset

    x = np.random.default_rng(681).normal(size=(32, 6))
    if mode == "large_offset":
        x += 1e6
    elif mode == "rank_one":
        x = x[:, :1] @ np.arange(1, 7.0)[None, :]
    else:
        x[:, 5] = 10
    y = np.column_stack((x[:, 0] * 3 - x[:, 1] * 2, x[:, 2] - x[:, 3]))
    # Near-zero final responses exercise cancellation relative to the baseline.
    y -= y[:1]
    ds = SherpaDataset(
        X=x,
        target=y,
        sample_axis=SampleAxis(labels=[f"c{i}" for i in range(32)]),
        feature_axis=SpectralAxis(values=np.arange(6.0), units="nm"),
    )
    output = (await FittedPLSV2Node("pls", {"n_components": 3, "scale": False}).execute(input_data=ds)).outputs
    state = verify_fitted_pls_state_envelope(output["fitted_state"])
    rows = [
        {"id": identity, "role": "calibration", "predicted": output["default"][i].tolist()}
        for i, identity in enumerate(ds.sample_axis.labels)
    ]
    detail = explanations.build_explanations(state, "model", "contract", [ds], rows, [], output["x_loadings"])
    if mode == "rank_one":
        assert len(detail["loadings"]) < 3
    for r in rows:
        for t, e in enumerate(detail["rows"][r["id"]]):
            assert detail["baseline"][t] + sum(v[1] for v in e["variables"]) == pytest.approx(
                r["predicted"][t], abs=1e-9
            )
            if mode == "constant_feature":
                assert next(v[1] for v in e["variables"] if v[0] == 5) == 0


@pytest.mark.asyncio
async def test_overflowed_absolute_mass_cannot_disable_prediction_integrity():
    review, _, results = await run()
    state = verify_fitted_pls_state_envelope(results["pls"]["fitted_state"])
    state["coefficients"] = [[v] for v in [1e308, -1e308, 1e308, -1e308, 0, 0, 0, 0]]
    train = results["split"]["X_train"].copy()
    x = np.tile(np.asarray(state["feature_offset"])[0] + 1, (train.shape[0], 1))
    train = train.with_data(x)
    rows = deepcopy([r for r in review["rows"] if r["role"] == "calibration"])
    for row in rows:
        row["predicted"] = [state["prediction_offset"][0][0] + 100]
    # All individual terms are finite; the absolute mass overflows while the
    # signed sum cancels. An infinite tolerance must not admit the wrong value.
    with np.errstate(over="ignore", invalid="ignore"):
        with pytest.raises(ValueError, match="exact retained predictions"):
            explanations.build_explanations(state, "model", "contract", [train], rows, [], results["pls"]["x_loadings"])
