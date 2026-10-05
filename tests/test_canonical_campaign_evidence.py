"""Closed, data-free campaign-ledger contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spectra_sherpa.app.services.dag.canonical_selection_policy import (
    CanonicalSelectionPolicy,
    build_canonical_development_decision,
    selection_candidate,
)
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.canonical_campaign_evidence import (
    CanonicalCampaignEvidence,
    CanonicalCampaignEvidenceError,
)


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _graph(seed: str) -> dict:
    selector = hashlib.sha256(seed.encode("utf-8")).digest()
    return admit_validation_graph(
        [
            WorkflowNode(
                "model",
                "model.fitted_pls",
                {
                    "n_components": 1 + selector[0] % 5,
                    "scale": bool(selector[1] % 2),
                },
            )
        ],
        [],
        require_live_runtime=False,
    ).as_dict()


def _candidate(*, candidate_id: str, ordinal: int, rmse: float, seed: str) -> dict:
    candidate_graph = _graph(seed)
    graph = candidate_graph["graph_digest"]
    metrics = {
        "registry_version": "2",
        "rmse": rmse,
        "mae": rmse - 0.1,
        "bias": 0.0,
        "r2": 0.75,
        "n_samples": 20,
        "sep": rmse,
        "slope": None,
        "intercept": None,
        "rer": None,
    }
    return {
        "status": "succeeded",
        "candidate_id": candidate_id,
        "ordinal": ordinal,
        "declared_ordinal": ordinal,
        "candidate_digest": graph,
        "graph_digest": graph,
        "candidate_graph": candidate_graph,
        "request_digest": _digest(chr(ord(seed) + 1)),
        "result_digest": _digest(chr(ord(seed) + 2)),
        "validation_execution": {
            "schema_version": "spectra-candidate-validation/3",
            "graph_digest": graph,
            "capability_content_digest": _digest("capability-content"),
            "capability_envelope_digest": _digest("capability-envelope"),
            "split_plan_digest": _digest("shared-split-plan"),
            "task_type": "regression",
            "model_operation_id": "model.fitted_pls",
            "metrics": metrics,
            "folds": [
                {
                    "partition_digest": _digest(f"partition-{index}"),
                    "metrics": {**metrics, "n_samples": 10},
                    "model_node_id": "model-pls",
                    "evaluator_node_id": "evaluate-regression",
                    "node_ids": ["model-pls", "evaluate-regression"],
                    "prediction_application_digest": None,
                }
                for index in range(2)
            ],
        },
    }


def _selection(item: dict) -> dict:
    validation = item["validation_execution"]
    return selection_candidate(
        candidate_id=item["candidate_id"],
        ordinal=item["ordinal"],
        result_digest=item["result_digest"],
        dataset_content_digest=validation["capability_content_digest"],
        split_plan_digest=validation["split_plan_digest"],
        metrics=validation["metrics"],
        folds=[
            {
                "partition_digest": fold["partition_digest"],
                "metrics": fold["metrics"],
            }
            for fold in validation["folds"]
        ],
    )


def _record() -> CanonicalCampaignEvidence:
    baseline = _candidate(candidate_id="baseline", ordinal=1, rmse=1.0, seed="a")
    selected = _candidate(candidate_id="candidate-scale", ordinal=2, rmse=0.8, seed="f")
    decision = build_canonical_development_decision(
        [_selection(baseline), _selection(selected)],
        policy=CanonicalSelectionPolicy.build(0.1),
    )
    return CanonicalCampaignEvidence.build(
        campaign={
            "campaign_id": "campaign-canonical-001",
            "search_space_digest": _digest("q"),
            "decision_digest": _digest("z"),  # build derives the actual digest.
            "claim_scope": "public_reproducibility_only",
            "optimization_lane": "quantitative_calibration",
        },
        candidates=[baseline, selected],
        decision=decision,
        winner_refit={
            "candidate_id": selected["candidate_id"],
            "authority_digest": _digest("m"),
            "refit_request_digest": _digest("n"),
            "refit_terminal_digest": _digest("o"),
            "full_refit_execution_digest": _digest("p"),
            "artifact_digest": _digest("r"),
        },
    )


def test_campaign_evidence_round_trips_a_complete_candidate_ledger() -> None:
    evidence = _record()
    loaded = CanonicalCampaignEvidence.from_dict(evidence.as_dict())

    assert loaded.content_digest == evidence.content_digest
    assert [item["candidate_id"] for item in loaded.payload["candidates"]] == ["baseline", "candidate-scale"]
    assert loaded.payload["decision"]["winner_candidate_id"] == "candidate-scale"
    assert loaded.payload["winner_refit"]["candidate_id"] == "candidate-scale"
    encoded = loaded.canonical_bytes()
    for forbidden_field in ("samples", "targets", "predictions", "fitted_state_bytes", "filesystem_path", "secret"):
        assert f'"{forbidden_field}"'.encode() not in encoded


def test_campaign_evidence_retains_failed_candidate_without_using_it_as_a_metric() -> None:
    baseline = _candidate(candidate_id="baseline", ordinal=1, rmse=1.0, seed="a")
    selected = _candidate(candidate_id="candidate-selected", ordinal=2, rmse=0.8, seed="f")
    selected["declared_ordinal"] = 3
    failed_configuration = _graph("failed-graph")
    failed_graph = failed_configuration["graph_digest"]
    failed = {
        "status": "failed",
        "candidate_id": "candidate-failed",
        "declared_ordinal": 2,
        "candidate_digest": failed_graph,
        "graph_digest": failed_graph,
        "candidate_graph": failed_configuration,
        "request_digest": _digest("failed-request"),
        "result_digest": _digest("failed-result"),
        "failure_status": "scientific_failure",
        "failure_code": "insufficient_class_residual_authority",
    }
    decision = build_canonical_development_decision(
        [_selection(baseline), _selection(selected)],
        policy=CanonicalSelectionPolicy.build(0.1),
    )

    evidence = CanonicalCampaignEvidence.build(
        campaign={
            "campaign_id": "campaign-canonical-failure-001",
            "search_space_digest": _digest("failure-search"),
            "decision_digest": _digest("placeholder"),
            "claim_scope": "public_reproducibility_only",
            "optimization_lane": "quantitative_calibration",
        },
        candidates=[baseline, failed, selected],
        decision=decision,
        winner_refit={
            "candidate_id": selected["candidate_id"],
            "authority_digest": _digest("failure-authority"),
            "refit_request_digest": _digest("failure-refit-request"),
            "refit_terminal_digest": _digest("failure-refit-terminal"),
            "full_refit_execution_digest": _digest("failure-refit-execution"),
            "artifact_digest": _digest("failure-artifact"),
        },
    )

    assert [item["status"] for item in evidence.payload["candidates"]] == [
        "succeeded",
        "failed",
        "succeeded",
    ]
    assert evidence.payload["candidates"][1]["failure_code"] == "insufficient_class_residual_authority"
    assert [item["candidate_id"] for item in evidence.payload["decision"]["candidate_results"]] == [
        "baseline",
        "candidate-selected",
    ]

    for field, replacement, message in (
        ("failure_status", "succeeded", "candidate failure status is invalid"),
        ("failure_code", "", "candidate failure code is invalid"),
        ("graph_digest", _digest("different-failed-graph"), "candidate graph identity changed"),
    ):
        mutated = evidence.as_dict()
        mutated["candidates"][1][field] = replacement
        unsigned = {key: item for key, item in mutated.items() if key != "content_digest"}
        mutated["content_digest"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        with pytest.raises(CanonicalCampaignEvidenceError, match=message):
            CanonicalCampaignEvidence.from_dict(mutated)


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda value: value["candidates"][1].__setitem__("ordinal", 3),
            "successful candidate ordinals are not closed",
        ),
        (
            lambda value: value["decision"].__setitem__("winner_primary_metric", 0.7),
            "development decision does not reproduce from fold evidence",
        ),
        (
            lambda value: value["winner_refit"].__setitem__("candidate_id", "baseline"),
            "winner refit does not bind the selected candidate",
        ),
        (
            lambda value: value["campaign"].__setitem__("claim_scope", "improved"),
            "campaign claim scope is invalid",
        ),
    ],
)
def test_campaign_evidence_rejects_a_rewritten_scientific_record(mutator, match: str) -> None:
    value = _record().as_dict()
    mutator(value)

    with pytest.raises(CanonicalCampaignEvidenceError, match=match):
        CanonicalCampaignEvidence.from_dict(value)


def test_campaign_evidence_rejects_a_rehashed_forged_metric() -> None:
    """Digest checks cannot replace cross-field scientific consistency checks."""

    value = _record().as_dict()
    value["candidates"][1]["validation_execution"]["folds"][0]["metrics"]["rmse"] = 0.7
    unsigned = {key: item for key, item in value.items() if key != "content_digest"}
    value["content_digest"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()

    with pytest.raises(CanonicalCampaignEvidenceError, match="candidate validation execution is invalid"):
        CanonicalCampaignEvidence.from_dict(value)


def test_campaign_evidence_rejects_a_rehashed_forged_fold_decision() -> None:
    """A new outer digest cannot turn invented scientific summaries into evidence."""

    value = _record().as_dict()
    value["decision"]["paired_fold_margin"]["paired_standard_error"] = 0.5
    value["decision"]["paired_fold_margin"]["required_dispersion_delta"] = 0.5
    value["decision"]["conclusion"] = "no_defensible_improvement"
    value["decision"]["conclusion_reason"] = "within_fold_dispersion"
    value["campaign"]["decision_digest"] = hashlib.sha256(
        json.dumps(value["decision"], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    unsigned = {key: item for key, item in value.items() if key != "content_digest"}
    value["content_digest"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()

    with pytest.raises(
        CanonicalCampaignEvidenceError,
        match="development decision does not reproduce from fold evidence",
    ):
        CanonicalCampaignEvidence.from_dict(value)


def test_campaign_evidence_rejects_v1_without_translation() -> None:
    value = _record().as_dict()
    value["schema_version"] = "spectra-canonical-campaign-evidence/1"

    with pytest.raises(CanonicalCampaignEvidenceError, match="version is unsupported"):
        CanonicalCampaignEvidence.from_dict(value)


def _reviewed_record():
    original = _record().as_dict()
    chosen = original["candidates"][0]  # Deliberately choose the non-metric leader.
    return CanonicalCampaignEvidence.build(
        campaign=original["campaign"],
        candidates=original["candidates"],
        decision={
            "schema_version": "spectra-scientist-reviewed-selection/1",
            "selection_claim": "scientist_selected_not_automatic_metric_winner",
            "winner_candidate_id": chosen["candidate_id"],
            "selected_graph_digest": chosen["graph_digest"],
            "selected_result_digest": chosen["result_digest"],
            "promotion_decision_digest": _digest("promotion"),
            "checkpoint_digest": _digest("checkpoint"),
            "settlement_digest": _digest("settlement"),
            "reason_code": "robustness",
        },
        winner_refit={**original["winner_refit"], "candidate_id": chosen["candidate_id"]},
    )


def test_reviewed_selection_preserves_scientist_choice_without_claiming_metric_superiority():
    evidence = _reviewed_record()
    assert evidence.payload["schema_version"] == "spectra-canonical-campaign-evidence/7"
    assert evidence.payload["decision"]["winner_candidate_id"] == "baseline"
    assert CanonicalCampaignEvidence.from_dict(evidence.as_dict()) == evidence
    assert _record().payload["schema_version"] == "spectra-canonical-campaign-evidence/6"


@pytest.mark.parametrize(
    "field,value",
    [
        ("winner_candidate_id", "candidate-scale"),
        ("selected_graph_digest", "0" * 64),
        ("selected_result_digest", "0" * 64),
        ("selection_claim", "automatic_metric_winner"),
        ("reason_code", "unknown"),
        ("checkpoint_digest", "missing"),
    ],
)
def test_reviewed_selection_refuses_rehashed_substitutions(field, value):
    record = _reviewed_record().as_dict()
    record["decision"][field] = value
    with pytest.raises(CanonicalCampaignEvidenceError):
        CanonicalCampaignEvidence.build(
            campaign=record["campaign"],
            candidates=record["candidates"],
            decision=record["decision"],
            winner_refit=record["winner_refit"],
        )


def test_reviewed_selection_cannot_be_relabelled_as_legacy_automatic_evidence():
    record = _reviewed_record().as_dict()
    record["schema_version"] = "spectra-canonical-campaign-evidence/6"
    record["content_digest"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in record.items() if key != "content_digest"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    with pytest.raises(CanonicalCampaignEvidenceError, match="interpretation"):
        CanonicalCampaignEvidence.from_dict(record)


@pytest.mark.parametrize("lane", ["categorical_classification", "class_modelling"])
def test_reviewed_selection_refuses_relabelling_a_regression_as_classification(lane):
    record = _reviewed_record().as_dict()
    record["campaign"]["optimization_lane"] = lane
    with pytest.raises(CanonicalCampaignEvidenceError, match="model interpretation"):
        CanonicalCampaignEvidence.build(
            campaign=record["campaign"],
            candidates=record["candidates"],
            decision=record["decision"],
            winner_refit=record["winner_refit"],
        )
