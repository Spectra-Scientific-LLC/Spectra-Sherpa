"""Two-user adversarial tests for user-scoped settings and workflow organization."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.user import User


async def _second_user(session: AsyncSession) -> User:
    user = User(username="other-settings-owner")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_egress_defaults_and_permissions_are_user_scoped(
    auth_client,
    test_session: AsyncSession,
    test_user: User,
    swap_user,
) -> None:
    defaults = await auth_client.put("/api/v1/egress/defaults", json={"allow_export": True})
    permission = await auth_client.post(
        "/api/v1/egress/permissions",
        json={"data_type": "spectra", "destination": "export", "allowed": True},
    )
    assert defaults.status_code == 200
    assert permission.status_code == 201
    permission_id = permission.json()["id"]
    other_user = await _second_user(test_session)

    swap_user(other_user)
    assert (await auth_client.get("/api/v1/egress/defaults")).json() is None
    assert (await auth_client.get("/api/v1/egress/permissions")).json() == []
    assert (await auth_client.get("/api/v1/egress/summary")).json()["permissions"] == []
    denied_update = await auth_client.put(
        f"/api/v1/egress/permissions/{permission_id}",
        json={"allowed": False},
    )
    assert denied_update.status_code == 404
    assert (await auth_client.delete(f"/api/v1/egress/permissions/{permission_id}")).status_code == 404

    other_defaults = await auth_client.put("/api/v1/egress/defaults", json={"allow_export": False})
    assert other_defaults.status_code == 200
    assert other_defaults.json()["user_id"] == other_user.id

    swap_user(test_user)
    own_defaults = await auth_client.get("/api/v1/egress/defaults")
    own_permissions = await auth_client.get("/api/v1/egress/permissions")
    assert own_defaults.json()["allow_export"] is True
    assert [item["id"] for item in own_permissions.json()] == [permission_id]
    assert own_permissions.json()[0]["allowed"] is True


@pytest.mark.asyncio
async def test_workflow_tags_and_folders_cannot_cross_user_boundaries(
    auth_client,
    test_session: AsyncSession,
    test_user: User,
    swap_user,
) -> None:
    tag = await auth_client.post("/api/v1/workflows/tags", json={"name": "private-tag", "color": "#445566"})
    folder = await auth_client.post("/api/v1/workflows/folders", json={"name": "private-folder"})
    assert tag.status_code == 201
    assert folder.status_code == 201
    tag_id = tag.json()["id"]
    folder_id = folder.json()["id"]
    other_user = await _second_user(test_session)

    swap_user(other_user)
    assert (await auth_client.get("/api/v1/workflows/tags")).json() == []
    assert (await auth_client.get("/api/v1/workflows/folders")).json() == []
    assert (await auth_client.get(f"/api/v1/workflows/tags/{tag_id}")).status_code == 404
    assert (await auth_client.put(f"/api/v1/workflows/tags/{tag_id}", json={"name": "stolen"})).status_code == 404
    assert (await auth_client.delete(f"/api/v1/workflows/tags/{tag_id}")).status_code == 404
    assert (await auth_client.get(f"/api/v1/workflows/folders/{folder_id}")).status_code == 404
    assert (await auth_client.put(f"/api/v1/workflows/folders/{folder_id}", json={"name": "stolen"})).status_code == 404
    assert (await auth_client.delete(f"/api/v1/workflows/folders/{folder_id}")).status_code == 404
    assert (
        await auth_client.post("/api/v1/workflows/folders", json={"name": "cross-user-child", "parent_id": folder_id})
    ).status_code == 404

    swap_user(test_user)
    assert (await auth_client.get(f"/api/v1/workflows/tags/{tag_id}")).json()["name"] == "private-tag"
    assert (await auth_client.get(f"/api/v1/workflows/folders/{folder_id}")).json()["name"] == "private-folder"


@pytest.mark.asyncio
async def test_workflow_tag_and_folder_static_routes_are_reachable(auth_client) -> None:
    """Static organization paths must precede workflows' ``/{workflow_id}`` route."""
    tag = await auth_client.post("/api/v1/workflows/tags", json={"name": "reachable-tag", "color": "#112233"})
    folder = await auth_client.post("/api/v1/workflows/folders", json={"name": "reachable-folder"})

    assert tag.status_code == 201
    assert folder.status_code == 201
    assert (await auth_client.get("/api/v1/workflows/tags")).status_code == 200
    assert (await auth_client.get("/api/v1/workflows/folders")).status_code == 200


@pytest.mark.asyncio
async def test_experiment_root_and_children_cannot_cross_user_boundaries(
    auth_client,
    test_session: AsyncSession,
    test_user: User,
    swap_user,
) -> None:
    created = await auth_client.post(
        "/api/v1/experiments",
        json={"name": "private-experiment", "metadata": {}},
    )
    assert created.status_code == 201
    experiment_id = created.json()["id"]
    other_user = await _second_user(test_session)

    swap_user(other_user)
    assert (await auth_client.get("/api/v1/experiments")).json() == []
    assert (await auth_client.get(f"/api/v1/experiments/{experiment_id}")).status_code == 404
    assert (
        await auth_client.put(f"/api/v1/experiments/{experiment_id}", json={"name": "stolen-experiment"})
    ).status_code == 404
    assert (await auth_client.delete(f"/api/v1/experiments/{experiment_id}")).status_code == 404
    assert (await auth_client.get(f"/api/v1/experiments/{experiment_id}/files")).status_code == 404
    assert (await auth_client.get(f"/api/v1/experiments/{experiment_id}/versions")).status_code == 404
    assert (
        await auth_client.post(
            f"/api/v1/experiments/{experiment_id}/versions",
            json={"version_name": "other-user-version"},
        )
    ).status_code == 404
    assert (await auth_client.post(f"/api/v1/experiments/{experiment_id}/versions/any/restore")).status_code == 404

    swap_user(test_user)
    own = await auth_client.get(f"/api/v1/experiments/{experiment_id}")
    assert own.status_code == 200
    assert own.json()["name"] == "private-experiment"


@pytest.mark.asyncio
async def test_api_key_metadata_and_deletion_are_user_scoped(
    auth_client,
    test_session: AsyncSession,
    test_user: User,
    swap_user,
) -> None:
    service_name = "private-provider"
    stored = await auth_client.post(
        "/api/v1/api-keys",
        json={"service_name": service_name, "key": "test-secret-key"},
    )
    assert stored.status_code == 201
    other_user = await _second_user(test_session)

    swap_user(other_user)
    assert (await auth_client.get("/api/v1/api-keys")).json() == []
    assert (await auth_client.delete(f"/api/v1/api-keys/{service_name}")).status_code == 404

    swap_user(test_user)
    own_keys = await auth_client.get("/api/v1/api-keys")
    assert own_keys.status_code == 200
    assert own_keys.json() == [{"service_name": service_name, "last_used_at": None}]


@pytest.mark.asyncio
async def test_model_artifact_metadata_cannot_cross_user_boundaries(
    auth_client,
    test_session: AsyncSession,
    test_user: User,
    swap_user,
) -> None:
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.services.model_store import get_model_store

    artifact_uid = "private-artifact-metadata"
    store = get_model_store()
    integrity_hash = store.save(
        artifact_uid,
        {"model_type": "pls", "node_id": "pls-train-1", "n_features": 4},
        {},
    )
    test_session.add(
        ModelArtifact(
            artifact_uid=artifact_uid,
            user_id=test_user.id,
            node_id="pls-train-1",
            model_type="pls",
            name="private-model",
            artifact_dir=str(store._artifact_dir(artifact_uid)),
            integrity_hash=integrity_hash,
            n_features=4,
            tags=[],
        )
    )
    await test_session.commit()
    other_user = await _second_user(test_session)

    swap_user(other_user)
    assert (await auth_client.get("/api/v1/models")).json() == []
    assert (await auth_client.get("/api/v1/models/select")).json() == []
    assert (await auth_client.get(f"/api/v1/models/{artifact_uid}")).status_code == 404
    assert (
        await auth_client.patch(f"/api/v1/models/{artifact_uid}", json={"display_name": "stolen-model"})
    ).status_code == 404
    assert (await auth_client.delete(f"/api/v1/models/{artifact_uid}?purge=false")).status_code == 404

    swap_user(test_user)
    own = await auth_client.get(f"/api/v1/models/{artifact_uid}")
    assert own.status_code == 200
    assert own.json()["name"] == "private-model"
    assert own.json()["is_active"] is True


@pytest.mark.asyncio
async def test_folder_watches_cannot_cross_user_boundaries(
    auth_client,
    test_session: AsyncSession,
    test_user: User,
    swap_user,
    deployment_artifact_factory,
    tmp_path,
) -> None:
    from spectra_sherpa.app.models.folder_watch import FolderWatch
    from spectra_sherpa.app.models.workflow import Workflow

    workflow = Workflow(user_id=test_user.id, name="private-watch-workflow")
    test_session.add(workflow)
    await test_session.flush()
    artifact = await deployment_artifact_factory(workflow)
    import numpy as np

    from spectra_sherpa.app.lib.fitted_state import LinearRegressionExtract
    from spectra_sherpa.app.services.model_store import get_model_store
    from spectra_sherpa.io import ingest

    manifest, arrays = LinearRegressionExtract(coef=np.array([2.0, -1.0]), intercept=np.array([0.5])).to_artifact()
    manifest["n_features"] = 2
    store = get_model_store()
    artifact.integrity_hash = store.save_new(artifact.artifact_uid, manifest, arrays)
    artifact.artifact_dir = store.artifact_directory(artifact.artifact_uid)
    representative = tmp_path / "representative.csv"
    representative.write_text("1000,1100\n1,0\n2,0.5\n3,1\n")
    selected_asset = ingest(representative).assets[0].asset_id
    watch = FolderWatch(
        user_id=test_user.id,
        workflow_id=workflow.id,
        artifact_uid=artifact.artifact_uid,
        workflow_version_id=artifact.workflow_version_id,
        name="private-folder-watch",
        folder_path=str(tmp_path),
        settle_time_seconds=0,
        file_pattern="*.csv",
        poll_interval_sec=60,
        is_enabled=False,
        asset_id="wrong",
        processed_files={"/tmp/private-watch/sample.0": "2026-08-21T00:00:00+00:00"},
    )
    test_session.add(watch)
    await test_session.commit()
    await test_session.refresh(watch)
    other_user = await _second_user(test_session)

    swap_user(other_user)
    assert (await auth_client.get("/api/v1/deploy/watches")).json() == []
    assert (await auth_client.get(f"/api/v1/deploy/watches/{watch.id}")).status_code == 404
    assert (
        await auth_client.patch(f"/api/v1/deploy/watches/{watch.id}", json={"name": "stolen-watch"})
    ).status_code == 404
    assert (await auth_client.post(f"/api/v1/deploy/watches/{watch.id}/enable")).status_code == 404
    assert (await auth_client.post(f"/api/v1/deploy/watches/{watch.id}/disable")).status_code == 404
    assert (await auth_client.delete(f"/api/v1/deploy/watches/{watch.id}")).status_code == 404

    swap_user(test_user)
    own = await auth_client.get(f"/api/v1/deploy/watches/{watch.id}")
    assert own.status_code == 200
    assert own.json()["name"] == "private-folder-watch"
    assert own.json()["is_enabled"] is False

    from spectra_sherpa.app.services.folder_watch_service import (
        _claim_watch_if_current,
        _write_watch_state_if_current,
    )

    watch.is_enabled = True
    await test_session.commit()
    claimed_asset_id = watch.asset_id
    claimed_generation = watch.configuration_generation
    old_claim_token = await _claim_watch_if_current(test_session, watch)
    assert old_claim_token is not None
    await test_session.refresh(watch)
    assert watch.active_poll_token == old_claim_token
    assert watch.last_poll_at is not None
    edited = await auth_client.patch(
        f"/api/v1/deploy/watches/{watch.id}",
        json={"asset_id": selected_asset},
    )
    assert edited.status_code == 200
    assert edited.json()["asset_id"] == selected_asset
    await test_session.refresh(watch)
    assert watch.configuration_generation > claimed_generation

    disabled = await auth_client.post(f"/api/v1/deploy/watches/{watch.id}/disable")
    assert disabled.status_code == 200
    # Editing the live configuration invalidates the earlier polling claim.
    assert disabled.json()["last_poll_at"] is None

    corrected = await auth_client.patch(
        f"/api/v1/deploy/watches/{watch.id}",
        json={"asset_id": selected_asset},
    )
    assert corrected.status_code == 200
    assert corrected.json()["asset_id"] == selected_asset
    assert corrected.json()["processed_files"] == {}

    # Exact stale-poll interleaving: an old-asset poll claimed the watch,
    # then the scientist disabled it, corrected the asset, and re-enabled it.
    # Its eventual operational-state write must lose the database CAS and
    # cannot contaminate the new asset's discovery history.
    # Representative-file inference is optional; it does not gate local activation.
    check = await auth_client.post(
        f"/api/v1/deploy/watches/{watch.id}/dry-run", json={"file_name": "representative.csv"}
    )
    assert check.status_code == 200 and check.json()["status"] == "completed", check.text
    reenabled = await auth_client.post(f"/api/v1/deploy/watches/{watch.id}/enable")
    assert reenabled.status_code == 200
    assert reenabled.json()["last_poll_at"] is None

    stale_write = await _write_watch_state_if_current(
        test_session,
        watch_id=watch.id,
        claimed_asset_id=claimed_asset_id,
        claimed_generation=claimed_generation,
        claim_token=old_claim_token,
        values={
            "processed_files": {"/tmp/private-watch/sample.0": "stale-old-asset"},
            "last_error": "stale old-asset failure",
        },
    )
    await test_session.commit()
    assert stale_write is False
    await test_session.refresh(watch)
    assert watch.asset_id == selected_asset
    assert watch.processed_files == {}
    assert watch.last_error is None

    # Cosmetic edits do not invalidate a scientifically valid in-flight poll.
    await test_session.refresh(watch)
    current_generation = watch.configuration_generation
    current_asset_id = watch.asset_id
    current_claim_token = await _claim_watch_if_current(test_session, watch)
    assert current_claim_token is not None
    renamed = await auth_client.patch(
        f"/api/v1/deploy/watches/{watch.id}",
        json={"name": "renamed-watch"},
    )
    assert renamed.status_code == 200
    await test_session.refresh(watch)
    assert watch.configuration_generation == current_generation
    valid_write = await _write_watch_state_if_current(
        test_session,
        watch_id=watch.id,
        claimed_asset_id=current_asset_id,
        claimed_generation=current_generation,
        claim_token=current_claim_token,
        values={"processed_files": {"/tmp/private-watch/sample.0": "current-asset"}},
    )
    await test_session.commit()
    assert valid_write is True

    # A real active lease survives repeated enable and a disable/re-enable
    # cycle. No second worker can claim the same files, and the accepted poll
    # can still persist its history under the unchanged source identity.
    await test_session.refresh(watch)
    watch.last_poll_at = None
    await test_session.commit()
    await test_session.refresh(watch)
    accepted_generation = watch.configuration_generation
    accepted_asset_id = watch.asset_id
    accepted_claim_token = await _claim_watch_if_current(test_session, watch)
    assert accepted_claim_token is not None
    await test_session.refresh(watch)
    claimed_at = watch.last_poll_at
    repeated_enable = await auth_client.post(f"/api/v1/deploy/watches/{watch.id}/enable")
    assert repeated_enable.status_code == 200
    await test_session.refresh(watch)
    assert watch.configuration_generation == accepted_generation
    assert watch.active_poll_token == accepted_claim_token
    assert watch.last_poll_at == claimed_at

    first_disable = await auth_client.post(f"/api/v1/deploy/watches/{watch.id}/disable")
    assert first_disable.status_code == 200
    reenable_cycle = await auth_client.post(f"/api/v1/deploy/watches/{watch.id}/enable")
    assert reenable_cycle.status_code == 200
    await test_session.refresh(watch)
    assert watch.configuration_generation == accepted_generation
    assert watch.active_poll_token == accepted_claim_token
    assert watch.last_poll_at == claimed_at
    assert await _claim_watch_if_current(test_session, watch) is None
    accepted_write = await _write_watch_state_if_current(
        test_session,
        watch_id=watch.id,
        claimed_asset_id=accepted_asset_id,
        claimed_generation=accepted_generation,
        claim_token=accepted_claim_token,
        values={"processed_files": {"/tmp/private-watch/cycle.0": "accepted-once"}},
    )
    await test_session.commit()
    assert accepted_write is True

    # A scheduling-only interval edit likewise preserves the active lease and
    # accepted poll history instead of making the same file runnable twice.
    await test_session.refresh(watch)
    watch.last_poll_at = None
    await test_session.commit()
    await test_session.refresh(watch)
    interval_generation = watch.configuration_generation
    interval_asset_id = watch.asset_id
    interval_claim_token = await _claim_watch_if_current(test_session, watch)
    assert interval_claim_token is not None
    interval_edit = await auth_client.patch(
        f"/api/v1/deploy/watches/{watch.id}",
        json={"poll_interval_sec": 120},
    )
    assert interval_edit.status_code == 200
    await test_session.refresh(watch)
    assert watch.configuration_generation == interval_generation
    assert watch.active_poll_token == interval_claim_token
    assert await _claim_watch_if_current(test_session, watch) is None
    interval_write = await _write_watch_state_if_current(
        test_session,
        watch_id=watch.id,
        claimed_asset_id=interval_asset_id,
        claimed_generation=interval_generation,
        claim_token=interval_claim_token,
        values={"processed_files": {"/tmp/private-watch/interval.0": "accepted-once"}},
    )
    await test_session.commit()
    assert interval_write is True
