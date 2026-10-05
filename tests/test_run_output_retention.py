import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pytest

from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.serialization import serialize_result
from tests.run_evidence_cases import executed_cases, reference_matrix


@pytest.fixture(autouse=True)
def output_store(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))


def test_exact_output_roundtrip_and_checksum():
    value = {"matrix": [[1.0, 2.0]], "labels": ["sample-a"], "units": "cm-1"}
    evidence = retention.retain_output(1, value)
    assert evidence.state == "exact"
    assert retention.read_output(1, evidence) == value
    path = retention._user_directory(1) / f"{evidence.sha256}.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        retention.read_output(1, evidence)


def test_quota_cache_avoids_repeated_directory_walks(monkeypatch):
    from pathlib import Path

    retention.retain_output(1, {"value": 0})
    directory = retention._user_directory(1)
    original = Path.iterdir

    def forbid_walk(path):
        if path == directory:
            raise AssertionError("unchanged output directory was rescanned")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", forbid_walk)
    for index in range(1, 100):
        retention.retain_output(1, {"value": index})


def test_retention_refuses_symlink_without_subtracting_its_target_size(tmp_path):
    value = {"value": 1}
    evidence = retention.retain_output(1, value)
    path = retention._user_directory(1) / f"{evidence.sha256}.json"
    path.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text("outside")
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        retention.retain_output(1, value)
    assert outside.read_text() == "outside"


def test_quota_cache_recovers_after_interrupted_update(monkeypatch):
    retention.retain_output(1, {"value": 0})
    original = retention._save_storage_usage
    monkeypatch.setattr(retention, "_save_storage_usage", lambda *args: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError, match="crash"):
        retention.retain_output(1, {"value": "x" * 100})
    monkeypatch.setattr(retention, "_save_storage_usage", original)
    directory = retention._user_directory(1)
    with retention._storage_lock(directory):
        used, _ = retention._storage_usage(directory)
    expected = sum(path.stat().st_size for path in directory.iterdir() if path.is_file())
    assert used == expected
    monkeypatch.setattr(retention, "USER_BYTES_LIMIT", used)
    with pytest.raises(ValueError, match="user quota"):
        retention.retain_output(1, {"value": "new"})


def test_quota_cache_reconciles_after_cleanup_and_corruption():
    first = retention.retain_output(1, {"value": 1})
    retention.retain_output(1, {"value": 2})
    directory = retention._user_directory(1)
    old = directory / f"{first.sha256}.json"
    os.utime(old, (0, 0))
    assert retention.prune_unreferenced_outputs(1, set()) == 1
    (directory / ".quota" / "state.json").write_text("not json")
    retention.retain_output(1, {"value": 3})
    with retention._storage_lock(directory):
        used, _ = retention._storage_usage(directory)
    assert used == sum(path.stat().st_size for path in directory.iterdir() if path.is_file())


def test_budget_prioritizes_definition_and_selection_over_node_outputs(monkeypatch):
    monkeypatch.setattr(retention, "RUN_BYTES_LIMIT", 2500)
    results = {f"node-{i}": {"default": "x" * 600} for i in range(6)}
    results["__application__"] = {"input": "x" * 600, "selection": {"sample_indices": [1, 3]}}
    results["__workflow__"] = {"definition": {"schema_version": 1, "nodes": [], "edges": []}}
    evidence = RunEvidence.model_validate(retention.retain_run_outputs(1, results, {}))
    assert evidence.outputs["__workflow__"]["definition"].state == "exact"
    assert evidence.outputs["__application__"]["selection"].state == "exact"
    assert evidence.outputs["__application__"]["input"].state == "exact"
    assert evidence.outputs["node-5"]["default"].state != "exact"


def test_dictionary_default_and_private_port_omissions_are_explicit():
    from spectra_sherpa.app.services.dag.node_base import NodeResult

    result = NodeResult(outputs={"default": {"_sample_id": "A", "score": 3}, "_runtime": object()})
    evidence = RunEvidence.model_validate(retention.retain_run_outputs(1, {"node": result.outputs}, {}))
    ports = evidence.outputs["node"]
    assert set(ports) == {"default", "_runtime"}
    assert retention.read_output(1, ports["default"]) == {"_sample_id": "A", "score": 3}
    assert ports["_runtime"].state == "missing"
    assert "excluded by policy" in ports["_runtime"].reason
    assert ports["_runtime"].storage is None


def test_unexpected_serialization_failure_does_not_destroy_run_evidence(monkeypatch):
    def fail_serialization(*_args, **_kwargs):
        raise RuntimeError("unexpected serializer failure")

    monkeypatch.setattr("spectra_sherpa.app.services.serialization.serialize_result", fail_serialization)
    evidence = RunEvidence.model_validate(retention.retain_run_outputs(1, {"node": {"default": [1]}}, {}))
    output = evidence.outputs["node"]["default"]
    assert output.state == "missing"
    assert output.reason == "Output could not be finalized in durable storage."


def test_output_survives_a_fresh_process():
    value = {"scores": [[1, 2]], "sample_labels": ["A"]}
    evidence = retention.retain_output(1, value)
    script = """
import json, sys
from dataclasses import replace
from pathlib import Path
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.schemas.run_evidence import OutputEvidence
retention.settings = replace(retention.settings, data_dir=Path(sys.argv[1]))
print(json.dumps(retention.read_output(1, OutputEvidence.model_validate_json(sys.argv[2]))))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(retention.settings.data_dir), evidence.model_dump_json()],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert json.loads(result.stdout) == value


def test_failed_publication_removes_temporary_file(monkeypatch):
    def fail_replace(*args):
        raise OSError("publication interrupted")

    monkeypatch.setattr(retention.os, "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted"):
        retention.retain_output(1, [1])
    directory = retention._user_directory(1)
    assert not list(directory.glob("*.json"))
    assert not list(directory.glob(".pending-*"))


def test_owner_namespace_is_not_interchangeable():
    evidence = retention.retain_output(1, {"secret": [1]})
    with pytest.raises(FileNotFoundError):
        retention.read_output(2, evidence)


def test_disabled_capture_preserves_previously_retained_evidence(monkeypatch):
    item = retention.retain_output(1, [1, 2])
    monkeypatch.setattr(retention, "settings", replace(retention.settings, run_output_retention_enabled=False))
    evidence = retention.retain_run_outputs(1, {"node": [3]}, {})
    assert evidence["qualification"] == "unverified"
    assert "disabled in configuration" in evidence["reason"]
    assert retention.read_output(1, item) == [1, 2]
    assert len(list(retention._user_directory(1).glob("*.json"))) == 1


def test_lower_capture_limit_does_not_reject_existing_output(monkeypatch):
    item = retention.retain_output(1, [1, 2])
    monkeypatch.setattr(retention, "OUTPUT_BYTES_LIMIT", 1)
    assert retention.read_output(1, item) == [1, 2]
    with pytest.raises(ValueError, match="configured"):
        retention.retain_output(1, [3])


def test_configuration_rejects_unqualified_limits(monkeypatch):
    from spectra_sherpa.app.core.config import _get_retention_limit

    for value in ("0", "-1", "8388609", "not-an-integer"):
        monkeypatch.setenv("RUN_OUTPUT_MAX_BYTES", value)
        with pytest.raises(ValueError):
            _get_retention_limit("RUN_OUTPUT_MAX_BYTES", 8388608)
    monkeypatch.setenv("RUN_OUTPUT_MAX_BYTES", "1048576")
    assert _get_retention_limit("RUN_OUTPUT_MAX_BYTES", 8388608) == 1048576


def test_previews_and_nonfinite_values_are_not_called_exact():
    assert retention.retain_output(1, {"data_truncated": True}).state == "reduced"
    evidence = retention.retain_output(1, [float("nan"), 1])
    assert evidence.state == "reduced"
    assert retention.read_output(1, evidence) == [None, 1]


def test_quota_and_materialization_limits_fail_before_publication(monkeypatch):
    with pytest.raises(ValueError, match="materialization"):
        retention.admit_retained_value(np.zeros(retention.MAX_OUTPUT_VALUES + 1))
    monkeypatch.setattr(retention, "USER_BYTES_LIMIT", 10)
    with pytest.raises(ValueError, match="quota"):
        retention.retain_output(1, [1, 2])
    assert not list(retention._user_directory(1).glob("*.json"))


def test_concurrent_publication_obeys_shared_user_quota(monkeypatch):
    monkeypatch.setattr(retention, "USER_BYTES_LIMIT", 500)

    def publish(index):
        try:
            return retention.retain_output(1, {"index": index, "value": "x" * 100})
        except ValueError as exc:
            assert "quota" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(publish, range(16)))
    admitted = [item for item in results if item is not None]
    assert 0 < len(admitted) < 16
    assert sum(item.byte_count for item in admitted) <= retention.USER_BYTES_LIMIT
    assert len(list(retention._user_directory(1).glob("*.json"))) == len(admitted)
    assert not list(retention._user_directory(1).glob(".pending-*"))
    for item in admitted:
        assert retention.read_output(1, item)["value"] == "x" * 100


def test_reclamation_keeps_referenced_and_recent_outputs():
    retained = retention.retain_output(1, [1])
    abandoned = retention.retain_output(1, [2])
    recent = retention.retain_output(1, [3])
    directory = retention._user_directory(1)
    for item in (retained, abandoned):
        os.utime(directory / f"{item.sha256}.json", (time.time() - 90000,) * 2)
    assert retention.prune_unreferenced_outputs(1, {retained.sha256}) == 1
    assert retention.read_output(1, retained) == [1]
    assert retention.read_output(1, recent) == [3]
    with pytest.raises(ValueError, match="24-hour"):
        retention.prune_unreferenced_outputs(1, set(), grace_seconds=0)


@pytest.mark.asyncio
async def test_all_six_executed_fixtures_roundtrip_per_output():
    cases = await executed_cases()
    evidence = RunEvidence.model_validate(retention.retain_run_outputs(1, cases, {}))
    assert evidence.qualification == "qualified"
    assert set(evidence.outputs) == set(cases)
    for case, ports in evidence.outputs.items():
        for port, item in ports.items():
            if port.startswith("_"):
                assert item.state == "missing"
                assert "excluded by policy" in item.reason
                assert item.storage is None
                continue
            assert item.state != "missing", (case, port, item.reason)
            actual = retention.read_output(1, item)
            expected = json.loads(json.dumps(serialize_result(cases[case][port], retain_full=True)))
            assert actual == expected, (case, port)


def test_full_projection_retains_matrix_and_sample_labels():
    dataset, _ = reference_matrix()
    value = serialize_result(dataset, retain_full=True)
    np.testing.assert_array_equal(value["data"], dataset.X)
    assert value["metadata"]["sample_labels"] == dataset.sample_axis.labels
    assert value["metadata"]["feature_names"] == dataset.feature_axis.labels
    assert value["metadata"]["api_serialization"]["mode"] == "full"


def test_nonfinite_dataset_wire_is_explicitly_reduced():
    dataset, _ = reference_matrix()
    dataset.X[0, 0] = np.nan
    evidence = RunEvidence.model_validate(retention.retain_run_outputs(1, {"source": dataset}, {}))
    item = evidence.outputs["source"]["default"]
    assert item.state == "reduced"
    assert retention.read_output(1, item)["data"][0][0] is None


def test_extra_metadata_is_admitted_before_wire_materialization():
    dataset, _ = reference_matrix()
    dataset.extra["oversized"] = "x" * retention.OUTPUT_BYTES_LIMIT
    with pytest.raises(ValueError, match="materialization"):
        serialize_result(dataset, retain_full=True)


@pytest.mark.asyncio
async def test_metadata_and_independent_retrieval_are_project_authorized(test_session, test_user):
    from fastapi import HTTPException

    from spectra_sherpa.app.api.v1.routes.runs import get_retained_run_output, inspect_run_evidence
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.project import Project

    project = Project(user_id=test_user.id, name="Retention")
    test_session.add(project)
    await test_session.flush()
    evidence = retention.retain_run_outputs(test_user.id, {"center": {"default": [[1, 2], [3, 4]]}}, {})
    row = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        name="Retained",
        status="completed",
        params_snapshot={"fit": {"n_components": 2, "scale": False, "random_state": 17}},
        results_summary={},
        evidence_completeness=evidence,
        executed_at=datetime.now(timezone.utc),
    )
    test_session.add(row)
    await test_session.commit()
    metadata = await inspect_run_evidence(row.id, project_id=project.id, session=test_session, current_user=test_user)
    assert metadata["params_snapshot"] == {"fit": {"n_components": 2, "scale": False, "random_state": 17}}
    assert "results_summary" not in metadata["run"]
    assert metadata["evidence"]["outputs"]["center"]["default"]["state"] == "exact"
    output = await get_retained_run_output(
        row.id, "center", "default", project_id=project.id, session=test_session, current_user=test_user
    )
    assert output["value"] == [[1, 2], [3, 4]]
    with pytest.raises(HTTPException) as denied:
        await get_retained_run_output(
            row.id, "center", "default", project_id=project.id + 1, session=test_session, current_user=test_user
        )
    assert denied.value.status_code == 404

    path = retention._user_directory(test_user.id) / f"{evidence['outputs']['center']['default']['sha256']}.json"
    path.write_text("corrupt")
    with pytest.raises(HTTPException) as corrupt:
        await get_retained_run_output(
            row.id, "center", "default", project_id=project.id, session=test_session, current_user=test_user
        )
    assert corrupt.value.status_code == 409
    path.unlink()
    with pytest.raises(HTTPException) as missing:
        await get_retained_run_output(
            row.id, "center", "default", project_id=project.id, session=test_session, current_user=test_user
        )
    assert missing.value.status_code == 410

    row.evidence_completeness = {"schema_version": 999}
    await test_session.commit()
    with pytest.raises(HTTPException) as invalid:
        await inspect_run_evidence(row.id, project_id=project.id, session=test_session, current_user=test_user)
    assert invalid.value.status_code == 409

    row.evidence_completeness = evidence
    row.notes = "x" * retention.DETAIL_METADATA_BUDGET_BYTES
    await test_session.commit()
    with pytest.raises(HTTPException) as oversized:
        await inspect_run_evidence(row.id, project_id=project.id, session=test_session, current_user=test_user)
    assert oversized.value.status_code == 413


@pytest.mark.asyncio
async def test_historical_results_are_explicitly_unverified(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes.runs import inspect_run_evidence
    from spectra_sherpa.app.models.execution_run import ExecutionRun

    row = ExecutionRun(
        user_id=test_user.id,
        name="Historical",
        status="completed",
        params_snapshot={},
        results_summary={"pca": {"scores": [[1, 2]]}},
        evidence_completeness=None,
        executed_at=datetime.now(timezone.utc),
    )
    test_session.add(row)
    await test_session.commit()
    metadata = await inspect_run_evidence(row.id, project_id=None, session=test_session, current_user=test_user)
    assert metadata["evidence"]["qualification"] == "unverified"
    assert metadata["evidence"]["outputs"]["pca"]["scores"]["state"] == "unverified"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "partial", "error"])
async def test_run_finalization_retains_raw_outputs_and_diagnostics(test_session, test_user, status):
    from spectra_sherpa.app.api.v1.routes.runs import get_retained_run_output
    from spectra_sherpa.app.api.v1.routes.workflows._helpers import _auto_persist_run
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="Finalization")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Retained results")
    test_session.add(workflow)
    await test_session.commit()
    run_id = await _auto_persist_run(
        test_session,
        workflow_id=workflow.id,
        user_id=test_user.id,
        project_id=project.id,
        wf_version_id=None,
        serialized_results={"node": {"scores": [[1]]}},
        diagnostics_serialized={},
        node_statuses={"node": "completed"},
        final_status=status,
        error_msg="Later node failed" if status != "completed" else None,
        integrity_hash=None,
        produced_artifact_uids=[],
        raw_outputs_for_retention={"node": {"scores": np.array([[1, 2], [3, 4]])}},
        diagnostics_for_retention={"node": {"sample_labels": ["A", "B"]}},
        definition_for_retention={
            "schema_version": 1,
            "name": "Retained results",
            "nodes": [{"node_id": "node", "node_type": "model.pca", "parameters": {"n_components": 2}}],
            "edges": [],
        },
    )
    assert run_id is not None
    workflow.name = "Edited after execution"
    await test_session.commit()
    test_session.expire_all()
    await test_session.refresh(project)
    await test_session.refresh(test_user)
    output = await get_retained_run_output(
        run_id, "node", "scores", project_id=project.id, session=test_session, current_user=test_user
    )
    assert output["value"] == [[1, 2], [3, 4]]
    diagnostic = await get_retained_run_output(
        run_id, "__diagnostics__", "node", project_id=project.id, session=test_session, current_user=test_user
    )
    assert diagnostic["value"]["sample_labels"] == ["A", "B"]
    definition = await get_retained_run_output(
        run_id, "__workflow__", "definition", project_id=project.id, session=test_session, current_user=test_user
    )
    assert definition["value"]["name"] == "Retained results"
    assert definition["value"]["nodes"][0]["parameters"] == {"n_components": 2}


@pytest.mark.asyncio
async def test_run_finalization_marks_budget_omission_as_partial(
    test_session, test_user, monkeypatch: pytest.MonkeyPatch
):
    from sqlalchemy import select

    from spectra_sherpa.app.api.v1.routes.workflows._helpers import _auto_persist_run
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.schemas.run_evidence import OutputEvidence

    project = Project(user_id=test_user.id, name="Retention warning")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Retention warning")
    test_session.add(workflow)
    await test_session.commit()

    missing = RunEvidence(
        qualification="unverified",
        reason="Some outputs were not retained.",
        outputs={
            "node": {
                "scores": OutputEvidence(
                    state="missing", reason="Output exceeds the retained materialization budget", role="scores"
                )
            }
        },
    ).model_dump()
    monkeypatch.setattr(retention, "retain_run_outputs", lambda *args, **kwargs: missing)
    feedback: dict[str, str] = {}
    run_id = await _auto_persist_run(
        test_session,
        workflow_id=workflow.id,
        user_id=test_user.id,
        project_id=project.id,
        wf_version_id=None,
        serialized_results={"node": {"scores": [[1]]}},
        diagnostics_serialized={"_run_summary": {}},
        node_statuses={"node": "completed"},
        final_status="completed",
        error_msg=None,
        integrity_hash=None,
        produced_artifact_uids=[],
        raw_outputs_for_retention={"node": {"scores": [[1]]}},
        diagnostics_for_retention={},
        retention_feedback=feedback,
    )

    assert run_id is not None
    assert "retained materialization budget" in feedback["warning"]
    row = (await test_session.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))).scalar_one()
    assert row.status == "partial"
    assert "retained materialization budget" in (row.error or "")
    assert row.source_metadata["retention_warning"] == feedback["warning"]
    assert row.diagnostics["_run_summary"]["retention_warning"] == feedback["warning"]


@pytest.mark.parametrize("nonfinite", [False, True])
def test_typed_outlier_evaluation_is_retained_and_nonfinite_is_reduced(nonfinite):
    from spectra_sherpa.app.lib.sherpa_dataset import EvaluationResult

    evaluation = EvaluationResult(
        evaluation_id="pca-outliers",
        model_type="pca",
        n_components=2,
        hotelling_t2=[1.0, float("nan") if nonfinite else 2.0],
        q_residuals=[0.1, 0.2],
        outlier_indices=[1],
        t2_limit=1.5,
        q_limit=0.15,
    )
    evidence = RunEvidence.model_validate(retention.retain_run_outputs(1, {"outliers": {"evaluation": evaluation}}, {}))
    item = evidence.outputs["outliers"]["evaluation"]
    assert item.state == ("reduced" if nonfinite else "exact")
    restored = retention.read_output(1, item)
    expected = evaluation.model_dump(mode="json")
    if nonfinite:
        expected["hotelling_t2"][1] = None
    assert restored == expected
