"""Canonical SIMCA scientific, fitted-state, projection, and cost proofs."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.classification.application_nodes import ApplySIMCANode
from spectra_sherpa.app.services.dag.nodes.classification.core_utils import classification_scalar_metrics
from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import (
    SIMCA_FITTED_STATE_SERIALIZER,
    SIMCANode,
    _canonical_simca_parameters,
    _simca_calibration_confusion,
    _simca_export_outputs,
    _simca_q_limit_from_residuals,
    _simca_scientific_core,
    apply_simca_fitted_state,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset(*, rows_per_class: int = 18, features: int = 10) -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(2008)
    labels = np.repeat(np.asarray(["authentic", "adulterated", "reference"], dtype=object), rows_per_class)
    latent = rng.normal(size=(labels.size, 3))
    class_effects = np.asarray([[-1.2, 0.4, 0.8], [0.7, 1.3, -0.6], [1.4, -0.8, 0.1]])
    latent += np.repeat(class_effects, rows_per_class, axis=0)
    loadings = rng.normal(size=(3, features))
    matrix = latent @ loadings + rng.normal(0.0, 0.16, size=(labels.size, features))
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, features), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(labels.size)]),
        target=labels,
        target_context=TargetContext(target_type="categorical", target_names=["material class"]),
    )
    return dataset, labels


def _parameters(**overrides: object) -> dict[str, object]:
    parameters: dict[str, object] = {
        "n_components": 2,
        "confidence_level": 0.95,
        "critical_limits_method": "ddmoments",
    }
    parameters.update(overrides)
    return parameters


@pytest.mark.parametrize(
    ("observed", "predicted", "expected_labels", "expected_matrix"),
    [
        (
            ["A", "A", "A", "B", "B", "B"],
            ["A", "A", "unassigned", "B", "unassigned", "A"],
            ["A", "B", "unassigned"],
            [[2, 0, 1], [1, 1, 1], [0, 0, 0]],
        ),
        (
            ["A", "B", "C", "A", "B", "C"],
            ["A", "B", "unassigned", "C", "B", "C"],
            ["A", "B", "C", "unassigned"],
            [[1, 0, 1, 0], [0, 2, 0, 0], [0, 0, 1, 1], [0, 0, 0, 0]],
        ),
        (["A", "A", "B", "B"], ["A", "B", "B", "A"], ["A", "B"], [[1, 1], [1, 1]]),
        (
            ["A", "A", "B", "B"],
            ["unassigned"] * 4,
            ["A", "B", "unassigned"],
            [[0, 0, 2], [0, 0, 2], [0, 0, 0]],
        ),
        (
            ["major", "major", "major", "major", "minor"],
            ["major", "major", "unassigned", "minor", "minor"],
            ["major", "minor", "unassigned"],
            [[2, 1, 1], [0, 1, 0], [0, 0, 0]],
        ),
    ],
)
def test_simca_calibration_confusion_accounts_for_five_dissimilar_rejection_cases(
    observed: list[str],
    predicted: list[str],
    expected_labels: list[str],
    expected_matrix: list[list[int]],
) -> None:
    classes = np.unique(np.asarray(observed, dtype=object))

    matrix, labels = _simca_calibration_confusion(
        np.asarray(observed, dtype=object),
        np.asarray(predicted, dtype=object),
        classes,
    )

    assert labels.tolist() == expected_labels
    assert matrix.tolist() == expected_matrix
    assert int(matrix.sum()) == len(observed)


def test_simca_rejection_fixture_uses_complete_known_class_specificity() -> None:
    observed = np.asarray(["A", "A", "A", "B", "B", "B"], dtype=object)
    predicted = np.asarray(["A", "A", "unassigned", "B", "unassigned", "A"], dtype=object)

    metrics = classification_scalar_metrics(observed, predicted, np.asarray(["A", "B"]), prefix="train_")

    assert metrics["train_accuracy"] == pytest.approx(0.5)
    assert metrics["train_specificity_macro"] == pytest.approx(5 / 6)


def test_simca_export_discloses_rejections_in_matrix_plot_and_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    from spectra_sherpa.app.services.dag.nodes.classification import simca_nodes

    dataset, labels = _dataset(rows_per_class=6)
    original_predict = simca_nodes._predict_simca

    def predict_with_two_rejections(*args, **kwargs):
        prediction, distances, distance_matrix, accepted, membership = original_predict(*args, **kwargs)
        prediction = np.asarray(prediction, dtype=object).copy()
        prediction[[0, 7]] = "unassigned"
        return prediction, distances, distance_matrix, accepted, membership

    monkeypatch.setattr(simca_nodes, "_predict_simca", predict_with_two_rejections)

    output = _simca_export_outputs(dataset, labels, parameters=_parameters())
    matrix = np.asarray(output["confusion_matrix_train"])
    plot = output["confusion_visualization"]

    assert int(matrix.sum()) == dataset.shape[0]
    assert output["n_rejected"] == 2
    assert output["rejection_rate"] == pytest.approx(2 / dataset.shape[0])
    assert output["metrics"]["n_samples"] == dataset.shape[0]
    assert output["metrics"]["confusion_matrix_labels"]["train"][-1] == "unassigned"
    assert plot["data"][0]["x"][-1] == "unassigned"
    assert plot["data"][0]["y"][-1] == "unassigned"
    assert sum(sum(row) for row in plot["data"][0]["z"]) == dataset.shape[0]


def test_simca_has_one_exact_local_fitted_model_contract() -> None:
    contract = node_registry.get_metadata("classification.simca").resolved_execution_contract()
    assert contract is not None
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["managed_optimization_eligibility"] == (
        ManagedOptimizationEligibility.LOCAL.value,
        ManagedOptimizationEligibility.DEVELOPMENT.value,
        ManagedOptimizationEligibility.FULL_REFIT.value,
    )
    assert contract.payload["managed_optimization_profiles"] == ("first_party_pls",)
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["fitted_state_serializer"] == SIMCA_FITTED_STATE_SERIALIZER
    assert any("Pomerantsev" in citation for citation in contract.payload["citations"])
    assert node_registry.get_metadata("classification.simca").requires_scp is False

    application = node_registry.get_metadata("classification.apply_simca").resolved_execution_contract()
    assert application is not None
    assert application.payload["lifecycle_kind"] == LifecycleKind.ARTIFACT_APPLICATION.value
    assert application.payload["fitted_state_serializer"] == SIMCA_FITTED_STATE_SERIALIZER


def test_simca_parameter_contract_is_closed() -> None:
    assert _canonical_simca_parameters(_parameters()) == _parameters()
    for invalid in (
        {},
        _parameters(n_components=True),
        _parameters(n_components=0),
        _parameters(n_components=51),
        _parameters(confidence_level=0.79),
        _parameters(confidence_level=1.0),
        _parameters(critical_limits_method="approximate"),
        {**_parameters(), "cv_folds": 3},
        {**_parameters(), "epsilon": 1e-10},
    ):
        with pytest.raises(ValueError):
            _canonical_simca_parameters(invalid)


def test_simca_classical_q_limit_refuses_undefined_moments() -> None:
    for residuals in (np.asarray([]), np.zeros(8), np.asarray([1.0])):
        with pytest.raises(ValueError, match="Q limits require"):
            _simca_q_limit_from_residuals(residuals, 0.95)


def test_simca_fitted_state_rejects_malformed_numeric_arrays() -> None:
    dataset, labels = _dataset()
    state = _simca_scientific_core(dataset, labels, parameters=_parameters())["fitted_state"]
    corruptions = []
    for key, replacement in (
        ("class_0_loadings", [[1.0]]),
        ("class_0_eigenvalues", [-1.0, 1.0]),
        ("class_0_scale", [0.0] * dataset.X.shape[1]),
        ("class_0_pca_mean", [float("nan")] * dataset.X.shape[1]),
    ):
        corrupted = copy.deepcopy(state)
        corrupted["arrays"][key] = replacement
        corruptions.append(corrupted)

    for corrupted in corruptions:
        with pytest.raises(ValueError, match="SIMCA fitted state"):
            apply_simca_fitted_state(dataset, corrupted)


def test_simca_live_generated_fold_and_application_share_one_authority() -> None:
    dataset, labels = _dataset()
    node = SIMCANode("simca", _parameters())
    core = _simca_scientific_core(dataset, labels, parameters=_parameters())
    namespace = {"dataset": dataset, "labels": labels, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "labels"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["simca"]
    replay_labels, replay_affinity = apply_simca_fitted_state(dataset, core["fitted_state"])

    np.testing.assert_array_equal(generated["predictions"], core["predictions"])
    np.testing.assert_array_equal(replay_labels, core["predictions"])
    np.testing.assert_allclose(generated["class_distance_matrix"], core["class_distance_matrix"], rtol=0.0, atol=0.0)
    assert replay_affinity.shape == core["class_distance_matrix"].shape
    assert generated["metrics"] == core["metrics"]
    assert generated["fitted_state"] == core["fitted_state"]
    applicability = generated["fitted_state"]["metadata"]["applicability"]
    assert set(applicability) == set(generated["fitted_state"]["metadata"]["classes"])
    for evidence in applicability.values():
        assert evidence["limits"]["t2"] > 0.0
        assert evidence["limits"]["q"] > 0.0
        assert evidence["score_statistics"]["count"] > 0
        assert "scores" not in json.dumps(evidence, sort_keys=True)


@pytest.mark.asyncio
async def test_simca_interactive_and_application_nodes_use_the_same_state() -> None:
    dataset, labels = _dataset()
    producer = SIMCANode("fit", _parameters())
    live = await producer.execute(X=dataset, y=labels)
    application = ApplySIMCANode("apply", {})
    applied = await application.execute(X_new=dataset, fitted_state=live.outputs["fitted_state"])
    expected_labels, expected_affinity = apply_simca_fitted_state(dataset, live.outputs["fitted_state"])
    for input_port in ("X_new", "default"):
        namespace = {"dataset": dataset, "fitted_state": live.outputs["fitted_state"], "results": {}}
        exec(  # noqa: S102
            "\n".join(
                application.generate_python(
                    {input_port: "dataset", "fitted_state": "fitted_state"},
                    indent="",
                )
            ),
            namespace,
        )
        generated = namespace["results"]["apply"]
        np.testing.assert_array_equal(generated["y_pred"], expected_labels)
        np.testing.assert_allclose(generated["class_affinity"], expected_affinity, rtol=0.0, atol=0.0)

    np.testing.assert_array_equal(applied.outputs["y_pred"], expected_labels)
    np.testing.assert_allclose(applied.outputs["class_affinity"], expected_affinity, rtol=0.0, atol=0.0)
    assert live.outputs["confusion_matrix"] == live.outputs["confusion_matrix_train"]
    presentation = producer.metadata.resolved_presentation_contract()
    assert presentation.default_presentation == "acceptance"
    assert [item.presentation_id for item in presentation.presentations] == [
        "acceptance",
        "class_distances",
        "metrics",
        "calibration_confusion",
        "first_class_projection",
    ]
    acceptance = live.outputs["acceptance_visualization"]
    assert acceptance["metadata"]["boundary"] == "accepted when T²/limit <= 1 and Q/limit <= 1"
    assert sum(len(trace["x"]) for trace in acceptance["data"][:-2]) == dataset.shape[0]
    assert [trace["name"] for trace in acceptance["data"][:-2]] == [
        "Nearest: adulterated",
        "Nearest: authentic",
        "Nearest: reference",
    ]
    assert live.outputs["confusion_visualization"] == live.outputs["plots"]["confusion_matrix_train"]
    assert "cv" not in live.outputs["metrics"]["splits"]


@pytest.mark.asyncio
async def test_simca_executes_in_the_base_profile_without_spectrochempy(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset, labels = _dataset()
    monkeypatch.setattr("spectra_sherpa.interoperability.spectrochempy_adapter.import_module", None)
    node = SIMCANode("fit", _parameters())

    result = await node.run(X=dataset, y=labels)

    assert node.status.value == "completed"
    assert result.outputs["fitted_state"]["serializer"] == SIMCA_FITTED_STATE_SERIALIZER


def test_simca_does_not_mutate_scientist_inputs() -> None:
    dataset, labels = _dataset()
    matrix_before = np.array(dataset.X, copy=True)
    labels_before = copy.deepcopy(labels)
    _simca_scientific_core(dataset, labels, parameters=_parameters())
    np.testing.assert_array_equal(dataset.X, matrix_before)
    np.testing.assert_array_equal(labels, labels_before)


def test_simca_fixed_local_workload_stays_inside_reviewed_ceiling() -> None:
    dataset, labels = _dataset(rows_per_class=40, features=120)
    with PerformanceCeiling("classification.simca", "120x120-three-class-fit-only", 5.0).measure():
        _simca_scientific_core(dataset, labels, parameters=_parameters())
