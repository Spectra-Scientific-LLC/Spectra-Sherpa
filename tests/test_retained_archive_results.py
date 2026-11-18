"""Offline result portability preserves original envelopes and exact port identity."""

import json
from dataclasses import replace

import pytest

from spectra_sherpa.app.schemas.execution_runs import ExecutionRunOut
from spectra_sherpa.app.schemas.run_evidence import OutputEvidence, RunEvidence
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.retained_archive_results import (
    RESULT_INDEX,
    ArchivedResults,
    ArchivedRun,
    capture_archived_runs,
    read_archived_output,
    read_archived_results,
    retained_output_member,
)
from spectra_sherpa.app.services.sherpa_object import ArchiveMember, build_archive


@pytest.fixture
def archived(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    value = {"sample": "one", "value": 1.23456789, "identity": 9007199254740993, "units": "mg/L", "role": "held_out"}
    evidence = retention.retain_output(7, value, role="record")
    encoded = retention.read_output_bytes(7, evidence)
    index = ArchivedResults(
        runs=(
            ArchivedRun(
                source_run_id=42,
                source_workflow_id=8,
                source_project_id=3,
                record_json='{"name":"Historical run","status":"completed"}',
                evidence=RunEvidence(
                    qualification="qualified",
                    reason=None,
                    outputs={
                        "absent": {
                            "record": evidence,
                            "missing": OutputEvidence(state="missing", reason="Not retained in the original run"),
                        }
                    },
                ),
            ),
        )
    )

    def archive(*, output=encoded, inventory=index.model_dump_json().encode()):
        return build_archive(
            project_payload={"name": "Historical project", "workflows": []},
            members=[
                ArchiveMember(RESULT_INDEX, inventory),
                ArchiveMember(retained_output_member(evidence.sha256), output),
            ],
        )

    return archive, encoded, index


def test_original_output_bytes_and_recorded_evidence_survive_archive(archived):
    archive, encoded, original = archived
    payload = archive()
    index = read_archived_results(payload, max_uncompressed_bytes=1024 * 1024)
    assert index == original
    assert index.inspection_only and index.prior_unrecorded_history == "unknown"
    received = read_archived_output(
        payload, run_id=42, node_id="absent", port="record", max_uncompressed_bytes=1024 * 1024
    )
    assert received == encoded
    assert b"9007199254740993" in received
    assert json.loads(received)["value"]["role"] == "held_out"


@pytest.mark.parametrize("port", ["default", "missing", "another"])
def test_missing_selected_port_never_falls_back_to_another_output(archived, port):
    archive, _, _ = archived
    with pytest.raises(ValueError, match="not retained"):
        read_archived_output(archive(), run_id=42, node_id="absent", port=port, max_uncompressed_bytes=1024 * 1024)


def test_rebuilt_zip_manifest_cannot_rebind_original_output_checksum(archived):
    archive, encoded, _ = archived
    changed = encoded.replace(b"1.23456789", b"9.23456789")
    with pytest.raises(ValueError, match="checksum"):
        read_archived_output(
            archive(output=changed), run_id=42, node_id="absent", port="record", max_uncompressed_bytes=1024 * 1024
        )


def test_duplicate_identity_or_json_key_is_refused(archived):
    archive, _, original = archived
    duplicate = original.model_dump(mode="json")
    duplicate["runs"] *= 2
    with pytest.raises(ValueError, match="source run identity"):
        read_archived_results(archive(inventory=json.dumps(duplicate).encode()), max_uncompressed_bytes=1024 * 1024)
    with pytest.raises(ValueError, match="repeats a JSON field"):
        read_archived_results(archive(inventory=b'{"runs":[],"runs":[]}'), max_uncompressed_bytes=1024 * 1024)


def test_total_decompression_budget_is_checked_before_results_are_read(archived):
    archive, _, _ = archived
    with pytest.raises(ValueError, match="verified retained-result"):
        read_archived_results(archive(), max_uncompressed_bytes=1)


def test_capture_uses_original_custody_and_never_marks_missing_outputs_exact(archived):
    _, encoded, original = archived
    run = ExecutionRunOut(
        id=42,
        project_id=3,
        workflow_id=8,
        workflow_version_id=None,
        user_id=7,
        name="Historical run",
        status="completed",
        params_snapshot={"absent": {"identity": 9007199254740993}},
        results_summary={},
        diagnostics=None,
        node_statuses=None,
        error=None,
        integrity_hash=None,
        executed_at="2026-11-18T00:00:00Z",
        created_at="2026-11-18T00:00:00Z",
        notes=None,
        evidence_completeness=original.runs[0].evidence,
    )
    index, members = capture_archived_runs((run,), max_bytes=1024 * 1024)
    output = index.runs[0].evidence.outputs["absent"]
    assert output["missing"].state == "missing"
    assert "9007199254740993" in index.runs[0].record_json
    assert next(member.data for member in members if member.path.startswith("retained-results/")) == encoded
    payload = build_archive(project_payload={"name": "Captured"}, members=members)
    assert (
        read_archived_output(payload, run_id=42, node_id="absent", port="record", max_uncompressed_bytes=1024 * 1024)
        == encoded
    )
    with pytest.raises(ValueError, match="byte limit"):
        capture_archived_runs((run,), max_bytes=1)
