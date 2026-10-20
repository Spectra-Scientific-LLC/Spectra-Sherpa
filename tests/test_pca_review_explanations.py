"""Independent numeric and identity checks for read-only PCA explanations."""

import json

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode
from spectra_sherpa.app.services.pca_review_explanations import build_explanations
from tests.test_pca_sample_review import dataset, run


@pytest.mark.asyncio
async def test_exact_excluded_contributions_and_restore_do_not_refit(monkeypatch):
    original = await run(dataset())
    from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode

    def block_fit(results):
        def forbidden(*args, **kwargs):
            raise AssertionError("Explanation must not fit")

        monkeypatch.setattr(ScaleNode, "fit_fitted_state", forbidden)
        monkeypatch.setattr(PCANode, "fit_fitted_state", forbidden)

    reviewed = await run(dataset(), ["s39"], before_receipt=block_fit)
    explanation = reviewed["explanations"]
    assert "unavailable_reason" not in explanation, explanation
    assert explanation["reference_count"] == 39
    assert explanation["reference_digest"] != original["explanations"]["reference_digest"]
    assert explanation["model_digest"] != original["explanations"]["model_digest"]
    assert explanation["feature_identity"] == original["explanations"]["feature_identity"]
    for row in reviewed["rows"]:
        detail = explanation["rows"][row["id"]]
        assert sum(v[1] for v in detail["variables"]) == pytest.approx(row["q"])
        assert sum(v[2] for v in detail["variables"]) == pytest.approx(row["t2"])
    monkeypatch.undo()
    restored = await run(dataset())
    for key in original["explanations"]:
        if key != "input_digests":  # execution provenance is correctly specific to each run
            assert restored["explanations"][key] == original["explanations"][key]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["center", "standard", "minmax", "full_rank"])
async def test_independent_model_space_formula_sparse_remainders_and_cancellation(mode, monkeypatch):
    import spectra_sherpa.app.services.pca_review_explanations as module

    rng = np.random.default_rng(81)
    x = rng.normal(size=(32, 8)) * np.arange(1, 9) + 13
    ds = SherpaDataset(
        X=x,
        sample_axis=SampleAxis(
            labels=[f"r{i}" for i in range(32)],
            sample_table={"sample_id": [f"r{i}" for i in range(32)]},
        ),
        feature_axis=SpectralAxis(values=np.arange(8.0), units="nm"),
    )
    parameters = {
        "n_components": "8" if mode == "full_rank" else "3",
        "standardized": mode == "standard",
        "scaled": mode == "minmax",
    }
    output = (await PCANode("p", parameters).execute(input_data=ds)).outputs
    state = output["fitted_state"]
    arrays = state["arrays"]
    # Independent preprocessing and linear-algebra calculation, not production helper.
    z = x.copy()
    for name in ("mean", "offset"):
        if arrays[name] is not None:
            z -= arrays[name]
    if arrays["scale"] is not None:
        z /= arrays["scale"]
    if arrays["center"] is not None:
        z -= arrays["center"]
    p = np.array(arrays["loadings"])
    lam = np.array(arrays["explained_variance"])
    t = z @ p.T
    q = (z - t @ p) ** 2
    if mode == "full_rank":
        q[:] = 0
    c = z * ((t / lam) @ p)
    rows = [
        {"id": f"r{i}", "role": "calibration", "scores": t[i].tolist(), "q": q[i].sum(), "t2": (t[i] ** 2 / lam).sum()}
        for i in range(32)
    ]
    monkeypatch.setattr(module, "MAX_RECORDS", 64)  # one leading variable per statistic
    result = build_explanations(state, [(ds, output["scores"].X)], rows, [])
    assert result["top_per_statistic"] == 1
    cancellation = False
    for i, row in enumerate(rows):
        detail = result["rows"][row["id"]]
        selected = {v[0] for v in detail["variables"]}
        for j, qj, tj in detail["variables"]:
            assert qj == pytest.approx(q[i, j], abs=1e-10)
            assert tj == pytest.approx(c[i, j], abs=1e-10)
        assert sum(v[1] for v in detail["variables"]) + detail["omitted_q"] == pytest.approx(row["q"])
        assert sum(v[2] for v in detail["variables"]) + detail["omitted_t2"] == pytest.approx(row["t2"])
        omitted = [j for j in range(8) if j not in selected]
        assert detail["omitted_t2_absolute"] == pytest.approx(np.abs(c[i, omitted]).sum())
        cancellation |= detail["omitted_t2_absolute"] > abs(detail["omitted_t2"]) + 1e-5
    assert cancellation
    assert len(json.dumps(result)) < module.MAX_BYTES
    # Axis and observation identities fail closed, even if numerical arrays agree.
    ds.sample_axis = SampleAxis(
        labels=ds.sample_axis.labels,
        sample_table={"sample_id": list(reversed(ds.sample_axis.sample_table["sample_id"]))},
    )
    with pytest.raises(ValueError, match="observation order"):
        build_explanations(state, [(ds, output["scores"].X)], rows, [])
    ds.sample_axis = SampleAxis(
        labels=[f"r{i}" for i in range(32)],
        sample_table={"sample_id": [f"r{i}" for i in range(32)]},
    )
    ds.feature_axis = SpectralAxis(values=np.arange(8.0) + 1, units="nm")
    with pytest.raises(ValueError, match="feature axis"):
        build_explanations(state, [(ds, output["scores"].X)], rows, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["budget", "loading_budget", "scores", "projection", "axis"])
async def test_optional_evidence_failure_keeps_review_usable(failure, monkeypatch):
    import spectra_sherpa.app.services.pca_review_explanations as module

    def corrupt(results):
        if failure == "scores":
            results["pca"]["scores"].X[0, 0] += 1
        if failure == "axis":
            results["scale"].feature_axis = SpectralAxis(values=np.arange(8.0) + 1, units="cm^-1")
        if failure == "projection":
            from spectra_sherpa.app.lib.sherpa_dataset import Provenance

            results["scale"].provenance = Provenance.from_list([])

    if failure == "budget":
        monkeypatch.setattr(module, "MAX_BYTES", 1)
    if failure == "loading_budget":
        monkeypatch.setattr(module, "MAX_LOADING_CELLS", 1)
    receipt = await run(dataset(), ["s39"], before_receipt=corrupt)
    assert len(receipt["rows"]) == 40
    if failure in {"budget", "scores", "axis"}:
        assert receipt["explanations"]["unavailable_reason"]
    elif failure == "loading_budget":
        assert receipt["explanations"]["loadings"] is None
        assert receipt["explanations"]["rows"]["s39"]
    else:
        assert "s39" not in receipt["explanations"]["rows"]
        assert receipt["rows"][-1]["projection_error"]


@pytest.mark.asyncio
async def test_work_budget_refuses_before_expensive_validation(monkeypatch):
    import spectra_sherpa.app.services.pca_review_explanations as module

    def block_validation(results):
        monkeypatch.setattr(module, "MAX_WORK", 0)

        def forbidden(*args, **kwargs):
            raise AssertionError("Work budget must precede state validation/replay")

        monkeypatch.setattr(module, "validate_pca_fitted_state", forbidden)

    receipt = await run(dataset(), before_receipt=block_validation)
    assert "calculation budget" in receipt["explanations"]["unavailable_reason"]
    assert len(receipt["rows"]) == 40
