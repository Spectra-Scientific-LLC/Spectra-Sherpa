"""Protected benchmark governance, promotion, and data-absence gates."""

from __future__ import annotations

import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from scripts.verify_protected_benchmarks import (
    BenchmarkGovernanceError,
    load_json,
    main,
    validate_preregistration,
    validate_registry,
    verify_protected_artifact_absence,
)

from spectra_sherpa.app.lib.reference_datasets import get_reference_dataset

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PACKAGE_ROOT / "benchmarks" / "protected-registry-v1.json"
REGISTRY_SCHEMA_PATH = PACKAGE_ROOT / "src" / "spectra_sherpa" / "contracts" / "protected_benchmark_registry_v1.json"
PREREGISTRATION_SCHEMA_PATH = (
    PACKAGE_ROOT / "src" / "spectra_sherpa" / "contracts" / "benchmark_preregistration_v1.json"
)


def _digest(character: str) -> str:
    return character * 64


@pytest.fixture(scope="module")
def registry_schema() -> dict:
    return load_json(REGISTRY_SCHEMA_PATH)


@pytest.fixture(scope="module")
def preregistration_schema() -> dict:
    return load_json(PREREGISTRATION_SCHEMA_PATH)


def _provisional_entry(**overrides) -> dict:
    entry = {
        "schema_version": "1",
        "benchmark_id": "pbm-lab-pls-001",
        "status": "provisional_internal",
        "artifact_attestations": {
            "canonicalization": "sealed-artifact-bytes-v1",
            "dataset_digest": _digest("a"),
            "labels_digest": _digest("b"),
            "development_split_digest": _digest("c"),
            "confirmation_split_digest": _digest("d"),
        },
        "provenance": {
            "source_class": "lab_owned",
            "provenance_ref": "urn:spectra:governance:provenance-001",
            "acquired_at": "2026-07-01T00:00:00Z",
        },
        "governance": {
            "steward_ref": "urn:spectra:actor:benchmark-steward",
            "custodian_ref": "urn:spectra:actor:data-custodian",
            "custody_policy_ref": "urn:spectra:governance:custody-policy-001",
            "access_policy_ref": "urn:spectra:governance:access-policy-001",
            "access_log_ref": "urn:spectra:governance:access-log-001",
            "confirmation_nonuse_attestation_digest": _digest("e"),
        },
        "protocol": {
            "protocol_ref": "urn:spectra:protocol:lab-pls-001",
            "protocol_digest": _digest("f"),
        },
        "allowed_uses": [
            "blind_confirmation_evaluation",
            "internal_architectural_evaluation",
            "reproducibility_audit",
        ],
        "prohibited_uses": [
            "workflow_development",
            "model_selection_tuning",
            "raw_data_repository_distribution",
            "public_performance_claims",
        ],
        "status_history": [
            {
                "from": None,
                "to": "provisional_internal",
                "actor_ref": "urn:spectra:actor:benchmark-steward",
                "decision_digest": _digest("1"),
                "effective_at": "2026-07-02T00:00:00Z",
            }
        ],
        "claim_review": None,
    }
    entry.update(overrides)
    return entry


def _registry(entry: dict | None = None) -> dict:
    return {
        "schema_version": "1",
        "registry_id": "spectra-protected-benchmarks-v1",
        "entries": [] if entry is None else [entry],
    }


def _claim_eligible_entry() -> dict:
    entry = _provisional_entry()
    entry["status"] = "claim_eligible"
    entry["allowed_uses"] = [
        "blind_confirmation_evaluation",
        "claim_eligible_performance_evaluation",
        "reproducibility_audit",
    ]
    entry["prohibited_uses"] = [
        "workflow_development",
        "model_selection_tuning",
        "raw_data_repository_distribution",
    ]
    entry["status_history"].append(
        {
            "from": "provisional_internal",
            "to": "claim_eligible",
            "actor_ref": "urn:spectra:actor:independent-reviewer",
            "decision_digest": _digest("2"),
            "effective_at": "2026-07-03T00:00:00Z",
        }
    )
    entry["claim_review"] = {
        "reviewer_ref": "urn:spectra:actor:independent-reviewer",
        "study_operator_ref": "urn:spectra:actor:study-operator",
        "review_digest": _digest("2"),
        "reviewed_at": "2026-07-03T00:00:00Z",
        "independent_of_study_operator": True,
    }
    return entry


def _preregistration(*, max_replacements: int = 2, intended_claim_class: str = "internal_architectural") -> dict:
    return {
        "schema_version": "1",
        "protocol_id": "urn:spectra:protocol:lab-pls-001",
        "frozen_at": "2026-07-04T00:00:00Z",
        "objective": {
            "task_type": "regression",
            "intended_use_ref": "urn:spectra:governance:intended-use-001",
            "target_population_ref": "urn:spectra:governance:population-001",
            "independent_unit": "specimen",
        },
        "benchmark": {
            "benchmark_id": "pbm-lab-pls-001",
            "development_split_digest": _digest("c"),
            "confirmation_split_digest": _digest("d"),
        },
        "primary_metric": {
            "metric_id": "rmsep",
            "registry_version": "1",
            "direction": "minimize",
            "minimum_meaningful_change": 0.05,
            "reproducibility_tolerance": 1e-10,
        },
        "uncertainty": {
            "method_id": "grouped_bootstrap",
            "method_version": "1",
            "confidence_level": 0.95,
        },
        "baselines": {
            "frozen": {
                "workflow_digest": _digest("4"),
                "evidence_digest": _digest("5"),
            },
            "transparent_grid": {
                "search_space_digest": _digest("6"),
                "execution_profile_digest": _digest("7"),
                "implementation_id": "spectra.pls_grid.v1",
            },
        },
        "search": {
            "allowed_space_digest": _digest("8"),
            "max_candidate_evaluations": 50,
            "max_wall_clock_seconds": 3600,
            "max_concurrent_evaluations": 2,
            "stopping_rule": {
                "kind": "no_improvement_patience",
                "value": 10,
            },
        },
        "confirmation": {
            "release_rule": "one_valid_aggregate_result",
            "max_replacements": max_replacements,
            "consume_on_failure": True,
            "replacement_policy_ref": "urn:spectra:governance:replacement-policy-001",
        },
        "permitted_interventions": [
            "pause",
            "resume",
            "terminate",
            "approve_infrastructure_replacement",
        ],
        "exclusion_policy_ref": "urn:spectra:governance:exclusion-policy-001",
        "intended_claim_class": intended_claim_class,
    }


def _bind_protocol(entry: dict, protocol: dict) -> str:
    document_digest = hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()
    entry["protocol"]["protocol_ref"] = protocol["protocol_id"]
    entry["protocol"]["protocol_digest"] = document_digest
    return document_digest


def test_published_schemas_are_valid_draft7(registry_schema: dict, preregistration_schema: dict) -> None:
    Draft7Validator.check_schema(registry_schema)
    Draft7Validator.check_schema(preregistration_schema)


def test_committed_registry_is_valid_and_honestly_empty(registry_schema: dict) -> None:
    registry = load_json(REGISTRY_PATH)

    validate_registry(registry, registry_schema)

    assert registry["entries"] == [], "P1 machinery must not fabricate the P2 protected-set evidence"


def test_provisional_entry_uses_only_opaque_refs_and_hashes(registry_schema: dict) -> None:
    validate_registry(_registry(_provisional_entry()), registry_schema)


def test_registry_rejects_locations_credentials_and_unknown_fields(registry_schema: dict) -> None:
    entry = _provisional_entry()
    entry["provenance"]["storage_path"] = "/srv/protected/raw.npz"
    entry["governance"]["access_policy_ref"] = "https://lab.example/protected?token=secret"

    with pytest.raises(BenchmarkGovernanceError, match="invalid protected benchmark registry"):
        validate_registry(_registry(entry), registry_schema)


def test_public_fixture_cannot_be_relabelled_as_protected(registry_schema: dict) -> None:
    public_fixture = get_reference_dataset("public-atmospheric-regression-v1").as_dict()

    with pytest.raises(BenchmarkGovernanceError, match="invalid protected benchmark registry"):
        validate_registry(_registry(public_fixture), registry_schema)


def test_claim_eligible_requires_transition_history_and_independent_review(registry_schema: dict) -> None:
    validate_registry(_registry(_claim_eligible_entry()), registry_schema)

    status_only_edit = _claim_eligible_entry()
    status_only_edit["status_history"] = _provisional_entry()["status_history"]
    with pytest.raises(BenchmarkGovernanceError, match="does not match status history"):
        validate_registry(_registry(status_only_edit), registry_schema)

    non_independent = _claim_eligible_entry()
    non_independent["claim_review"]["independent_of_study_operator"] = False
    with pytest.raises(BenchmarkGovernanceError, match="independent_of_study_operator"):
        validate_registry(_registry(non_independent), registry_schema)

    self_reviewed = _claim_eligible_entry()
    self_reviewed["claim_review"]["reviewer_ref"] = self_reviewed["governance"]["steward_ref"]
    self_reviewed["status_history"][-1]["actor_ref"] = self_reviewed["governance"]["steward_ref"]
    with pytest.raises(BenchmarkGovernanceError, match="must be independent"):
        validate_registry(_registry(self_reviewed), registry_schema)


def test_preregistration_enforces_contract_replacement_ceiling(preregistration_schema: dict) -> None:
    validate_preregistration(_preregistration(max_replacements=2), preregistration_schema)

    with pytest.raises(BenchmarkGovernanceError, match="greater than the maximum of 2"):
        validate_preregistration(_preregistration(max_replacements=3), preregistration_schema)


def test_public_performance_protocol_requires_claim_eligible_entry(
    registry_schema: dict,
    preregistration_schema: dict,
) -> None:
    protocol = _preregistration(intended_claim_class="public_performance")
    provisional_entry = _provisional_entry()
    provisional_digest = _bind_protocol(provisional_entry, protocol)
    provisional_registry = _registry(provisional_entry)
    validate_registry(provisional_registry, registry_schema)

    with pytest.raises(BenchmarkGovernanceError, match="requires a claim_eligible benchmark"):
        validate_preregistration(
            protocol,
            preregistration_schema,
            registry=provisional_registry,
            document_digest=provisional_digest,
        )

    claim_entry = _claim_eligible_entry()
    claim_digest = _bind_protocol(claim_entry, protocol)
    claim_registry = _registry(claim_entry)
    validate_registry(claim_registry, registry_schema)
    validate_preregistration(
        protocol,
        preregistration_schema,
        registry=claim_registry,
        document_digest=claim_digest,
    )


def test_preregistration_requires_exact_registry_protocol_binding(
    registry_schema: dict,
    preregistration_schema: dict,
) -> None:
    protocol = _preregistration()
    entry = _provisional_entry()
    document_digest = _bind_protocol(entry, protocol)
    registry = _registry(entry)
    validate_registry(registry, registry_schema)

    validate_preregistration(
        protocol,
        preregistration_schema,
        registry=registry,
        document_digest=document_digest,
    )

    with pytest.raises(BenchmarkGovernanceError, match="exact document digest"):
        validate_preregistration(protocol, preregistration_schema, registry=registry)
    with pytest.raises(BenchmarkGovernanceError, match="protocol_digest"):
        validate_preregistration(
            protocol,
            preregistration_schema,
            registry=registry,
            document_digest=_digest("9"),
        )

    wrong_protocol = deepcopy(protocol)
    wrong_protocol["protocol_id"] = "urn:spectra:protocol:other-pls-study"
    with pytest.raises(BenchmarkGovernanceError, match="protocol_id"):
        validate_preregistration(
            wrong_protocol,
            preregistration_schema,
            registry=registry,
            document_digest=document_digest,
        )


def test_absence_gate_detects_raw_protected_artifact(tmp_path: Path, registry_schema: dict) -> None:
    protected_bytes = b"sealed protected spectra fixture"
    raw_path = tmp_path / "raw-protected.npz"
    raw_path.write_bytes(protected_bytes)
    entry = _provisional_entry()
    entry["artifact_attestations"]["dataset_digest"] = hashlib.sha256(protected_bytes).hexdigest()
    registry = _registry(entry)
    validate_registry(registry, registry_schema)

    with pytest.raises(BenchmarkGovernanceError, match="raw-protected.npz"):
        verify_protected_artifact_absence(registry, [tmp_path])


def test_absence_gate_detects_protected_member_in_built_archive(
    tmp_path: Path,
    registry_schema: dict,
) -> None:
    protected_labels = b"sample_id,target\nsecret,1.0\n"
    archive_path = tmp_path / "spectra_sherpa-1-py3-none-any.whl"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("spectra_sherpa/data/protected-labels.csv", protected_labels)
    entry = _provisional_entry()
    entry["artifact_attestations"]["labels_digest"] = hashlib.sha256(protected_labels).hexdigest()
    registry = _registry(entry)
    validate_registry(registry, registry_schema)

    with pytest.raises(BenchmarkGovernanceError, match=r"whl!spectra_sherpa/data/protected-labels.csv"):
        verify_protected_artifact_absence(registry, [archive_path])


def test_repository_verifier_runs_against_committed_empty_registry(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--package-root", str(PACKAGE_ROOT), "--scan-root", str(PACKAGE_ROOT)]) == 0
    assert "0 entries" in capsys.readouterr().out


def test_registry_revalidation_detects_caller_mutation(registry_schema: dict) -> None:
    entry = _provisional_entry()
    registry = _registry(entry)
    validate_registry(deepcopy(registry), registry_schema)
    entry["artifact_attestations"]["dataset_digest"] = "not-a-digest"

    with pytest.raises(BenchmarkGovernanceError, match="dataset_digest"):
        validate_registry(registry, registry_schema)
