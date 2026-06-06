"""H2 — GET /models/{uid}/inspect must verify integrity before returning stats.

Audit DATA-3 documents the contract: every "use the model" load path must
re-verify the npz hash so corrupt/truncated arrays fail loud instead of
silently feeding wrong numbers into prediction OR inspection. PR #161/#164
left inspect_model bypassing this — load_manifest + load_arrays separately
both skip the integrity check.
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.user import User


async def _seed_artifact_with_files(test_session, test_user: User, tmp_path):
    """Create a ModelArtifact row + on-disk npz / manifest that load() can
    open."""
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.model_store import init_model_store

    project = Project(user_id=test_user.id, name="inspect-p")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="inspect-wf")
    test_session.add(workflow)
    await test_session.flush()

    store = init_model_store(tmp_path)
    arrays = {"weights": np.arange(10, dtype=np.float64)}
    metadata = {
        "model_type": "pls",
        "name": "inspect-target",
        "n_features": 10,
    }
    artifact_uid = "test-inspect-uid-0001"
    integrity_hash = store.save(artifact_uid, metadata, arrays)

    artifact = ModelArtifact(
        artifact_uid=artifact_uid,
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        node_id="node_1",
        model_type="pls",
        name="inspect",
        display_name="inspect",
        artifact_dir=str(store._artifact_dir(artifact_uid)),
        integrity_hash=integrity_hash,
        n_features=10,
        tags=[],
        is_active=True,
    )
    test_session.add(artifact)
    await test_session.commit()
    return artifact_uid, store


@pytest.mark.asyncio
async def test_inspect_returns_stats_for_intact_artifact(auth_client, test_session, test_user: User, tmp_path):
    artifact_uid, _ = await _seed_artifact_with_files(test_session, test_user, tmp_path)

    resp = await auth_client.get(f"/api/v1/models/{artifact_uid}/inspect")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["artifact_uid"] == artifact_uid
    assert "weights" in body["arrays"]


@pytest.mark.asyncio
async def test_inspect_returns_422_when_arrays_file_is_corrupt(auth_client, test_session, test_user: User, tmp_path):
    """Truncating arrays.npz must surface as a 422 from inspect (audit DATA-3),
    NOT a silent 200 with wrong stats."""
    artifact_uid, store = await _seed_artifact_with_files(test_session, test_user, tmp_path)

    npz_path = store._artifact_dir(artifact_uid) / "arrays.npz"
    # Truncate to the first 16 bytes so the hash no longer matches.
    npz_path.write_bytes(npz_path.read_bytes()[:16])

    resp = await auth_client.get(f"/api/v1/models/{artifact_uid}/inspect")
    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", "")
    assert "corrupt" in detail.lower() or "hash" in detail.lower()
