"""Classification inspection keeps saved scope, custody and identity withholding."""

import json

import numpy as np
import pytest

from spectra_sherpa.app.services import run_output_retention as retention
from tests.test_inspection_runs import call, run_facts  # noqa: F401
from tests.test_inspection_science import scientific_run  # noqa: F401


async def persist(fixture_data, node, outputs):
    facts, _, evidence = fixture_data
    sessions, _, runs, user = facts
    evidence["outputs"][node] = {
        port: retention.retain_output(user.id, value).model_dump() for port, value in outputs.items()
    }
    async with sessions() as session:
        run = await session.get(type(runs[0]), runs[0].id)
        run.evidence_completeness = evidence
        await session.commit()
    return facts


async def test_canonical_classification_splits_and_metric_parity(scientific_run):  # noqa: F811
    from spectra_sherpa.app.services.dag.nodes.classification.core_utils import (
        classification_metrics_contract,
        classification_scalar_metrics,
        flatten_classification_metrics_contract,
    )

    expected = ["private-A", "private-A", "private-B", "private-B"]
    predicted = ["private-A", "private-B", "private-B", "private-B"]
    metrics = classification_scalar_metrics(expected, predicted, ["private-A", "private-B"])
    contract = classification_metrics_contract(
        classes=["private-A", "private-B"],
        train_metrics=metrics,
        cv_metrics={"accuracy": 0.5},
        test_metrics={"accuracy": 0.25},
        primary_split="test",
    )
    facts = await persist(scientific_run, "classifier", {"metrics": contract})
    result = await call(facts, "get_results", {"run_id": facts[2][0].id})
    record = result["classification_results"][0]
    assert record["n_classes"] == 2 and record["primary_split"] == "test"
    assert record["splits"]["train"]["accuracy"] == pytest.approx(3 / 4)
    assert record["splits"]["cv"]["accuracy"] == 0.5
    assert record["splits"]["test"]["accuracy"] == 0.25
    flat = flatten_classification_metrics_contract(contract)
    assert {f"{split}_{key}": value for split, values in record["splits"].items() for key, value in values.items()} == {
        key: value for key, value in flat.items() if key != "n_classes"
    }
    assert "private-" not in json.dumps(result)
    assert "classes" not in record


async def test_unqualified_accuracy_is_not_promoted_to_classification_performance(scientific_run):  # noqa: F811
    facts = await persist(scientific_run, "historical", {"metrics": {"accuracy": 0.99}})
    result = await call(facts, "get_results", {"run_id": facts[2][0].id})
    assert result["classification_results"] == []
    assert "0.99" not in json.dumps(result)


@pytest.fixture
async def plsda_run(scientific_run):  # noqa: F811
    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
    from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import _plsda_scientific_core
    from spectra_sherpa.app.services.dag.nodes.classification.plsda_sample_diagnostics import build_sample_diagnostics

    rng = np.random.default_rng(1203)
    labels = np.repeat(["private-A", "private-B", "private-C"], 12)
    matrix = rng.normal(size=(len(labels), 8))
    for index, label in enumerate(np.unique(labels)):
        matrix[labels == label, index] += 1.0
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.linspace(1000, 1700, 8), units="cm-1"),
        sample_axis=SampleAxis(
            labels=[f"private-label-{i}" for i in range(len(labels))],
            sample_table={"sample_id": [f"private-observation-{i}" for i in range(len(labels))]},
        ),
        target=labels,
        target_context=TargetContext(target_type="categorical", target_names=["class"]),
    )
    core = _plsda_scientific_core(dataset, labels, parameters={"n_components": 2, "scale": True})
    receipt = build_sample_diagnostics(core)
    state = core["artifact"].to_fitted_state()
    facts = await persist(
        scientific_run, "classifier", {"metrics": core["metrics"], "fitted_state": state, "sample_diagnostics": receipt}
    )
    return facts, receipt, state


async def test_plsda_whole_calibration_screening_uses_verified_saved_authority(plsda_run):
    from spectra_sherpa.app.services.diagnostic_review_summary import build_summary

    facts, receipt, _ = plsda_run
    result = await call(facts, "get_diagnostics", {"run_id": facts[2][0].id, "node_id": "classifier"})
    assert result["model_kind"] == "plsda" and result["availability"] == "available"
    assert result["populations"] == {"calibration": {"total": 36, "selected": 36}}
    expected = build_summary(receipt, selected_ids=[row["id"] for row in receipt["rows"]])
    for key in ("screening.t2_limit", "screening.q_limit", "selection.t2.outside", "selection.q.outside"):
        assert result["facts"][key]["value"] == expected["facts"][key]["value"]
    # Independent scalar oracle on complete saved terms, no new fitting in reader.
    assert result["facts"]["selection.q.outside"]["value"] == sum(
        row["q"] > receipt["q_limit"] for row in receipt["rows"]
    )
    assert result["response"] is None
    assert "private-" not in json.dumps(result)
    assert all(not key.startswith("S") for key in result["facts"])
    assert result["methods"]["screening.method"] == receipt["screening_method"]


async def test_plsda_fitted_state_digest_mismatch_is_unavailable(plsda_run):
    facts, receipt, _ = plsda_run
    receipt = {**receipt, "fitted_state_sha256": "0" * 64}
    # Keep the original fitted-state file; change only the exact retained receipt.
    sessions, _, runs, user = facts
    async with sessions() as session:
        run = await session.get(type(runs[0]), runs[0].id)
        evidence = json.loads(json.dumps(run.evidence_completeness))
        evidence["outputs"]["classifier"]["sample_diagnostics"] = retention.retain_output(user.id, receipt).model_dump()
        run.evidence_completeness = evidence
        await session.commit()
    result = await call(facts, "get_diagnostics", {"run_id": runs[0].id, "node_id": "classifier"})
    assert result["availability"] == "unavailable" and result["facts"] == {}


async def test_source_population_counts_match_authority_without_row_map(scientific_run):  # noqa: F811
    from tests.test_run_population_summary import saved_run

    facts, *_ = scientific_run
    sessions, _, runs, user = facts
    saved, _, _ = saved_run(user_id=user.id)
    async with sessions() as session:
        run = await session.get(type(runs[0]), runs[0].id)
        evidence = json.loads(json.dumps(run.evidence_completeness))
        evidence["outputs"].update(saved.evidence_completeness["outputs"])
        run.evidence_completeness = evidence
        run.params_snapshot = saved.params_snapshot
        await session.commit()
    result = await call(facts, "get_results", {"run_id": runs[0].id})
    context = result["retained_context"]
    assert context["graph_digest"] == "b" * 64
    assert context["source_populations"] == [
        {
            "node_id": "load",
            "availability": "available",
            "source_count": 6,
            "active_count": 4,
            "source_excluded_count": 1,
            "workflow_excluded_count": 2,
            "excluded_count": 2,
        }
    ]
    assert context["source_inventory_notes"] == []
    encoded = json.dumps(result)
    for secret in ("identity-", "duplicate", "excluded_refs", "observation_ref", "params_snapshot"):
        assert secret not in encoded


async def test_missing_classification_file_reports_gap_not_zero(scientific_run):  # noqa: F811
    from spectra_sherpa.app.services.dag.nodes.classification.core_utils import classification_metrics_contract

    contract = classification_metrics_contract(classes=["secret-A", "secret-B"], train_metrics={"accuracy": 0.5})
    facts = await persist(scientific_run, "classifier", {"metrics": contract})
    sessions, _, runs, user = facts
    async with sessions() as session:
        run = await session.get(type(runs[0]), runs[0].id)
        digest = run.evidence_completeness["outputs"]["classifier"]["metrics"]["sha256"]
    (retention._user_directory(user.id) / f"{digest}.json").unlink()
    result = await call(facts, "get_results", {"run_id": runs[0].id})
    assert result["classification_results"] == []
    assert result["classification_read_gaps"] == [
        {
            "node_id": "classifier",
            "port": "metrics",
            "reason": "Retained classification evidence is unavailable or unverified.",
        }
    ]
    assert str(retention._user_directory(user.id)) not in json.dumps(result)


@pytest.mark.parametrize("bad", [True, 1.1, -0.1])
async def test_malformed_classification_metric_cannot_be_disclosed(scientific_run, bad):  # noqa: F811
    from spectra_sherpa.app.services.inspection_bridge import InspectionRefused

    facts = await persist(
        scientific_run,
        "classifier",
        {
            "metrics": {
                "schema_version": 1,
                "task_type": "classification",
                "n_classes": 2,
                "primary_split": "train",
                "splits": {"train": {"accuracy": bad}},
            }
        },
    )
    with pytest.raises(InspectionRefused, match="inspection_failed"):
        await call(facts, "get_results", {"run_id": facts[2][0].id})
