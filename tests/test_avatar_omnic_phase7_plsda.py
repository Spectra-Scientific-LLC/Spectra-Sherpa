"""Systemic and evidence-boundary tests for the Phase 7B collector."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.classification  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.classification_evaluator_node  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.selection  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    execute_candidate_validation_with_private_classification_trace,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import attach_target_dataset
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.supervision_binding import bind_sample_table_supervision
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import ensure_type_registry_loaded
from spectra_sherpa.sdk.validate import make_leave_one_group_out_classification_plan


def _tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "avatar_omnic_phase7_plsda.py"
    spec = importlib.util.spec_from_file_location("avatar_phase7_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dataset() -> SherpaDataset:
    rng = np.random.default_rng(20260824)
    axis = np.linspace(4000.0, 400.0, 40)
    specimens = ["A", "B", "C", "D"] * 3
    blocks = [1] * 4 + [2] * 4 + [3] * 4
    labels = [f"{specimen}__B{block}" for specimen, block in zip(specimens, blocks, strict=True)]
    X = np.vstack([rng.normal(loc=float(index % 4), scale=0.05, size=axis.size) for index in range(len(labels))])
    return SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(values=axis, units="cm-1", title="Wavenumber"),
        sample_axis=SampleAxis(
            labels=labels,
            sample_table={"sample_id": labels, "specimen_id": specimens, "block": blocks},
        ),
        units="absorbance",
        data_role="X_spectra",
        extra={
            "source_collection": {
                "manifest_digest": "a" * 64,
                "collection_definition_sha256": "b" * 64,
                "scientific_collection_sha256": "c" * 64,
            }
        },
    )


@pytest.mark.asyncio
async def test_interval_selection_runs_inside_the_generic_held_group_graph() -> None:
    ensure_type_registry_loaded()
    attached = attach_target_dataset(
        _dataset(),
        None,
        target_type="categorical",
        node_id="attach",
        target_source="sample_table_column",
        target_column="specimen_id",
        group_column="block",
    )
    binding = bind_sample_table_supervision(
        attached, target_column="specimen_id", target_type="categorical", group_column="block"
    )
    plan = make_leave_one_group_out_classification_plan(
        binding.target, binding.groups, require_one_per_class_group=True
    )
    capability = SpectralDatasetCapability.from_dataset(
        attached,
        custody_id="phase7-selection-systemic",
        dataset_ref_digest=binding.digest,
        split_plan_digest=plan.digest,
        groups=binding.groups,
    )
    original_metadata = capability.to_wire()["metadata"]
    reconstructed_capability = SpectralDatasetCapability(
        arrays=capability.arrays,
        metadata=original_metadata,
    )
    assert reconstructed_capability.content_digest == capability.content_digest
    assert reconstructed_capability.envelope_digest == capability.envelope_digest
    graph = admit_validation_graph(
        [
            WorkflowNode(
                "window",
                "selection.variable_select",
                {"method": "interval", "region_start": 3100.0, "region_end": 650.0},
            ),
            WorkflowNode("model", "classification.plsda", {"n_components": 2, "scale": False}),
            WorkflowNode("score", "diagnostics.classification_evaluator", {}),
        ],
        [
            WorkflowEdge("window", "model"),
            WorkflowEdge("model", "score", from_output="predictions", to_input="default"),
        ],
    )
    validation, trace = await execute_candidate_validation_with_private_classification_trace(graph, capability, plan)
    refit = await execute_selected_candidate_full_refit(graph, capability, validation)

    assert validation.metrics.n_samples == 12
    assert [fold.metrics.n_samples for fold in validation.folds] == [4, 4, 4]
    assert sorted(index for fold in trace.folds for index in fold.test_indices) == list(range(12))
    assert [node.operation_id for node in graph.nodes] == [
        "selection.variable_select",
        "classification.plsda",
        "diagnostics.classification_evaluator",
    ]
    assert refit.validation_execution_digest == validation.digest


def _nominal_public_report(module) -> dict:
    return {
        "schema_version": module.SCHEMA_VERSION,
        "dataset_id": "avatar-essential-oils/1",
        "dataset_version": 1,
        "status": "phase7_exact_closed_set_plsda_pipeline_and_phase8_custody_complete_author_operated",
        "observed_at": "2026-08-25",
        "runtime_implementation_commit": "d" * 40,
        "source_and_supervision": {"exact": True},
        "workflow_and_split": {
            "held_out_blocks": [1, 2, 3],
            "fold_count": 3,
            "training_count_per_fold": 22,
            "test_count_per_fold": 11,
            "all_rows_scored_once": True,
        },
        "validation": {
            "n_samples": 33,
            "validation_execution_sha256": "e" * 64,
            "aggregate_metrics": {
                "accuracy": 0.8,
                "balanced_accuracy": 0.75,
                "macro_f1": 0.7,
                "per_class_recall": {"A": 1.0, "B": 0.5},
            },
            "pooled_metrics": {
                "accuracy": 0.8,
                "balanced_accuracy": 0.75,
                "macro_f1": 0.7,
                "per_class_recall": {"A": 1.0, "B": 0.5},
            },
        },
        "full_refit": {
            "validation_execution_sha256": "e" * 64,
            "performance_estimate_attached_to_refit": False,
            "original_capability_metadata_retained_private": True,
            "original_capability_metadata_sha256": "a" * 64,
        },
        "privacy_boundary": {"private_arrays_published": False},
        "claim_boundary": "exact-corpus only",
        "nonclaims": ["authenticity", "physical_action_2"],
        "private_evidence_authority": {
            "private_report_size_bytes": 123,
            "private_report_sha256": "f" * 64,
            "private_report_published": False,
        },
    }


@pytest.mark.parametrize(
    ("section", "mutation"),
    [
        ("source_and_supervision", lambda value: value.update(exact=False)),
        ("workflow_and_split", lambda value: value.update(held_out_blocks=[1, 3, 2])),
        ("validation", lambda value: value.update(n_samples=32)),
        ("validation", lambda value: value["aggregate_metrics"].update(accuracy=0.9)),
        ("full_refit", lambda value: value.update(performance_estimate_attached_to_refit=True)),
        ("full_refit", lambda value: value.update(original_capability_metadata_retained_private=False)),
        ("full_refit", lambda value: value.update(original_capability_metadata_sha256="0" * 64)),
        ("private_evidence_authority", lambda value: value.update(private_report_published=True)),
    ],
)
def test_semantic_authorities_reject_refreshed_whole_file_mutations(section: str, mutation) -> None:
    module = _tool()
    report = _nominal_public_report(module)
    expected = {
        name: module._json_digest(projection) for name, projection in module._section_projections(report).items()
    }
    assert module._semantic_failures(report, expected) == []
    changed = deepcopy(report)
    mutation(changed[section])
    assert module._semantic_failures(changed, expected)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["aggregate_metrics"].pop("macro_f1"),
        lambda value: value["pooled_metrics"].pop("macro_f1"),
        lambda value: value["aggregate_metrics"].update(macro_f1=2.0),
        lambda value: value["aggregate_metrics"].update(per_class_recall={}),
    ],
)
def test_aggregate_metrics_remain_semantically_closed_after_section_digest_refresh(mutation) -> None:
    module = _tool()
    report = _nominal_public_report(module)
    mutation(report["validation"])
    if "macro_f1" not in report["validation"]["aggregate_metrics"]:
        report["validation"]["pooled_metrics"].pop("macro_f1", None)
    if "macro_f1" not in report["validation"]["pooled_metrics"]:
        report["validation"]["aggregate_metrics"].pop("macro_f1", None)
    expected = {
        name: module._json_digest(projection) for name, projection in module._section_projections(report).items()
    }
    assert module._semantic_failures(report, expected)


def test_private_writer_rejects_symlink_leaf_without_touching_target(tmp_path: Path) -> None:
    module = _tool()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    target = private / "target.json"
    target.write_text("unchanged", encoding="utf-8")
    link = private / "report.json"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="absent"):
        module._atomic_write(link, b"{}\n", private=True, limit=1024)
    assert target.read_text(encoding="utf-8") == "unchanged"


def test_split_payload_reproduces_the_plan_digest() -> None:
    module = _tool()
    plan = make_leave_one_group_out_classification_plan(
        np.asarray(["A", "B", "A", "B", "A", "B"]),
        np.asarray([1, 1, 2, 2, 3, 3]),
        require_one_per_class_group=True,
    )
    assert module._json_digest(module._split_plan_payload(plan)) == plan.digest
