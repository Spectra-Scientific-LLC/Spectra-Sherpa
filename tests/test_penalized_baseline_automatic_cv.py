"""One qualified sample-local operation, not generic stateless-CV admission."""

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.component_validation import cv_unavailable_reason
from spectra_sherpa.app.services.dag.nodes.preprocessing import penalized_baseline_node as baseline
from spectra_sherpa.app.types import type_registry


@pytest.fixture(autouse=True)
def _types():
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).parents[1] / "src/spectra_sherpa/app/types")


def source():
    rng = np.random.default_rng(750)
    axis = np.linspace(0, 1, 81)
    target = np.linspace(0.5, 2, 24)
    matrix = (
        0.2
        + 0.3 * axis
        + target[:, None] * np.exp(-(((axis - 0.35) / 0.06) ** 2))
        + rng.uniform(0.2, 0.6, (24, 1)) * np.exp(-(((axis - 0.7) / 0.08) ** 2))
        + rng.normal(0, 0.002, (24, 81))
    )
    ids = [f"fixture-{i}" for i in range(24)]
    ds = SherpaDataset(
        X=matrix,
        target=target,
        units="absorbance",
        data_role="X_spectra",
        feature_axis=SpectralAxis(values=1000 + axis * 800, units="cm-1"),
        sample_axis=SampleAxis(labels=ids, sample_table={"sample_id": ids}),
        target_context=TargetContext(target_names=["Analyte"], target_units="mg/L"),
    )
    ds.provenance.append(op_id="data.file_load", parameters={"stage": "raw"})
    return ds


def params(method):
    return {"method": method, "lam": 1e5, "p": 0.001, "max_iter": 5, "tol": 1e-6}


@pytest.mark.parametrize("method", ["als", "arpls", "airpls"])
def test_baseline_is_identical_by_partition_single_row_and_permutation(method):
    ds = source()
    original = ds.X.copy()
    full, _ = baseline._penalized_baseline_dispatch(ds.X, **params(method))
    parts = [
        baseline._penalized_baseline_dispatch(ds.X[ids], **params(method))[0]
        for ids in [np.arange(18), np.arange(18, 24)]
    ]
    np.testing.assert_array_equal(full, np.concatenate(parts))
    individual = [baseline._penalized_baseline_dispatch(row, **params(method))[0] for row in ds.X]
    np.testing.assert_array_equal(full, individual)
    permutation = np.random.default_rng(752).permutation(24)
    reordered, _ = baseline._penalized_baseline_dispatch(ds.X[permutation], **params(method))
    np.testing.assert_array_equal(reordered, full[permutation])
    changed = ds.X.copy()
    changed[18:] += 100 * np.sin(np.linspace(0, 4, 81))
    changed_full, _ = baseline._penalized_baseline_dispatch(changed, **params(method))
    np.testing.assert_array_equal(changed_full[:18], full[:18])
    np.testing.assert_array_equal(ds.X, original)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["als", "arpls", "airpls"])
async def test_real_baseline_split_and_automatic_pls_keep_warning_and_train_only_folds(method):
    ds = source()
    transformed = await node_registry.create_node("baseline.penalized_ls", "baseline", params(method)).execute(ds)
    corrected = transformed.outputs["default"]
    assert np.isfinite(corrected.X).all()
    np.testing.assert_array_equal(corrected.target, ds.target)
    assert corrected.sample_axis.sample_table == ds.sample_axis.sample_table
    assert corrected.target_context.target_units == "mg/L"
    split = NodeResult.wrap(
        await node_registry.create_node(
            "data.train_test_split", "split", {"split_method": "sequential", "test_size": 0.25}
        ).execute(X=corrected)
    ).outputs
    train, heldout = split["X_train"], split["X_test"]
    assert train.shape == (18, 81) and heldout.shape == (6, 81)
    assert cv_unavailable_reason(train) is None
    model = node_registry.create_node(
        "model.fitted_pls",
        "pls",
        {
            "component_fit_mode": "one_standard_error",
            "n_components": 3,
            "component_curve_max": 4,
            "component_cv_folds": 3,
            "scale": False,
        },
    )
    fitted = await model.execute(input_data=train)
    curve = fitted.outputs["component_curve"]
    cv = curve["cross_validation"]
    assert cv["status"] == "available" and cv["n_samples"] == 18 and cv["n_folds"] == 3
    assert curve["response_names"] == ["Analyte"] and curve["response_units"] == ["mg/L"]
    assert curve["component_fit_mode"] == "one_standard_error"
    assert curve["selection_rule_status"] == "matches_curve"
    assert 1 <= curve["selected_components"] <= 4
    seen = []
    for fold in cv["folds"]:
        fit, validation = fold["train"], fold["test"]
        assert not set(fit) & set(validation)
        assert set(fit + validation) == set(range(18))
        seen.extend(validation)
    assert sorted(seen) == list(range(18))
    state = fitted.outputs["fitted_state"]["state"]
    predictions = model.apply_fitted_state(heldout, state)
    assert predictions.shape == (6, 1) and np.isfinite(predictions).all()
    before = deepcopy(state)
    # Perturb held-out values/targets only; the original training fit must be identical.
    altered = ds.snapshot()
    altered.X[18:] += 100
    altered.target[18:] -= 1e5
    again = await node_registry.create_node("baseline.penalized_ls", "baseline", params(method)).execute(altered)
    again_split = NodeResult.wrap(
        await node_registry.create_node(
            "data.train_test_split", "split", {"split_method": "sequential", "test_size": 0.25}
        ).execute(X=again.outputs["default"])
    ).outputs
    refitted = await model.execute(input_data=again_split["X_train"])
    assert refitted.outputs["fitted_state"]["state"] == before
    if method == "arpls":
        diagnostics = transformed.diagnostics
        assert diagnostics["nonconverged_spectra"] > 0
        assert diagnostics["maximum_iterations_used"] == 5
        assert "last baseline was kept" in diagnostics["warning"]
        assert corrected.meta["baseline_diagnostics"] == diagnostics


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("preprocess.scale", {}),
        ("preprocess.msc", {}),
        ("preprocess.emsc", {}),
        ("preprocess.osc", {}),
        ("selection.variable_select", {}),
        ("unknown.sample_local", {}),
        ("data.train_test_split", {"split": "test"}),
        ("data.train_test_split", {}),
        ("data.file_load", {"stage": "preprocessed"}),
    ],
)
def test_unqualified_upstream_operations_still_refuse(operation, parameters):
    ds = source()
    ds.provenance.append(op_id="baseline.penalized_ls", parameters=params("arpls"))
    ds.provenance.append(op_id=operation, parameters=parameters)
    assert cv_unavailable_reason(ds) is not None


def test_baseline_nonfinite_inputs_and_nonfinite_solver_results_still_fail(monkeypatch):
    ds = source()
    ds.X[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        baseline._penalized_baseline_dispatch(ds.X, **params("arpls"))
    monkeypatch.setattr(baseline, "_fit_arpls", lambda spectrum, **_: (np.full_like(spectrum, np.nan), 5, False))
    with pytest.raises(ValueError, match="non-finite baseline"):
        baseline._penalized_baseline_dispatch(source().X, **params("arpls"))
