"""The whole orphan sweep must preserve retained paths, not just matching UIDs."""

from uuid import uuid4

import pytest

from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.model_publication import ModelPublication
from spectra_sherpa.app.services.model_store import ModelStore, reconcile_orphan_artifacts


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["artifact", "publication"])
@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("relationship", ["same", "parent", "child"])
@pytest.mark.parametrize("directory_kind", ["artifact", "staging", "backup", "backup_recovery"])
async def test_orphan_sweep_preserves_other_uid_path_custody(
    test_session, test_user, tmp_path, owner, relative, relationship, directory_kind
):
    store = ModelStore(tmp_path)
    candidate_uid = str(uuid4())
    name = {
        "artifact": candidate_uid,
        "staging": f".staging-{candidate_uid}-interrupted",
        "backup": f"{candidate_uid}.old-interrupted",
        "backup_recovery": f"{candidate_uid}.old-interrupted",
    }[directory_kind]
    candidate = store.models_dir / name
    candidate.mkdir()
    retained_child = candidate / "retained"
    retained_child.mkdir()
    sentinel = retained_child / "scientific-bytes"
    sentinel.write_bytes(b"retained model evidence")
    if directory_kind == "backup":
        # Exercise stale-backup deletion, not just recovery into a missing path.
        (store.models_dir / candidate_uid).mkdir()
    protected = {"same": candidate, "parent": store.models_dir, "child": retained_child}[relationship]
    recorded_path = str(protected.relative_to(tmp_path) if relative else protected)
    uid = str(uuid4())  # Deliberately different from the directory's UID.
    if owner == "publication":
        record = ModelPublication(artifact_uid=uid, user_id=test_user.id, artifact_dir=recorded_path)
    else:
        record = ModelArtifact(
            artifact_uid=uid,
            user_id=test_user.id,
            node_id="retained-model",
            model_type="pca",
            name="Retained model",
            artifact_dir=recorded_path,
            integrity_hash="a" * 64,
            n_features=2,
        )
    test_session.add(record)
    await test_session.commit()

    removed = await reconcile_orphan_artifacts(test_session, store=store, grace_seconds=0)

    assert name not in removed
    assert sentinel.read_bytes() == b"retained model evidence"
    assert await test_session.get(type(record), uid if owner == "publication" else record.id) is not None
