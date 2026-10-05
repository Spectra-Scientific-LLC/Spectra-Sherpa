"""Phase 7 generic supervision, held-block, and one-path classification proofs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    FoldGraphExecutionError,
    execute_candidate_validation,
    execute_candidate_validation_with_private_classification_trace,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset
from spectra_sherpa.app.services.dag.spectral_capability import (
    SpectralCapabilityError,
    SpectralDatasetCapability,
)
from spectra_sherpa.app.services.dag.supervision_binding import (
    admit_attached_sample_table_supervision,
    bind_sample_table_supervision,
    rebind_sample_preserving_supervision,
)
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.canonical_execution_evidence import validate_canonical_validation_execution
from spectra_sherpa.sdk.validate import (
    make_leave_one_group_out_classification_plan,
    make_split_plan,
    validate_classification_split_plan,
)


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _collection_dataset(specimen: list[str] | None = None) -> SherpaDataset:
    labels = [f"sample-{index + 1}" for index in range(6)]
    specimen = specimen or ["A", "B", "A", "B", "A", "B"]
    blocks = [1, 1, 2, 2, 3, 3]
    matrix = np.asarray(
        [
            [2.0, 1.1, 0.0, 0.2],
            [0.1, 0.2, 1.0, 2.0],
            [2.1, 1.0, 0.1, 0.2],
            [0.2, 0.1, 1.2, 1.9],
            [1.9, 1.2, 0.0, 0.1],
            [0.0, 0.2, 0.9, 2.1],
        ],
        dtype=np.float64,
    )
    return SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(
            values=np.asarray([1800.0, 1600.0, 1400.0, 1200.0]),
            units="cm-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(
            labels=labels,
            sample_table={
                "sample_id": labels,
                "specimen_id": specimen,
                "block": blocks,
                "acquisition_order": [1, 2, 1, 2, 1, 2],
            },
        ),
        units="absorbance",
        data_role="X_spectra",
        extra={
            "source_collection": {
                "schema_version": "spectrasherpa-source-collection/1",
                "file_count": 6,
                "files": [],
                "manifest_digest": "a" * 64,
                "collection_definition_sha256": "b" * 64,
                "scientific_collection_sha256": "c" * 64,
            }
        },
    )


def _replicate_structured_classifier_dataset() -> SherpaDataset:
    labels: list[str] = []
    specimens: list[str] = []
    blocks: list[int] = []
    rows: list[np.ndarray] = []
    for block in (1, 2, 3):
        for specimen, center in (("A", 1.5), ("B", -1.5)):
            for replicate in range(3):
                labels.append(f"{specimen}-B{block}-R{replicate + 1}")
                specimens.append(specimen)
                blocks.append(block)
                delta = 0.015 * (replicate - 1) + 0.005 * (block - 2)
                rows.append(np.asarray([center + delta, 0.6 * center - delta, delta, -delta]))
    return SherpaDataset(
        X=np.asarray(rows, dtype=np.float64),
        feature_axis=SpectralAxis(
            values=np.asarray([1800.0, 1600.0, 1400.0, 1200.0]),
            units="cm-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(
            labels=labels,
            sample_table={
                "sample_id": labels,
                "specimen_id": specimens,
                "block": blocks,
            },
        ),
        units="absorbance",
        data_role="X_spectra",
        extra={
            "source_collection": {
                "schema_version": "spectrasherpa-source-collection/1",
                "file_count": len(labels),
                "files": [],
                "manifest_digest": "d" * 64,
                "collection_definition_sha256": "e" * 64,
                "scientific_collection_sha256": "f" * 64,
            }
        },
    )


def test_attach_target_parameters_are_explicit_and_closed() -> None:
    node = node_registry.create_node(
        "data.attach_target",
        "attach",
        {
            "target_source": "sample_table_column",
            "target_type": "categorical",
            "target_column": "specimen_id",
            "group_column": "block",
        },
    )

    result = node_registry.get_metadata("data.attach_target").canonical_parameter_validator(node._resolve_params())
    assert result["target_column"] == "specimen_id"
    assert result["group_column"] == "block"


@pytest.mark.asyncio
async def test_attach_target_node_uses_exact_sample_table_columns() -> None:
    dataset = _collection_dataset()
    node = node_registry.create_node(
        "data.attach_target",
        "attach",
        {
            "target_source": "sample_table_column",
            "target_type": "categorical",
            "target_column": "specimen_id",
            "group_column": "block",
        },
    )
    attached = (await node.execute(X=dataset))["default"]
    binding = bind_sample_table_supervision(
        attached,
        target_column="specimen_id",
        target_type="categorical",
        group_column="block",
    )

    np.testing.assert_array_equal(attached.X, dataset.X)
    np.testing.assert_array_equal(attached.target, np.asarray(["A", "B", "A", "B", "A", "B"]))
    np.testing.assert_array_equal(binding.groups, np.asarray([1, 1, 2, 2, 3, 3]))
    assert attached.sample_axis.sample_table == dataset.sample_axis.sample_table
    assert attached.meta["supervision_binding"]["supervision_binding_sha256"] == binding.digest
    assert binding.record["target_authority"]["column"] == "specimen_id"
    assert binding.record["group_column"] == "block"


@pytest.mark.parametrize(
    "mutator,message",
    [
        (lambda table: table["sample_id"].reverse(), "does not exactly match"),
        (lambda table: table.pop("specimen_id"), "no aligned column"),
        (lambda table: table["block"].__setitem__(0, "1"), "one exact scalar"),
        (lambda table: table["specimen_id"].__setitem__(0, None), "missing values"),
    ],
)
def test_sample_table_target_binding_refuses_identity_mutations(mutator, message: str) -> None:
    dataset = _collection_dataset()
    table = {name: list(values) for name, values in dataset.sample_axis.sample_table.items()}
    mutator(table)
    axis = dataset.sample_axis.model_copy(deep=True)
    axis.sample_table = table
    dataset.sample_axis = axis
    with pytest.raises(ValueError, match=message):
        bind_sample_table_supervision(
            dataset,
            target_column="specimen_id",
            target_type="categorical",
            group_column="block",
        )


def test_capability_revalidates_the_bound_table_target_and_groups() -> None:
    dataset = _collection_dataset()
    attached = attach_target_dataset(
        dataset,
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    binding = attached.meta["supervision_binding"]
    groups = np.asarray([1, 1, 2, 2, 3, 3])
    capability = SpectralDatasetCapability.from_dataset(
        attached,
        custody_id="phase7-synthetic",
        dataset_ref_digest=binding["supervision_binding_sha256"],
        groups=groups,
    )
    assert "sample_table" not in capability.metadata["axes"]["sample"]

    changed = attached.copy()
    changed_axis = changed.sample_axis.model_copy(deep=True)
    changed_axis.sample_table["block"][0] = 3
    changed.sample_axis = changed_axis
    with pytest.raises(SpectralCapabilityError, match="does not match its exact sample table"):
        SpectralDatasetCapability.from_dataset(
            changed,
            custody_id="phase7-synthetic",
            dataset_ref_digest=binding["supervision_binding_sha256"],
            groups=groups,
        )
    with pytest.raises(SpectralCapabilityError, match="validation groups do not match"):
        SpectralDatasetCapability.from_dataset(
            attached,
            custody_id="phase7-synthetic",
            dataset_ref_digest=binding["supervision_binding_sha256"],
            groups=np.asarray([1, 1, 2, 2, 1, 3]),
        )

    changed_matrix = attached.copy()
    changed_matrix.X[0, 0] += 0.25
    with pytest.raises(SpectralCapabilityError, match="does not match its exact sample table"):
        SpectralDatasetCapability.from_dataset(
            changed_matrix,
            custody_id="phase7-synthetic",
            dataset_ref_digest=binding["supervision_binding_sha256"],
            groups=groups,
        )

    changed_axis = attached.copy()
    spectral_axis = changed_axis.get_feature_axis().model_copy(deep=True)
    spectral_axis.values[0] += 1.0
    changed_axis.feature_axis = spectral_axis
    with pytest.raises(SpectralCapabilityError, match="does not match its exact sample table"):
        SpectralDatasetCapability.from_dataset(
            changed_axis,
            custody_id="phase7-synthetic",
            dataset_ref_digest=binding["supervision_binding_sha256"],
            groups=groups,
        )


@pytest.mark.asyncio
async def test_feature_clip_rebinds_supervision_in_live_and_exported_execution() -> None:
    source = attach_target_dataset(
        _collection_dataset(),
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    original = admit_attached_sample_table_supervision(source)
    node = node_registry.create_node("preprocess.clip_range", "clip", {"minimum": 1400, "maximum": 1800})
    live = (await node.execute(input_data=source)).outputs["default"]
    namespace = {"dataset": source, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="", use_scp=False)), namespace)  # noqa: S102
    generated = namespace["results"]["clip"]
    for result in (live, generated):
        binding = admit_attached_sample_table_supervision(result)
        assert binding is not None and original is not None
        assert binding.digest != original.digest
        assert binding.record["target_authority"] == original.record["target_authority"]
        np.testing.assert_array_equal(binding.target, original.target)
        np.testing.assert_array_equal(binding.groups, original.groups)
        np.testing.assert_array_equal(result.X, source.X[:, :3])
        np.testing.assert_array_equal(result.feature_axis.values, [1800, 1600, 1400])
    assert live.meta["supervision_binding"] == generated.meta["supervision_binding"]
    assert admit_attached_sample_table_supervision(source).digest == original.digest


@pytest.mark.parametrize("tamper", ["matrix", "axis", "target", "table"])
@pytest.mark.asyncio
async def test_feature_clip_does_not_repair_tampered_input_supervision(tamper: str) -> None:
    source = attach_target_dataset(
        _collection_dataset(),
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    if tamper == "matrix":
        source.X[0, 0] += 0.25
    elif tamper == "axis":
        axis = source.feature_axis.model_copy(deep=True)
        axis.values[0] += 1
        source.feature_axis = axis
    elif tamper == "target":
        source.target = np.roll(source.target, 1)
    else:
        axis = source.sample_axis.model_copy(deep=True)
        axis.sample_table["block"][0] = 3
        source.sample_axis = axis
    node = node_registry.create_node("preprocess.clip_range", "clip", {"minimum": 1400, "maximum": 1800})
    with pytest.raises(ValueError, match="does not match"):
        await node.execute(input_data=source)


def test_feature_rebinding_refuses_changed_output_sample_context() -> None:
    source = attach_target_dataset(
        _collection_dataset(),
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    result = source[:, :3]
    axis = result.sample_axis.model_copy(deep=True)
    axis.sample_table["block"][0] = 3
    result.sample_axis = axis
    with pytest.raises(ValueError, match="changed the exact sample supervision context"):
        rebind_sample_preserving_supervision(source, result)


def test_connected_target_attachment_retires_a_prior_table_binding() -> None:
    table_bound = attach_target_dataset(
        _collection_dataset(),
        None,
        target_type="categorical",
        node_id="attach-table",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    connected = attach_target_dataset(
        table_bound,
        np.asarray(table_bound.target, dtype=object),
        target_type="categorical",
        node_id="attach-connected",
        target_source="connected_target",
    )
    assert "supervision_binding" not in connected.meta
    with pytest.raises(SpectralCapabilityError, match="sample_table is not admitted"):
        SpectralDatasetCapability.from_dataset(
            connected,
            custody_id="phase7-synthetic",
            dataset_ref_digest=table_bound.meta["supervision_binding"]["supervision_binding_sha256"],
            groups=np.asarray([1, 1, 2, 2, 3, 3]),
        )


def test_leave_one_group_out_plan_is_exact_and_deterministic() -> None:
    labels = np.asarray(["A", "B", "A", "B", "A", "B"])
    groups = np.asarray([1, 1, 2, 2, 3, 3])

    first = make_leave_one_group_out_classification_plan(
        labels,
        groups,
        require_one_per_class_group=True,
    )
    second = make_leave_one_group_out_classification_plan(
        labels,
        groups,
        require_one_per_class_group=True,
    )

    assert first.digest == second.digest
    assert first.method == "leave_one_group_out_classification"
    assert first.held_out_groups == (1, 2, 3)
    assert [fold.test.tolist() for fold in first.folds] == [[0, 1], [2, 3], [4, 5]]
    assert [fold.train.size for fold in first.folds] == [4, 4, 4]


def test_leave_one_specimen_out_allows_single_class_test_groups() -> None:
    labels = np.asarray(
        ["angustifolia"] * 21 + ["latifolia"] * 6 + ["intermedia"] * 6,
        dtype=object,
    )
    groups = np.repeat(np.arange(11), 3)

    plan = make_leave_one_group_out_classification_plan(labels, groups)

    assert len(plan.folds) == 11
    assert all(fold.test.size == 3 for fold in plan.folds)
    assert all(set(labels[fold.train]) == set(labels) for fold in plan.folds)
    assert sorted(np.concatenate([fold.test for fold in plan.folds]).tolist()) == list(range(33))


def test_leave_one_group_out_rejects_a_class_present_in_only_one_group() -> None:
    with pytest.raises(ValueError, match="train partition omits a declared class"):
        make_leave_one_group_out_classification_plan(
            np.asarray(["major", "major", "major", "minor"], dtype=object),
            np.asarray([1, 2, 3, 4]),
        )


@pytest.mark.parametrize("replacement", [True, 1.0, 2**53, float("nan"), {"group": 1}])
def test_leave_one_group_out_plan_refuses_inexact_declared_group_identity(replacement: object) -> None:
    labels = np.asarray(["A", "B", "A", "B", "A", "B"])
    groups = np.asarray([1, 1, 2, 2, 3, 3], dtype=object)
    plan = make_leave_one_group_out_classification_plan(labels, groups)
    changed = replace(plan, held_out_groups=(replacement, *plan.held_out_groups[1:]))
    with pytest.raises(ValueError, match="group|JSON|finite|lossless"):
        validate_classification_split_plan(changed, labels, groups=groups)


def test_ordinary_split_plan_digest_reproduces_from_its_v1_payload() -> None:
    plan = make_split_plan(6, n_splits=3)
    payload = {
        "schema_version": "spectra-split-plan/1",
        "method": plan.method,
        "n_samples": plan.n_samples,
        "grouped": plan.grouped,
        "folds": [{"train": fold.train.tolist(), "test": fold.test.tolist()} for fold in plan.folds],
    }
    assert (
        hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        == plan.digest
    )


def test_leave_one_group_out_refuses_incomplete_class_group_cell() -> None:
    with pytest.raises(ValueError, match="omits a declared class|exactly one row per class/group"):
        make_leave_one_group_out_classification_plan(
            np.asarray(["A", "B", "A", "B", "A", "A"]),
            np.asarray([1, 1, 2, 2, 3, 3]),
            require_one_per_class_group=True,
        )


@pytest.mark.asyncio
async def test_plsda_validation_uses_three_fits_three_applications_and_one_terminal_refit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _collection_dataset()
    attached = attach_target_dataset(
        dataset,
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    binding = bind_sample_table_supervision(
        attached,
        target_column="specimen_id",
        target_type="categorical",
        group_column="block",
    )
    plan = make_leave_one_group_out_classification_plan(
        binding.target,
        binding.groups,
        require_one_per_class_group=True,
    )
    capability = SpectralDatasetCapability.from_dataset(
        attached,
        custody_id="phase7-synthetic",
        dataset_ref_digest=binding.digest,
        split_plan_digest=plan.digest,
        groups=binding.groups,
    )
    graph = admit_validation_graph(
        [
            WorkflowNode("model", "classification.plsda", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.classification_evaluator", {}),
        ],
        [WorkflowEdge("model", "score", from_output="predictions", to_input="default")],
    )
    counts = {"fit": 0, "apply": 0}
    # Patch the exact class held by the frozen registry.  Other containment
    # tests deliberately reload optional modules, so a module-level class
    # reference is not a reliable full-suite execution authority.
    registered_plsda = node_registry.get_node_class("classification.plsda")
    original_fit = registered_plsda.fit_fitted_state
    original_apply = registered_plsda.predict_fitted_classification

    def counted_fit(self, input_data, target):
        counts["fit"] += 1
        return original_fit(self, input_data, target)

    def counted_apply(self, input_data, state):
        counts["apply"] += 1
        return original_apply(self, input_data, state)

    monkeypatch.setattr(registered_plsda, "fit_fitted_state", counted_fit)
    monkeypatch.setattr(registered_plsda, "predict_fitted_classification", counted_apply)

    validation, private_trace = await execute_candidate_validation_with_private_classification_trace(
        graph,
        capability,
        plan,
    )
    assert counts == {"fit": 3, "apply": 3}
    assert validation.task_type == "classification"
    assert validation.model_operation_id == "classification.plsda"
    assert validation.metrics.n_samples == 6
    assert validation.metrics.registry_version == "2"
    assert len(validation.metrics.class_sensitivities) == 2
    assert len(validation.metrics.class_specificities) == 2
    assert validation.metrics.simca_acceptance is None
    assert len(private_trace.folds) == 3
    with pytest.raises(TypeError):
        type(private_trace)("0" * 64, ())
    assert sorted(index for fold in private_trace.folds for index in fold.test_indices) == list(range(6))
    for public_fold, private_fold in zip(validation.folds, private_trace.folds, strict=True):
        assert public_fold.prediction_application_digest == private_fold.application_digest
        assert private_fold.fitted_state.digest == private_fold.fitted_state_digest
        assert private_fold.fitted_state.state_size_bytes == len(private_fold.fitted_state.canonical_state_bytes())
        state = private_fold.fitted_state.state
        assert set(state["arrays"]) == {
            "coefficients",
            "x_explained_variance",
            "x_loadings",
            "x_offset",
            "y_explained_variance",
            "y_loadings",
            "y_offset",
        }
        expected = np.asarray(private_fold.class_labels, dtype=object)[np.argmax(private_fold.class_responses, axis=1)]
        np.testing.assert_array_equal(np.asarray(private_fold.predictions, dtype=object), expected)
        assert np.all(private_fold.decision_margins >= 0.0)

    monkeypatch.setattr(registered_plsda, "predict_fitted_classification", original_apply)
    verifier = registered_plsda("verify-private-custody", {"n_components": 1, "scale": False})
    for plan_fold, private_fold in zip(plan.folds, private_trace.folds, strict=True):
        mask = np.zeros(attached.shape[0], dtype=bool)
        mask[plan_fold.test] = True
        labels, responses, classes, _semantics = verifier.predict_fitted_classification(
            attached[mask],
            private_fold.fitted_state.state,
        )
        np.testing.assert_array_equal(labels, np.asarray(private_fold.predictions, dtype=object))
        np.testing.assert_array_equal(responses, private_fold.class_responses)
        np.testing.assert_array_equal(classes, np.asarray(private_fold.class_labels, dtype=object))

    rewritten = validation.as_dict()
    rewritten["folds"][0]["prediction_application_digest"] = None
    # Other containment tests deliberately reload SDK modules.  Assert the
    # stable public ValueError contract and exact field message rather than a
    # reload-sensitive class object identity.
    with pytest.raises(ValueError, match="prediction_application_digest"):
        validate_canonical_validation_execution(rewritten)

    refit = await execute_selected_candidate_full_refit(graph, capability, validation)
    assert counts == {"fit": 4, "apply": 3}
    assert refit.model_node_id == "model"
    assert len(refit.fitted_states) == 1


@pytest.mark.parametrize(
    ("operation_id", "parameters"),
    [
        ("classification.knn", {"n_neighbors": 3, "weights": "uniform", "metric": "euclidean", "scale": True}),
        (
            "classification.simca",
            {"n_components": 1, "confidence_level": 0.99, "critical_limits_method": "classical"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_generic_classifiers_use_the_same_explicit_grouped_fold_executor(
    operation_id: str,
    parameters: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _replicate_structured_classifier_dataset()
    attached = attach_target_dataset(
        dataset,
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    binding = bind_sample_table_supervision(
        attached,
        target_column="specimen_id",
        target_type="categorical",
        group_column="block",
    )
    plan = make_leave_one_group_out_classification_plan(binding.target, binding.groups)
    capability = SpectralDatasetCapability.from_dataset(
        attached,
        custody_id=f"generic-{operation_id}",
        dataset_ref_digest=binding.digest,
        split_plan_digest=plan.digest,
        groups=binding.groups,
    )
    graph = admit_validation_graph(
        [
            WorkflowNode("model", operation_id, parameters),
            WorkflowNode("score", "diagnostics.classification_evaluator", {}),
        ],
        [WorkflowEdge("model", "score", from_output="predictions", to_input="default")],
    )
    registered = node_registry.get_node_class(operation_id)
    original_fit = registered.fit_fitted_state
    original_apply = registered.predict_fitted_labels
    counts = {"fit": 0, "apply": 0}

    def counted_fit(self, input_data, target):
        counts["fit"] += 1
        return original_fit(self, input_data, target)

    def counted_apply(self, input_data, state):
        counts["apply"] += 1
        return original_apply(self, input_data, state)

    monkeypatch.setattr(registered, "fit_fitted_state", counted_fit)
    monkeypatch.setattr(registered, "predict_fitted_labels", counted_apply)

    validation = await execute_candidate_validation(graph, capability, plan)

    assert counts == {"fit": 3, "apply": 3}
    assert validation.model_operation_id == operation_id
    assert validation.metrics.n_samples == attached.shape[0]
    assert plan.held_out_groups == (1, 2, 3)
    for fold, held_out in zip(plan.folds, plan.held_out_groups, strict=True):
        assert set(binding.groups[fold.test].tolist()) == {held_out}
        assert held_out not in set(binding.groups[fold.train].tolist())


@pytest.mark.asyncio
async def test_simca_rejections_remain_counted_in_grouped_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _replicate_structured_classifier_dataset()
    attached = attach_target_dataset(
        dataset,
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    binding = bind_sample_table_supervision(
        attached,
        target_column="specimen_id",
        target_type="categorical",
        group_column="block",
    )
    plan = make_leave_one_group_out_classification_plan(binding.target, binding.groups)
    capability = SpectralDatasetCapability.from_dataset(
        attached,
        custody_id="simca-rejection-accounting",
        dataset_ref_digest=binding.digest,
        split_plan_digest=plan.digest,
        groups=binding.groups,
    )
    graph = admit_validation_graph(
        [
            WorkflowNode(
                "model",
                "classification.simca",
                {"n_components": 1, "confidence_level": 0.99, "critical_limits_method": "classical"},
            ),
            WorkflowNode("score", "diagnostics.classification_evaluator", {}),
        ],
        [WorkflowEdge("model", "score", from_output="predictions", to_input="default")],
    )
    registered = node_registry.get_node_class("classification.simca")
    monkeypatch.setattr(
        registered,
        "predict_fitted_labels",
        lambda _self, input_data, _state: np.full(input_data.shape[0], "unassigned", dtype=object),
    )
    from spectra_sherpa.app.services.dag.nodes.classification import simca_nodes

    monkeypatch.setattr(
        simca_nodes,
        "simca_acceptance_membership",
        lambda input_data, state: (
            tuple(state["metadata"]["classes"]),
            np.zeros((input_data.shape[0], len(state["metadata"]["classes"])), dtype=bool),
        ),
    )

    validation = await execute_candidate_validation(graph, capability, plan)

    assert validation.metrics.n_samples == attached.shape[0]
    assert validation.metrics.accuracy == 0.0
    assert validation.metrics.balanced_accuracy == 0.0
    assert validation.metrics.labels[-1] == "unassigned"
    assert sum(row[-1] for row in validation.metrics.confusion_matrix) == attached.shape[0]
    acceptance = validation.metrics.simca_acceptance
    assert acceptance is not None
    assert acceptance.n_samples == attached.shape[0]
    assert acceptance.unassigned_count == attached.shape[0]
    assert acceptance.multiple_acceptance_count >= 0
    evidence = acceptance.as_dict()
    assert evidence["class_acceptance_specificity"] is None
    assert evidence["representative_challenge_population_declared"] is False


@pytest.mark.asyncio
async def test_simca_refuses_modeled_class_that_collides_with_reserved_rejection_label() -> None:
    dataset = _collection_dataset(["unassigned", "B", "unassigned", "B", "unassigned", "B"])
    attached = attach_target_dataset(
        dataset,
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    binding = bind_sample_table_supervision(
        attached,
        target_column="specimen_id",
        target_type="categorical",
        group_column="block",
    )
    plan = make_leave_one_group_out_classification_plan(binding.target, binding.groups)
    capability = SpectralDatasetCapability.from_dataset(
        attached,
        custody_id="simca-reserved-rejection-label",
        dataset_ref_digest=binding.digest,
        split_plan_digest=plan.digest,
        groups=binding.groups,
    )
    graph = admit_validation_graph(
        [
            WorkflowNode(
                "model",
                "classification.simca",
                {"n_components": 1, "confidence_level": 0.99, "critical_limits_method": "classical"},
            ),
            WorkflowNode("score", "diagnostics.classification_evaluator", {}),
        ],
        [WorkflowEdge("model", "score", from_output="predictions", to_input="default")],
    )

    with pytest.raises(FoldGraphExecutionError, match="reserved for rejected samples"):
        await execute_candidate_validation(graph, capability, plan)


@pytest.mark.asyncio
async def test_private_trace_accepts_distinct_response_and_metric_class_orders() -> None:
    # Deliberately make first-observed metric order differ from the estimator's
    # lexicographic response-column order while preserving the balanced cells.
    dataset = _collection_dataset(["Z", "A", "Z", "A", "Z", "A"])
    attached = attach_target_dataset(
        dataset,
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    binding = bind_sample_table_supervision(
        attached,
        target_column="specimen_id",
        target_type="categorical",
        group_column="block",
    )
    plan = make_leave_one_group_out_classification_plan(
        binding.target, binding.groups, require_one_per_class_group=True
    )
    capability = SpectralDatasetCapability.from_dataset(
        attached,
        custody_id="phase7-distinct-class-orders",
        dataset_ref_digest=binding.digest,
        split_plan_digest=plan.digest,
        groups=binding.groups,
    )
    graph = admit_validation_graph(
        [
            WorkflowNode("model", "classification.plsda", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.classification_evaluator", {}),
        ],
        [WorkflowEdge("model", "score", from_output="predictions", to_input="default")],
    )

    validation, trace = await execute_candidate_validation_with_private_classification_trace(graph, capability, plan)

    assert validation.metrics.labels == ("Z", "A")
    assert trace.folds[0].class_labels == ("A", "Z")
    assert validation.metrics.n_samples == 6


def test_phase7_path_has_no_node_local_cv_or_second_estimator() -> None:
    root = Path(__file__).resolve().parents[1]
    classifier_root = root / "src/spectra_sherpa/app/services/dag/nodes/classification"
    model_sources = {
        name: (classifier_root / name).read_text(encoding="utf-8")
        for name in ("knn_nodes.py", "plsda_nodes.py", "simca_nodes.py")
    }
    executor_source = (root / "src/spectra_sherpa/app/services/dag/fold_graph_executor.py").read_text(encoding="utf-8")
    binding_source = (root / "src/spectra_sherpa/app/services/dag/supervision_binding.py").read_text(encoding="utf-8")
    for model_source in model_sources.values():
        assert "StratifiedKFold" not in model_source
        assert "cross_val_predict" not in model_source
        assert "cv_folds" not in model_source
    assert "PLSRegression" not in model_sources["plsda_nodes.py"]
    for forbidden in ("_plsda_scientific_core", "PLSDANode", "PLSRegression"):
        assert forbidden not in executor_source
        assert forbidden not in binding_source


@pytest.mark.parametrize(
    "source",
    [
        "from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import _native_plsda_fit\n",
        "from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import PLSDANode as Model\n",
        (
            "import spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes as model\n"
            "fit = model._native_plsda_fit\n"
        ),
        "from sklearn.cross_decomposition import PLSRegression\n",
        "def run(node, data, target):\n    return node.fit_fitted_state(data, target)\n",
        "def run(node, data):\n    return getattr(node, 'predict_fitted_classification')(data)\n",
    ],
)
def test_phase7_ast_gate_rejects_new_direct_or_aliased_authority(
    tmp_path: Path,
    source: str,
) -> None:
    gate_path = Path(__file__).resolve().parents[1] / "tools" / "check_plsda_execution_path.py"
    spec = importlib.util.spec_from_file_location("check_plsda_execution_path", gate_path)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    path = tmp_path / "tools" / "avatar_omnic_phase7_attack.py"
    path.parent.mkdir()
    path.write_text(source, encoding="utf-8")
    assert gate.scan_python_path(path, root=tmp_path)


def test_phase7_ast_gate_accepts_the_current_repository() -> None:
    gate_path = Path(__file__).resolve().parents[1] / "tools" / "check_plsda_execution_path.py"
    spec = importlib.util.spec_from_file_location("check_plsda_execution_path", gate_path)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    assert gate.scan_repository() == []


def test_phase8_bridge_gate_rejects_manual_state_mapping(
    tmp_path: Path,
) -> None:
    package_root = Path(__file__).resolve().parents[1]
    gate_path = package_root / "tools" / "check_plsda_execution_path.py"
    spec = importlib.util.spec_from_file_location("check_plsda_execution_path", gate_path)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    relative = Path("packages/spectra-sherpa/src/spectra_sherpa/app/services/canonical_model_bridge.py")
    source = (package_root / "src/spectra_sherpa/app/services/canonical_model_bridge.py").read_text(encoding="utf-8")
    assert "native_metadata, native_arrays = native.to_artifact()" in source
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        source.replace(
            "native_metadata, native_arrays = native.to_artifact()", "native_metadata, native_arrays = {}, {}", 1
        ),
        encoding="utf-8",
    )
    violations = gate.scan_python_path(path, root=tmp_path)
    assert any(
        "bridge conversion inventory entry is stale or missing native.to_artifact" in item for item in violations
    )


def test_phase8_bridge_gate_rejects_a_second_or_direct_bridge(
    tmp_path: Path,
) -> None:
    gate_path = Path(__file__).resolve().parents[1] / "tools" / "check_plsda_execution_path.py"
    spec = importlib.util.spec_from_file_location("check_plsda_execution_path", gate_path)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    path = tmp_path / "packages/spectra-sherpa/src/spectra_sherpa/app/services/second_bridge.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import SherpaPLSDAArtifact\n"
        "def bridge(state):\n"
        "    return SherpaPLSDAArtifact(state, state, state, state, state, state, state)\n",
        encoding="utf-8",
    )
    violations = gate.scan_python_path(path, root=tmp_path)
    assert any("forbidden PLS-DA authority reference SherpaPLSDAArtifact" in item for item in violations)


def test_phase8_bridge_gate_rejects_a_second_bridge_in_an_allowlisted_consumer(
    tmp_path: Path,
) -> None:
    package_root = Path(__file__).resolve().parents[1]
    gate_path = package_root / "tools" / "check_plsda_execution_path.py"
    spec = importlib.util.spec_from_file_location("check_plsda_execution_path", gate_path)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    relative = Path("packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_state.py")
    source = (package_root / "src/spectra_sherpa/app/services/dag/nodes/classification/plsda_state.py").read_text(
        encoding="utf-8"
    )
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        source + "\n\ndef second_bridge(state):\n" + "    return SherpaPLSDAArtifact.from_fitted_state(state)\n",
        encoding="utf-8",
    )
    violations = gate.scan_python_path(path, root=tmp_path)
    assert any("bridge conversion is outside the closed inventory" in item for item in violations)


@pytest.mark.parametrize(
    ("old", "new", "expected_message"),
    [
        (
            'fit = getattr(node, "fit_fitted_state", None)',
            'fit = getattr(node, "fit_fitted_state", None); rogue = other.fit_fitted_state',
            "outside the closed inventory",
        ),
        (
            'fit = getattr(node, "fit_fitted_state", None)',
            'fit = getattr(node, "unrelated_fit", None)',
            "inventory entry is stale or missing",
        ),
    ],
)
def test_phase7_ast_gate_enforces_bidirectional_occurrence_inventory(
    tmp_path: Path,
    old: str,
    new: str,
    expected_message: str,
) -> None:
    package_root = Path(__file__).resolve().parents[1]
    gate_path = package_root / "tools" / "check_plsda_execution_path.py"
    spec = importlib.util.spec_from_file_location("check_plsda_execution_path", gate_path)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    relative = Path("packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/fold_graph_executor.py")
    source = (package_root / "src/spectra_sherpa/app/services/dag/fold_graph_executor.py").read_text(encoding="utf-8")
    assert old in source
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    violations = gate.scan_python_path(path, root=tmp_path)
    assert any(expected_message in item for item in violations)


@pytest.mark.parametrize(
    "operation_expression",
    ["'classification.plsda'", "'.'.join(('classification', 'plsda'))"],
)
def test_phase7_ast_gate_rejects_server_constructed_plsda_lifecycle(
    tmp_path: Path,
    operation_expression: str,
) -> None:
    gate_path = Path(__file__).resolve().parents[1] / "tools" / "check_plsda_execution_path.py"
    spec = importlib.util.spec_from_file_location("check_plsda_execution_path", gate_path)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    path = tmp_path / "packages" / "spectra-server" / "src" / "attack.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "def run(registry, data, y):\n"
        f"    node = registry.create_node({operation_expression}, 'attack', {{}})\n"
        "    state = getattr(node, 'fit_fitted_state')(data, y)\n"
        "    return getattr(node, 'predict_fitted_labels')(data, state)\n",
        encoding="utf-8",
    )
    violations = gate.scan_python_path(path, root=tmp_path)
    assert any("fit_fitted_state" in item for item in violations)
    assert any("predict_fitted_labels" in item for item in violations)


@pytest.mark.parametrize(
    "source",
    [
        (
            "def run(node, data, y):\n"
            "    state = node.fit_fitted_state(data, y)\n"
            "    return node.predict_fitted_labels(data, state)\n"
        ),
        (
            "def run(registry, data, y):\n"
            "    cls = registry._node_classes['classification.plsda']\n"
            "    node = cls('attack', {})\n"
            "    state = node.fit_fitted_state(data, y)\n"
            "    return node.predict_fitted_labels(data, state)\n"
        ),
        (
            "def run(node, data, y, should_fit):\n"
            "    method = 'fit_fitted_state' if should_fit else 'apply_fitted_state'\n"
            "    return getattr(node, method)(data, y)\n"
        ),
        (
            "def run(node, data, y):\n"
            "    method = ''.join(('fit', '_fitted_state'))\n"
            "    return getattr(node, method)(data, y)\n"
        ),
    ],
)
def test_phase7_ast_gate_rejects_sherpa_production_lifecycle_calls(
    tmp_path: Path,
    source: str,
) -> None:
    gate_path = Path(__file__).resolve().parents[1] / "tools" / "check_plsda_execution_path.py"
    spec = importlib.util.spec_from_file_location("check_plsda_execution_path", gate_path)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    path = tmp_path / "packages" / "spectra-sherpa" / "src" / "spectra_sherpa" / "app" / "services" / "attack.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    violations = gate.scan_python_path(path, root=tmp_path)
    expected_methods = {
        method
        for method in (
            "fit_fitted_state",
            "apply_fitted_state",
            "predict_fitted_labels",
            "predict_fitted_classification",
        )
        if method in source
    }
    assert violations
    if expected_methods:
        for method in expected_methods:
            assert any(method in item for item in violations)
    else:
        assert any("fit_fitted_state" in item for item in violations)


def test_public_plsda_starter_migrates_to_explicit_held_out_evaluation() -> None:
    template = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "spectra_sherpa"
        / "data"
        / "templates"
        / "classification_plsda.yaml"
    ).read_text(encoding="utf-8")
    assert "node_type: data.train_test_split" in template
    assert "split_method: stratified" in template
    assert "node_type: diagnostics.classification_evaluator" in template
    assert "cv_folds" not in template
