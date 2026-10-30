"""End-to-end identity, units and per-record retention regression probes."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DatasetSourceIdentity, SherpaDataset, TargetContext
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.dag.nodes.labeled_regression_evaluator_node import evaluate_labeled_regression
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import evaluate_regression_v2
from spectra_sherpa.app.services.dag.population_authority import qualify_evaluation_result
from spectra_sherpa.app.services.scientific_comparison import compare_evidence, resolve_run_evidence


@pytest.fixture
def handoff_facts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        retention, "settings", replace(retention.settings, data_dir=tmp_path, run_output_retention_enabled=True)
    )
    facts = {}
    receipt = {
        "role": "held_out_test",
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }

    # 1. Actual typed joins versus optional context annotation.
    values = np.arange(4.0)
    axis = SampleAxis(labels=["ref-a", "ref-b", "ref-c", "ref-d"], sample_table={"sample_id": list("abcd")})
    context = SherpaDataset(
        X=np.ones((4, 2)),
        target=values,
        sample_axis=axis,
        target_context=TargetContext(target_type="continuous", target_names=["Y"], target_units="ppm"),
    )
    reference = SherpaDataset(X=values[:, None], sample_axis=axis.copy())
    mismatched = SherpaDataset(
        X=values[:, None],
        sample_axis=SampleAxis(sample_table={"sample_id": list("bacd")}),
    )
    strict_refusal = False
    try:
        evaluate_regression_v2(mismatched, reference)
    except ValueError:
        strict_refusal = True
    labeled_refusal = False
    labeled_rmse = None
    try:
        result = evaluate_labeled_regression(mismatched, reference, sample_context=context)
        labeled_rmse = result.outputs["default"]["rmse"]
    except ValueError:
        labeled_refusal = True
    legacy_prediction = SherpaDataset(
        X=values[:, None],
        sample_axis=axis.copy(),
        source_identity=DatasetSourceIdentity(source_format="eigenvector-dso"),
    )
    legacy_result = evaluate_labeled_regression(legacy_prediction, reference, sample_context=context)
    qualify_evaluation_result(legacy_result, receipt, source_results={"split": {"X_test": context}})
    legacy_metadata = legacy_result.outputs["comparison"]["metadata"]
    duplicates = SherpaDataset(
        X=np.ones((4, 2)),
        target=values,
        sample_axis=SampleAxis(labels=["repeat"] * 4, sample_table={"sample_id": ["repeat"] * 4}),
        target_context=TargetContext(target_type="continuous", target_names=["Y"]),
    )
    duplicate_result = evaluate_labeled_regression(values + 0.1, values, sample_context=duplicates)
    qualify_evaluation_result(duplicate_result, receipt, source_results={"split": {"X_test": duplicates}})
    duplicate_metadata = duplicate_result.outputs["comparison"]["metadata"]
    facts["labeled"] = {
        "canonical_mismatch_refused": strict_refusal,
        "labeled_mismatch_refused": labeled_refusal,
        "labeled_mismatch_rmse": labeled_rmse,
        "legacy_prediction_identity_after_graph": legacy_metadata.get("sample_identity"),
        "legacy_prediction_refusal_after_graph": legacy_metadata.get("sample_identity_unavailable"),
        "duplicate_optional_context_rmse": duplicate_result.outputs["default"]["rmse"],
        "duplicate_optional_context_identity": duplicate_metadata.get("sample_identity"),
    }
    assert strict_refusal
    assert abs(duplicate_result.outputs["default"]["rmse"] - 0.1) < 1e-10
    assert duplicate_metadata["sample_identity"] == "unavailable"

    # 2/3. Real fitted PLS with a separate response dataset, then real retention.
    rng = np.random.default_rng(91)
    x = rng.normal(size=(20, 5))
    y = x[:, 0] + 0.1 * x[:, 1]
    axis = SampleAxis(
        labels=[f"sample{i}" for i in range(20)],
        sample_table={"sample_id": [f"id{i}" for i in range(20)]},
    )
    source = SherpaDataset(
        X=x,
        sample_axis=axis,
        feature_axis=SpectralAxis(values=np.arange(5) + 600, units="nm"),
        extra={"source_collection": {"source_manifest_sha256": "a" * 64}},
    )
    definition = {
        "schema_version": 1,
        "nodes": [{"node_id": "pls", "node_type": "model.fitted_pls"}],
        "edges": [
            {"from_node_id": "source", "from_output": "default", "to_node_id": "pls", "to_input": "default"},
            {"from_node_id": "target", "from_output": "default", "to_node_id": "pls", "to_input": "y"},
        ],
    }

    def retain_run(name, outputs, diagnostics):
        evidence = retention.retain_run_outputs(
            1,
            {**outputs, "__workflow__": {"definition": definition}},
            diagnostics,
        )
        return SimpleNamespace(
            id=name,
            user_id=1,
            name=name,
            diagnostics=diagnostics,
            source_metadata={},
            evidence_completeness=evidence,
        )

    cases = {}
    for name, units, origin in (
        ("generic_ppm", "ppm", None),
        ("legacy_ppm", "ppm", "eigenvector-dso"),
        ("generic_percent", "%", None),
    ):
        target = SherpaDataset(
            X=y[:, None],
            sample_axis=axis.copy(),
            units=units,
            source_identity=DatasetSourceIdentity(source_format=origin) if origin else None,
        )
        result = asyncio.run(FittedPLSV2Node("pls", {"n_components": 2}).execute(source, y=target))
        outputs = {"source": {"default": source}, "target": {"default": target}, "pls": result.outputs}
        run = retain_run(name, outputs, result.diagnostics)
        resolved = resolve_run_evidence(run)
        cases[name] = (result, resolved, outputs)

    def calibration_pair(left, right):
        return next(
            section.state
            for section in compare_evidence([left, right]).pairs[0].sections
            if section.role == "calibration"
        )

    facts["external_y"] = {}
    for name, (result, resolved, _) in cases.items():
        metadata = result.outputs["calibration_comparison"]["metadata"]
        facts["external_y"][name] = {
            "fitted_response_units": result.diagnostics["response_identity"]["units"],
            "calibration_identity": metadata.get("sample_identity"),
            "calibration_refusal": metadata.get("sample_identity_unavailable"),
            "retained_evaluations": len(resolved.evaluations),
            "retained_units": [item.units for item in resolved.evaluations],
        }
    origin_pair = calibration_pair(cases["generic_ppm"][1], cases["legacy_ppm"][1])
    unit_pair = calibration_pair(cases["generic_ppm"][1], cases["generic_percent"][1])
    facts["external_y"]["generic_vs_legacy_pair"] = origin_pair
    facts["external_y"]["ppm_vs_percent_pair"] = unit_pair

    # 4. A missing unrelated report must not erase a valid calibration record.
    # No mocking: remove exactly the throwaway file just created by retention.
    result, _, outputs = cases["generic_ppm"]
    run = retain_run(
        "unrelated-missing",
        {**outputs, "unrelated": {"default": {"report": "unrelated descriptive output"}}},
        result.diagnostics,
    )
    before = resolve_run_evidence(run)
    bad_digest = run.evidence_completeness["outputs"]["unrelated"]["default"]["sha256"]
    files = list((tmp_path).rglob(bad_digest + ".json"))
    assert len(files) == 1 and files[0].resolve().is_relative_to(tmp_path)
    files[0].unlink()
    after = resolve_run_evidence(run)
    facts["unrelated_missing_output"] = {
        "evaluations_before": len(before.evaluations),
        "evaluations_after": len(after.evaluations),
        "reason_after": after.unavailable_reason,
    }
    assert len(before.evaluations) == 1

    # 5. Inspect the real registered MCR implementation closure.
    from spectra_sherpa.app.services.dag.node_base import node_registry

    contract = node_registry.get_metadata("model.mcr_als").resolved_execution_contract()
    axis_bound = any(
        item["component_id"] == "spectra_sherpa.core.axis_semantics"
        for item in contract.payload["implementation_components"]
    )
    facts["mcr_axis_semantics_bound"] = axis_bound

    # Additional real-retention boundaries; only pytest-owned files are removed.
    import copy

    from spectra_sherpa.app.services.dag.nodes.data.split_planner import (
        materialize_split_outputs,
        plan_train_test_split,
    )

    array_source = source.copy()
    array_source.target = y + 50
    array_source.target_context = TargetContext(
        target_type="continuous", target_names=["unrelated"], target_units="ppm"
    )
    array_result = asyncio.run(FittedPLSV2Node("pls", {"n_components": 2}).execute(array_source, y=y))
    array_run = retain_run(
        "external-array",
        {"source": {"default": array_source}, "target": {"default": y}, "pls": array_result.outputs},
        array_result.diagnostics,
    )
    array_resolved = resolve_run_evidence(array_run)
    facts["external_array_with_unrelated_embedded_target"] = {
        "fitted_response_units": array_result.diagnostics["response_identity"]["units"],
        "retained_response_units": [e.units for e in array_resolved.evaluations],
    }
    base_definition = copy.deepcopy(definition)
    definition["nodes"].append({"node_id": "unused_split", "node_type": "data.train_test_split"})
    split_plan = plan_train_test_split(x, y, method="random")
    split_outputs = materialize_split_outputs(source, x, y, split_plan, node_id="unused_split")
    base_result, _, base_outputs = cases["generic_ppm"]
    split_run = retain_run(
        "unrelated-split-missing", {**base_outputs, "unused_split": split_outputs}, base_result.diagnostics
    )
    split_before = resolve_run_evidence(split_run)
    missing = split_run.evidence_completeness["outputs"]["unused_split"]["X_train"]["sha256"]
    stored = list((tmp_path).rglob(missing + ".json"))
    assert len(stored) == 1 and stored[0].resolve().is_relative_to(tmp_path)
    stored[0].unlink()
    split_after = resolve_run_evidence(split_run)
    facts["unrelated_split_missing_X_train"] = {
        "before": len(split_before.evaluations),
        "after": len(split_after.evaluations),
        "reason": split_after.unavailable_reason,
    }
    # Integrity failures remain distinct from an unreadable file. The unrelated
    # valid calibration survives, but the invalid split never yields a plan.
    import hashlib
    import json

    from spectra_sherpa.app.schemas.run_evidence import OutputEvidence
    from spectra_sherpa.app.services.run_validation_summary import _split_summaries

    original_wire = retention.read_output(
        1, OutputEvidence.model_validate(split_run.evidence_completeness["outputs"]["unused_split"]["X_test"])
    )
    facts["invalid_split"] = {}
    for failure in ("digest", "overlap"):
        wire = copy.deepcopy(original_wire)
        plan = next(p["parameters"] for p in wire["provenance"] if p["op_id"] == "data.train_test_split")
        if failure == "digest":
            plan["digest"] = "0" * 64
        else:
            plan["test_indices"][0] = plan["train_indices"][0]
            unsigned = {k: v for k, v in plan.items() if k not in {"split", "digest"}}
            plan["digest"] = hashlib.sha256(
                json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            ).hexdigest()
        bad = retain_run(failure, {**base_outputs, "unused_split": {"X_test": wire}}, base_result.diagnostics)
        errors = []
        assert _split_summaries(bad, definition, on_read_error=lambda *args: errors.append(args)) == []
        assert len(errors) == 1
        resolved = resolve_run_evidence(bad)
        facts["invalid_split"][failure] = {
            "evaluations": len(resolved.evaluations),
            "limitations": resolved.population.limitations,
        }

    definition.clear()
    definition.update(base_definition)
    capped = retain_run(
        "budget",
        {
            **base_outputs,
            "too_large": {"default": {"unused": True}},
            "after_limit": {"default": {"must_not_read": True}},
        },
        base_result.diagnostics,
    )
    # Oversized declared length must stop before opening this or any later file.
    capped.evidence_completeness["outputs"]["too_large"]["default"]["byte_count"] = 17 * 1024 * 1024
    from spectra_sherpa.app.services import run_validation_summary as summary_module

    opened = []
    original_read = summary_module.read_output

    def tracking_read(owner, item):
        opened.append(item.sha256)
        return original_read(owner, item)

    with monkeypatch.context() as patch:
        patch.setattr(summary_module, "read_output", tracking_read)
        resolved = resolve_run_evidence(capped)
    for name in ("too_large", "after_limit"):
        assert capped.evidence_completeness["outputs"][name]["default"]["sha256"] not in opened
    facts["budget_partial"] = {"evaluations": len(resolved.evaluations), "limitations": resolved.population.limitations}

    # A cap between two producers must not turn ambiguous evidence into a pair.
    definition["nodes"].append({"node_id": "second_pls", "node_type": "model.fitted_pls"})
    definition["edges"].extend([{**edge, "to_node_id": "second_pls"} for edge in base_definition["edges"]])
    both = retain_run(
        "ambiguous-producers",
        {**base_outputs, "too_large": {"default": {"unused": True}}, "second_pls": base_result.outputs},
        base_result.diagnostics,
    )
    complete = resolve_run_evidence(both)
    both.evidence_completeness["outputs"]["too_large"]["default"]["byte_count"] = 17 * 1024 * 1024
    partial = resolve_run_evidence(both)
    facts["partial_ambiguity"] = {
        "complete_count": len(complete.evaluations),
        "partial_count": len(partial.evaluations),
        "complete_state": calibration_pair(complete, complete),
        "partial_state": calibration_pair(partial, partial),
        "partial_metrics": next(
            section.metric_values
            for section in compare_evidence([partial, partial]).pairs[0].sections
            if section.role == "calibration"
        ),
        "incomplete_roles": partial.incomplete_roles,
    }
    return facts


def test_labeled_evaluator_preserves_strict_operand_identity(handoff_facts):
    facts = handoff_facts["labeled"]
    assert facts["canonical_mismatch_refused"]
    assert facts["labeled_mismatch_refused"]
    assert facts["legacy_prediction_refusal_after_graph"]
    assert facts["duplicate_optional_context_rmse"] == pytest.approx(0.1)
    assert facts["duplicate_optional_context_identity"] == "unavailable"


def test_external_response_origin_is_not_certified_by_predictor_axis(handoff_facts):
    facts = handoff_facts["external_y"]
    assert facts["legacy_ppm"]["calibration_refusal"]
    assert facts["generic_vs_legacy_pair"] != "comparable"


def test_external_response_units_survive_retention(handoff_facts):
    facts = handoff_facts["external_y"]
    assert facts["generic_ppm"]["retained_units"] == ["ppm"]
    assert facts["generic_percent"]["retained_units"] == ["%"]
    assert facts["ppm_vs_percent_pair"] != "comparable"


def test_unrelated_missing_report_does_not_erase_verified_evaluation(handoff_facts):
    facts = handoff_facts["unrelated_missing_output"]
    assert facts["evaluations_before"] == facts["evaluations_after"] == 1


def test_mcr_qualifies_axis_semantics_implementation(handoff_facts):
    assert handoff_facts["mcr_axis_semantics_bound"]


def test_external_array_never_borrows_unrelated_predictor_target_units(handoff_facts):
    facts = handoff_facts["external_array_with_unrelated_embedded_target"]
    assert facts["fitted_response_units"] == facts["retained_response_units"] == [None]


def test_unrelated_missing_split_does_not_erase_other_verified_evaluations(handoff_facts):
    facts = handoff_facts["unrelated_split_missing_X_train"]
    assert facts["before"] == facts["after"] == 1


@pytest.mark.parametrize("failure", ["digest", "overlap"])
def test_bad_split_is_explicitly_unqualified_without_erasing_independent_result(handoff_facts, failure):
    result = handoff_facts["invalid_split"][failure]
    assert result["evaluations"] == 1
    assert any("failed integrity" in message for message in result["limitations"])
    assert not any("could not be read" in message for message in result["limitations"])


def test_read_cap_preserves_verified_results_with_explicit_partial_notice(handoff_facts):
    result = handoff_facts["budget_partial"]
    assert result["evaluations"] == 1
    assert any("Comparison incomplete" in message and "16 MiB" in message for message in result["limitations"])


def test_partial_inventory_cannot_remove_producer_ambiguity(handoff_facts):
    result = handoff_facts["partial_ambiguity"]
    assert result["complete_count"] == 2 and result["partial_count"] == 1
    assert result["complete_state"] == result["partial_state"] == "descriptive_only"
    assert "calibration" in result["incomplete_roles"]
    assert all("delta" not in metric for metric in result["partial_metrics"].values())
