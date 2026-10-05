"""C2k canonical out-of-fold evaluation scientific and contract proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.services.dag import out_of_fold_evidence
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodePolicy,
    NodeResult,
    PortMetadata,
    node_registry,
)
from spectra_sherpa.app.services.dag.nodes.diagnostics import (
    CrossValidationNode,
    _canonical_cross_validation_parameters,
    _cross_validation_execute,
    verify_cross_validation_report,
)
from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import NestedCVNode
from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow
from spectra_sherpa.app.types import ensure_type_registry_loaded, type_registry
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _regression_vectors() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    observed = np.array([1.0, 2.0, 2.5, 4.0, 5.0, 7.0])
    predicted = np.array([1.2, 1.8, 2.7, 3.8, 5.4, 6.6])
    folds = np.array([0, 1, 2, 0, 1, 2], dtype=np.int64)
    return observed, predicted, folds


def _bound_evidence(
    observed: np.ndarray,
    predicted: np.ndarray,
    assignments: np.ndarray,
    *,
    task_type: str = "regression",
) -> dict[str, object]:
    indices = np.arange(observed.shape[0], dtype=np.int64)
    split_plan = {
        "schema_version": "spectra-split-plan/1",
        "method": "kfold",
        "n_samples": int(observed.shape[0]),
        "grouped": False,
        "folds": [
            {
                "train": indices[assignments != fold].tolist(),
                "test": indices[assignments == fold].tolist(),
            }
            for fold in np.unique(assignments)
        ],
    }
    return out_of_fold_evidence.build_out_of_fold_evidence(
        producer_node_id="nested",
        task_type=task_type,
        observations=observed,
        predictions=predicted,
        split_plan=split_plan,
    )


def test_cross_validation_has_one_exact_local_evaluator_contract() -> None:
    metadata = node_registry.get_metadata("diagnostics.cross_validation")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "diagnostics.cross_validation"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.EVALUATOR.value
    assert contract.payload["implementation_id"] == "spectrasherpa.diagnostics.cross_validation"
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["deterministic"] is True
    assert contract.payload["target_access"] == "required"
    assert any("mdatools" in citation for citation in contract.payload["citations"])
    assert metadata.input_types == ["dict"]
    assert metadata.parameters == []
    assert _canonical_cross_validation_parameters({}) == {"task_type": "regression"}
    assert [port.name for port in metadata.input_ports] == ["evidence"]
    assert metadata.input_ports[0].type_ref == out_of_fold_evidence.OUT_OF_FOLD_EVIDENCE_TYPE
    assert [port.name for port in metadata.output_ports] == [
        "cv_metrics",
        "observations",
        "predictions",
        "fold_assignments",
        "plots",
    ]
    assert metadata.output_ports[2].type_ref == "spectrasherpa://types/Array1D/1.0"
    assert metadata.output_ports[3].type_ref == "spectrasherpa://types/Array1D/1.0"


def test_cross_validation_type_boundary_is_one_indivisible_record() -> None:
    ensure_type_registry_loaded()
    oof = out_of_fold_evidence.OUT_OF_FOLD_EVIDENCE_TYPE

    assert type_registry.is_compatible(oof, oof) == (True, "")
    assert type_registry.is_compatible("spectrasherpa://types/TargetMatrix/1.0", oof)[0] is False
    assert type_registry.is_compatible("spectrasherpa://types/Array1D/1.0", oof)[0] is False


def test_workflow_preflight_accepts_only_the_closed_nested_cv_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_type_registry_loaded()
    nested = WorkflowNode(node_id="nested", node_type="selection.nested_cv", parameters={})
    evaluator = WorkflowNode(
        node_id="evaluate",
        node_type="diagnostics.cross_validation",
        parameters={},
    )
    accepted = preflight_workflow(
        [nested, evaluator],
        [WorkflowEdge(from_node="nested", from_output="oof_evidence", to_node="evaluate", to_input="evidence")],
    )
    accepted_edges = {
        (edge.from_output, edge.to_input): edge.status
        for edge in accepted.edges
        if edge.from_node_id == "nested" and edge.to_node_id == "evaluate"
    }
    assert accepted_edges == {("oof_evidence", "evidence"): "typed_valid"}

    class NominalPluginProducer(Node):
        metadata = NodeMetadata(
            policy=NodePolicy(),
            node_type="test.nominal_oof",
            category="custom",
            label="Nominal OOF",
            description="Test-only nominal type claim",
            input_ports=[],
            output_ports=[PortMetadata("evidence", out_of_fold_evidence.OUT_OF_FOLD_EVIDENCE_TYPE)],
        )

        async def execute(self, **kwargs: object) -> NodeResult:
            del kwargs
            return NodeResult(outputs={"evidence": {}})

    original_get_metadata = node_registry.get_metadata
    monkeypatch.setattr(
        node_registry,
        "get_metadata",
        lambda node_type: (
            NominalPluginProducer.get_metadata()
            if node_type == "test.nominal_oof"
            else original_get_metadata(node_type)
        ),
    )
    impostor = WorkflowNode(node_id="impostor", node_type="test.nominal_oof", parameters={})
    rejected = preflight_workflow(
        [impostor, evaluator],
        [WorkflowEdge(from_node="impostor", from_output="evidence", to_node="evaluate", to_input="evidence")],
    )
    assert any(
        issue.code == "unauthorized_out_of_fold_evidence_producer"
        and issue.node_id == "evaluate"
        and issue.port == "evidence"
        for issue in rejected.issues
    )


@pytest.mark.parametrize(
    "parameters",
    [
        {"cv_folds": 5},
        {"cv_method": "auto"},
        {"task_type": "regression"},
        {"task_type": "unknown"},
        {"task_type": None},
    ],
)
def test_cross_validation_parameters_are_closed(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _canonical_cross_validation_parameters(parameters)


def test_regression_metrics_match_independent_out_of_fold_oracle() -> None:
    observed, predicted, folds = _regression_vectors()
    evidence = _bound_evidence(observed, predicted, folds)
    outputs, diagnostics = _cross_validation_execute(
        evidence,
        node_id="cv",
        parameters={},
    )
    metrics = outputs["cv_metrics"]
    residuals = predicted - observed
    press = float(np.sum(residuals**2))
    rmse = float(np.sqrt(np.mean(residuals**2)))
    bias = float(np.mean(residuals))

    assert metrics["scope"] == "producer_bound_out_of_fold_evidence_not_model_refitting"
    assert metrics["n_folds"] == 3
    assert metrics["overall_metrics"]["PRESS"] == pytest.approx(press)
    assert metrics["overall_metrics"]["rmsecv"] == pytest.approx(rmse)
    assert metrics["overall_metrics"]["bias"] == pytest.approx(bias)
    assert metrics["overall_metrics"]["registry_version"] == "2"
    assert metrics["overall_metrics"]["slope"] is not None
    assert metrics["overall_metrics"]["intercept"] is not None
    assert metrics["overall_metrics"]["rer"] == pytest.approx(np.ptp(observed) / metrics["overall_metrics"]["sep"])
    assert metrics["schema_version"] == "spectrasherpa-cross-validation-evaluation/3"
    assert len(metrics["fold_metrics"]) == 3
    assert diagnostics["rmsecv"] == pytest.approx(rmse)
    assert verify_cross_validation_report(metrics, evidence) == metrics


def test_cross_validation_has_a_representative_absolute_performance_ceiling() -> None:
    observed = np.linspace(0.0, 100.0, 10_000, dtype=np.float64)
    predicted = observed + 0.1 * np.sin(observed)
    folds = np.arange(observed.size, dtype=np.int64) % 10
    evidence = _bound_evidence(observed, predicted, folds)

    with PerformanceCeiling(
        "diagnostics.cross_validation",
        "10000-observations-ten-fold-bound-evidence",
        5.0,
    ).measure():
        outputs, diagnostics = _cross_validation_execute(evidence, node_id="cv", parameters={})

    assert outputs["cv_metrics"]["n_folds"] == 10
    assert diagnostics["n_samples"] == 10_000


@pytest.mark.asyncio
async def test_registered_nested_cv_evidence_is_consumed_without_rebinding_its_parts() -> None:
    rng = np.random.default_rng(712)
    matrix = rng.normal(size=(24, 8))
    observed = matrix @ np.linspace(0.2, 1.1, 8) + rng.normal(scale=0.05, size=24)
    producer = NestedCVNode(
        "nested",
        {"selection_method": "none", "n_components": 3, "cv_folds": 4, "random_seed": 42},
    )
    produced = await producer.execute(X=matrix, y=observed)
    evaluator = CrossValidationNode("evaluate", {})

    evaluated = await evaluator.execute(evidence=produced.outputs["oof_evidence"])

    assert evaluated.outputs["cv_metrics"]["evidence_sha256"] == produced.outputs["oof_evidence"]["evidence_sha256"]
    assert evaluated.outputs["cv_metrics"]["split_plan_digest"] == produced.outputs["cv_metrics"]["split_plan_digest"]
    assert evaluated.outputs["cv_metrics"]["overall_metrics"]["rmsecv"] == pytest.approx(
        produced.outputs["cv_metrics"]["rmsecv"]
    )


def test_leave_one_out_folds_do_not_invent_fold_local_r2_or_sep() -> None:
    observed = np.array([1.0, 2.0, 4.0])
    predicted = np.array([1.1, 1.8, 4.2])
    folds = np.array([0, 1, 2], dtype=np.int64)
    evidence = _bound_evidence(observed, predicted, folds)

    outputs, _ = _cross_validation_execute(
        evidence,
        node_id="loocv",
        parameters={},
    )

    for fold in outputs["cv_metrics"]["fold_metrics"]:
        assert fold["r2_cv"] is None
        assert fold["q2"] is None
        assert fold["r2_q2_status"] == "undefined_zero_reference_variance"
        assert fold["sep"] is None
        assert fold["sep_status"] == "undefined_single_sample"


def test_classification_evidence_is_rejected_until_a_canonical_producer_exists() -> None:
    observed = np.array(["a", "b", "a", "b", "a", "b"])
    predicted = np.array(["a", "b", "b", "b", "a", "a"])
    folds = np.array([0, 0, 1, 1, 2, 2], dtype=np.int64)
    with pytest.raises(ValueError, match="supports regression only"):
        _bound_evidence(observed, predicted, folds, task_type="classification")


def test_cross_validation_rejects_fold_assignments_that_differ_from_the_split_plan() -> None:
    observed, predicted, folds = _regression_vectors()
    evidence = _bound_evidence(observed, predicted, folds)
    evidence["fold_assignments"][0] = 2

    with pytest.raises(ValueError, match="do not match the bound split_plan"):
        _cross_validation_execute(evidence, node_id="cv", parameters={})


@pytest.mark.parametrize("field", ["observations", "predictions"])
def test_cross_validation_rejects_vectors_mixed_from_another_execution(field: str) -> None:
    observed, predicted, folds = _regression_vectors()
    evidence = _bound_evidence(observed, predicted, folds)
    evidence[field][0] = float(evidence[field][0]) + 10.0

    with pytest.raises(ValueError, match="evidence digest"):
        _cross_validation_execute(evidence, node_id="cv", parameters={})


def test_cross_validation_rejects_a_changed_split_plan_or_producer_contract() -> None:
    observed, predicted, folds = _regression_vectors()
    evidence = _bound_evidence(observed, predicted, folds)
    changed_split = copy.deepcopy(evidence)
    changed_split["split_plan_digest"] = "0" * 64
    with pytest.raises(ValueError, match="split_plan digest"):
        _cross_validation_execute(changed_split, node_id="cv", parameters={})

    changed_producer = copy.deepcopy(evidence)
    changed_producer["producer"]["execution_contract_digest"] = "0" * 64
    with pytest.raises(ValueError, match="current canonical contract"):
        _cross_validation_execute(changed_producer, node_id="cv", parameters={})


def test_report_verifier_recomputes_metrics_and_rejects_tampering() -> None:
    observed, predicted, folds = _regression_vectors()
    evidence = _bound_evidence(observed, predicted, folds)
    outputs, _ = _cross_validation_execute(
        evidence,
        node_id="cv",
        parameters={},
    )
    tampered = copy.deepcopy(outputs["cv_metrics"])
    tampered["overall_metrics"]["rmsecv"] = 0.0

    with pytest.raises(ValueError, match="recomputed metrics"):
        verify_cross_validation_report(tampered, evidence)


@pytest.mark.asyncio
async def test_live_and_generated_paths_share_the_same_implementation() -> None:
    observed, predicted, folds = _regression_vectors()
    evidence = _bound_evidence(observed, predicted, folds)
    node = CrossValidationNode("cv", {})
    live = await node.execute(evidence=evidence)

    lines = node.generate_python({"evidence": "evidence"}, indent="")
    namespace = {"evidence": evidence, "results": {}}
    exec("\n".join(lines), namespace)

    assert namespace["results"]["cv"] == live.outputs


@pytest.mark.asyncio
async def test_inputs_are_not_mutated_and_output_is_deterministic() -> None:
    observed, predicted, folds = _regression_vectors()
    evidence = _bound_evidence(observed, predicted, folds)
    original = copy.deepcopy(evidence)
    node = CrossValidationNode("cv", {})

    first = await node.execute(evidence=evidence)
    second = await node.execute(evidence=evidence)

    assert first.outputs == second.outputs
    assert evidence == original
