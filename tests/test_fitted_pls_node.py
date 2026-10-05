"""Tests for the sole canonical fitted PLS producer and state ABI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.executor_validation import _is_model_payload
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import (
    FittedPLSV2Node,
    make_fitted_pls_state_envelope,
    verify_fitted_pls_state_envelope,
)
from spectra_sherpa.app.services.dag.nodes.modeling.pls_core import ALGORITHM_ID, ALGORITHM_VERSION, fit_simpls
from spectra_sherpa.app.services.dag.stable_execution_contract import ensure_registered_execution_contract
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.services.python_export import generate_python_code
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.axis_semantics import AxisQuantity
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, RuntimeFamily, WorkerCapability
from tests.performance_contract import PerformanceCeiling


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _dataset(rows: list[list[float]]) -> SherpaDataset:
    return SherpaDataset(X=np.asarray(rows, dtype=np.float64))


def _training_data() -> tuple[SherpaDataset, np.ndarray, SherpaDataset]:
    X_train = _dataset(
        [
            [1.0, 1.0, 0.0],
            [2.0, 0.0, 1.0],
            [3.0, 4.0, 1.0],
            [4.0, 2.0, 3.0],
            [5.0, 6.0, 2.0],
            [6.0, 3.0, 5.0],
        ]
    )
    y_train = np.asarray([0.5, 1.2, 2.1, 2.5, 3.8, 4.1], dtype=np.float64)
    X_held_out = _dataset([[7.0, 5.0, 4.0], [8.0, 7.0, 6.0]])
    return X_train, y_train, X_held_out


def test_fitted_pls_fit_and_application_have_representative_absolute_performance_ceilings() -> None:
    rng = np.random.default_rng(20260902)
    latent = rng.normal(size=(200, 6))
    loadings = rng.normal(size=(6, 700))
    matrix = latent @ loadings + rng.normal(scale=0.01, size=(200, 700))
    target = latent @ np.asarray([1.3, -0.8, 0.4, 0.2, -0.1, 0.05])
    training = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(
            values=np.linspace(1_100.0, 2_500.0, 700),
            units="nm",
            title="Wavelength",
        ),
    )
    held_out = training.copy()
    node = FittedPLSV2Node("pls-v2", {"n_components": 6, "scale": True})

    with PerformanceCeiling("model.fitted_pls", "200x700-six-component-fit", 5.0).measure():
        state = node.fit_fitted_state(training, target)

    with PerformanceCeiling(
        "model.apply_fitted_pls",
        "200x700-six-component-application",
        5.0,
    ).measure():
        predictions = node.apply_fitted_state(held_out, state)

    assert predictions.shape == (200, 1)
    assert np.isfinite(predictions).all()


def test_fitted_pls_refuses_same_unit_with_different_axis_quantity() -> None:
    rows, target, _held_out = _training_data()
    values = np.asarray([1200.0, 1100.0, 1000.0])
    rows.feature_axis = SpectralAxis(
        values=values,
        units="cm-1",
        title="Wavenumber",
        quantity=AxisQuantity.WAVENUMBER,
    )
    node = FittedPLSV2Node("pls-v2", {"n_components": 2, "scale": True})
    state = node.fit_fitted_state(rows, target)
    assert state["feature_axis_quantity"] == "wavenumber"
    raman = SherpaDataset(
        X=np.array(rows.X, copy=True),
        feature_axis=SpectralAxis(
            values=values,
            units="cm-1",
            title="Raman Shift",
            quantity=AxisQuantity.RAMAN_SHIFT,
        ),
    )

    with pytest.raises(ValueError, match="fitted feature axis"):
        node.apply_fitted_state(raman, state)


@pytest.mark.parametrize("scale", [False, True])
def test_sherpa_state_matches_independent_pls1_nipals_reference(scale: bool) -> None:
    X_train, y_train, X_held_out = _training_data()
    node = FittedPLSV2Node("pls-v2", {"n_components": 2, "scale": scale})

    state = node.fit_fitted_state(X_train, y_train)
    actual = node.apply_fitted_state(X_held_out, state)
    expected = PLSRegression(n_components=2, scale=scale).fit(X_train.X, y_train[:, None]).predict(X_held_out.X)

    assert state["algorithm_id"] == ALGORITHM_ID
    assert state["algorithm_version"] == ALGORITHM_VERSION
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
    assert actual.shape == (2, 1)
    assert json.loads(json.dumps(state, allow_nan=False)) == state
    assert set(state) == {
        "serializer",
        "algorithm_id",
        "algorithm_version",
        "n_components",
        "effective_n_components",
        "scale",
        "reference_samples",
        "features",
        "targets",
        "response_identity",
        "input_identity",
        "diagnostic_state",
        "feature_axis_values_sha256",
        "feature_axis_labels_sha256",
        "feature_axis_units",
        "feature_axis_quantity",
        "coefficients",
        "feature_offset",
        "prediction_offset",
        "vip_scores",
        "x_explained_variance",
        "y_explained_variance",
    }


@pytest.mark.parametrize("scale", [False, True])
@pytest.mark.parametrize("offset", [1e6, 1e8])
def test_centered_state_matches_public_predict_for_large_uncentered_inputs(scale: bool, offset: float) -> None:
    """The portable state must preserve public predict without origin cancellation."""

    rng = np.random.default_rng(20260811)
    X_train_array = offset + rng.normal(scale=10.0, size=(80, 12))
    response_weights = rng.normal(size=(12, 2))
    y_train = (X_train_array - offset) @ response_weights + rng.normal(scale=0.01, size=(80, 2))
    X_apply_array = offset + rng.normal(scale=10.0, size=(20, 12))
    X_train = _dataset(X_train_array.tolist())
    X_apply = _dataset(X_apply_array.tolist())
    node = FittedPLSV2Node("pls-v2", {"n_components": 5, "scale": scale})

    state = node.fit_fitted_state(X_train, y_train)
    actual = node.apply_fitted_state(X_apply, state)
    expected = fit_simpls(X_train_array, y_train, n_components=5, scale=scale).predict(X_apply_array)

    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-11)
    np.testing.assert_allclose(state["feature_offset"], np.mean(X_train_array, axis=0, keepdims=True))


def test_vip_scores_match_independent_chong_jun_oracle() -> None:
    X_train, y_train, _ = _training_data()
    model = fit_simpls(X_train.X, y_train, n_components=2, scale=False)
    weights = np.asarray(model.x_weights, dtype=np.float64)
    weights = weights / np.linalg.norm(weights, axis=0)
    explained_y = np.sum(np.asarray(model.x_scores) ** 2, axis=0) * np.sum(
        np.asarray(model.y_loadings) ** 2,
        axis=0,
    )
    oracle = np.sqrt(X_train.shape[1] * ((weights**2) @ explained_y) / np.sum(explained_y))

    state = FittedPLSV2Node("pls-v2", {"n_components": 2}).fit_fitted_state(X_train, y_train)

    np.testing.assert_allclose(state["vip_scores"], oracle, rtol=1e-13, atol=1e-13)


def test_fitted_pls_uses_the_shared_vip_authority_for_multiple_responses() -> None:
    from spectra_sherpa.app.services.dag.nodes.selection._vip import calculate_vip

    X_train, y_train, _ = _training_data()
    targets = np.column_stack((y_train, 2.5 * y_train + np.linspace(-0.2, 0.2, y_train.size)))
    model = fit_simpls(X_train.X, targets, n_components=2, scale=False)
    expected = calculate_vip(model.x_scores, model.x_weights, model.y_loadings, X_train.shape[1])

    state = FittedPLSV2Node("pls-v2", {"n_components": 2}).fit_fitted_state(X_train, targets)

    np.testing.assert_allclose(state["vip_scores"], expected, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(np.sum(np.square(state["vip_scores"])), X_train.shape[1], rtol=1e-13)


@pytest.mark.parametrize("target_scale", [1e-10, 1e10])
def test_vip_scores_are_invariant_to_target_measurement_units(target_scale: float) -> None:
    X_train, y_train, _ = _training_data()
    node = FittedPLSV2Node("pls-v2", {"n_components": 2})

    reference = node.fit_fitted_state(X_train, y_train)
    rescaled = node.fit_fitted_state(X_train, y_train * target_scale)

    np.testing.assert_allclose(rescaled["vip_scores"], reference["vip_scores"], rtol=1e-12, atol=1e-12)


def test_pls_records_reduction_when_a_requested_component_has_no_response_covariance() -> None:
    X = _dataset(
        [
            [1.0, 2.0, 3.0],
            [2.0, 4.0, 6.0],
            [3.0, 6.0, 9.0],
            [4.0, 8.0, 12.0],
        ]
    )
    y = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float64)

    state = FittedPLSV2Node("pls-v2", {"n_components": 2}).fit_fitted_state(X, y)
    assert state["n_components"] == 2
    assert state["effective_n_components"] == 1
    assert len(state["x_explained_variance"]) == 1


def test_held_out_targets_cannot_affect_apply_predictions() -> None:
    X_train, y_train, X_held_out = _training_data()
    node = FittedPLSV2Node("pls-v2", {"n_components": 2})
    state = node.fit_fitted_state(X_train, y_train)

    first = node.apply_fitted_state(X_held_out, state)
    # Applying takes no target argument.  A substantially changed held-out
    # target vector therefore has no path into prediction.
    changed_held_out_targets = np.asarray([1_000_000.0, -1_000_000.0])
    assert changed_held_out_targets.shape[0] == first.shape[0]
    second = node.apply_fitted_state(X_held_out, state)

    np.testing.assert_array_equal(first, second)


def test_apply_rejects_same_width_reordered_feature_axis() -> None:
    X_train, y_train, X_held_out = _training_data()
    axis = SpectralAxis(
        values=np.asarray([1000.0, 1100.0, 1200.0]),
        labels=["band-a", "band-b", "band-c"],
        units="cm-1",
    )
    fitted_input = SherpaDataset(X=np.asarray(X_train.X), feature_axis=axis)
    state = FittedPLSV2Node("pls-v2", {"n_components": 2}).fit_fitted_state(fitted_input, y_train)
    reversed_axis = SpectralAxis(
        values=np.asarray(axis.values)[::-1],
        labels=list(reversed(axis.labels)),
        units=axis.units,
    )
    reordered_input = SherpaDataset(X=np.asarray(X_held_out.X)[:, ::-1], feature_axis=reversed_axis)

    with pytest.raises(ValueError, match="fitted feature axis"):
        FittedPLSV2Node("pls-v2", {"n_components": 2}).apply_fitted_state(reordered_input, state)


def test_one_shot_local_execute_has_same_math_as_explicit_lifecycle() -> None:
    X_train, y_train, _ = _training_data()
    node = FittedPLSV2Node("pls-v2", {"n_components": 2})

    expected = node.apply_fitted_state(X_train, node.fit_fitted_state(X_train, y_train))
    actual = asyncio.run(node.execute(input_data=X_train, y=y_train))

    np.testing.assert_allclose(actual.outputs["default"], expected)
    verified = verify_fitted_pls_state_envelope(actual.outputs["fitted_state"])
    np.testing.assert_allclose(node.apply_fitted_state(X_train, verified), expected)


def test_one_shot_local_execute_can_use_embedded_continuous_target() -> None:
    X_train, y_train, _ = _training_data()
    dataset = SherpaDataset(X=X_train.X, target=y_train)
    dataset.target_context = dataset.target_context.model_copy(
        update={
            "target_type": "continuous",
            "target_name": "Carbon dioxide",
            "target_names": ["Carbon dioxide"],
            "selected_target": "Carbon dioxide",
        }
    )

    result = asyncio.run(FittedPLSV2Node("pls-v2", {"n_components": 2}).run(dataset))

    assert result.outputs["default"].shape == (6, 1)
    assert result.outputs["fitted_state"]["schema_version"] == "spectrasherpa.fitted-pls-state/9"
    assert result.outputs["vip_scores"].shape == (3,)
    assert result.outputs["x_scores"].shape == (6, 2)
    assert result.outputs["x_loadings"].shape == (2, 3)
    assert result.outputs["explained_variance"].shape == (2, 2)
    assert result.outputs["regression_coefficients"].shape == (3, 1)
    comparison = result.outputs["calibration_comparison"]
    assert comparison["metadata"]["role"] == "calibration"
    assert comparison["metadata"]["target_names"] == ["Carbon dioxide"]
    assert comparison["shape"] == [6, 6]
    np.testing.assert_allclose(
        [row["reference"] - row["predicted"] for row in comparison["data"]],
        [row["residual"] for row in comparison["data"]],
    )


def test_one_shot_local_execute_preserves_explicit_target_dataset_identity() -> None:
    X_train, y_train, _ = _training_data()
    y_dataset = SherpaDataset(
        X=y_train.reshape(-1, 1),
        feature_axis=FeatureAxis(labels=["Carbon dioxide"], title="Response"),
    )

    result = asyncio.run(FittedPLSV2Node("pls-v2", {"n_components": 2}).execute(input_data=X_train, y=y_dataset))

    comparison = result.outputs["calibration_comparison"]
    assert comparison["metadata"]["target_names"] == ["Carbon dioxide"]
    assert {row["target"] for row in comparison["data"]} == {"Carbon dioxide"}


def test_one_shot_local_execute_uses_bound_target_identity_for_plain_target_array() -> None:
    X_train, y_train, _ = _training_data()
    node = FittedPLSV2Node(
        "pls-v2",
        {
            "n_components": 2,
            "target_names": ["Carbon dioxide"],
        },
    )

    result = asyncio.run(node.execute(input_data=X_train, y=y_train))

    comparison = result.outputs["calibration_comparison"]
    assert comparison["metadata"]["target_names"] == ["Carbon dioxide"]
    assert {row["target"] for row in comparison["data"]} == {"Carbon dioxide"}


def test_local_fitted_state_envelope_rejects_changed_state_or_contract() -> None:
    X_train, y_train, _ = _training_data()
    state = FittedPLSV2Node("pls-v2", {"n_components": 2}).fit_fitted_state(X_train, y_train)
    envelope = make_fitted_pls_state_envelope(state)
    changed_state = dict(envelope)
    changed_state["state"] = {**state, "prediction_offset": [[999.0]]}
    changed_contract = dict(envelope)
    changed_contract["source_contract_digest"] = "0" * 64

    with pytest.raises(ValueError, match="content digest"):
        verify_fitted_pls_state_envelope(changed_state)
    with pytest.raises(ValueError, match="producer contract"):
        verify_fitted_pls_state_envelope(changed_contract)


@pytest.mark.parametrize(
    "legacy_digest",
    [
        "64bdf49b4d1cc289f43edca2e760037b3ce6c82e731bbb3c9aa1b7c7460028a8",
        "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d",
    ],
)
def test_local_fitted_state_envelope_refuses_suffix_era_contracts_without_response_authority(
    legacy_digest: str,
) -> None:
    X_train, y_train, _ = _training_data()
    state = FittedPLSV2Node("pls-v2", {"n_components": 2}).fit_fitted_state(X_train, y_train)
    envelope = make_fitted_pls_state_envelope(state)
    envelope["source_contract_digest"] = legacy_digest

    with pytest.raises(ValueError, match="producer contract"):
        verify_fitted_pls_state_envelope(envelope)


def test_local_fitted_state_envelope_is_the_runtime_model_port_payload() -> None:
    X_train, y_train, _ = _training_data()
    state = FittedPLSV2Node("pls-v2", {"n_components": 2}).fit_fitted_state(X_train, y_train)
    envelope = make_fitted_pls_state_envelope(state)

    assert _is_model_payload(envelope) is True
    assert _is_model_payload({**envelope, "unexpected": True}) is False
    assert _is_model_payload({**envelope, "state_content_digest": "not-a-digest"}) is False


def test_local_fitted_state_envelope_rejects_pre_rank_aware_v4_identity() -> None:
    X_train, y_train, _ = _training_data()
    state = FittedPLSV2Node("pls-v2", {"n_components": 2}).fit_fitted_state(X_train, y_train)
    envelope = make_fitted_pls_state_envelope(state)
    envelope["schema_version"] = "spectrasherpa.fitted-pls-state/4"
    envelope["serializer"] = "spectra.sherpa-simpls-regression-json/4"

    with pytest.raises(ValueError, match="unsupported identity"):
        verify_fitted_pls_state_envelope(envelope)


def test_generated_fit_and_local_apply_reuse_the_live_state_authorities() -> None:
    X_train, y_train, X_held_out = _training_data()
    fit = node_registry.create_node("model.fitted_pls", "fit", {"n_components": 2})
    apply = node_registry.create_node("model.apply_fitted_pls", "apply", {})
    namespace: dict[str, object] = {
        "X_train": X_train,
        "y_train": y_train,
        "X_held_out": X_held_out,
        "results": {},
    }
    lines = [
        *fit.generate_python({"default": "X_train", "y": "y_train"}, indent=""),
        *apply.generate_python(
            {"default": "X_held_out", "fitted_state": "results['fit']['fitted_state']"},
            indent="",
        ),
    ]

    exec("\n".join(lines), namespace)  # noqa: S102 - executes node-owned generated code in an isolated test map

    results = namespace["results"]
    assert isinstance(results, dict)
    expected_state = FittedPLSV2Node("fit", {"n_components": 2}).fit_fitted_state(X_train, y_train)
    expected = FittedPLSV2Node("fit", {"n_components": 2}).apply_fitted_state(X_held_out, expected_state)
    np.testing.assert_allclose(results["apply"]["default"], expected)


def test_generated_local_application_preserves_the_typed_state_and_default_edges(tmp_path: Path) -> None:
    """The workflow exporter must not pass the apply node's output mapping as data."""

    workflow = SimpleNamespace(
        name="canonical PLS local application export",
        description="",
        integrity_hash="canonical-pls-local-application",
        nodes=[
            SimpleNamespace(
                node_id="source",
                node_type="data.file_load",
                parameters={
                    "experiment_id": 1,
                    "file_id": 2,
                    "stage": "raw",
                    "selected_target": "target",
                    "target_type": "continuous",
                },
            ),
            SimpleNamespace(node_id="fit", node_type="model.fitted_pls", parameters={"n_components": 2}),
            SimpleNamespace(node_id="apply", node_type="model.apply_fitted_pls", parameters={}),
            SimpleNamespace(node_id="summary", node_type="stats.summary", parameters={}),
        ],
        edges=[
            SimpleNamespace(from_node_id="source", to_node_id="fit", from_output="default", to_input="default"),
            SimpleNamespace(from_node_id="source", to_node_id="fit", from_output="target", to_input="y"),
            SimpleNamespace(from_node_id="source", to_node_id="apply", from_output="default", to_input="default"),
            SimpleNamespace(
                from_node_id="fit", to_node_id="apply", from_output="fitted_state", to_input="fitted_state"
            ),
            SimpleNamespace(from_node_id="apply", to_node_id="summary", from_output="default", to_input="default"),
        ],
    )

    from spectra_sherpa.app.services.prepared_data import PreparedDataOverrides
    from spectra_sherpa.app.services.workflow_export_context import (
        BundledSourceFile,
        SourceExportSpec,
        WorkflowExportContext,
    )

    source_path = tmp_path / "diabetes.csv"
    source_path.write_text("target,1,2\n1,2,3\n2,4,6\n3,6,9\n", encoding="utf-8")
    context = WorkflowExportContext(
        source_specs={
            "source": SourceExportSpec(
                node_id="source",
                source="experiment",
                loader_mode="single_file",
                overrides=PreparedDataOverrides(
                    target_column="target",
                    selected_target="target",
                    target_mode="single",
                    target_type="continuous",
                ),
                bundle_files=(
                    BundledSourceFile(
                        absolute_path=source_path,
                        source_relative_path="references/diabetes.csv",
                        bundle_relative_path="source/diabetes.csv",
                    ),
                ),
            )
        }
    )
    code = generate_python_code(workflow, export_context=context)

    assert "'from_node_id': 'fit'" in code
    assert "'from_output': 'fitted_state'" in code
    assert "'to_node_id': 'apply'" in code
    assert "'from_node_id': 'apply'" in code
    assert "'to_node_id': 'summary'" in code
    assert code.count("ss.runtime.execute_workflow(") == 1


@pytest.mark.parametrize(
    ("input_rows", "target", "message"),
    [
        ([[1.0, 2.0], [2.0, float("nan")]], [1.0, 2.0], "finite training spectra"),
        ([[1.0, 2.0], [2.0, 3.0]], [1.0, float("inf")], "finite target matrix"),
        ([[1.0, 2.0]], [1.0], "at least two finite training spectra"),
    ],
)
def test_fit_rejects_nonfinite_or_insufficient_reference_data(
    input_rows: list[list[float]], target: list[float], message: str
) -> None:
    node = FittedPLSV2Node("pls-v2", {"n_components": 1})

    with pytest.raises(ValueError, match=message):
        node.fit_fitted_state(_dataset(input_rows), target)


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"n_components": 1.5}, "n_components"),
        ({"n_components": True}, "n_components"),
        ({"n_components": "1"}, "n_components"),
        ({"n_components": 1, "scale": "false"}, "scale"),
    ],
)
def test_node_admission_rejects_noncanonical_parameter_values(parameters: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        FittedPLSV2Node("pls-v2", parameters)


@pytest.mark.parametrize(
    "state",
    [
        {"serializer": "spectra.sherpa-simpls-regression-json/5"},
        {
            "serializer": "spectra.sherpa-simpls-regression-json/5",
            "n_components": 1,
            "scale": False,
            "reference_samples": 2,
            "features": 2,
            "targets": 1,
            "coefficients": [[float("nan")], [1.0]],
            "feature_offset": [[0.0, 0.0]],
            "prediction_offset": [[0.0]],
            "vip_scores": [1.0, 1.0],
        },
        {
            "serializer": "spectra.sherpa-simpls-regression-json/5",
            "n_components": 1,
            "scale": False,
            "reference_samples": 2,
            "features": 3,
            "targets": 1,
            "coefficients": [[1.0], [2.0], [3.0]],
            "feature_offset": [[0.0, 0.0, 0.0]],
            "prediction_offset": [[0.0]],
            "vip_scores": [1.0, 1.0, 1.0],
        },
    ],
)
def test_apply_rejects_malformed_or_feature_incompatible_state(state: dict[str, object]) -> None:
    node = FittedPLSV2Node("pls-v2", {"n_components": 1})

    with pytest.raises(ValueError, match="fitted PLS"):
        node.apply_fitted_state(_dataset([[1.0, 2.0]]), state)


def test_pre_simpls_v3_state_is_not_accepted_as_current() -> None:
    X_train, y_train, X_held_out = _training_data()
    state = FittedPLSV2Node("pls-v2", {"n_components": 2}).fit_fitted_state(X_train, y_train)
    legacy = dict(state)
    legacy["serializer"] = "spectra.sklearn-pls-reference-json.v3"
    legacy.pop("algorithm_id")
    legacy.pop("algorithm_version")
    legacy.pop("x_explained_variance")
    legacy.pop("y_explained_variance")

    with pytest.raises(ValueError, match="closed serializer schema"):
        FittedPLSV2Node("pls-v2", {"n_components": 2}).apply_fitted_state(X_held_out, legacy)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("n_components", 0, "n_components"),
        ("n_components", True, "n_components"),
        ("n_components", 4, "n_components"),
        ("scale", "false", "scale flag"),
        ("reference_samples", True, "reference_samples"),
    ],
)
def test_apply_rejects_forged_declared_fit_configuration(field: str, value: object, message: str) -> None:
    X_train, y_train, X_held_out = _training_data()
    node = FittedPLSV2Node("pls-v2", {"n_components": 2})
    state = node.fit_fitted_state(X_train, y_train)
    forged = dict(state)
    forged[field] = value

    with pytest.raises(ValueError, match=message):
        node.apply_fitted_state(X_held_out, forged)


def test_fitted_pls_v2_has_a_complete_local_state_contract() -> None:
    metadata = node_registry.get_metadata("model.fitted_pls")
    contract = ensure_registered_execution_contract(metadata)

    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["implementation_id"] == "spectrasherpa.simpls.pls_regression"
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["fitted_state_serializer"] == "spectra.sherpa-simpls-regression-json/9"
    assert contract.payload["runtime_requirements"] == ({"distribution": "numpy", "version": "1.26.4"},)
    assert {
        component["component_id"]
        for component in contract.payload["implementation_components"]
        if component["component_id"].startswith("distribution.")
    } == {"distribution.numpy"}
    assert contract.payload["feature_effect"] == "generates_features"
    assert [port["type_ref"] for port in contract.payload["semantic_inputs"]] == [
        "spectrasherpa://types/SpectralDataset/1.0",
        "spectrasherpa://types/TargetMatrix/1.0",
    ]
    assert [port["type_ref"] for port in contract.payload["semantic_outputs"]] == [
        "spectrasherpa://types/TargetMatrix/1.0",
        "spectrasherpa://types/RegressionModel/1.0",
        "spectrasherpa://types/VariableImportance/1.0",
        "spectrasherpa://types/RegressionComparison/1.0",
        "spectrasherpa://types/ScoreMatrix/1.0",
        "spectrasherpa://types/LoadingMatrix/1.0",
        "spectrasherpa://types/ExplainedVarianceMatrix/1.0",
        "spectrasherpa://types/RegressionCoefficientMatrix/1.0",
    ]


def test_apply_fitted_pls_artifact_bindings_are_not_scientist_parameters() -> None:
    metadata = node_registry.get_metadata("model.apply_fitted_pls")

    assert {parameter.category for parameter in metadata.parameters} == {"internal"}
    assert {parameter.name for parameter in metadata.parameters} == {
        "artifact_digest",
        "serializer",
        "source_contract_digest",
        "state_content_digest",
        "state_digest",
        "state_node_id",
    }


def test_fitted_pls_v2_is_graph_admitted_only_as_the_explicit_new_lifecycle_identity() -> None:
    graph = admit_validation_graph([WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1})], [])

    assert graph.nodes[0].operation_id == "model.fitted_pls"
    assert graph.nodes[0].contract.payload["implementation_id"] == "spectrasherpa.simpls.pls_regression"


def test_run_refuses_permuted_response_rows_and_accepts_explicit_alignment():
    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis

    X, target, _ = _training_data()
    ids = [f"sample-{i}" for i in range(6)]
    X.sample_axis = SampleAxis(labels=ids)
    wrong = SherpaDataset(X=target[::-1, None], sample_axis=SampleAxis(labels=ids[::-1]))
    node = FittedPLSV2Node("identity", {"n_components": 2})
    with pytest.raises(ValueError, match="identities/order differ"):
        asyncio.run(node.run(default=X, y=wrong))
    with pytest.raises(ValueError, match="identities/order differ"):
        node.fit_fitted_state(X, wrong)
    aligned = SherpaDataset(X=target[:, None], sample_axis=SampleAxis(labels=ids))
    result = asyncio.run(node.run(default=X, y=aligned))
    positional = asyncio.run(node.run(default=X, y=target))
    np.testing.assert_allclose(result.outputs["default"], positional.outputs["default"])


def test_response_identity_survives_json_application_without_borrowing_new_target_metadata():
    from spectra_sherpa.app.services.dag.nodes.modeling.apply_fitted_pls_node import ApplyFittedPLSV2Node

    X, target, held_out = _training_data()
    response = SherpaDataset(
        X=np.column_stack((target, target * 2 + 3)),
        feature_axis=FeatureAxis(labels=["Oil", "Moisture"]),
        units="mass%",
    )
    state = FittedPLSV2Node("fit", {"n_components": 2}).fit_fitted_state(X, response)
    expected = {"names": ["Oil", "Moisture"], "units": ["mass%", "mass%"]}
    assert state["response_identity"] == expected
    envelope = json.loads(json.dumps(make_fitted_pls_state_envelope(state), allow_nan=False))
    held_out.target_context = held_out.target_context.model_copy(
        update={"target_names": ["Unrelated"], "target_units": "kelvin"}
    )
    applied = asyncio.run(ApplyFittedPLSV2Node("apply", {}).run(default=held_out, fitted_state=envelope))
    assert applied.diagnostics["response_identity"] == expected
    np.testing.assert_allclose(
        applied.outputs["default"], FittedPLSV2Node("fit", {}).apply_fitted_state(held_out, state)
    )


def test_embedded_response_never_borrows_predictor_column_names():
    X, target, _ = _training_data()
    X.feature_axis = FeatureAxis(labels=["Channel A", "Channel B", "Channel C"])
    X.target = target
    state = FittedPLSV2Node("fit", {"n_components": 2}).fit_fitted_state(X, None)
    assert state["response_identity"] == {"names": None, "units": [None]}


def test_embedded_response_retains_declared_name_and_units():
    X, target, _ = _training_data()
    X.target = target
    X.target_context = X.target_context.model_copy(update={"target_names": ["CN"], "target_units": "cetane"})
    result = asyncio.run(FittedPLSV2Node("fit", {"n_components": 2}).run(X))
    assert result.diagnostics["response_identity"] == {"names": ["CN"], "units": ["cetane"]}


@pytest.mark.parametrize(
    "identity",
    [
        {"names": ["CN", "Density"], "units": [None]},
        {"names": [""], "units": [None]},
        {"names": ["CN"], "units": []},
        {"names": ["CN"], "units": [False]},
    ],
)
def test_invalid_response_identity_is_refused(identity):
    X, target, _ = _training_data()
    node = FittedPLSV2Node("fit", {"n_components": 2})
    state = node.fit_fitted_state(X, target)
    state["response_identity"] = identity
    with pytest.raises(ValueError, match="response"):
        node.validate_fitted_state(state)


def test_legacy_state_without_response_authority_requires_rebuild():
    X, target, _ = _training_data()
    node = FittedPLSV2Node("fit", {"n_components": 2})
    state = node.fit_fitted_state(X, target)
    del state["response_identity"]
    state["serializer"] = "spectra.sherpa-simpls-regression-json/6"
    with pytest.raises(ValueError, match="legacy state without response authority"):
        node.validate_fitted_state(state)


def test_external_data_matrix_does_not_inherit_its_embedded_target_identity():
    from spectra_sherpa.app.lib.sherpa_dataset import TargetContext

    X, target, _ = _training_data()
    response = SherpaDataset(
        X=target[:, None],
        feature_axis=FeatureAxis(labels=["Density"]),
        units="g/mL",
        target=target * 10,
        target_context=TargetContext(target_names=["CN"], target_units="cetane"),
    )
    node = FittedPLSV2Node("fit", {"n_components": 2})
    state = node.fit_fitted_state(X, response)
    assert state["response_identity"] == {"names": ["Density"], "units": ["g/mL"]}
    live = asyncio.run(node.run(default=X, y=response))
    assert live.diagnostics["response_identity"] == state["response_identity"]
    np.testing.assert_allclose(live.outputs["default"], node.apply_fitted_state(X, state))


def test_application_only_export_retains_model_owned_prediction_identity(tmp_path, monkeypatch):
    import hashlib
    import zipfile

    from spectra_sherpa.app.services.export_utils import export_artifacts

    X, target, held_out = _training_data()
    X.target = target
    X.target_context = X.target_context.model_copy(update={"target_names": ["CN"], "target_units": "cetane"})
    state = FittedPLSV2Node("fit", {"n_components": 2}).fit_fitted_state(X, None)
    envelope = make_fitted_pls_state_envelope(state)
    apply = node_registry.create_node("model.apply_fitted_pls", "apply", {})
    namespace = {"application_input": held_out, "fitted": envelope, "results": {}}
    exec(
        "\n".join(apply.generate_python({"default": "application_input", "fitted_state": "fitted"}, indent="")),
        namespace,
    )  # noqa: S102 - trusted node-owned generator
    outputs = namespace["results"]["apply"]
    assert set(outputs) == apply.exported_output_ports()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPECTRA_SHERPA_EXPORT_DIR", str(tmp_path))
    archive = export_artifacts({"apply": outputs}, workflow_name="application-only")
    with zipfile.ZipFile(tmp_path / archive) as saved:
        receipt_path = next(name for name in saved.namelist() if name.endswith("apply_summary.json"))
        receipt = json.loads(saved.read(receipt_path))["prediction_identity"]
    assert receipt["response_identity"] == {"names": ["CN"], "units": ["cetane"]}
    assert receipt["fitted_state_custody"]["state_content_digest"] == envelope["state_content_digest"]
    assert receipt["shape"] == [2, 1]
    assert (
        receipt["prediction_sha256"]
        == hashlib.sha256(np.asarray(outputs["default"], dtype="<f8").tobytes(order="C")).hexdigest()
    )
