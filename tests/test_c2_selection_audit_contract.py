"""C2k canonical selection-provenance audit proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.selection.selection_audit_node import (
    SelectionAuditNode,
    _canonical_audit_parameters,
    verify_selection_audit_report,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset() -> SherpaDataset:
    return SherpaDataset(
        X=np.arange(48, dtype=np.float64).reshape(6, 8),
        feature_axis=SpectralAxis(
            values=np.linspace(900.0, 1600.0, 8),
            labels=[f"band-{index}" for index in range(8)],
            units="cm-1",
        ),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(6)]),
    )


def _record_selection(dataset: SherpaDataset) -> None:
    add_processing_step(
        dataset,
        "selection.cars",
        {"n_iterations": 50, "n_components": 3, "seed": 42},
        node_id="cars",
        input_shape=(6, 8),
        impact={
            "schema_version": "spectrasherpa.selection.cars.impact/1",
            "n_selected": 4,
        },
    )


def test_selection_audit_has_one_exact_local_contract() -> None:
    metadata = node_registry.get_metadata("selection.audit")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "selection.audit"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["implementation_id"] == "spectrasherpa.selection.audit"
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["deterministic"] is True
    assert contract.payload["target_access"] == "none"
    assert contract.payload["feature_effect"] == "preserves_features"


@pytest.mark.parametrize(
    "parameters",
    [
        {"other": True},
        {"include_scores": 1},
        {"include_scores": "yes"},
        {"include_scores": None},
    ],
)
def test_selection_audit_parameters_are_closed(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _canonical_audit_parameters(parameters)


@pytest.mark.asyncio
async def test_audit_records_exact_bounded_selection_history_without_timestamps() -> None:
    dataset = _dataset()
    _record_selection(dataset)
    add_processing_step(dataset, "preprocess.scale", {"method": "autoscale"}, node_id="scale")

    result = await SelectionAuditNode("audit", {"include_scores": True}).execute(X=dataset)
    report = result.outputs["audit"]

    assert result.outputs["X_out"] is dataset
    assert report["schema_version"] == "spectrasherpa.selection.audit.report/1"
    assert report["scope"] == "recorded_provenance_not_independent_scientific_verification"
    assert report["n_selection_steps"] == 1
    assert report["total_provenance_steps"] == 2
    assert report["methods_applied"] == ["selection.cars"]
    assert report["selection_steps"][0]["source_ordinal"] == 0
    assert report["selection_steps"][0]["parameters"] == {
        "n_components": 3,
        "n_iterations": 50,
        "seed": 42,
    }
    assert "timestamp" not in report["selection_steps"][0]
    assert len(report["selection_steps"][0]["parameters_sha256"]) == 64
    assert len(report["selection_steps"][0]["step_sha256"]) == 64
    assert verify_selection_audit_report(report) == report


@pytest.mark.asyncio
async def test_audit_is_deterministic_across_source_timestamps() -> None:
    first = _dataset()
    second = _dataset()
    _record_selection(first)
    _record_selection(second)

    first_report = (await SelectionAuditNode("audit", {}).execute(X=first)).outputs["audit"]
    second_report = (await SelectionAuditNode("audit", {}).execute(X=second)).outputs["audit"]

    assert first_report == second_report


@pytest.mark.asyncio
async def test_audit_scores_are_explicitly_included_or_digest_only() -> None:
    dataset = _dataset()
    axis = dataset.feature_axis
    axis.selection_method = "cars"
    axis.selection_scores = np.linspace(0.1, 0.8, 8)
    dataset.feature_axis = axis

    included = (await SelectionAuditNode("audit", {"include_scores": True}).execute(X=dataset)).outputs["audit"][
        "feature_axis"
    ]
    digest_only = (await SelectionAuditNode("audit", {"include_scores": False}).execute(X=dataset)).outputs["audit"][
        "feature_axis"
    ]

    assert included["selection_scores"] == pytest.approx(np.linspace(0.1, 0.8, 8).tolist())
    assert digest_only["selection_scores"] is None
    assert included["selection_scores_sha256"] == digest_only["selection_scores_sha256"]
    assert len(included["selection_scores_sha256"]) == 64


@pytest.mark.asyncio
async def test_audit_rejects_unknown_selection_identity_and_nonfinite_data() -> None:
    unknown = _dataset()
    add_processing_step(unknown, "selection.unreviewed", {"alpha": 1.0}, node_id="unknown")
    with pytest.raises(ValueError, match="unknown operation"):
        await SelectionAuditNode("audit", {}).execute(X=unknown)

    nonfinite = _dataset()
    nonfinite.X[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite X"):
        await SelectionAuditNode("audit", {}).execute(X=nonfinite)


@pytest.mark.asyncio
async def test_audit_verifier_rejects_tampering() -> None:
    dataset = _dataset()
    _record_selection(dataset)
    report = (await SelectionAuditNode("audit", {}).execute(X=dataset)).outputs["audit"]

    changed = copy.deepcopy(report)
    changed["selection_steps"][0]["parameters"]["n_iterations"] = 51
    with pytest.raises(ValueError, match="parameter digest mismatch|step digest mismatch"):
        verify_selection_audit_report(changed)

    extra = copy.deepcopy(report)
    extra["verified"] = True
    with pytest.raises(ValueError, match="field set"):
        verify_selection_audit_report(extra)

    axis_tamper = copy.deepcopy(report)
    axis_tamper["feature_axis"]["values"][0] += 1.0
    with pytest.raises(ValueError, match="feature_axis.values digest mismatch"):
        verify_selection_audit_report(axis_tamper)

    axis_extra = copy.deepcopy(report)
    axis_extra["feature_axis"]["verified"] = True
    with pytest.raises(ValueError, match="feature-axis field set"):
        verify_selection_audit_report(axis_extra)

    axis_short = copy.deepcopy(report)
    axis_short["feature_axis"]["values"] = axis_short["feature_axis"]["values"][:-1]
    with pytest.raises(ValueError, match="feature-axis values are invalid"):
        verify_selection_audit_report(axis_short)


@pytest.mark.asyncio
async def test_audit_live_and_generated_python_share_one_operation() -> None:
    dataset = _dataset()
    _record_selection(dataset)
    node = SelectionAuditNode("audit", {"include_scores": False})
    live = await node.execute(X=dataset)
    namespace = {"dataset": dataset, "results": {}}
    exec(  # noqa: S102
        "\n".join(node.generate_python({"X": "dataset"}, indent="")),
        namespace,
    )
    generated = namespace["results"]["audit"]

    assert generated["audit"] == live.outputs["audit"]
    assert generated["X_out"] is dataset


@pytest.mark.asyncio
async def test_selection_audit_has_a_representative_absolute_performance_ceiling() -> None:
    rng = np.random.default_rng(505)
    matrix = rng.normal(size=(200, 1_600))
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.linspace(400.0, 4_000.0, matrix.shape[1]), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
    )
    add_processing_step(
        dataset,
        "selection.cars",
        {"n_iterations": 100, "n_components": 5, "seed": 42},
        node_id="cars",
        input_shape=matrix.shape,
        impact={"schema_version": "spectrasherpa.selection.cars.impact/1", "n_selected": 320},
    )

    with PerformanceCeiling("selection.audit", "200x1600-one-bounded-selection-step", 5.0).measure():
        result = await SelectionAuditNode("audit", {"include_scores": False}).execute(X=dataset)

    assert result.outputs["audit"]["n_selection_steps"] == 1
