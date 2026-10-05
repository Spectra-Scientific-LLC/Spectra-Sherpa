"""Known recorded overlap outranks declarations; absent identities remain unknown."""

import pytest

from spectra_sherpa.sdk.validation_independence import assess_independence


def evidence(ids, namespace="lab", batches=None):
    return {
        "schema_version": "spectrasherpa.recorded-independence/1",
        "populations": [
            {
                "role": "fit",
                "namespace": namespace,
                "specimen_ids": ids,
                "batch_ids": batches,
                "source_description": "Recorded calibration register",
            }
        ],
    }


def assess(record=None, declared=False):
    return assess_independence(specimen_ids=["v1", "v2"], namespace="lab", declaration=declared, evidence=record)


def test_absent_ids_are_never_compared_against_recorded_lists():
    assert assess()["identity_separation_status"] == "unknown"
    assert assess(declared=True)["identity_separation_status"] == "operator_declared"


def test_disjoint_ids_verify_only_the_recorded_role_not_sampling():
    result = assess(evidence(["c1", "c2"]))
    assert result["identity_separation_status"] == "compared_against_recorded_lists"
    assert result["verified_roles"] == ["fit"]
    assert result["unverified_roles"] == ["interval_calibration", "selection"]
    assert result["sampling_independence_status"] == "unknown"


def test_different_namespaces_are_not_evidence_of_separation():
    result = assess(evidence(["v1"], namespace="another-lab"))
    assert result["identity_separation_status"] == "unknown"
    assert result["comparisons"][0]["specimens_separate"] is None


def test_known_overlap_survives_positive_declaration():
    result = assess(evidence(["v1"]), declared=True)
    assert result["known_specimen_overlap"] is True


def test_batch_overlap_detected_with_distinct_specimens():
    record = evidence(["c1"], batches=["lot1"])
    record["validation_batches"] = {"v1": "lot1", "v2": "lot2"}
    result = assess(record)
    assert not result["known_specimen_overlap"]
    assert result["known_batch_overlap"]


def test_incomplete_batch_map_refuses_instead_of_dropping_rows():
    record = evidence(["c1"], batches=["lot1"])
    record["validation_batches"] = {"v1": "lot2"}
    with pytest.raises(ValueError, match="omits"):
        assess(record)


def test_declared_chronology_does_not_become_compared_against_recorded_lists():
    record = evidence(["c1"])
    record.update(model_frozen_at="2026-01-03T00:00:00Z", validation_acquired_from="2026-01-01T00:00:00Z")
    result = assess(record)
    assert result["chronology"]["status"] == "operator_declared"
    assert result["chronology"]["model_frozen_before_acquisition"] is False
