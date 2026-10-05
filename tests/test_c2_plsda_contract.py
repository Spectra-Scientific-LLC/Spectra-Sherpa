"""C2i canonical PLS-DA scientific, replay, and contract proofs."""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest
import yaml
from sklearn.cross_decomposition import PLSRegression
from sklearn.datasets import load_breast_cancer, load_iris, load_wine

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.executor_validation import _is_model_payload
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.classification.application_nodes import ApplyPLSDANode
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import (
    PLSDANode,
    _canonical_plsda_parameters,
    _dummy_response,
    _native_plsda_fit,
    _plsda_export_outputs,
    _plsda_inputs,
    _plsda_scientific_core,
    apply_plsda_fitted_state,
)
from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import (
    FITTED_STATE_SERIALIZER,
    SherpaPLSDAArtifact,
)
from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import apply_fitted_state as apply_native_state
from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import _apply_model_artifact
from spectra_sherpa.core.model_artifact import ORDINARY_MODEL_ARTIFACT_AUTHORITY
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset() -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(2003)
    labels = np.repeat(np.asarray(["polymer-a", "polymer-b", "polymer-c"], dtype=object), 15)
    matrix = rng.normal(scale=0.2, size=(labels.size, 8))
    matrix[labels == "polymer-a", :3] += np.asarray([1.2, 0.6, -0.2])
    matrix[labels == "polymer-b", :3] += np.asarray([-0.4, 1.3, 0.5])
    matrix[labels == "polymer-c", :3] += np.asarray([0.1, -0.5, 1.4])
    return (
        SherpaDataset(
            X=matrix,
            feature_axis=SpectralAxis(values=np.linspace(900.0, 1700.0, matrix.shape[1]), units="cm-1"),
            sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
            target=labels,
            target_context=TargetContext(target_type="categorical", target_names=["polymer"]),
        ),
        labels,
    )


def _parameters(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {"n_components": 2, "scale": False}
    values.update(overrides)
    return values


def test_native_plsda_state_replays_dummy_response_and_argmax() -> None:
    dataset, labels = _dataset()
    classes = np.unique(labels)
    fit, artifact = _native_plsda_fit(
        dataset.X,
        _dummy_response(labels, classes),
        classes,
        n_components=2,
        scale=True,
    )
    restored = SherpaPLSDAArtifact.from_fitted_state(artifact.to_fitted_state())
    predicted, responses = restored.predict(dataset.X, allow_unverified_positional=True)

    np.testing.assert_allclose(responses, fit.predict(dataset.X), rtol=0.0, atol=0.0)
    np.testing.assert_array_equal(predicted, classes[np.argmax(responses, axis=1)])
    assert restored.requested_n_components == 2
    assert restored.effective_n_components == fit.n_components
    assert restored.algorithm_id == "sherpa.simpls.de_jong_1993"


def test_native_plsda_state_fails_closed_on_old_serializer() -> None:
    dataset, labels = _dataset()
    classes = np.unique(labels)
    _, artifact = _native_plsda_fit(
        dataset.X,
        _dummy_response(labels, classes),
        classes,
        n_components=2,
        scale=False,
    )
    state = artifact.to_fitted_state()
    state["serializer"] = "spectrasherpa.model-artifact.plsda-state/2"
    with pytest.raises(ValueError, match="unsupported serializer"):
        SherpaPLSDAArtifact.from_fitted_state(state)


def test_plsda_state_binds_typed_feature_order_and_axis_semantics() -> None:
    dataset, labels = _dataset()
    node = PLSDANode("fit", _parameters(scale=True))
    state = node.fit_fitted_state(dataset, labels)
    np.testing.assert_allclose(node.apply_fitted_state(dataset, state), node.apply_fitted_state(dataset, state))

    order = np.asarray([1, 0, *range(2, dataset.n_features)])
    reordered = SherpaDataset(
        X=dataset.X[:, order],
        feature_axis=SpectralAxis(
            values=np.asarray(dataset.feature_axis.values)[order],
            units=dataset.feature_axis.units,
        ),
    )
    with pytest.raises(ValueError, match="feature identity differs"):
        node.apply_fitted_state(reordered, state)

    wrong_units = SherpaDataset(
        X=np.array(dataset.X),
        feature_axis=SpectralAxis(values=np.asarray(dataset.feature_axis.values), units="nm"),
    )
    with pytest.raises(ValueError, match="feature identity differs"):
        node.apply_fitted_state(wrong_units, state)

    with pytest.raises(ValueError, match="requires the fitted typed feature axis"):
        node.apply_fitted_state(SherpaDataset(X=np.array(dataset.X)), state)


def test_plsda_named_feature_identity_rejects_duplicate_training_labels() -> None:
    dataset, labels = _dataset()
    dataset.feature_axis = FeatureAxis(
        values=np.arange(dataset.n_features, dtype=np.float64),
        labels=["duplicate", "duplicate", *[f"feature-{index}" for index in range(2, dataset.n_features)]],
    )
    with pytest.raises(ValueError, match="ordered, non-empty, and unique"):
        PLSDANode("fit", _parameters()).fit_fitted_state(dataset, labels)


def test_plsda_named_feature_identity_rejects_same_width_reordering() -> None:
    dataset, labels = _dataset()
    feature_names = [f"analyte-{index}" for index in range(dataset.n_features)]
    dataset.feature_axis = FeatureAxis(values=np.arange(dataset.n_features), labels=feature_names, title="Analyte")
    node = PLSDANode("fit", _parameters())
    state = node.fit_fitted_state(dataset, labels)
    expected = node.apply_fitted_state(dataset, state)

    order = np.asarray([1, 0, *range(2, dataset.n_features)])
    reordered = SherpaDataset(
        X=dataset.X[:, order],
        feature_axis=FeatureAxis(
            values=np.arange(dataset.n_features),
            labels=np.asarray(feature_names, dtype=object)[order].tolist(),
            title="Analyte",
        ),
    )
    with pytest.raises(ValueError, match="feature identity differs.*labels"):
        node.apply_fitted_state(reordered, state)
    np.testing.assert_allclose(node.apply_fitted_state(dataset, state), expected, rtol=0.0, atol=0.0)


@pytest.mark.parametrize("loader", [load_iris, load_wine, load_breast_cancer])
def test_public_named_feature_panels_reject_same_width_reordering(loader) -> None:
    source = loader()
    feature_names = [str(value) for value in source.feature_names]
    dataset = SherpaDataset(
        X=np.asarray(source.data, dtype=np.float64),
        feature_axis=FeatureAxis(values=np.arange(len(feature_names)), labels=feature_names),
    )
    state = PLSDANode("fit", _parameters()).fit_fitted_state(dataset, np.asarray(source.target))
    responses = PLSDANode("apply", _parameters()).apply_fitted_state(dataset, state)
    assert responses.shape == (dataset.n_samples, len(np.unique(source.target)))

    order = np.asarray([1, 0, *range(2, dataset.n_features)])
    reordered = SherpaDataset(
        X=dataset.X[:, order],
        feature_axis=FeatureAxis(
            values=np.arange(dataset.n_features),
            labels=np.asarray(feature_names, dtype=object)[order].tolist(),
        ),
    )
    with pytest.raises(ValueError, match="feature identity differs.*labels"):
        PLSDANode("apply", _parameters()).apply_fitted_state(reordered, state)


@pytest.mark.asyncio
async def test_plsda_application_node_and_generated_path_reject_same_width_reordering() -> None:
    dataset, labels = _dataset()
    state = PLSDANode("fit", _parameters()).fit_fitted_state(dataset, labels)
    order = np.asarray([1, 0, *range(2, dataset.n_features)])
    reordered = SherpaDataset(
        X=dataset.X[:, order],
        feature_axis=SpectralAxis(values=np.asarray(dataset.feature_axis.values)[order], units="cm-1"),
    )
    predictor = ApplyPLSDANode("apply", {})
    accepted = await predictor.execute(default=dataset, fitted_state=state)
    assert accepted.diagnostics["feature_identity_verified"] is True
    with pytest.raises(ValueError, match="feature identity differs"):
        await predictor.execute(default=reordered, fitted_state=state)

    namespace = {"dataset": reordered, "fitted_state": state, "results": {}}
    with pytest.raises(ValueError, match="feature identity differs"):
        exec(  # noqa: S102
            "\n".join(predictor.generate_python({"default": "dataset", "fitted_state": "fitted_state"}, indent="")),
            namespace,
        )


def test_saved_plsda_artifact_accepts_full_or_selected_masked_axis_and_rejects_reorder() -> None:
    dataset, labels = _dataset()
    full = SherpaDataset(
        X=dataset.X[:, :4],
        feature_axis=FeatureAxis(values=np.arange(4), labels=["a", "b", "c", "d"]),
    )
    mask = np.asarray([False, True, False, True])
    selected = SherpaDataset(
        X=full.X[:, mask],
        feature_axis=FeatureAxis(values=np.asarray(full.feature_axis.values)[mask], labels=["b", "d"]),
    )
    state = PLSDANode("fit", _parameters(n_components=1)).fit_fitted_state(selected, labels)
    artifact = SherpaPLSDAArtifact.from_fitted_state(state)
    manifest, arrays = artifact.to_artifact()
    manifest.update(
        artifact_uid="feature-mask-fixture",
        artifact_authority=ORDINARY_MODEL_ARTIFACT_AUTHORITY,
        feature_mask=mask.tolist(),
    )

    class _Replay:
        def prepare(self, X, source, saved_manifest):
            matrix = np.asarray(X)
            saved_mask = np.asarray(saved_manifest["feature_mask"], dtype=bool)
            return (matrix[:, saved_mask] if matrix.shape[1] == saved_mask.size else matrix), ()

        def applicability(self, extract, X):
            return None

    for valid in (full, selected):
        result = _apply_model_artifact(manifest, arrays, valid, model_id="feature-mask-fixture", replay=_Replay())
        assert result["metadata"]["feature_identity_verified"] is True

    reordered = SherpaDataset(
        X=selected.X[:, ::-1],
        feature_axis=FeatureAxis(values=np.asarray(selected.feature_axis.values)[::-1], labels=["d", "b"]),
    )
    with pytest.raises(ValueError, match="feature identity differs"):
        _apply_model_artifact(manifest, arrays, reordered, model_id="feature-mask-fixture", replay=_Replay())


def test_legacy_plsda_state_is_explicitly_positional_only() -> None:
    dataset, labels = _dataset()
    state = PLSDANode("fit", _parameters()).fit_fitted_state(dataset, labels)
    state["serializer"] = "spectrasherpa.sherpa-plsda-state/3"
    state["metadata"]["serializer"] = "spectrasherpa.model-artifact.sherpa-plsda/2"
    state["metadata"].pop("feature_identity")

    restored = SherpaPLSDAArtifact.from_fitted_state(state)
    assert restored.feature_identity_mode == "positional"
    with pytest.raises(ValueError, match="unverified positional feature identity"):
        restored.predict(dataset.X)
    with pytest.raises(ValueError, match="unverified positional feature identity"):
        apply_native_state(dataset.X, state)
    with pytest.raises(ValueError, match="unverified positional feature identity"):
        PLSDANode("apply", _parameters()).apply_fitted_state(dataset, state)

    expected_labels, expected_scores = restored.predict(dataset.X, allow_unverified_positional=True)
    actual_labels, actual_scores = apply_native_state(
        dataset.X,
        state,
        allow_unverified_positional=True,
    )
    np.testing.assert_array_equal(actual_labels, expected_labels)
    np.testing.assert_allclose(actual_scores, expected_scores, rtol=0.0, atol=0.0)


@pytest.mark.asyncio
async def test_current_axisless_state_is_limited_to_trusted_fitted_lifecycle() -> None:
    dataset, labels = _dataset()
    axisless = SherpaDataset(X=np.asarray(dataset.X))
    node = PLSDANode("fit", _parameters())
    state = node.fit_fitted_state(axisless, labels)

    responses = node.apply_fitted_state(axisless, state)
    assert responses.shape == (axisless.n_samples, len(np.unique(labels)))

    with pytest.raises(ValueError, match="unverified positional feature identity"):
        await ApplyPLSDANode("apply", {}).execute(default=axisless, fitted_state=state)


@pytest.mark.asyncio
async def test_legacy_plsda_application_rejects_unverified_positional_identity() -> None:
    dataset, labels = _dataset()
    state = PLSDANode("fit", _parameters()).fit_fitted_state(dataset, labels)
    state["serializer"] = "spectrasherpa.sherpa-plsda-state/3"
    state["metadata"]["serializer"] = "spectrasherpa.model-artifact.sherpa-plsda/2"
    state["metadata"].pop("feature_identity")

    predictor = ApplyPLSDANode("apply", {})
    with pytest.raises(ValueError, match="unverified positional feature identity"):
        await predictor.execute(default=dataset, fitted_state=state)

    namespace = {"dataset": dataset, "fitted_state": state, "results": {}}
    with pytest.raises(ValueError, match="unverified positional feature identity"):
        exec(  # noqa: S102
            "\n".join(predictor.generate_python({"default": "dataset", "fitted_state": "fitted_state"}, indent="")),
            namespace,
        )


def test_native_plsda_core_reports_calibration_diagnostics_only() -> None:
    dataset, labels = _dataset()
    core = _plsda_scientific_core(dataset, labels, parameters=_parameters(scale=True))

    expected_metrics = {
        "accuracy",
        "balanced_accuracy",
        "f1_macro",
        "precision_macro",
        "recall_macro",
        "sensitivity_macro",
        "specificity_macro",
    }
    assert set(core["metrics"]["splits"]) == {"train"}
    assert expected_metrics <= set(core["metrics"]["splits"]["train"])
    np.testing.assert_array_equal(
        core["train_predictions"],
        core["classes"][np.argmax(core["train_class_scores"], axis=1)],
    )
    assert core["metrics"]["requested_n_components"] == 2
    assert core["metrics"]["effective_n_components"] == core["fit"].n_components
    assert core["metrics"]["decision_rule"] == "maximum_predicted_dummy_response"
    assert core["metrics"]["numeric_output_semantics"] == "class_response_scores_not_probabilities"
    assert core["metrics"]["evidence_scope"] == "calibration_fit_diagnostics_not_validation_evidence"


def test_native_plsda_rank_exhaustion_records_effective_components() -> None:
    rng = np.random.default_rng(44)
    labels = np.repeat(np.asarray(["a", "b"], dtype=object), 12)
    direction = rng.normal(size=(labels.size, 1)) + (labels == "b")[:, None]
    matrix = direction @ np.asarray([[1.0, 2.0, -0.5, 4.0]])

    core = _plsda_scientific_core(matrix, labels, parameters=_parameters(n_components=3))

    assert core["fit"].requested_n_components == 3
    assert core["fit"].n_components == 1
    assert core["metrics"]["effective_n_components"] == 1


def test_native_plsda_generated_projection_is_complete_and_replayable() -> None:
    dataset, labels = _dataset()
    generated = _plsda_export_outputs(dataset, labels, parameters=_parameters(scale=True))
    restored = SherpaPLSDAArtifact.from_fitted_state(generated["fitted_state"])
    replayed_labels, replayed_scores = restored.predict(dataset)
    applied_labels, applied_scores = apply_native_state(dataset, generated["fitted_state"])

    assert set(generated) == {
        "default",
        "X_scores",
        "X_loadings",
        "loadings",
        "explained_variance",
        "class_coefficients",
        "fitted_state",
        "predictions",
        "class_scores",
        "vip_scores",
        "confusion_matrix_train",
        "metrics",
        "plots",
        "metadata",
    }
    np.testing.assert_array_equal(replayed_labels, np.asarray(generated["metadata"]["y_pred"], dtype=object))
    np.testing.assert_array_equal(applied_labels, replayed_labels)
    np.testing.assert_allclose(applied_scores, replayed_scores, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(
        generated["explained_variance"],
        np.column_stack((restored.x_explained_variance, restored.y_explained_variance)),
    )
    np.testing.assert_allclose(generated["class_coefficients"], restored.coefficients)
    assert replayed_scores.shape == (dataset.shape[0], 3)
    assert generated["metadata"]["numeric_output_semantics"] == "class_response_scores_not_probabilities"
    assert _is_model_payload(generated["fitted_state"]) is True


def test_native_plsda_has_a_representative_absolute_performance_ceiling() -> None:
    rng = np.random.default_rng(912)
    labels = np.repeat(np.asarray(["a", "b", "c"], dtype=object), 40)
    matrix = rng.normal(size=(labels.size, 700))
    matrix[labels == "a", :20] += 0.8
    matrix[labels == "b", 20:40] += 0.8
    matrix[labels == "c", 40:60] += 0.8

    with PerformanceCeiling("classification.plsda", "120x700-fit-only", 5.0).measure():
        core = _plsda_scientific_core(
            matrix,
            labels,
            parameters=_parameters(n_components=5, scale=True),
        )
    assert core["train_class_scores"].shape == (120, 3)


def test_plsda_application_has_a_representative_absolute_performance_ceiling() -> None:
    rng = np.random.default_rng(913)
    labels = np.repeat(np.asarray(["a", "b", "c"], dtype=object), 40)
    training = rng.normal(size=(labels.size, 700))
    training[labels == "a", :20] += 0.8
    training[labels == "b", 20:40] += 0.8
    training[labels == "c", 40:60] += 0.8
    dataset = SherpaDataset(
        X=training,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1700.0, training.shape[1]), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(training.shape[0])]),
        target=labels,
        target_context=TargetContext(target_type="categorical", target_names=["class"]),
    )
    fitted_state = PLSDANode("fit", _parameters(n_components=5, scale=True)).fit_fitted_state(dataset, labels)
    application = np.tile(training, (9, 1))[:1_000]
    application_dataset = SherpaDataset(
        X=application,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1700.0, application.shape[1]), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"application-{index}" for index in range(application.shape[0])]),
    )

    with PerformanceCeiling("classification.apply_plsda", "1000x700-fitted-state-replay", 5.0).measure():
        decisions, scores = apply_plsda_fitted_state(application_dataset, fitted_state)

    assert decisions.shape == (1_000,)
    assert scores.shape == (1_000, 3)


@pytest.mark.parametrize("scale,max_score_delta", [(False, 1.0e-5), (True, 5.0e-4)])
def test_native_plsda_agrees_with_independent_pls2_decisions(
    scale: bool,
    max_score_delta: float,
) -> None:
    dataset, labels = _dataset()
    classes = np.unique(labels)
    dummy = _dummy_response(labels, classes)
    fit, artifact = _native_plsda_fit(
        dataset.X,
        dummy,
        classes,
        n_components=2,
        scale=scale,
    )
    reference = PLSRegression(n_components=2, scale=scale, max_iter=1000, tol=1e-12)
    reference.fit(dataset.X, dummy)
    expected = np.asarray(reference.predict(dataset.X), dtype=np.float64)
    labels_actual, actual = artifact.predict(dataset.X, allow_unverified_positional=True)

    # NIPALS and SIMPLS use different multi-response deflation authorities;
    # their response scores need not be bit-identical after component one.
    # The independent reference therefore checks the declared discriminant
    # decision and guards against a material score-scale divergence, while
    # exact replay is proven separately against the native fitted state.
    assert float(np.max(np.abs(actual - expected))) < max_score_delta
    np.testing.assert_array_equal(labels_actual, classes[np.argmax(expected, axis=1)])
    assert fit.algorithm_id == "sherpa.simpls.de_jong_1993"


def test_native_plsda_centred_replay_is_stable_for_large_raw_offsets() -> None:
    dataset, labels = _dataset()
    matrix = dataset.X + 1.0e8
    classes = np.unique(labels)
    fit, artifact = _native_plsda_fit(
        matrix,
        _dummy_response(labels, classes),
        classes,
        n_components=2,
        scale=True,
    )
    _, actual = artifact.predict(matrix, allow_unverified_positional=True)

    np.testing.assert_allclose(actual, fit.predict(matrix), rtol=0.0, atol=0.0)
    assert np.isfinite(actual).all()


@pytest.mark.parametrize("nonfinite", [np.nan, np.inf, -np.inf])
def test_native_plsda_rejects_missing_or_nonfinite_measurements(nonfinite: float) -> None:
    dataset, labels = _dataset()
    matrix = np.array(dataset.X, copy=True)
    matrix[0, 0] = nonfinite
    with pytest.raises(ValueError, match="finite"):
        _plsda_scientific_core(matrix, labels, parameters=_parameters())


def test_plsda_contract_names_one_reference_faithful_operation() -> None:
    metadata = node_registry.get_metadata("classification.plsda")
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["managed_optimization_eligibility"] == (
        ManagedOptimizationEligibility.LOCAL.value,
        ManagedOptimizationEligibility.DEVELOPMENT.value,
        ManagedOptimizationEligibility.FULL_REFIT.value,
    )
    assert contract.payload["supervised_task"] == "classification"
    assert contract.payload["fitted_state_serializer"] == FITTED_STATE_SERIALIZER
    assert {entry["distribution"] for entry in contract.payload["runtime_requirements"]} == {
        "numpy",
        "scikit-learn",
    }
    assert contract.payload["target_access"] == "fit_only"
    assert any("10.1016/0169-7439(93)85002-X" in citation for citation in contract.payload["citations"])
    assert any("10.1002/cem.785" in citation for citation in contract.payload["citations"])
    assert metadata.canonical_parameter_validator is _canonical_plsda_parameters
    ports = {port.name for port in metadata.output_ports or []}
    assert "class_scores" in ports
    assert "probabilities" not in ports


@pytest.mark.parametrize(
    "parameters, message",
    [
        ({**_parameters(), "probability_method": "softmax"}, "exactly"),
        ({**_parameters(), "calibrate_probabilities": False}, "exactly"),
        ({**_parameters(), "cv_folds": 3}, "exactly"),
        (_parameters(n_components=True), "exact integer"),
        (_parameters(scale=1), "strict boolean"),
    ],
)
def test_plsda_parameters_fail_closed(parameters: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _canonical_plsda_parameters(parameters)


def test_plsda_decision_is_argmax_of_predicted_dummy_responses() -> None:
    dataset, labels = _dataset()
    core = _plsda_scientific_core(dataset, labels, parameters=_parameters(scale=True))

    np.testing.assert_array_equal(
        core["train_predictions"],
        core["classes"][np.argmax(core["train_class_scores"], axis=1)],
    )
    assert core["metrics"]["decision_rule"] == "maximum_predicted_dummy_response"
    assert core["metrics"]["numeric_output_semantics"] == "class_response_scores_not_probabilities"
    assert core["metrics"]["evidence_scope"] == "calibration_fit_diagnostics_not_validation_evidence"


def test_plsda_core_fits_once_without_hidden_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset, labels = _dataset()
    calls = 0
    original = _native_plsda_fit

    def counted_fit(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        "spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes._native_plsda_fit",
        counted_fit,
    )
    core = _plsda_scientific_core(dataset, labels, parameters=_parameters())

    assert calls == 1
    assert "split_record" not in core
    assert "cv_predictions" not in core
    assert "cv_class_scores" not in core


@pytest.mark.parametrize(
    "raw_labels,expected",
    [
        (np.asarray([1, 2, 1, 2], dtype=np.int64), ["1", "2", "1", "2"]),
        (
            np.asarray(
                [
                    ["2026-01-01T00:00:00", "Class A"],
                    ["2026-01-02T00:00:00", "Class B"],
                    ["2026-01-03T00:00:00", "Class A"],
                    ["2026-01-04T00:00:00", "Class B"],
                ],
                dtype=object,
            ),
            ["Class A", "Class B", "Class A", "Class B"],
        ),
    ],
)
def test_plsda_preserves_one_canonical_class_label_per_sample(raw_labels, expected) -> None:
    matrix = np.arange(16, dtype=np.float64).reshape(4, 4)
    _, _, labels, _ = _plsda_inputs(matrix, raw_labels)
    assert labels.tolist() == expected


@pytest.mark.parametrize("nonfinite", [np.nan, np.inf, -np.inf])
def test_plsda_rejects_nonfinite_numeric_class_labels(nonfinite: float) -> None:
    matrix = np.arange(16, dtype=np.float64).reshape(4, 4)
    with pytest.raises(ValueError, match="non-finite"):
        _plsda_inputs(matrix, np.asarray([1.0, 2.0, nonfinite, 2.0]))


def test_plsda_rejects_explicit_continuous_target_dataset() -> None:
    dataset, _ = _dataset()
    levels = np.tile(np.asarray([0.0, 1.0, 2.0]), 15)
    continuous_y = SherpaDataset(
        X=levels.reshape(-1, 1),
        target=levels,
        target_context=TargetContext(target_type="continuous", target_names=["response"]),
    )
    with pytest.raises(ValueError, match="requires categorical targets"):
        _plsda_inputs(dataset, continuous_y)


@pytest.mark.asyncio
async def test_plsda_live_and_generated_python_share_the_operation() -> None:
    dataset, labels = _dataset()
    node = PLSDANode("plsda", _parameters(scale=True))
    live = await node.execute(X=dataset, y=labels)
    namespace = {"dataset": dataset, "labels": labels, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "labels"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["plsda"]

    np.testing.assert_array_equal(generated["predictions"], live.outputs["predictions"])
    np.testing.assert_allclose(generated["class_scores"], live.outputs["class_scores"], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["vip_scores"], live.outputs["vip_scores"], rtol=0.0, atol=0.0)
    np.testing.assert_array_equal(generated["confusion_matrix_train"], live.outputs["confusion_matrix_train"])
    np.testing.assert_allclose(generated["default"], live.outputs["default"].X, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["loadings"], live.outputs["loadings"].X, rtol=0.0, atol=0.0)
    assert generated["metrics"] == live.outputs["metrics"]
    assert set(generated["plots"]) == set(live.outputs["plots"])
    assert live.diagnostics["classes"] == ["polymer-a", "polymer-b", "polymer-c"]
    assert live.diagnostics["label_categories"] == ["polymer-a", "polymer-b", "polymer-c"]
    assert live.diagnostics["sample_classes"] == labels.tolist()
    assert live.diagnostics["sample_labels"] == [f"sample-{index}" for index in range(labels.size)]


def test_plsda_predictor_preserves_class_score_semantics_in_generated_execution() -> None:
    dataset, labels = _dataset()
    producer = PLSDANode("fit", _parameters(scale=True))
    fitted_state = producer.fit_fitted_state(dataset, labels)
    predictor = node_registry.create_node("classification.apply_plsda", "apply", {})
    namespace = {"dataset": dataset, "fitted_state": fitted_state, "results": {}}
    exec(  # noqa: S102
        "\n".join(predictor.generate_python({"default": "dataset", "fitted_state": "fitted_state"}, indent="")),
        namespace,
    )
    result = namespace["results"]["apply"]
    expected = producer.apply_fitted_state(dataset, fitted_state)
    np.testing.assert_allclose(result["class_scores"], expected, rtol=0.0, atol=0.0)


def test_plsda_combined_predictor_returns_one_exact_application_surface() -> None:
    dataset, labels = _dataset()
    producer = PLSDANode("fit", _parameters(scale=True))
    fitted_state = producer.fit_fitted_state(dataset, labels)

    decisions, responses, classes, semantics = producer.predict_fitted_classification(dataset, fitted_state)
    expected_decisions, expected_responses = apply_plsda_fitted_state(dataset, fitted_state)

    np.testing.assert_array_equal(decisions, expected_decisions)
    np.testing.assert_allclose(responses, expected_responses, rtol=0.0, atol=0.0)
    np.testing.assert_array_equal(decisions, classes[np.argmax(responses, axis=1)])
    assert semantics == "class_response_scores_not_probabilities"


def test_plsda_application_ports_describe_local_and_imported_custody_without_a_phantom_edge() -> None:
    ports = {port.name: port for port in ApplyPLSDANode.metadata.input_ports}

    assert ports["default"].required is True
    assert ports["fitted_state"].required is False
    assert "omit for imported-artifact application" in (ports["fitted_state"].description or "")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_scores",
    [
        np.asarray([[np.nan, 0.2], [0.3, 0.7]]),
        np.asarray([[0.1, 0.2, 0.7], [0.3, 0.4, 0.3]]),
    ],
)
async def test_plsda_live_and_generated_application_reject_the_same_invalid_responses(invalid_scores) -> None:
    dataset, labels = _dataset()
    fitted_state = PLSDANode("fit", _parameters()).fit_fitted_state(dataset, labels)
    fitted_state["arrays"]["coefficients"] = invalid_scores.tolist()
    node = ApplyPLSDANode("apply", {})
    with pytest.raises(ValueError):
        await node.execute(default=dataset, fitted_state=fitted_state)

    namespace = {"dataset": dataset, "fitted_state": fitted_state, "results": {}}
    with pytest.raises(ValueError):
        exec(  # noqa: S102
            "\n".join(
                node.generate_python({"default": "dataset", "fitted_state": "fitted_state"}, indent="", use_scp=False)
            ),
            namespace,
        )


def test_plsda_starter_fits_scaling_inside_the_model_and_not_upstream() -> None:
    path = Path(__file__).resolve().parents[1] / "src/spectra_sherpa/data/templates/classification_plsda.yaml"
    template = yaml.safe_load(path.read_text(encoding="utf-8"))["template_data"]
    nodes = {node["node_id"]: node for node in template["nodes"]}
    assert nodes["model_1"]["parameters"] == {"n_components": 2, "scale": True}
    assert not any(node["node_type"] == "preprocess.scale" for node in nodes.values())
    edge_set = {
        (edge["from_node_id"], edge["to_node_id"], edge.get("from_output"), edge.get("to_input"))
        for edge in template["edges"]
    }
    assert ("partition_1", "model_1", "X_train", "X") in edge_set
    assert ("partition_1", "predict_1", "X_test", "default") in edge_set


def test_plsda_artifact_replays_native_predicted_dummy_responses() -> None:
    dataset, labels = _dataset()
    core = _plsda_scientific_core(dataset, labels, parameters=_parameters(scale=True))
    metadata, arrays = core["artifact"].to_artifact()
    restored = SherpaPLSDAArtifact.from_artifact(metadata, arrays)
    replayed_labels, replayed_scores = restored.predict(dataset)
    native_scores = core["fit"].predict(dataset.X)

    np.testing.assert_allclose(replayed_scores, native_scores, rtol=0.0, atol=0.0)
    np.testing.assert_array_equal(replayed_labels, np.asarray(restored.classes)[np.argmax(native_scores, axis=1)])


@pytest.mark.parametrize(
    "mutator",
    [
        lambda metadata, arrays: metadata.__setitem__("serializer", "legacy"),
        lambda metadata, arrays: metadata.__setitem__("decision_rule", "softmax"),
        lambda metadata, arrays: metadata.__setitem__("output_semantics", "probabilities"),
        lambda metadata, arrays: metadata.__setitem__("features", 999),
        lambda metadata, arrays: arrays.__setitem__("unexpected", np.ones(1)),
        lambda metadata, arrays: arrays["coefficients"].__setitem__((0, 0), np.nan),
        lambda metadata, arrays: arrays.__setitem__("x_loadings", np.full((2, 8), np.nan)),
        lambda metadata, arrays: arrays.__setitem__("x_loadings", np.ones((1, 8))),
        lambda metadata, arrays: arrays.__setitem__("y_loadings", np.ones((99, 99))),
    ],
)
def test_plsda_artifact_rejects_open_or_forged_state(mutator) -> None:
    dataset, labels = _dataset()
    core = _plsda_scientific_core(dataset, labels, parameters=_parameters())
    metadata, arrays = core["artifact"].to_artifact()
    metadata = copy.deepcopy(metadata)
    arrays = {name: np.array(value, copy=True) for name, value in arrays.items()}
    mutator(metadata, arrays)
    with pytest.raises(ValueError):
        SherpaPLSDAArtifact.from_artifact(metadata, arrays)


def test_plsda_does_not_mutate_inputs() -> None:
    dataset, labels = _dataset()
    matrix_before = dataset.X.copy()
    labels_before = labels.copy()
    _plsda_scientific_core(dataset, labels, parameters=_parameters())
    np.testing.assert_array_equal(dataset.X, matrix_before)
    np.testing.assert_array_equal(labels, labels_before)
