"""Signed optimized campaign -> local import -> real offline folder inference."""

import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.api.v1.routes import projects as projects_route
from spectra_sherpa.app.models.batch_prediction import BatchPrediction
from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services import canonical_project_custody, folder_watch_service
from spectra_sherpa.app.services.run_output_retention import read_output
from tests.test_canonical_project_import import _PACKAGE, _REVIEW_ANCHORS, _REVIEW_PACKAGE
from tests.test_canonical_project_package import _package, _review_package

_EARLY_CANONICAL_PACKAGE = _package(preprocessing_node_id="a-scale")
_EARLY_NODE_PACKAGE, _EARLY_NODE_ANCHORS = _review_package(_EARLY_CANONICAL_PACKAGE)

pytestmark = pytest.mark.usefixtures("deny_inference_network")


@pytest.fixture(params=["normal", "preprocessing_sorts_before_input"])
async def campaign(auth_client, test_session, test_user, tmp_path, monkeypatch, request):
    package, anchors = (
        (_REVIEW_PACKAGE, _REVIEW_ANCHORS) if request.param == "normal" else (_EARLY_NODE_PACKAGE, _EARLY_NODE_ANCHORS)
    )
    monkeypatch.setattr(
        canonical_project_custody, "settings", replace(canonical_project_custody.settings, data_dir=tmp_path)
    )
    factory = async_sessionmaker(test_session.bind, expire_on_commit=False)
    monkeypatch.setattr(projects_route, "async_session", factory)
    monkeypatch.setattr(
        projects_route,
        "settings",
        replace(projects_route.settings, data_dir=tmp_path, campaign_review_publisher_trust_anchors_path=None),
    )
    # A fresh OSS installation uses independently obtained public keys, not operator env configuration.
    response = await auth_client.post(
        "/api/v1/projects/import",
        files={
            "file": ("campaign-review.sherpa", package.archive, "application/octet-stream"),
            "publisher_trust_anchors": ("publisher.json", json.dumps(anchors.as_dict()), "application/json"),
        },
        data={"publisher_trust_confirmed": "true"},
    )
    assert response.status_code == 201, response.text
    await test_session.refresh(test_user)  # The unified importer expires its injected request session.
    imported = SimpleNamespace(project_id=response.json()["id"])
    record = await test_session.scalar(
        select(CanonicalProjectArtifact).where(CanonicalProjectArtifact.project_id == imported.project_id)
    )
    imported.workflow_id = record.workflow_id
    imported.canonical_package = _PACKAGE if request.param == "normal" else _EARLY_CANONICAL_PACKAGE
    imported.canonical_archive = imported.canonical_package.archive
    return imported, record, factory


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["application_handle", "canonical_artifact_id"])
async def test_signed_campaign_import_real_folder_watch(
    campaign, auth_client, test_session, test_user, tmp_path, monkeypatch, binding
):
    imported, record, factory = campaign
    targets = await auth_client.get("/api/v1/deploy/canonical-targets", params={"project_id": imported.project_id})
    assert targets.status_code == 200, targets.text
    assert targets.json()[0]["deploy_ready"], targets.json()
    applications = await auth_client.get("/api/v1/deploy/applications", params={"project_id": imported.project_id})
    assert applications.status_code == 200, applications.text
    application = applications.json()[0]
    assert application["canonical_artifact_id"] == record.id
    handle = application["handle"]
    selected = await auth_client.get(f"/api/v1/deploy/applications/{handle}")
    assert selected.status_code == 200, selected.text
    binding_value = handle if binding == "application_handle" else record.id
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    # Entirely new observations; no training matrix accompanies the imported model.
    X = np.arange(160, 184, dtype=float).reshape(3, 8)
    from spectra_sherpa.app.lib.export_artifact import build_export_artifact, materialize_export_artifact
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, SpectralAxis

    dataset = SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(values=np.arange(8, dtype=float), units="cm-1"),
        domain=DomainContext(measurement_mode="reflectance"),
    )
    materialize_export_artifact(build_export_artifact(dataset, filename="new.csv", format="csv"), incoming)
    created = await auth_client.post(
        "/api/v1/deploy/watches",
        json={
            "workflow_id": imported.workflow_id,
            binding: binding_value,
            "name": "Optimized local solution",
            "folder_path": str(incoming),
            "file_pattern": "*.csv",
            "settle_time_seconds": 0,
        },
    )
    assert created.status_code == 201, created.text
    watch_id = created.json()["id"]
    enabled = await auth_client.post(f"/api/v1/deploy/watches/{watch_id}/enable")
    assert enabled.status_code == 200, enabled.text
    watch = await test_session.get(FolderWatch, watch_id)
    monkeypatch.setattr(folder_watch_service, "async_session", factory)

    await folder_watch_service.FolderWatchService()._process_watch(watch)
    prediction = await test_session.scalar(select(BatchPrediction))
    assert prediction is not None
    assert prediction.status == "completed", prediction.error_message
    run = await test_session.get(ExecutionRun, prediction.run_id)
    assert run.source_metadata["canonical_plan_digest"] == record.application_plan_digest
    assert run.source_metadata["canonical_artifact_digest"] == record.artifact_digest
    assert run.succeeded_artifact_uids == []  # A canonical package has no ModelArtifact UID.
    history = await auth_client.get("/api/v1/deploy/runs", params={"project_id": imported.project_id})
    assert history.status_code == 200, history.text
    assert history.json()["runs"][0]["succeeded_artifact_uids"] == []
    # Older canonical watches persisted [null]; their history must stay readable.
    run.succeeded_artifact_uids = [None]
    await test_session.commit()
    legacy_history = await auth_client.get("/api/v1/deploy/runs", params={"project_id": imported.project_id})
    assert legacy_history.status_code == 200, legacy_history.text
    assert legacy_history.json()["runs"][0]["succeeded_artifact_uids"] == []
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    outputs = evidence.outputs["file_0::model"]
    screening = read_output(test_user.id, outputs["applicability"])
    assert screening["claim_scope"] == "provisional_calibration_screening"
    assert len(screening["rows"]) == len(X)
    assert all(row["applicability_status"] == "unqualified" for row in screening["rows"])
    assert screening["prediction_identity"]["shape"] == [len(X), 1]
    assert screening["prediction_identity"]["fitted_state_custody"]["artifact_digest"] == record.artifact_digest
    values = read_output(test_user.id, outputs["default"])
    np.testing.assert_allclose(np.asarray(values).ravel(), X[:, 0] * 0.3 + X[:, 1] * 0.1, atol=1e-8)

    # A fresh worker/session after restart retains the same sealed authority and does not repeat files.
    reopened = await auth_client.get(f"/api/v1/deploy/applications/{handle}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json() == selected.json()
    await test_session.refresh(watch)
    await folder_watch_service.FolderWatchService()._process_watch(watch)
    assert len((await test_session.scalars(select(BatchPrediction))).all()) == 1
    singleton = SherpaDataset(
        X=X[:1] + 8,
        feature_axis=SpectralAxis(values=np.arange(8, dtype=float), units="cm-1"),
        domain=DomainContext(measurement_mode="reflectance"),
    )
    materialize_export_artifact(build_export_artifact(singleton, filename="singleton.csv", format="csv"), incoming)
    await test_session.refresh(watch)
    await folder_watch_service.FolderWatchService()._process_watch(watch)
    predictions = (await test_session.scalars(select(BatchPrediction))).all()
    assert len(predictions) == 2
    assert all(p.status == "completed" for p in predictions)
    restarted_run = await test_session.get(ExecutionRun, predictions[-1].run_id)
    restarted_evidence = RunEvidence.model_validate(restarted_run.evidence_completeness)
    singleton_screening = read_output(test_user.id, restarted_evidence.outputs["file_0::model"]["applicability"])
    assert len(singleton_screening["rows"]) == 1
    assert singleton_screening["t2_limit"] == screening["t2_limit"]
    assert singleton_screening["q_limit"] == screening["q_limit"]
    singleton_values = read_output(test_user.id, restarted_evidence.outputs["file_0::model"]["default"])
    np.testing.assert_allclose(
        np.asarray(singleton_values).ravel(), [(X[0, 0] + 8) * 0.3 + (X[0, 1] + 8) * 0.1], atol=1e-8
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_input",
    [
        "missing_units",
        "wrong_units",
        "wrong_order",
        "missing_feature",
        "nonfinite",
        "empty",
        "missing_mode",
        "wrong_mode",
    ],
)
async def test_incompatible_incoming_file_is_visible_failure(
    campaign, auth_client, test_session, test_user, tmp_path, monkeypatch, bad_input
):
    from spectra_sherpa.app.lib.export_artifact import build_export_artifact, materialize_export_artifact
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, SpectralAxis

    imported, record, factory = campaign
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    X = np.arange(160, 184, dtype=float).reshape(3, 8)
    if bad_input == "nonfinite":
        X[0, 0] = np.nan
    if bad_input in ("missing_units", "nonfinite", "empty"):
        np.savetxt(
            incoming / "bad.csv",
            X if bad_input != "empty" else X[:0],
            delimiter=",",
            header=",".join(map(str, range(8))),
            comments="",
        )
    else:
        axis = np.arange(8, dtype=float)
        if bad_input == "wrong_order":
            axis = axis[::-1]
        if bad_input == "missing_feature":
            X = X[:, :7]
            axis = axis[:7]
        data = SherpaDataset(
            X=X,
            feature_axis=SpectralAxis(values=axis, units="nm" if bad_input == "wrong_units" else "cm-1"),
            domain=DomainContext(
                measurement_mode=(
                    None
                    if bad_input == "missing_mode"
                    else "transmission" if bad_input == "wrong_mode" else "reflectance"
                )
            ),
        )
        materialize_export_artifact(build_export_artifact(data, filename="bad.csv", format="csv"), incoming)
    response = await auth_client.post(
        "/api/v1/deploy/watches",
        json={
            "workflow_id": imported.workflow_id,
            "canonical_artifact_id": record.id,
            "name": "Refusal",
            "folder_path": str(incoming),
            "settle_time_seconds": 0,
        },
    )
    assert response.status_code == 201, response.text
    watch_id = response.json()["id"]
    assert (await auth_client.post(f"/api/v1/deploy/watches/{watch_id}/enable")).status_code == 200
    watch = await test_session.get(FolderWatch, watch_id)
    monkeypatch.setattr(folder_watch_service, "async_session", factory)
    await folder_watch_service.FolderWatchService()._process_watch(watch)
    prediction = await test_session.scalar(select(BatchPrediction))
    assert prediction is not None and prediction.status == "error"
    assert prediction.error_message
    if bad_input in ("missing_mode", "wrong_mode"):
        assert "measurement_mode" in prediction.error_message
    assert prediction.results is None
    run = await test_session.get(ExecutionRun, prediction.run_id)
    assert run.source_metadata["canonical_plan_digest"] == record.application_plan_digest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_owner",
        "wrong_workflow",
        "mixed_targets",
        "missing_target",
        "changed_graph",
        "changed_plan",
        "changed_bytes",
    ],
)
async def test_campaign_binding_refuses_lost_authority(
    campaign, auth_client, test_session, test_user, tmp_path, mutation
):
    from spectra_sherpa.app.models.workflow_node import WorkflowNode

    imported, record, _ = campaign
    payload = {
        "workflow_id": imported.workflow_id,
        "canonical_artifact_id": record.id,
        "name": "Authority refusal",
        "folder_path": str(tmp_path),
    }
    if mutation == "wrong_owner":
        from spectra_sherpa.app.models.user import User

        other = User(username="other-campaign-owner")
        test_session.add(other)
        await test_session.flush()
        record.user_id = other.id
    elif mutation == "wrong_workflow":
        payload["workflow_id"] += 1000
    elif mutation == "mixed_targets":
        payload["artifact_uid"] = "another-model"
    elif mutation == "missing_target":
        del payload["canonical_artifact_id"]
    elif mutation == "changed_graph":
        node = await test_session.scalar(select(WorkflowNode).where(WorkflowNode.workflow_id == imported.workflow_id))
        node.parameters = {"modified": True}
    elif mutation == "changed_plan":
        record.application_plan_digest = "0" * 64
    elif mutation == "changed_bytes":
        from pathlib import Path

        state = next((Path(record.artifact_dir) / "states").glob("*.json"))
        state.write_bytes(b"tampered")
    await test_session.commit()
    response = await auth_client.post("/api/v1/deploy/watches", json=payload)
    assert response.status_code == 422, response.text
    assert not (await test_session.scalars(select(FolderWatch))).all()


@pytest.mark.asyncio
async def test_bound_plan_is_rechecked_on_enable_and_poll(campaign, auth_client, test_session, tmp_path, monkeypatch):
    imported, record, factory = campaign
    response = await auth_client.post(
        "/api/v1/deploy/watches",
        json={
            "workflow_id": imported.workflow_id,
            "canonical_artifact_id": record.id,
            "name": "Pinned plan",
            "folder_path": str(tmp_path),
            "settle_time_seconds": 0,
        },
    )
    assert response.status_code == 201
    watch = await test_session.get(FolderWatch, response.json()["id"])
    watch.canonical_plan_digest = "0" * 64
    await test_session.commit()
    enabled = await auth_client.post(f"/api/v1/deploy/watches/{watch.id}/enable")
    assert enabled.status_code == 422
    assert "bound plan" in enabled.text
    watch.is_enabled = True
    await test_session.commit()
    (tmp_path / "incoming.csv").write_text("0,1\n1,2\n")
    monkeypatch.setattr(folder_watch_service, "async_session", factory)
    await folder_watch_service.FolderWatchService()._process_watch(watch)
    await test_session.refresh(watch)
    assert not watch.is_enabled
    assert "bound plan" in watch.last_error
    assert not (await test_session.scalars(select(BatchPrediction))).all()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "unconfirmed", "wrong_key", "hosted_override"])
async def test_fresh_install_publisher_trust_is_explicit(auth_client, monkeypatch, tmp_path, case):
    monkeypatch.setattr(
        projects_route,
        "settings",
        replace(projects_route.settings, data_dir=tmp_path, campaign_review_publisher_trust_anchors_path=None),
    )
    files = {"file": ("campaign.sherpa", _REVIEW_PACKAGE.archive, "application/octet-stream")}
    if case != "missing":
        anchors = _REVIEW_ANCHORS.as_dict()
        if case == "wrong_key":
            anchors["issuer"] = "untrusted-publisher"
        files["publisher_trust_anchors"] = ("publisher.json", json.dumps(anchors), "application/json")
    if case == "hosted_override":
        monkeypatch.setattr(projects_route, "app_config", SimpleNamespace(mode="enterprise"))
    response = await auth_client.post(
        "/api/v1/projects/canonical-import",
        files=files,
        data={"publisher_trust_confirmed": "false" if case == "unconfirmed" else "true"},
    )
    assert (
        response.status_code == {"missing": 503, "unconfirmed": 422, "wrong_key": 400, "hosted_override": 403}[case]
    ), response.text


def test_canonical_watch_migration_preserves_existing_bindings_and_refuses_destructive_downgrade():
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from spectra_sherpa.app.db.canonical_watch_migration import migrate_canonical_watch
    from spectra_sherpa.app.db.sqlite_migration import migration_transaction

    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE canonical_project_artifact (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE folder_watch (id INTEGER PRIMARY KEY, artifact_uid TEXT, is_enabled BOOLEAN)"
        )
        connection.exec_driver_sql("INSERT INTO folder_watch VALUES (1, 'original-model', 1)")
        connection.commit()

        def migrate(downgrade=False):
            with migration_transaction(connection):
                with Operations.context(MigrationContext.configure(connection)):
                    migrate_canonical_watch(downgrade=downgrade)

        migrate()
        migrate()
        original = connection.execute(sa.text("SELECT * FROM folder_watch")).mappings().one()
        assert original["artifact_uid"] == "original-model" and original["is_enabled"]
        connection.exec_driver_sql("INSERT INTO canonical_project_artifact VALUES (42)")
        connection.exec_driver_sql(
            "UPDATE folder_watch SET artifact_uid=NULL, canonical_artifact_id=42, canonical_plan_digest='plan'"
        )
        connection.commit()
        with pytest.raises(RuntimeError, match="retain canonical"):
            migrate(True)
        with pytest.raises(sa.exc.IntegrityError):
            connection.exec_driver_sql("DELETE FROM canonical_project_artifact WHERE id=42")
        connection.rollback()
        connection.exec_driver_sql(
            "UPDATE folder_watch SET canonical_artifact_id=NULL, canonical_plan_digest=NULL, is_enabled=0"
        )
        connection.commit()
        migrate(True)
        assert "canonical_artifact_id" not in {c["name"] for c in sa.inspect(connection).get_columns("folder_watch")}
    engine.dispose()
