from dataclasses import replace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from spectra_sherpa.app.contracts.comparison_evidence import (
    EvaluationEvidence,
    ResolvedComparisonEvidence,
    get_comparison_evidence_provider,
    register_comparison_evidence_provider,
)
from spectra_sherpa.app.schemas.scientific_comparison import CompareEvidenceRequest, EvidenceReference
from spectra_sherpa.app.services.scientific_comparison import compare_evidence, resolve_run_evidence


def evaluation(role="training_cv", *, delta=0.1, changed_fold=False):
    ids = ("source:0", "source:1", "source:2", "source:3")
    return EvaluationEvidence(
        role=role,
        sample_ids=ids,
        observations=(1.0, 2.0, 3.0, 4.0),
        predictions=tuple(v + delta for v in (1.0, 2.0, 3.0, 4.0)),
        feature_receipt="a" * 64,
        response_identity="casein",
        units="wt %",
        fitted_sample_ids=ids if role == "calibration" else ("train:0", "train:1"),
        split_plan={
            "schema_version": "spectra-split-plan/1",
            "method": "kfold",
            "n_samples": 4,
            "grouped": False,
            "folds": (
                [{"train": [0, 2], "test": [1, 3]}, {"train": [1, 3], "test": [0, 2]}]
                if changed_fold
                else [{"train": [0, 1], "test": [2, 3]}, {"train": [2, 3], "test": [0, 1]}]
            ),
        },
    )


def item(identifier, *records):
    return ResolvedComparisonEvidence(
        EvidenceReference(kind="external", id=str(identifier), provider="test-reader", revision=str(identifier) * 64),
        f"Evidence {identifier}",
        tuple(records),
    )


def sections(result):
    return {section.role: section for section in result.pairs[0].sections}


def test_valid_heldout_remains_comparable_when_cv_folds_differ():
    result = compare_evidence(
        [
            item(1, evaluation(), evaluation("held_out")),
            item(2, evaluation(changed_fold=True), evaluation("held_out", delta=0.2)),
        ]
    )
    assert sections(result)["training_cv"].state == "reevaluation_needed"
    held = sections(result)["held_out"]
    assert held.state == "comparable"
    assert held.metric_values["rmse"] == pytest.approx({"left": 0.1, "right": 0.2})
    assert "independence" in result.items[0].sections["held_out"].reason


def test_cv_leakage_and_heldout_fit_overlap_cannot_be_verified():
    cv = evaluation()
    cv.split_plan["folds"][0]["train"] = [0, 1, 2]
    held = replace(evaluation("held_out"), fitted_sample_ids=("source:0", "source:9"))
    result = compare_evidence([item(1, cv, held), item(2, evaluation(), evaluation("held_out"))])
    assert sections(result)["training_cv"].state == "descriptive_only"
    assert sections(result)["held_out"].state == "descriptive_only"
    assert not sections(result)["held_out"].metric_values


def test_aggregates_are_visible_but_never_claim_paired_qualification():
    partial = replace(evaluation(), sample_ids=(), observations=(), predictions=(), aggregate_metrics={"rmse": 0.01})
    result = compare_evidence([item(1, partial), item(2, evaluation())])
    assert result.items[0].sections["training_cv"].metrics == {"rmse": 0.01}
    assert sections(result)["training_cv"].state == "descriptive_only"


@pytest.mark.parametrize("change", ["ids", "target", "units", "source"])
def test_equal_scores_never_substitute_for_exact_population_and_response(change):
    other = evaluation()
    changes = {
        "ids": {"sample_ids": tuple(reversed(other.sample_ids))},
        "target": {"response_identity": "moisture"},
        "units": {"units": "mg/kg"},
        "source": {"feature_receipt": "b" * 64},
    }
    result = compare_evidence([item(1, evaluation()), item(2, replace(other, **changes[change]))])
    assert sections(result)["training_cv"].state == "reevaluation_needed"


def test_counts_unknown_without_membership_are_not_zero():
    result = compare_evidence([item(1, evaluation()), item(2, evaluation())])
    population = result.items[0].sections["training_cv"].population
    assert population.development_count == population.evaluation_count == 4
    assert population.source_count is None and population.held_out_count is None
    assert population.excluded_count is None and population.fold_count == 2


def test_no_provider_code_or_url_can_be_loaded_from_client_reference():
    with pytest.raises(ValidationError):
        EvidenceReference(kind="external", id="1", provider="https://attacker.example", revision="a" * 64)
    with pytest.raises(ValueError, match="unavailable"):
        get_comparison_evidence_provider("never-registered")
    with pytest.raises(ValueError, match="reserved"):
        register_comparison_evidence_provider("runs", lambda: None)


@pytest.mark.asyncio
async def test_native_resolution_refuses_foreign_project_and_stale_revision():
    from types import SimpleNamespace

    from spectra_sherpa.app.api.v1.routes.runs import compare_project_evidence

    class Session:
        def __init__(self, value):
            self.value = value

        async def execute(self, query):
            # Both ownership and project scope must be in every lookup.
            assert "execution_run.user_id" in str(query) and "execution_run.project_id" in str(query)
            return SimpleNamespace(scalar_one_or_none=lambda: self.value)

    refs = [EvidenceReference(kind="run", provider="runs", id=str(i), revision="a" * 64) for i in (1, 2)]
    request = CompareEvidenceRequest(references=refs)
    with pytest.raises(HTTPException) as absent:
        await compare_project_evidence(request, 3, Session(None), SimpleNamespace(id=1))
    assert absent.value.status_code == 404
    run = SimpleNamespace(id=1, name="old", evidence_completeness=None, diagnostics=None, source_metadata=None)
    with pytest.raises(HTTPException) as stale:
        await compare_project_evidence(request, 3, Session(run), SimpleNamespace(id=1))
    assert stale.value.status_code == 409


def test_legacy_run_remains_readable_without_inventing_folds():
    from types import SimpleNamespace

    run = SimpleNamespace(id=7, name="Legacy", evidence_completeness=None, diagnostics=None, source_metadata=None)
    record = resolve_run_evidence(run)
    assert record.label == "Legacy" and not record.evaluations
    assert record.population.development_count is None


def test_unsplit_pls_calibration_is_inspectable_without_inventing_a_test_set(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import numpy as np

    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import run_output_retention as retention
    from spectra_sherpa.app.services.dag.regression_comparison import build_regression_comparison

    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    source = SherpaDataset(
        X=np.arange(12, dtype=float).reshape(4, 3),
        target=np.arange(4, dtype=float),
        extra={"source_collection": {"source_manifest_sha256": "a" * 64}},
    )
    definition = {
        "schema_version": 1,
        "nodes": [{"node_id": "pls", "node_type": "model.fitted_pls"}],
        "edges": [{"from_node_id": "source", "from_output": "default", "to_node_id": "pls", "to_input": "default"}],
    }
    comparison = build_regression_comparison(source.target, source.target + 0.1, role="calibration")
    run = SimpleNamespace(
        id=3,
        user_id=1,
        diagnostics={},
        source_metadata={},
        evidence_completeness=retention.retain_run_outputs(
            1,
            {
                "source": {"default": source},
                "pls": {"calibration_comparison": comparison},
                "__workflow__": {"definition": definition},
            },
            {},
        ),
    )
    result = resolve_run_evidence(run)
    assert len(result.evaluations) == 1 and result.evaluations[0].role == "calibration"
    assert result.population.development_count == 4 and result.population.held_out_count is None


def test_native_heldout_receipt_retains_counts_and_ignores_unqualified_cv(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import numpy as np

    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import run_output_retention as retention
    from spectra_sherpa.app.services.dag.nodes.data.split_planner import (
        materialize_split_outputs,
        plan_train_test_split,
    )
    from spectra_sherpa.app.services.dag.regression_comparison import build_regression_comparison

    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    x = np.arange(36, dtype=float).reshape(12, 3)
    y = np.arange(12, dtype=float)
    source = SherpaDataset(X=x, target=y, extra={"source_collection": {"source_manifest_sha256": "a" * 64}})
    plan = plan_train_test_split(x, y, method="random")
    outputs = materialize_split_outputs(source, x, y, plan, node_id="split")
    target = y[plan.test_indices]
    comparison = build_regression_comparison(target, target + 0.2, role="held_out_test")
    comparison["metadata"]["population_authority"] = {
        "schema_version": "spectrasherpa-population-authority/1",
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }
    definition = {
        "schema_version": 1,
        "nodes": [{"node_id": "split", "node_type": "data.train_test_split"}],
        "edges": [],
    }
    run = SimpleNamespace(
        id=1,
        user_id=1,
        name="Held out",
        diagnostics={},
        source_metadata={},
        evidence_completeness=retention.retain_run_outputs(
            1,
            {
                "split": outputs,
                "eval": {"comparison": comparison},
                "__workflow__": {"definition": definition},
            },
            {},
        ),
    )
    resolved = resolve_run_evidence(run)
    assert len(resolved.evaluations) == 1
    assert resolved.evaluations[0].role == "held_out"
    result = compare_evidence(
        [resolved, replace(resolved, reference=resolved.reference.model_copy(update={"id": "2"}))]
    )
    assert sections(result)["held_out"].state == "comparable"
    assert sections(result)["training_cv"].state == "unavailable"
    assert result.items[0].population.development_count == len(plan.train_indices)
    assert result.items[0].population.held_out_count == len(plan.test_indices)
    comparison["metadata"]["population_authority"]["qualification"] = "unverified_lineage"
    run.evidence_completeness = retention.retain_run_outputs(
        1,
        {
            "split": outputs,
            "eval": {"comparison": comparison},
            "__workflow__": {"definition": definition},
        },
        {},
    )
    assert not resolve_run_evidence(run).evaluations


def test_preprocessed_training_calibration_preserves_serialized_sample_identity(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import numpy as np

    from spectra_sherpa.app.lib.axes import SampleAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import run_output_retention as retention
    from spectra_sherpa.app.services.dag.nodes.data.split_planner import (
        materialize_split_outputs,
        plan_train_test_split,
    )
    from spectra_sherpa.app.services.dag.regression_comparison import build_regression_comparison

    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    x = np.arange(36, dtype=float).reshape(12, 3)
    y = np.arange(12, dtype=float)
    source = SherpaDataset(
        X=x,
        target=y,
        sample_axis=SampleAxis(labels=[f"sample-{i}" for i in range(12)]),
        extra={"source_collection": {"source_manifest_sha256": "a" * 64}},
    )
    plan = plan_train_test_split(x, y, method="random")
    outputs = materialize_split_outputs(source, x, y, plan, node_id="split")
    scaled = outputs["X_train"].copy()
    scaled.X[:] = (scaled.X - scaled.X.mean(axis=0)) / scaled.X.std(axis=0)
    scaled.provenance.append("preprocess.scale", {"method": "autoscale"}, node_id="scale")
    comparison = build_regression_comparison(scaled.target, scaled.target + 0.1, role="calibration")
    definition = {
        "schema_version": 1,
        "nodes": [
            {"node_id": "split", "node_type": "data.train_test_split"},
            {"node_id": "scale", "node_type": "preprocess.scale"},
            {"node_id": "pls", "node_type": "model.fitted_pls"},
        ],
        "edges": [
            {"from_node_id": "split", "from_output": "X_train", "to_node_id": "scale", "to_input": "default"},
            {"from_node_id": "scale", "from_output": "default", "to_node_id": "pls", "to_input": "default"},
        ],
    }
    run = SimpleNamespace(
        id=1,
        user_id=1,
        diagnostics={},
        source_metadata={},
        evidence_completeness=retention.retain_run_outputs(
            1,
            {
                "split": outputs,
                "scale": {"default": scaled},
                "pls": {"calibration_comparison": comparison},
                "__workflow__": {"definition": definition},
            },
            {},
        ),
    )
    result = resolve_run_evidence(run)
    assert len(result.evaluations) == 1
    assert result.evaluations[0].role == "calibration"
    assert len(result.evaluations[0].sample_ids) == len(plan.train_indices)


@pytest.mark.parametrize("other_has_rows", [False, True])
def test_aggregate_receipt_cannot_rescue_invalid_row_evidence(other_has_rows):
    leaking = evaluation()
    leaking.split_plan["folds"][0]["train"] = [0, 1, 2]
    leaking = replace(leaking, aggregate_protocol="a" * 64, aggregate_metrics={"rmse": 0.01})
    other = replace(evaluation(), aggregate_protocol="a" * 64, aggregate_metrics={"rmse": 0.02})
    if not other_has_rows:
        other = replace(other, sample_ids=(), observations=(), predictions=(), split_plan=None)
    result = compare_evidence([item(1, leaking), item(2, other)])
    assert "overlaps training and test" in result.items[0].sections["training_cv"].reason
    assert sections(result)["training_cv"].state == "descriptive_only"
