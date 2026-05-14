"""Phase 3 — route-level E2E tests for the expanded audited model set.

Phase 1 covered Workflow / WorkflowVersion / ExecutionRun /
ModelArtifact via real HTTP routes. Phase 3 adds Project /
Experiment / APIKey. Each new audited model gets one happy-path test
that POSTs through the real route and asserts the corresponding
audit event materialises through the AuditMiddleware → emitter →
session chain.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.models.audit_event import AuditEvent
from spectra_sherpa.app.services.audit import install_audit_flush_listener
from spectra_sherpa.app.services.audit.boot import _reset_process_boot_id_for_tests
from spectra_sherpa.app.services.audit.reproducibility import (
    _reset_environment_snapshot_for_tests,
)


@pytest.fixture(autouse=True)
def _enable_audit_for_phase3_e2e(monkeypatch):
    install_audit_flush_listener()
    _reset_process_boot_id_for_tests()
    _reset_environment_snapshot_for_tests()
    monkeypatch.setattr(app_config, "audit_enabled", True)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


async def test_project_create_emits_audit_event(auth_client, test_session):
    """POST /api/v1/projects → project.created with full identity."""
    resp = await auth_client.post(
        "/api/v1/projects",
        json={"name": "audit-e2e-project", "technique": "FTIR"},
    )
    assert resp.status_code in (200, 201), resp.text
    project_id = resp.json()["id"]

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    created = [r for r in rows if r.action == "project.created"]
    assert len(created) == 1
    event = created[0]
    assert event.target_type == "Project"
    assert int(event.target_id) == project_id
    assert event.after_state["name"] == "audit-e2e-project"
    assert event.after_state["technique"] == "FTIR"


async def test_project_delete_emits_audit_event(auth_client, test_session):
    """DELETE /api/v1/projects/{id} → project.deleted with before_state."""
    create = await auth_client.post("/api/v1/projects", json={"name": "to-delete"})
    assert create.status_code in (200, 201)
    proj_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.delete(f"/api/v1/projects/{proj_id}")
    assert resp.status_code == 204

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    deletes = [r for r in rows if r.action == "project.deleted"]
    assert len(deletes) == 1
    assert deletes[0].before_state["name"] == "to-delete"
    assert int(deletes[0].target_id) == proj_id


async def test_project_update_emits_audit_event(auth_client, test_session):
    """PUT /api/v1/projects/{id} → project.updated with before+after state."""
    create = await auth_client.post("/api/v1/projects", json={"name": "orig-name", "technique": "FTIR"})
    assert create.status_code in (200, 201)
    proj_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.put(
        f"/api/v1/projects/{proj_id}",
        json={"name": "renamed", "description": "now described"},
    )
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    updates = [r for r in rows if r.action == "project.updated"]
    assert len(updates) == 1
    event = updates[0]
    assert event.target_type == "Project"
    assert int(event.target_id) == proj_id
    # Before/after must both be present and the diff must be visible.
    assert event.before_state["name"] == "orig-name"
    assert event.after_state["name"] == "renamed"
    assert event.after_state["description"] == "now described"


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------


async def test_experiment_create_emits_audit_event(auth_client, test_session):
    """POST /api/v1/experiments → experiment.created."""
    resp = await auth_client.post(
        "/api/v1/experiments",
        json={"name": "audit-e2e-exp", "metadata": {}},
    )
    assert resp.status_code in (200, 201), resp.text
    exp_id = resp.json()["id"]

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    created = [r for r in rows if r.action == "experiment.created"]
    assert len(created) == 1
    assert created[0].target_type == "Experiment"
    assert int(created[0].target_id) == exp_id
    assert created[0].after_state["name"] == "audit-e2e-exp"


async def test_experiment_delete_emits_audit_event(auth_client, test_session):
    """DELETE /api/v1/experiments/{id} → experiment.deleted."""
    create = await auth_client.post(
        "/api/v1/experiments",
        json={"name": "to-delete", "metadata": {}},
    )
    assert create.status_code in (200, 201)
    exp_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.delete(f"/api/v1/experiments/{exp_id}")
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    deletes = [r for r in rows if r.action == "experiment.deleted"]
    assert len(deletes) == 1
    assert deletes[0].before_state["name"] == "to-delete"


async def test_experiment_update_emits_audit_event(auth_client, test_session):
    """PUT /api/v1/experiments/{id} → experiment.updated with before+after."""
    create = await auth_client.post(
        "/api/v1/experiments",
        json={"name": "orig-exp", "description": "v1", "metadata": {}},
    )
    assert create.status_code in (200, 201)
    exp_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.put(
        f"/api/v1/experiments/{exp_id}",
        json={"name": "renamed-exp", "description": "v2", "metadata": None},
    )
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    updates = [r for r in rows if r.action == "experiment.updated"]
    assert len(updates) == 1
    event = updates[0]
    assert event.target_type == "Experiment"
    assert int(event.target_id) == exp_id
    assert event.before_state["name"] == "orig-exp"
    assert event.after_state["name"] == "renamed-exp"
    assert event.after_state["description"] == "v2"


async def test_experiment_update_idle_does_not_emit(auth_client, test_session):
    """PUT with no real change → no experiment.updated row.

    The service-layer idempotency guard (only emit when state changed
    OR metadata is not None) prevents UI/idle PUTs from polluting the
    audit trail.
    """
    create = await auth_client.post(
        "/api/v1/experiments",
        json={"name": "idle", "description": "stay", "metadata": {}},
    )
    exp_id = create.json()["id"]
    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    # Send None for all fields — payload triggers update_experiment with
    # name=None, description=None, metadata=None → emit guard suppresses.
    resp = await auth_client.put(
        f"/api/v1/experiments/{exp_id}",
        json={},
    )
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    assert [r for r in rows if r.action == "experiment.updated"] == []


# ---------------------------------------------------------------------------
# ExperimentFile (service-helper-level — upload route uses multipart + disk)
# ---------------------------------------------------------------------------


async def test_experiment_file_create_and_delete_emit_audit_events(auth_client, test_session, test_user):
    """add_experiment_file / delete_experiment_file emit the
    experiment_file.created / .deleted pair. These run through the
    service helper directly because the HTTP route also writes bytes
    to disk under settings.data_dir — irrelevant to the audit path.
    """
    from spectra_sherpa.app.services.experiments import (
        add_experiment_file,
        create_experiment,
        delete_experiment_file,
    )

    experiment = await create_experiment(
        test_session,
        user_id=test_user.id,
        name="exp-for-file-audit",
        description=None,
        metadata={},
        project_id=None,
    )

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    exp_file = await add_experiment_file(
        session=test_session,
        experiment_id=experiment.id,
        stage="raw",
        file_path="raw/sample.csv",
        file_size_bytes=123,
        file_type="csv",
    )

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    creates = [r for r in rows if r.action == "experiment_file.created"]
    assert len(creates) == 1
    assert creates[0].target_type == "ExperimentFile"
    assert int(creates[0].target_id) == exp_file.id
    assert creates[0].after_state["experiment_id"] == experiment.id
    assert creates[0].after_state["stage"] == "raw"
    assert creates[0].after_state["file_path"] == "raw/sample.csv"

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    await delete_experiment_file(test_session, exp_file)

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    deletes = [r for r in rows if r.action == "experiment_file.deleted"]
    assert len(deletes) == 1
    assert deletes[0].before_state["experiment_id"] == experiment.id
    assert deletes[0].before_state["file_path"] == "raw/sample.csv"


# ---------------------------------------------------------------------------
# ProjectDataSource
# ---------------------------------------------------------------------------


async def test_project_data_source_create_emits_audit_event(auth_client, test_session):
    """POST /api/v1/projects/{id}/data-sources → project_data_source.created."""
    proj = await auth_client.post("/api/v1/projects", json={"name": "ds-host"})
    proj_id = proj.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.post(
        f"/api/v1/projects/{proj_id}/data-sources",
        json={
            "display_name": "instrument-a",
            "source_type": "manual",
            "source_ref": "/data/raw",
            "fingerprint": "fp-abc-123",
        },
    )
    assert resp.status_code == 201, resp.text
    ds_id = resp.json()["id"]

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    creates = [r for r in rows if r.action == "project_data_source.created"]
    assert len(creates) == 1
    event = creates[0]
    assert event.target_type == "ProjectDataSource"
    assert int(event.target_id) == ds_id
    assert event.after_state["project_id"] == proj_id
    assert event.after_state["display_name"] == "instrument-a"
    assert event.after_state["fingerprint"] == "fp-abc-123"


async def test_project_data_source_update_emits_audit_event(auth_client, test_session):
    """PUT /api/v1/projects/{id}/data-sources/{ds_id} → project_data_source.updated."""
    proj = await auth_client.post("/api/v1/projects", json={"name": "ds-update-host"})
    proj_id = proj.json()["id"]
    create = await auth_client.post(
        f"/api/v1/projects/{proj_id}/data-sources",
        json={
            "display_name": "old-name",
            "source_type": "manual",
            "source_ref": "/data/x",
            "fingerprint": "fp-1",
        },
    )
    ds_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.put(
        f"/api/v1/projects/{proj_id}/data-sources/{ds_id}",
        json={"display_name": "new-name", "color": "#ff00aa"},
    )
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    updates = [r for r in rows if r.action == "project_data_source.updated"]
    assert len(updates) == 1
    event = updates[0]
    assert event.target_type == "ProjectDataSource"
    assert int(event.target_id) == ds_id
    assert event.before_state["display_name"] == "old-name"
    assert event.after_state["display_name"] == "new-name"
    assert event.after_state["color"] == "#ff00aa"


# ---------------------------------------------------------------------------
# APIKey
# ---------------------------------------------------------------------------


async def test_api_key_create_emits_audit_event(auth_client, test_session):
    """POST /api/v1/users/me/api-keys → api_key.created.

    The plaintext key never reaches the audit log — the test verifies
    after_state carries only service_name and the FK user_id."""
    resp = await auth_client.post(
        "/api/v1/api-keys",
        json={"service_name": "anthropic", "key": "sk-secret-do-not-log"},
    )
    assert resp.status_code in (200, 201), resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    created = [r for r in rows if r.action == "api_key.created"]
    assert len(created) == 1
    event = created[0]
    assert event.target_type == "APIKey"
    assert event.after_state["service_name"] == "anthropic"
    # Secret-leak guard: no field in the audit row may contain the
    # plaintext key. before/after_state and context are checked
    # because that's where free-form data lands.
    serialised = (event.after_state, event.before_state, event.context)
    for blob in serialised:
        assert "sk-secret-do-not-log" not in repr(blob), "plaintext API key leaked into audit log"


async def test_api_key_update_emits_audit_event(auth_client, test_session):
    """A second POST for the same service is an update, not a create."""
    await auth_client.post(
        "/api/v1/api-keys",
        json={"service_name": "openai", "key": "sk-original"},
    )

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.post(
        "/api/v1/api-keys",
        json={"service_name": "openai", "key": "sk-rotated"},
    )
    assert resp.status_code in (200, 201)

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    updates = [r for r in rows if r.action == "api_key.updated"]
    assert len(updates) == 1
    serialised = (updates[0].after_state, updates[0].before_state, updates[0].context)
    for blob in serialised:
        assert "sk-original" not in repr(blob)
        assert "sk-rotated" not in repr(blob)


async def test_api_key_delete_emits_audit_event(auth_client, test_session):
    """DELETE /api/v1/users/me/api-keys/{service} → api_key.deleted."""
    await auth_client.post(
        "/api/v1/api-keys",
        json={"service_name": "gemini", "key": "sk-x"},
    )

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.delete("/api/v1/api-keys/gemini")
    assert resp.status_code == 204, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    deletes = [r for r in rows if r.action == "api_key.deleted"]
    assert len(deletes) == 1
    assert deletes[0].before_state["service_name"] == "gemini"


# ---------------------------------------------------------------------------
# Project membership — link/unlink for Experiment, Workflow, ModelArtifact
#
# These were the critical Phase 3 review-feedback gap: the link/unlink
# routes mutated the entity's project_id and committed without an audit
# event, so project composition could change with no trail. The fix
# wires emits in all six routes; the tests below pin them.
# ---------------------------------------------------------------------------


async def test_link_experiment_emits_project_linked(auth_client, test_session):
    """POST /api/v1/projects/{pid}/experiments/{eid} → experiment.project_linked."""
    proj = await auth_client.post("/api/v1/projects", json={"name": "link-host"})
    proj_id = proj.json()["id"]
    exp = await auth_client.post(
        "/api/v1/experiments",
        json={"name": "loose-exp", "metadata": {}},
    )
    exp_id = exp.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.post(f"/api/v1/projects/{proj_id}/experiments/{exp_id}")
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    links = [r for r in rows if r.action == "experiment.project_linked"]
    assert len(links) == 1
    event = links[0]
    assert event.target_type == "Experiment"
    assert int(event.target_id) == exp_id
    assert event.before_state == {"project_id": None}
    assert event.after_state == {"project_id": proj_id}


async def test_unlink_experiment_emits_project_unlinked(auth_client, test_session):
    """DELETE /api/v1/projects/{pid}/experiments/{eid} → experiment.project_unlinked."""
    proj = await auth_client.post("/api/v1/projects", json={"name": "unlink-host"})
    proj_id = proj.json()["id"]
    exp = await auth_client.post(
        "/api/v1/experiments",
        json={"name": "exp-to-unlink", "metadata": {}},
    )
    exp_id = exp.json()["id"]
    await auth_client.post(f"/api/v1/projects/{proj_id}/experiments/{exp_id}")

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.delete(f"/api/v1/projects/{proj_id}/experiments/{exp_id}")
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    unlinks = [r for r in rows if r.action == "experiment.project_unlinked"]
    assert len(unlinks) == 1
    event = unlinks[0]
    assert event.target_type == "Experiment"
    assert int(event.target_id) == exp_id
    assert event.before_state == {"project_id": proj_id}
    assert event.after_state == {"project_id": None}


async def test_relink_experiment_to_same_project_is_idempotent(auth_client, test_session):
    """Re-POSTing the same link MUST NOT emit a second event.

    The route checks ``previous_project_id != project_id`` so the audit
    trail doesn't fill with no-op rows when the UI fires a duplicate
    link request.
    """
    proj = await auth_client.post("/api/v1/projects", json={"name": "idem"})
    proj_id = proj.json()["id"]
    exp = await auth_client.post(
        "/api/v1/experiments",
        json={"name": "idem-exp", "metadata": {}},
    )
    exp_id = exp.json()["id"]
    await auth_client.post(f"/api/v1/projects/{proj_id}/experiments/{exp_id}")

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.post(f"/api/v1/projects/{proj_id}/experiments/{exp_id}")
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    assert [r for r in rows if r.action == "experiment.project_linked"] == []


async def test_link_workflow_emits_project_linked(auth_client, test_session, test_user):
    """POST /api/v1/projects/{pid}/workflows/{wid} → workflow.project_linked."""
    from spectra_sherpa.app.models.workflow import Workflow

    workflow = Workflow(user_id=test_user.id, name="wf-to-link", status="draft")
    test_session.add(workflow)
    await test_session.commit()
    await test_session.refresh(workflow)

    proj = await auth_client.post("/api/v1/projects", json={"name": "wf-host"})
    proj_id = proj.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.post(f"/api/v1/projects/{proj_id}/workflows/{workflow.id}")
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    links = [r for r in rows if r.action == "workflow.project_linked"]
    assert len(links) == 1
    event = links[0]
    assert event.target_type == "Workflow"
    assert int(event.target_id) == workflow.id
    assert event.before_state == {"project_id": None}
    assert event.after_state == {"project_id": proj_id}


async def test_unlink_workflow_emits_project_unlinked(auth_client, test_session, test_user):
    """DELETE /api/v1/projects/{pid}/workflows/{wid} → workflow.project_unlinked."""
    from spectra_sherpa.app.models.workflow import Workflow

    workflow = Workflow(user_id=test_user.id, name="wf-to-unlink", status="draft")
    test_session.add(workflow)
    await test_session.commit()
    await test_session.refresh(workflow)

    proj = await auth_client.post("/api/v1/projects", json={"name": "wf-unlink-host"})
    proj_id = proj.json()["id"]
    await auth_client.post(f"/api/v1/projects/{proj_id}/workflows/{workflow.id}")

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.delete(f"/api/v1/projects/{proj_id}/workflows/{workflow.id}")
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    unlinks = [r for r in rows if r.action == "workflow.project_unlinked"]
    assert len(unlinks) == 1
    event = unlinks[0]
    assert event.target_type == "Workflow"
    assert int(event.target_id) == workflow.id
    assert event.before_state == {"project_id": proj_id}
    assert event.after_state == {"project_id": None}


async def test_link_model_artifact_emits_project_linked(auth_client, test_session, test_user):
    """POST /api/v1/projects/{pid}/models/{uid} → model_artifact.project_linked."""
    import uuid

    from spectra_sherpa.app.models.model_artifact import ModelArtifact

    artifact_uid = str(uuid.uuid4())
    artifact = ModelArtifact(
        artifact_uid=artifact_uid,
        user_id=test_user.id,
        node_id="pca_1",
        model_type="pca",
        name="link-test-model",
        artifact_dir=f"models/{artifact_uid}",
        integrity_hash="0" * 64,
        n_features=10,
        n_components=2,
    )
    test_session.add(artifact)
    await test_session.commit()
    await test_session.refresh(artifact)

    proj = await auth_client.post("/api/v1/projects", json={"name": "model-host"})
    proj_id = proj.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.post(f"/api/v1/projects/{proj_id}/models/{artifact_uid}")
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    links = [r for r in rows if r.action == "model_artifact.project_linked"]
    assert len(links) == 1
    event = links[0]
    assert event.target_type == "ModelArtifact"
    assert int(event.target_id) == artifact.id
    assert event.before_state["project_id"] is None
    assert event.before_state["artifact_uid"] == artifact_uid
    assert event.after_state["project_id"] == proj_id
    assert event.after_state["artifact_uid"] == artifact_uid


async def test_unlink_model_artifact_emits_project_unlinked(auth_client, test_session, test_user):
    """DELETE /api/v1/projects/{pid}/models/{uid} → model_artifact.project_unlinked."""
    import uuid

    from spectra_sherpa.app.models.model_artifact import ModelArtifact

    artifact_uid = str(uuid.uuid4())
    artifact = ModelArtifact(
        artifact_uid=artifact_uid,
        user_id=test_user.id,
        node_id="pca_1",
        model_type="pca",
        name="unlink-test-model",
        artifact_dir=f"models/{artifact_uid}",
        integrity_hash="0" * 64,
        n_features=10,
        n_components=2,
    )
    test_session.add(artifact)
    await test_session.commit()
    await test_session.refresh(artifact)

    proj = await auth_client.post("/api/v1/projects", json={"name": "model-unlink-host"})
    proj_id = proj.json()["id"]
    await auth_client.post(f"/api/v1/projects/{proj_id}/models/{artifact_uid}")

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.delete(f"/api/v1/projects/{proj_id}/models/{artifact_uid}")
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    unlinks = [r for r in rows if r.action == "model_artifact.project_unlinked"]
    assert len(unlinks) == 1
    event = unlinks[0]
    assert event.target_type == "ModelArtifact"
    assert int(event.target_id) == artifact.id
    assert event.before_state["project_id"] == proj_id
    assert event.after_state["project_id"] is None


# ---------------------------------------------------------------------------
# Idempotency — project.updated and project_data_source.updated
#
# Phase 3 fix-commit (bab7ac0) claimed "no emit when nothing actually
# changed" but the guard only landed in update_experiment. These tests
# pin the guard for project / data-source updates added in this fix.
# ---------------------------------------------------------------------------


async def test_project_update_idle_does_not_emit(auth_client, test_session):
    """PUT with empty payload → no project.updated row."""
    create = await auth_client.post(
        "/api/v1/projects",
        json={"name": "idle-proj", "technique": "FTIR"},
    )
    proj_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.put(f"/api/v1/projects/{proj_id}", json={})
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    assert [r for r in rows if r.action == "project.updated"] == []


async def test_project_update_same_value_does_not_emit(auth_client, test_session):
    """PUT with values equal to current state → no project.updated row.

    Catches the UI re-saving an unmodified form without flipping the
    audit trail. Distinct from the idle test because the payload is
    non-empty — the guard must compare before vs after, not just check
    payload presence.
    """
    create = await auth_client.post(
        "/api/v1/projects",
        json={"name": "same-name", "description": "same"},
    )
    proj_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.put(
        f"/api/v1/projects/{proj_id}",
        json={"name": "same-name", "description": "same"},
    )
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    assert [r for r in rows if r.action == "project.updated"] == []


async def test_project_data_source_update_idle_does_not_emit(auth_client, test_session):
    """PUT with empty payload → no project_data_source.updated row."""
    proj = await auth_client.post("/api/v1/projects", json={"name": "ds-idle"})
    proj_id = proj.json()["id"]
    create = await auth_client.post(
        f"/api/v1/projects/{proj_id}/data-sources",
        json={"display_name": "ds", "source_type": "manual"},
    )
    ds_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.put(
        f"/api/v1/projects/{proj_id}/data-sources/{ds_id}",
        json={},
    )
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    assert [r for r in rows if r.action == "project_data_source.updated"] == []


async def test_project_data_source_update_same_value_does_not_emit(auth_client, test_session):
    """PUT with values equal to current state → no project_data_source.updated row."""
    proj = await auth_client.post("/api/v1/projects", json={"name": "ds-same"})
    proj_id = proj.json()["id"]
    create = await auth_client.post(
        f"/api/v1/projects/{proj_id}/data-sources",
        json={"display_name": "alpha", "color": "#3b82f6"},
    )
    ds_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.put(
        f"/api/v1/projects/{proj_id}/data-sources/{ds_id}",
        json={"display_name": "alpha", "color": "#3b82f6"},
    )
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    assert [r for r in rows if r.action == "project_data_source.updated"] == []


# ---------------------------------------------------------------------------
# Experiment.updated — metadata before/after snapshot + sha256 anchor
#
# Phase 3 review high-severity gap: the audit row proved "metadata
# touched" without recording the old/new content. The fix snapshots
# both metadata dicts and an sha256 hash of canonical-JSON.
# ---------------------------------------------------------------------------


async def test_experiment_update_includes_metadata_diff(auth_client, test_session):
    """PUT with changed metadata → before/after include the full dict
    AND a sha256 anchor that reflects the change.
    """
    create = await auth_client.post(
        "/api/v1/experiments",
        json={
            "name": "meta-exp",
            "metadata": {"sample_id": "S-1", "operator": "alice"},
        },
    )
    exp_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.put(
        f"/api/v1/experiments/{exp_id}",
        json={"metadata": {"sample_id": "S-1", "operator": "bob"}},
    )
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    updates = [r for r in rows if r.action == "experiment.updated"]
    assert len(updates) == 1
    event = updates[0]
    assert event.before_state["metadata"] == {"sample_id": "S-1", "operator": "alice"}
    assert event.after_state["metadata"] == {"sample_id": "S-1", "operator": "bob"}
    # sha256 anchor must change with the content
    assert event.before_state["metadata_sha256"] != event.after_state["metadata_sha256"]
    # Both anchors must be 64-char hex digests (canonical JSON sha256)
    assert len(event.before_state["metadata_sha256"]) == 64
    assert len(event.after_state["metadata_sha256"]) == 64


async def test_experiment_update_metadata_only_unchanged_does_not_emit(auth_client, test_session):
    """PUT with the same metadata dict (no other changes) → no event.

    Pins the idempotency guard: the original Phase 3 fix would emit
    whenever ``metadata is not None`` regardless of whether the bytes
    actually changed. The metadata-snapshot fix subsumes that into a
    real before/after equality check.
    """
    create = await auth_client.post(
        "/api/v1/experiments",
        json={"name": "meta-noop", "metadata": {"k": "v"}},
    )
    exp_id = create.json()["id"]

    await test_session.execute(AuditEvent.__table__.delete())
    await test_session.commit()

    resp = await auth_client.put(
        f"/api/v1/experiments/{exp_id}",
        json={"metadata": {"k": "v"}},
    )
    assert resp.status_code == 200, resp.text

    rows = (await test_session.execute(select(AuditEvent))).scalars().all()
    assert [r for r in rows if r.action == "experiment.updated"] == []


# ---------------------------------------------------------------------------
# File-delete TX ordering
#
# Phase 3 review high-severity gap: the route unlinked the disk file
# before the audited DB transaction committed. If the audit insert /
# chainer commit failed, the row stayed but the file was gone. The fix
# reorders: DB+audit commit FIRST, then best-effort filesystem unlink.
# ---------------------------------------------------------------------------


async def test_file_delete_keeps_disk_file_when_audit_commit_fails(
    auth_client, test_session, test_user, monkeypatch, tmp_path
):
    """If the audit-bearing DB transaction aborts, the disk file MUST
    still exist — the user can retry; an orphan disk file is recoverable
    but an orphan DB row is not.

    Drives the route via the real HTTP path so the ordering between
    ``file_path.unlink()`` and ``delete_experiment_file(...)`` is
    exercised end-to-end. Forces the audit insert to fail by patching
    the emitter to raise inside the same TX.
    """
    from spectra_sherpa.app.services.experiments import (
        add_experiment_file,
        create_experiment,
        experiment_dir,
    )

    experiment = await create_experiment(
        test_session,
        user_id=test_user.id,
        name="exp-tx-ordering",
        description=None,
        metadata={},
        project_id=None,
    )

    # Stage a real file on disk + a matching ExperimentFile row.
    exp_dir = experiment_dir(experiment.id)
    (exp_dir / "raw").mkdir(parents=True, exist_ok=True)
    file_path = exp_dir / "raw" / "must-survive.csv"
    file_path.write_text("col_a,col_b\n1,2\n")
    exp_file = await add_experiment_file(
        session=test_session,
        experiment_id=experiment.id,
        stage="raw",
        file_path="raw/must-survive.csv",
        file_size_bytes=file_path.stat().st_size,
        file_type="csv",
    )

    assert file_path.exists(), "precondition: file must be staged on disk"

    # Patch the emitter so the audit insert raises — simulates an
    # audit-chain failure (e.g. chainer unavailable) at commit time.
    from spectra_sherpa.app.services import audit as audit_module

    def _boom(*a, **kw):
        raise RuntimeError("simulated audit failure during TX")

    monkeypatch.setattr(audit_module.audit_emitter, "emit", _boom)

    # The route bubbles the audit failure up — depending on the test
    # transport, the failure may appear as 5xx or be re-raised through
    # the call. Either is acceptable; the file-state contract below is
    # what we are pinning.
    try:
        resp = await auth_client.delete(f"/api/v1/experiments/{experiment.id}/files/{exp_file.id}")
        # If the transport returned a response, it must signal failure.
        assert resp.status_code >= 400, "audit failure should fail the request"
    except RuntimeError as exc:
        assert "simulated audit failure" in str(exc)

    # ── The actual contract: disk file MUST still exist. ──
    assert file_path.exists(), (
        "Audit-bearing TX failed but the disk file was removed. The "
        "route is unlinking before the audited commit; orphan-row risk."
    )

    # ── DB row MUST still exist (TX rolled back). ──
    from spectra_sherpa.app.models.experiment_file import ExperimentFile as _EF

    rows = (await test_session.execute(select(_EF).where(_EF.id == exp_file.id))).scalars().all()
    assert len(rows) == 1, "audit failure should roll back the DB delete"


async def test_file_delete_removes_disk_file_when_audit_commit_succeeds(auth_client, test_session, test_user):
    """Happy path: when the audit-bearing TX commits, the disk file is
    cleaned up too. Pairs with the failure test above to prove the
    reordering didn't accidentally leave files orphaned in the success
    path.
    """
    from spectra_sherpa.app.services.experiments import (
        add_experiment_file,
        create_experiment,
        experiment_dir,
    )

    experiment = await create_experiment(
        test_session,
        user_id=test_user.id,
        name="exp-happy-delete",
        description=None,
        metadata={},
        project_id=None,
    )

    exp_dir = experiment_dir(experiment.id)
    (exp_dir / "raw").mkdir(parents=True, exist_ok=True)
    file_path = exp_dir / "raw" / "to-be-removed.csv"
    file_path.write_text("ok\n")
    exp_file = await add_experiment_file(
        session=test_session,
        experiment_id=experiment.id,
        stage="raw",
        file_path="raw/to-be-removed.csv",
        file_size_bytes=file_path.stat().st_size,
        file_type="csv",
    )

    assert file_path.exists()

    resp = await auth_client.delete(f"/api/v1/experiments/{experiment.id}/files/{exp_file.id}")
    assert resp.status_code == 200, resp.text
    assert not file_path.exists(), "successful audited delete should also remove the file"
