from __future__ import annotations

import hashlib
import json

import pytest

import spectra_sherpa.sdk as ss


def _digest(seed: str) -> str:
    return seed * 64


def _content_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _valid_bundle(**overrides):
    values = {
        "dataset_attestation": {"dataset_digest": _digest("a"), "n_samples": 20},
        "split_attestation": {"split_digest": _digest("b"), "method": "group_kfold"},
        "baseline": {"workflow_digest": _digest("c"), "metrics": {"rmse": 0.4}},
        "candidates": [
            {"candidate_id": "baseline-copy", "workflow_digest": _digest("c"), "outcome": "evaluated"},
            {
                "candidate_id": "bad-selector",
                "workflow_digest": _digest("d"),
                "outcome": "failed",
                "failure": {"node_id": "selector", "class": "ValueError"},
            },
            {"candidate_id": "winner", "workflow_digest": _digest("e"), "outcome": "selected"},
        ],
        "evaluation_diagnostics": [
            {
                "subject_id": subject_id,
                "cross_validation": {
                    "split_method": "kfold",
                    "grouped": False,
                    "folds": [
                        {
                            "fold_index": 0,
                            "train_indices": [0, 1],
                            "test_indices": [2],
                            "observed": [1.2],
                            "predictions": [1.1],
                            "metrics": {"rmse": 0.1},
                        }
                    ],
                },
            }
            for subject_id in ("baseline", "baseline-copy", "winner")
        ],
        "environment": {"software_version": "0.5.30", "python_runtime": "CPython 3.11"},
        "human_decisions": [{"decision": "approve confirmation", "actor": "scientist"}],
        "confirmation": {"candidate_id": "winner", "metrics": {"rmsep": 0.31}},
        "conclusion": "improved",
    }
    values.update(overrides)
    if "candidates" in overrides and "evaluation_diagnostics" not in overrides:
        template = values["evaluation_diagnostics"][0]["cross_validation"]
        values["evaluation_diagnostics"] = [
            {"subject_id": "baseline", "cross_validation": template},
            *[
                {"subject_id": candidate["candidate_id"], "cross_validation": template}
                for candidate in values["candidates"]
                if candidate["outcome"] in {"evaluated", "selected"}
            ],
        ]
    return ss.report.evidence_bundle(**values)


def test_evidence_bundle_is_content_addressed_independent_of_mapping_order() -> None:
    first = _valid_bundle()
    second = _valid_bundle(
        environment={"python_runtime": "CPython 3.11", "software_version": "0.5.30"},
        dataset_attestation={"n_samples": 20, "dataset_digest": _digest("a")},
    )

    assert first.content_digest == second.content_digest
    assert ss.report.verify_evidence_bundle(first)
    assert ss.report.verify_evidence_bundle(first.as_dict())


def test_evidence_bundle_rejects_tampered_serialized_manifest() -> None:
    manifest = _valid_bundle().as_dict()
    manifest["baseline"]["metrics"]["rmse"] = 0.01

    with pytest.raises(ss.report.EvidenceBundleError, match="digest mismatch"):
        ss.report.EvidenceBundle.from_dict(manifest)
    assert ss.report.verify_evidence_bundle(manifest) is False


def test_evidence_bundle_requires_complete_candidate_lineage() -> None:
    candidates = [
        {"candidate_id": "duplicate", "workflow_digest": _digest("a"), "outcome": "evaluated"},
        {"candidate_id": "duplicate", "workflow_digest": _digest("b"), "outcome": "selected"},
    ]

    with pytest.raises(ss.report.EvidenceBundleError, match="duplicate evidence candidate_id"):
        _valid_bundle(candidates=candidates)


def test_evidence_bundle_requires_exact_diagnostics_for_evaluated_subjects() -> None:
    diagnostics = _valid_bundle().payload["evaluation_diagnostics"]
    diagnostics = [record for record in diagnostics if record["subject_id"] != "winner"]

    with pytest.raises(ss.report.EvidenceBundleError, match="missing exact evaluation diagnostics"):
        _valid_bundle(evaluation_diagnostics=diagnostics)


def test_evidence_bundle_rejects_confirmation_for_unknown_candidate() -> None:
    with pytest.raises(ss.report.EvidenceBundleError, match="not present in candidates"):
        _valid_bundle(confirmation={"candidate_id": "not-recorded", "metrics": {"rmsep": 0.2}})


def test_evidence_bundle_detaches_from_caller_mutation() -> None:
    candidates = [
        {"candidate_id": "winner", "workflow_digest": _digest("e"), "outcome": "selected"},
    ]
    bundle = _valid_bundle(candidates=candidates, confirmation={"candidate_id": "winner"})
    original_digest = bundle.content_digest
    candidates[0]["outcome"] = "failed"

    assert bundle.content_digest == original_digest
    assert bundle.payload["candidates"][0]["outcome"] == "selected"
    assert ss.report.verify_evidence_bundle(bundle)


def test_evidence_bundle_rejects_noncanonical_numbers() -> None:
    payload = _valid_bundle().as_dict()
    payload["baseline"]["metrics"]["rmse"] = float("nan")
    payload.pop("content_digest")

    with pytest.raises(ss.report.EvidenceBundleError, match="canonical-JSON"):
        ss.report.EvidenceBundle.from_dict({**payload, "content_digest": "0" * 64})


def _execution(subject_id: str, seed: str, *, succeeded: bool = True) -> dict:
    return {
        "subject_id": subject_id,
        "request_digest": _digest(seed),
        "result_digest": _digest(seed),
        "local_evidence_digest": _digest(seed) if succeeded else None,
        "workflow_capsule_digest": _digest(seed),
        "receipt_digest": None,
    }


def test_schema_two_separates_development_evidence_from_confirmation_claims() -> None:
    executions = [
        _execution("baseline", "1"),
        _execution("baseline-copy", "2"),
        _execution("winner", "3"),
        _execution("bad-selector", "4", succeeded=False),
    ]
    history = [
        {
            "sequence": 1,
            "event_kind": "search_stopped",
            "actor_kind": "orchestrator",
            "subject_id": "campaign-001",
            "payload": {
                "reason": "budget_exhausted",
                "development_conclusion": "development_no_defensible_improvement",
            },
        }
    ]
    bundle = _valid_bundle(
        scope="development_campaign",
        execution_records=executions,
        campaign_history=history,
        confirmation=None,
        conclusion="not_demonstrated",
    )

    assert bundle.payload["schema_version"] == "2"
    assert ss.report.verify_evidence_bundle(bundle)

    with pytest.raises(ss.report.EvidenceBundleError, match="cannot contain confirmation"):
        _valid_bundle(
            scope="development_campaign",
            execution_records=executions,
            campaign_history=history,
            confirmation={"candidate_id": "winner"},
            conclusion="not_demonstrated",
        )
    with pytest.raises(ss.report.EvidenceBundleError, match="cannot claim"):
        _valid_bundle(
            scope="development_campaign",
            execution_records=executions,
            campaign_history=history,
            confirmation=None,
            conclusion="improved",
        )


def test_schema_two_closes_managed_proposal_history_provenance() -> None:
    executions = [
        _execution("baseline", "1"),
        _execution("baseline-copy", "2"),
        _execution("winner", "3"),
        _execution("bad-selector", "4", succeeded=False),
    ]
    history = [
        {
            "sequence": 1,
            "event_kind": "candidate_planned",
            "actor_kind": "orchestrator",
            "subject_id": "winner",
            "payload": {
                "candidate_kind": "managed_proposal",
                "candidate_digest": _digest("f"),
                "workflow_digest": _digest("e"),
                "proposal_provenance": {
                    "proposer_kind": "llm",
                    "proposer_id": "provider-model",
                    "proposer_version": "model-version",
                    "policy_digest": _digest("a"),
                    "parameters_digest": _digest("b"),
                },
            },
        },
        {
            "sequence": 2,
            "event_kind": "search_stopped",
            "actor_kind": "orchestrator",
            "subject_id": "campaign-001",
            "payload": {
                "reason": "budget_exhausted",
                "development_conclusion": "development_improvement",
            },
        },
        {
            "sequence": 3,
            "event_kind": "candidate_selected",
            "actor_kind": "orchestrator",
            "subject_id": "winner",
            "payload": {"reason": "budget_exhausted"},
        },
    ]
    bundle = _valid_bundle(
        scope="development_campaign",
        execution_records=executions,
        campaign_history=history,
        confirmation=None,
        conclusion="not_demonstrated",
    )

    assert ss.report.verify_evidence_bundle(bundle)

    manifest = bundle.as_dict()
    manifest.pop("content_digest")
    manifest["campaign_history"][0]["payload"]["proposal_provenance"] = {}
    with pytest.raises(ss.report.EvidenceBundleError, match="proposal_provenance fields are closed"):
        ss.report.EvidenceBundle.from_dict({**manifest, "content_digest": _content_digest(manifest)})


@pytest.mark.parametrize(
    ("event_index", "mutation", "message"),
    [
        (
            0,
            lambda payload: payload.update({"unexpected": True}),
            "payload fields are closed",
        ),
        (
            1,
            lambda payload: payload.update({"status": "timeout"}),
            "status contradicts event_kind",
        ),
    ],
)
def test_schema_two_rejects_noncanonical_development_history_payloads(
    event_index: int,
    mutation,
    message: str,
) -> None:
    history = [
        {
            "sequence": 1,
            "event_kind": "candidate_planned",
            "actor_kind": "orchestrator",
            "subject_id": "winner",
            "payload": {
                "candidate_kind": "transparent_grid",
                "candidate_digest": _digest("f"),
                "workflow_digest": _digest("e"),
                "proposal_provenance": None,
            },
        },
        {
            "sequence": 2,
            "event_kind": "evaluation_succeeded",
            "actor_kind": "runner",
            "subject_id": "winner",
            "payload": {
                "status": "succeeded",
                "result_digest": _digest("a"),
                "local_evidence_digest": _digest("b"),
                "failure_class": None,
            },
        },
        {
            "sequence": 3,
            "event_kind": "search_stopped",
            "actor_kind": "orchestrator",
            "subject_id": "campaign-001",
            "payload": {
                "reason": "budget_exhausted",
                "development_conclusion": "development_improvement",
            },
        },
    ]
    mutation(history[event_index]["payload"])

    with pytest.raises(ss.report.EvidenceBundleError, match=message):
        _valid_bundle(
            scope="development_campaign",
            execution_records=[
                _execution("baseline", "1"),
                _execution("baseline-copy", "2"),
                _execution("winner", "3"),
                _execution("bad-selector", "4", succeeded=False),
            ],
            campaign_history=history,
            confirmation=None,
            conclusion="not_demonstrated",
        )


def test_confirmation_scope_requires_a_nonempty_receipt_chain() -> None:
    with pytest.raises(ss.report.EvidenceBundleError, match="requires a confirmation and receipt chain"):
        _valid_bundle(
            scope="confirmation_campaign",
            execution_records=[
                _execution("baseline", "1"),
                _execution("baseline-copy", "2"),
                _execution("winner", "3"),
                _execution("bad-selector", "4", succeeded=False),
            ],
            campaign_history=[
                {
                    "sequence": 1,
                    "event_kind": "confirmation_completed",
                    "actor_kind": "runner",
                    "subject_id": "winner",
                    "payload": {},
                }
            ],
            receipt_chain=[],
        )


def _valid_confirmation_bundle(**confirmation_overrides):
    receipt_chain = [_digest("8"), _digest("9")]
    confirmation = {
        "schema_version": "spectra-harness-confirmation-evidence/1",
        "candidate_id": "winner",
        "benchmark_id": "pbm-public-corn-m5",
        "benchmark_status": "public_reproducibility_only",
        "request_digest": _digest("1"),
        "result_digest": _digest("2"),
        "local_evidence_digest": _digest("3"),
        "terminal_receipt_digest": receipt_chain[-1],
        "development_dataset_reference_digest": _digest("4"),
        "development_content_digest": _digest("5"),
        "development_split_digest": _digest("6"),
        "confirmation_dataset_reference_digest": _digest("7"),
        "confirmation_content_digest": _digest("a"),
        "confirmation_split_digest": _digest("b"),
        "metric_plan_digest": _digest("c"),
        "decision_plan_digest": _digest("d"),
        "status": "succeeded",
        "metrics": {"rmse": 0.2, "bias": 0.01},
        "uncertainty": {"rmse": {"lower": 0.1, "upper": 0.3}},
        "failure_class": None,
        "conclusion": "improved",
        "claim_eligible": False,
    }
    confirmation.update(confirmation_overrides)
    receipt_payloads = [
        {
            "receipt_digest": receipt_chain[0],
            "authorization_id": "cauth_original",
            "evaluation_sequence": 1,
            "disposition": "admitted",
            "result_digest": None,
            "evidence_digest": None,
            "failure_code": None,
            "claim_eligibility_effect": "unchanged",
        },
        {
            "receipt_digest": receipt_chain[1],
            "authorization_id": "cauth_original",
            "evaluation_sequence": 1,
            "disposition": "succeeded",
            "result_digest": confirmation["result_digest"],
            "evidence_digest": confirmation["local_evidence_digest"],
            "failure_code": None,
            "claim_eligibility_effect": "unchanged",
        },
    ]
    history = [
        {
            "sequence": 1,
            "event_kind": "search_stopped",
            "actor_kind": "orchestrator",
            "subject_id": "campaign-001",
            "payload": {
                "reason": "budget_exhausted",
                "development_conclusion": "development_improvement",
            },
        },
        {
            "sequence": 2,
            "event_kind": "confirmation_authorization_consumed",
            "actor_kind": "human",
            "subject_id": "winner",
            "payload": receipt_payloads[0],
        },
        {
            "sequence": 3,
            "event_kind": "confirmation_attempt_terminal",
            "actor_kind": "runner",
            "subject_id": "winner",
            "payload": receipt_payloads[1],
        },
        {
            "sequence": 4,
            "event_kind": "campaign_concluded",
            "actor_kind": "orchestrator",
            "subject_id": "campaign-001",
            "payload": {
                "conclusion": confirmation["conclusion"],
                "reason_code": "rmse_and_bias_rules_satisfied",
                "decision_plan_digest": confirmation["decision_plan_digest"],
                "terminal_receipt_digest": confirmation["terminal_receipt_digest"],
            },
        },
    ]
    return _valid_bundle(
        scope="confirmation_campaign",
        execution_records=[
            _execution("baseline", "1"),
            _execution("baseline-copy", "2"),
            _execution("winner", "3"),
            _execution("bad-selector", "4", succeeded=False),
        ],
        campaign_history=history,
        confirmation=confirmation,
        receipt_chain=receipt_chain,
        conclusion=confirmation["conclusion"],
    )


def test_confirmation_scope_closes_result_identity_history_and_public_claim_status() -> None:
    bundle = _valid_confirmation_bundle()

    assert ss.report.verify_evidence_bundle(bundle)
    with pytest.raises(ss.report.EvidenceBundleError, match="cannot be claim eligible"):
        _valid_confirmation_bundle(claim_eligible=True)

    manifest = bundle.as_dict()
    manifest["campaign_history"][2]["payload"]["receipt_digest"] = _digest("f")
    manifest["content_digest"] = _content_digest(
        {key: value for key, value in manifest.items() if key != "content_digest"}
    )
    with pytest.raises(ss.report.EvidenceBundleError, match="receipt chain"):
        ss.report.EvidenceBundle.from_dict(manifest)


def test_failed_confirmation_cannot_claim_no_defensible_improvement() -> None:
    with pytest.raises(ss.report.EvidenceBundleError, match="cannot carry successful metrics|cannot support"):
        _valid_confirmation_bundle(
            status="crash",
            request_digest=_digest("1"),
            local_evidence_digest=None,
            metrics=None,
            uncertainty=None,
            failure_class="WorkerCrash",
            conclusion="no_defensible_improvement",
        )


def test_schema_one_manifests_fail_closed_and_new_bundles_are_schema_two() -> None:
    manifest = _valid_bundle().as_dict()
    manifest.pop("content_digest")
    for field in ("scope", "execution_records", "campaign_history", "receipt_chain"):
        manifest.pop(field)
    manifest["schema_version"] = "1"
    digest = _content_digest(manifest)

    with pytest.raises(ss.report.EvidenceBundleError, match="unsupported evidence schema version"):
        ss.report.EvidenceBundle.from_dict({**manifest, "content_digest": digest})

    assert _valid_bundle().payload["schema_version"] == "2"
