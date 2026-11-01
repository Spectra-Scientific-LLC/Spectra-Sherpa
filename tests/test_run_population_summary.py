"""Retained source curation projections, independent of labels/live workflow."""

import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.workflow_population import source_population_outputs
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services import run_population_summary as summary
from spectra_sherpa.app.services.run_validation_summary import validation_summary


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    with summary._count_cache_lock:
        summary._count_cache.clear()


def saved_run(node="load", user_id=1):
    dataset = SherpaDataset(
        np.arange(24.0).reshape(6, 4),
        sample_axis=SampleAxis(
            count=6,
            labels=["duplicate"] * 6,
            include_mask=[False, True, True, True, True, True],
            sample_table={"sample_id": [f"identity-{i}" for i in range(6)]},
        ),
    )
    initial = source_population_outputs(dataset, node_id=node)["exclusions"]
    decision = {
        "source_digest": initial["source_digest"],
        "excluded_refs": [initial["rows"][i]["observation_ref"] for i in [0, 4]],
    }
    state = source_population_outputs(dataset, node_id=node, exclusions=decision)["exclusions"]
    definition = {
        "schema_version": 1,
        "nodes": [{"node_id": node, "node_type": "data.file_load", "parameters": {}}],
        "edges": [],
    }
    run = SimpleNamespace(
        id=42,
        user_id=user_id,
        status="completed",
        diagnostics={},
        source_metadata={},
        params_snapshot={node: {"workflow_exclusions": decision}},
        evidence_completeness=retention.retain_run_outputs(
            user_id,
            {
                "__workflow__": {"definition": definition},
                node: {"exclusions": state},
            },
            {},
        ),
    )
    return run, state, definition


def test_summary_and_report_share_retained_counts_and_exact_map_without_row_copy():
    run, state, definition = saved_run()
    before = copy.deepcopy(vars(run))
    files = {p: p.read_bytes() for p in retention._user_directory(1).glob("*.json")}
    result = summary.retained_population_summary(run)
    source = result["sources"][0]
    assert {
        key: source[key]
        for key in (
            "source_count",
            "active_count",
            "excluded_count",
            "source_excluded_count",
            "workflow_excluded_count",
        )
    } == {
        "source_count": 6,
        "active_count": 4,
        "excluded_count": 2,
        "source_excluded_count": 1,
        "workflow_excluded_count": 2,
    }
    assert source["source_digest"] == state["source_digest"]
    assert source["output_sha256"] == run.evidence_completeness["outputs"]["load"]["exclusions"]["sha256"]
    assert "duplicate" not in json.dumps(result) and "identity-" not in json.dumps(result)
    assert "observation_ref" not in json.dumps(result)
    report = validation_summary(run, definition)
    for row in result["rows"]:
        assert row in report["summary_rows"]
        assert {**row, "row_level": False} in report["rows"]
    assert vars(run) == before
    assert {p: p.read_bytes() for p in files} == files


@pytest.mark.parametrize(
    "damage", ["missing", "reduced", "checksum", "count", "mapping", "flags", "reference", "params", "unsupported"]
)
def test_unavailable_never_means_zero_exclusions(damage):
    run, state, _ = saved_run()
    item = run.evidence_completeness["outputs"]["load"]["exclusions"]
    if damage == "missing":
        del run.evidence_completeness["outputs"]["load"]["exclusions"]
    elif damage == "reduced":
        item.update(state="reduced", reason="preview only")
    elif damage == "checksum":
        (retention._user_directory(1) / f"{item['sha256']}.json").write_text("{}")
    elif damage == "params":
        run.params_snapshot["load"]["workflow_exclusions"]["excluded_refs"] = []
    else:
        if damage == "count":
            state["active_count"] = 5
        elif damage == "mapping":
            state["rows"][1]["result_row"] = 2
        elif damage == "flags":
            state["rows"][0]["included"] = True
        elif damage == "reference":
            state["rows"][0]["observation_ref"] = state["rows"][1]["observation_ref"]
        elif damage == "unsupported":
            state["schema_version"] = "unknown"
        run.evidence_completeness["outputs"]["load"]["exclusions"] = retention.retain_output(1, state).model_dump()
    source = summary.retained_population_summary(run)["sources"][0]
    assert source["availability"] == "unavailable"
    assert "active_count" not in source and "output_sha256" not in source


def test_old_records_never_borrow_current_labels_or_settings():
    run = SimpleNamespace(
        id=1,
        user_id=1,
        params_snapshot={},
        evidence_completeness=None,
        results_summary={"load": {"labels": ["excluded"]}},
    )
    result = summary.retained_population_summary(run)
    assert result["sources"] == []
    assert "zero exclusions cannot be inferred" in json.dumps(result)


def test_saved_definition_finds_source_without_inventory_or_parameters():
    run, _, _ = saved_run()
    run.params_snapshot = {}
    del run.evidence_completeness["outputs"]["load"]
    source = summary.retained_population_summary(run)["sources"][0]
    assert source["node_id"] == "load" and source["availability"] == "unavailable"


def test_exact_state_without_historical_params_still_has_its_own_authority():
    run, _, _ = saved_run()
    run.params_snapshot = {}
    assert summary.retained_population_summary(run)["sources"][0]["active_count"] == 4


def test_explicit_zero_is_distinct_from_unavailable_and_labels_are_not_decisions():
    run, state, _ = saved_run()
    dataset = SherpaDataset(np.ones((2, 3)), sample_axis=SampleAxis(count=2, labels=["excluded", "excluded"]))
    state = source_population_outputs(dataset, node_id="load")["exclusions"]
    run.params_snapshot = {"load": {"workflow_exclusions": None}}
    run.evidence_completeness["outputs"]["load"]["exclusions"] = retention.retain_output(1, state).model_dump()
    source = summary.retained_population_summary(run)["sources"][0]
    assert source["availability"] == "available"
    assert source["excluded_count"] == source["workflow_excluded_count"] == 0
    assert source["active_count"] == 2


def test_source_map_limit_and_unavailable_canonical_receipt():
    run, state, _ = saved_run()
    state.update(availability="unavailable", rows=[], reason="N-D source cannot supply a sample map")
    run.evidence_completeness["outputs"]["load"]["exclusions"] = retention.retain_output(1, state).model_dump()
    for i in range(33):
        run.evidence_completeness["outputs"][f"missing-{i:02}"] = {
            "exclusions": {"state": "missing", "reason": "quota"},
        }
    result = summary.retained_population_summary(run)
    assert len(result["sources"]) == 32
    assert all(source["availability"] == "unavailable" for source in result["sources"])
    assert "Summary limited to 32 sources" in json.dumps(result)


def test_sources_are_separate_and_reads_are_bounded(monkeypatch):
    run, _, _ = saved_run()
    other, _, _ = saved_run("other")
    run.evidence_completeness["outputs"]["other"] = other.evidence_completeness["outputs"]["other"]
    result = summary.retained_population_summary(run)
    assert [source["node_id"] for source in result["sources"]] == ["load", "other"]
    monkeypatch.setattr(summary, "SUMMARY_BYTES", 1)
    monkeypatch.setattr(summary, "read_output", lambda *args: pytest.fail("budget must be checked before any read"))
    assert all(
        source["availability"] == "unavailable" for source in summary.retained_population_summary(run)["sources"]
    )


@pytest.mark.asyncio
async def test_owned_run_endpoint_and_output_expose_same_immutable_map(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes.runs import get_retained_run_output, inspect_run_evidence
    from spectra_sherpa.app.models.execution_run import ExecutionRun

    saved, state, _ = saved_run(user_id=test_user.id)
    run = ExecutionRun(
        executed_at=datetime.now(timezone.utc),
        user_id=test_user.id,
        name="Retained exclusions",
        status="completed",
        run_kind="data",
        params_snapshot=saved.params_snapshot,
        evidence_completeness=saved.evidence_completeness,
        results_summary={},
    )
    test_session.add(run)
    await test_session.commit()
    response = await inspect_run_evidence(run.id, project_id=None, session=test_session, current_user=test_user)
    assert response["population_summary"]["run_id"] == run.id
    assert response["population_summary"]["sources"][0]["active_count"] == 4
    output = await get_retained_run_output(
        run.id, "load", "exclusions", project_id=None, session=test_session, current_user=test_user
    )
    assert output["value"] == state
    await test_session.refresh(run)
    assert run.evidence_completeness == saved.evidence_completeness


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["owned", "other_project", "other_owner"])
async def test_http_evidence_with_deferred_owner_uses_admitted_snapshot(
    auth_client, test_session, test_user, monkeypatch, scope
):
    import threading

    from sqlalchemy import inspect

    from spectra_sherpa.app.api.v1.routes import runs
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.user import User

    other = User(username="other-population-owner")
    project = Project(user_id=test_user.id, name="Retained source")
    other_project = Project(user_id=test_user.id, name="Other source")
    test_session.add_all([other, project, other_project])
    await test_session.flush()
    owner_id = other.id if scope == "other_owner" else test_user.id
    saved, _, _ = saved_run(user_id=owner_id)
    run = ExecutionRun(
        executed_at=datetime.now(timezone.utc),
        user_id=owner_id,
        project_id=project.id,
        name="Deferred owner",
        status="completed",
        run_kind="data",
        params_snapshot=saved.params_snapshot,
        evidence_completeness=saved.evidence_completeness,
        results_summary={},
    )
    test_session.add(run)
    await test_session.commit()
    run_id = run.id
    test_session.expunge(run)  # A new HTTP request cannot reuse an already-loaded owner.
    admitted = []
    received = []
    request_thread = threading.get_ident()
    original_owned = runs._owned_run
    original_summary = summary.retained_population_summary

    def capture_input(value):
        received.append((value, threading.get_ident()))
        return original_summary(value)

    async def check_deferred(*args, **kwargs):
        record = await original_owned(*args, **kwargs)
        assert "user_id" in inspect(record).unloaded
        admitted.append(record)
        return record

    monkeypatch.setattr(runs, "_owned_run", check_deferred)
    monkeypatch.setattr(summary, "retained_population_summary", capture_input)
    files_before = {p: p.read_bytes() for p in retention._user_directory(owner_id).glob("*.json")}
    if scope != "owned":
        monkeypatch.setattr(summary, "read_output", lambda *args: pytest.fail("unowned source must not be read"))
    response = await auth_client.get(
        f"/api/v1/runs/{run_id}/evidence",
        params={"project_id": other_project.id if scope == "other_project" else project.id},
    )
    if scope == "owned":
        assert response.status_code == 200, response.text
        result = response.json()["population_summary"]
        assert result["run_id"] == run_id
        source = result["sources"][0]
        assert source["availability"] == "available"
        assert (source["source_count"], source["active_count"], source["excluded_count"]) == (6, 4, 2)
        assert source["output_sha256"] == saved.evidence_completeness["outputs"]["load"]["exclusions"]["sha256"]
        assert "user_id" in inspect(admitted[0]).unloaded
        assert admitted[0].evidence_completeness == saved.evidence_completeness
        assert admitted[0].params_snapshot == saved.params_snapshot
        snapshot, worker_thread = received[0]
        assert isinstance(snapshot, summary.RetainedPopulationInput)
        assert worker_thread != request_thread
        assert snapshot.user_id == test_user.id
        assert snapshot.evidence_completeness == admitted[0].evidence_completeness
        assert snapshot.evidence_completeness is not admitted[0].evidence_completeness
        assert snapshot.params_snapshot["load"] is not admitted[0].params_snapshot["load"]
    else:
        assert response.status_code == 404
        assert admitted == []
        assert received == []
    assert {p: p.read_bytes() for p in files_before} == files_before


def test_definition_cap_does_not_spend_the_source_map_budget(monkeypatch):
    run, _, _ = saved_run()
    item = run.evidence_completeness["outputs"]["__workflow__"]["definition"]
    item["byte_count"] = summary.SUMMARY_BYTES
    read = summary.read_output
    opened = []

    def checked_read(owner, evidence):
        opened.append(evidence.sha256)
        assert evidence.sha256 != item["sha256"], "Oversized definition must not be opened"
        return read(owner, evidence)

    monkeypatch.setattr(summary, "read_output", checked_read)
    result = summary.retained_population_summary(run)
    assert result["sources"][0]["availability"] == "available"
    assert result["sources"][0]["active_count"] == 4
    assert len(opened) == 1
    assert "source coverage cannot be established" in json.dumps(result)


def test_definition_snapshot_is_bounded_bound_and_isolated(monkeypatch):
    from spectra_sherpa.app.api.v1.routes.workflow_export import _saved_report_definition
    from spectra_sherpa.app.schemas.run_evidence import OutputEvidence

    run, _, definition = saved_run()
    reader = summary.RetainedDefinitionRead()
    read = summary.read_output
    opened = []

    def checked_read(owner, item):
        opened.append((owner, item.sha256))
        return read(owner, item)

    monkeypatch.setattr(summary, "read_output", checked_read)
    item = OutputEvidence.model_validate(run.evidence_completeness["outputs"]["__workflow__"]["definition"])
    returned = reader.read(run.user_id, item)
    returned["nodes"].clear()
    assert _saved_report_definition(run, definition_read=reader) == definition
    result = summary.retained_population_summary(run, definition_read=reader)
    assert result["sources"][0]["availability"] == "available"
    assert opened.count((run.user_id, item.sha256)) == 1
    # Same SHA with a changed receipt must be revalidated, not hit the snapshot.
    changed = item.model_copy(update={"byte_count": item.byte_count + 1})
    with pytest.raises(ValueError, match="checksum"):
        reader.read(run.user_id, changed)
    with pytest.raises(FileNotFoundError):
        reader.read(999, item)
    # A new request must not reuse this request's successful read.
    (retention._user_directory(run.user_id) / f"{item.sha256}.json").unlink()
    assert _saved_report_definition(run) is None


@pytest.mark.parametrize("damage", ["same_size_tamper", "missing", "symlink"])
def test_warm_counts_still_detect_current_storage_damage(damage, monkeypatch):
    import os

    run, _, _ = saved_run()
    assert summary.retained_population_summary(run)["sources"][0]["availability"] == "available"
    item = run.evidence_completeness["outputs"]["load"]["exclusions"]
    path = retention._user_directory(run.user_id) / f"{item['sha256']}.json"
    payload, stat = path.read_bytes(), path.stat()
    if damage == "same_size_tamper":
        altered = payload.replace(b'"source_count":6', b'"source_count":9')
        assert altered != payload and len(altered) == len(payload)
        path.write_bytes(altered)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif damage == "missing":
        path.unlink()
    else:
        target = path.with_suffix(".backup")
        path.rename(target)
        path.symlink_to(target)
    monkeypatch.setattr(summary, "_counts", lambda *args: pytest.fail("warm counts require verified current bytes"))
    assert summary.retained_population_summary(run)["sources"][0]["availability"] == "unavailable"
    if path.is_symlink():
        path.unlink()
    path.write_bytes(payload)
    assert summary.retained_population_summary(run)["sources"][0]["availability"] == "available"


def test_count_cache_binds_owner_receipt_node_and_parameters_and_has_finite_size(monkeypatch):
    run, _, _ = saved_run()
    read, count = summary.read_output, summary._counts
    opened, validated = [], []

    def checked_read(owner, item):
        opened.append((owner, item.sha256))
        return read(owner, item)

    def checked_count(value, node, params):
        validated.append(node)
        return count(value, node, params)

    monkeypatch.setattr(summary, "read_output", checked_read)
    monkeypatch.setattr(summary, "_counts", checked_count)
    monkeypatch.setattr(summary, "COUNT_CACHE_ENTRIES", 2)
    first = summary.retained_population_summary(run)
    first["sources"][0]["active_count"] = -1
    run.id += 1  # Immutable inputs may share counts; run-specific result must not be cached.
    again = summary.retained_population_summary(run)
    assert again["run_id"] == run.id and again["sources"][0]["active_count"] == 4
    assert len(validated) == 1 and len(opened) == 4
    other, _, _ = saved_run(user_id=2)
    assert summary.retained_population_summary(other)["sources"][0]["active_count"] == 4
    assert len(validated) == 2
    run.params_snapshot["load"]["workflow_exclusions"]["excluded_refs"] = []
    assert summary.retained_population_summary(run)["sources"][0]["availability"] == "unavailable"
    assert len(validated) == 3  # Failed validation is never cached.
    assert summary.retained_population_summary(run)["sources"][0]["availability"] == "unavailable"
    assert len(validated) == 4
    moved, _, _ = saved_run()
    moved.evidence_completeness["outputs"]["wrong"] = moved.evidence_completeness["outputs"].pop("load")
    moved.params_snapshot = {}
    assert all(s["availability"] == "unavailable" for s in summary.retained_population_summary(moved)["sources"])
    for revision in range(3):
        other.params_snapshot["load"]["revision"] = revision
        assert summary.retained_population_summary(other)["sources"][0]["availability"] == "available"
    assert len(summary._count_cache) == 2
    assert all(len(key) == 64 for key in summary._count_cache)
    assert all(all(isinstance(v, (str, int)) for v in value.values()) for value in summary._count_cache.values())
    validations_before = len(validated)
    other.params_snapshot["load"]["revision"] = 0  # Evicted by revisions 1 and 2.
    summary.retained_population_summary(other)
    assert len(validated) == validations_before + 1
    summary.retained_population_summary(other)
    assert len(validated) == validations_before + 1


def test_warm_counts_do_not_ignore_a_changed_receipt(monkeypatch):
    from unittest.mock import Mock

    run, _, _ = saved_run()
    count = Mock(wraps=summary._counts)
    monkeypatch.setattr(summary, "_counts", count)
    summary.retained_population_summary(run)
    item = run.evidence_completeness["outputs"]["load"]["exclusions"]
    item["role"] = "amended-receipt-role"
    assert summary.retained_population_summary(run)["sources"][0]["availability"] == "available"
    assert count.call_count == 2
    item["byte_count"] += 1
    assert summary.retained_population_summary(run)["sources"][0]["availability"] == "unavailable"
    assert count.call_count == 2
