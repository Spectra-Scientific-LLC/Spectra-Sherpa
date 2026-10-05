"""Tests for the sample-free canonical remote summary."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.canonical_summary import CanonicalRemoteSummary, CanonicalRemoteSummaryError
from tests.test_canonical_capsule import _capsule


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _redigest(payload: dict) -> None:
    import spectra_sherpa.sdk.canonical_summary as contract

    payload["summary_digest"] = contract._digest(
        {key: value for key, value in payload.items() if key != "summary_digest"}
    )


def test_summary_is_a_bounded_sample_free_projection_of_the_verified_capsule() -> None:
    capsule = _capsule()
    summary = CanonicalRemoteSummary.from_capsule(capsule)
    loaded = CanonicalRemoteSummary.from_bytes(summary.canonical_bytes())

    loaded.require_matches(capsule)
    assert loaded.payload["capsule_digest"] == capsule.capsule_digest
    assert loaded.payload["metrics"] == capsule.execution_evidence.payload["validation_execution"]["metrics"]
    assert [node["operation_id"] for node in loaded.payload["nodes"]] == [
        node.operation_id for node in capsule.graph.nodes
    ]
    assert loaded.payload["application_refit"] == {"status": "not_materialized"}
    encoded = loaded.canonical_bytes().decode()
    for forbidden in (
        "dataset_content_digest",
        "dataset_ref_digest",
        "capability_digest",
        '"parameters"',
        '"role_envelopes"',
        '"target"',
        '"predictions"',
        "fitted_state_digest",
        "dataset_path",
        "/Users/",
    ):
        assert forbidden not in encoded


def test_summary_carries_only_bounded_identity_for_a_materialized_application_refit() -> None:
    capsule = _capsule(materialize_refit=True)
    summary = CanonicalRemoteSummary.from_capsule(capsule)
    loaded = CanonicalRemoteSummary.from_bytes(summary.canonical_bytes())

    refit = loaded.payload["application_refit"]
    assert refit["status"] == "materialized"
    assert refit["full_refit_evidence_digest"] == capsule.full_refit_evidence.content_digest
    assert refit["fitted_state_node_ids"] == ["scale", "model"]
    assert "metrics" not in refit
    encoded = summary.canonical_bytes().decode()
    for forbidden in ("predictions", '"target"', "fitted_state_bytes", "file://", "/Users/"):
        assert forbidden not in encoded


def test_summary_mutation_cannot_match_the_source_capsule() -> None:
    capsule = _capsule()
    payload = deepcopy(CanonicalRemoteSummary.from_capsule(capsule).as_dict())
    payload["metrics"]["rmse"] += 0.1
    _redigest(payload)
    changed = CanonicalRemoteSummary.from_dict(payload)

    with pytest.raises(CanonicalRemoteSummaryError, match="differs"):
        changed.require_matches(capsule)


@pytest.mark.parametrize("field", ["raw_spectra", "secret", "dataset_path", "python_source"])
def test_summary_rejects_any_undeclared_egress_field(field: str) -> None:
    payload = CanonicalRemoteSummary.from_capsule(_capsule()).as_dict()
    payload[field] = "forbidden"
    _redigest(payload)

    with pytest.raises(CanonicalRemoteSummaryError, match="fields are closed"):
        CanonicalRemoteSummary.from_dict(payload)


def test_summary_rejects_duplicate_noncanonical_and_oversized_bytes() -> None:
    summary = CanonicalRemoteSummary.from_capsule(_capsule())
    with pytest.raises(CanonicalRemoteSummaryError, match="canonical JSON"):
        CanonicalRemoteSummary.from_bytes((summary.canonical_bytes() + b"\n"))
    with pytest.raises(CanonicalRemoteSummaryError, match="repeats field"):
        CanonicalRemoteSummary.from_bytes(
            b'{"summary_digest":"' + b"0" * 64 + b'","summary_digest":"' + b"0" * 64 + b'"}'
        )
    with pytest.raises(CanonicalRemoteSummaryError, match="size"):
        CanonicalRemoteSummary.from_bytes(b"x" * (64 * 1024 + 1))


def test_summary_rejects_self_rehashed_semantic_contradictions() -> None:
    wrong_role = CanonicalRemoteSummary.from_capsule(_capsule()).as_dict()
    wrong_role["dataset_role"] = "development"
    _redigest(wrong_role)
    with pytest.raises(CanonicalRemoteSummaryError, match="inconsistent"):
        CanonicalRemoteSummary.from_dict(wrong_role)

    impossible_metric = CanonicalRemoteSummary.from_capsule(_capsule()).as_dict()
    impossible_metric["metrics"]["mae"] = impossible_metric["metrics"]["rmse"] + 1
    _redigest(impossible_metric)
    with pytest.raises(CanonicalRemoteSummaryError, match="cannot exceed"):
        CanonicalRemoteSummary.from_dict(impossible_metric)
