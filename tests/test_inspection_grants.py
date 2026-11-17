"""Real database admission, expiry, revocation and registered-client isolation."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.models.inspection_grant import InspectionGrant
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.inspection_grants import (
    InspectionAccessDenied,
    authenticate_inspection_client,
    issue_inspection_credential,
    revoke_inspection_credential,
)


@pytest.fixture
async def project(test_session, test_user):
    row = Project(user_id=test_user.id, name="Granted project")
    test_session.add(row)
    await test_session.commit()
    return row


async def authenticate(session, credential, **overrides):
    arguments = dict(client_id=credential.identity.client_id, project_id=credential.identity.project_id)
    arguments.update(overrides)
    return await authenticate_inspection_client(session, credential.token, **arguments)


async def test_secret_stored_only_as_digest_and_client_label_grants_nothing(test_session, test_user, project):
    first = await issue_inspection_credential(test_session, test_user, project.id, "Same client")
    second = await issue_inspection_credential(test_session, test_user, project.id, "Same client")
    await test_session.commit()
    assert first.identity != second.identity
    assert first.token not in repr(first)
    row = await test_session.get(InspectionGrant, first.identity.client_id)
    assert len(row.token_digest) == 64 and row.token_digest != first.token
    assert "values" not in first.identity.disclosures and "identifiers" not in first.identity.disclosures
    assert await authenticate(test_session, first) == first.identity
    with pytest.raises(InspectionAccessDenied):
        await authenticate(test_session, first, client_id=second.identity.client_id)
    with pytest.raises(InspectionAccessDenied):
        await authenticate(test_session, first, client_id="Same client")


async def test_cross_project_and_cross_actor_denied(test_session, test_user, project):
    other = User(username="other")
    test_session.add(other)
    await test_session.flush()
    other_project = Project(user_id=other.id, name="Private")
    test_session.add(other_project)
    await test_session.commit()
    with pytest.raises(InspectionAccessDenied):
        await issue_inspection_credential(test_session, test_user, other_project.id, "Client")
    credential = await issue_inspection_credential(test_session, test_user, project.id, "Client")
    with pytest.raises(InspectionAccessDenied):
        await authenticate(test_session, credential, project_id=other_project.id)
    with pytest.raises(InspectionAccessDenied):
        await revoke_inspection_credential(test_session, other, credential.identity.client_id)
    assert await authenticate(test_session, credential) == credential.identity


@pytest.mark.parametrize("change", ["expiry", "revocation", "disabled_actor", "deleted_project", "changed_owner"])
async def test_every_call_rechecks_live_authority(test_session, test_user, project, change):
    credential = await issue_inspection_credential(test_session, test_user, project.id, "Client")
    await test_session.commit()
    assert await authenticate(test_session, credential) == credential.identity
    grant = await test_session.get(InspectionGrant, credential.identity.client_id)
    if change == "expiry":
        grant.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif change == "revocation":
        await revoke_inspection_credential(test_session, test_user, grant.id)
    elif change == "disabled_actor":
        test_user.is_active = False
    elif change == "deleted_project":
        project.deleted_at = datetime.now(timezone.utc)
    else:
        other = User(username="replacement_owner")
        test_session.add(other)
        await test_session.flush()
        project.user_id = other.id
    await test_session.commit()
    with pytest.raises(InspectionAccessDenied):
        await authenticate(test_session, credential)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ttl_seconds": 0},
        {"ttl_seconds": True},
        {"ttl_seconds": 2592001},
        {"client_label": " "},
        {"client_label": "Injected\nlabel"},
        {"disclosures": frozenset({"values"})},
        {"disclosures": frozenset({"identifiers"})},
    ],
)
async def test_issuance_rejects_unreviewed_bounds(test_session, test_user, project, kwargs):
    arguments = dict(client_label="Client")
    arguments.update(kwargs)
    with pytest.raises(ValueError):
        await issue_inspection_credential(test_session, test_user, project.id, **arguments)
    assert (await test_session.scalars(select(InspectionGrant))).all() == []


async def test_credential_and_revocation_survive_database_reopen(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'grants.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(username="owner")
        session.add(user)
        await session.flush()
        project = Project(user_id=user.id, name="Persistent")
        session.add(project)
        await session.flush()
        credential = await issue_inspection_credential(session, user, project.id, "Desktop client")
        await session.commit()
    await engine.dispose()

    engine = create_async_engine(url)
    async with AsyncSession(engine) as session:
        assert await authenticate(session, credential) == credential.identity
        await revoke_inspection_credential(session, user, credential.identity.client_id)
        await session.commit()
    await engine.dispose()
    engine = create_async_engine(url)
    async with AsyncSession(engine) as session:
        with pytest.raises(InspectionAccessDenied):
            await authenticate(session, credential)
        stored = (await session.execute(text("SELECT * FROM inspection_grant"))).all()
        assert credential.token not in repr(stored)
    await engine.dispose()


async def test_revocation_in_another_session_invalidates_cached_grant(test_session, test_engine, test_user, project):
    credential = await issue_inspection_credential(test_session, test_user, project.id, "Client")
    await test_session.commit()
    cached = await test_session.get(InspectionGrant, credential.identity.client_id)
    assert cached.revoked_at is None
    async with AsyncSession(test_engine) as other_session:
        await revoke_inspection_credential(other_session, test_user, credential.identity.client_id)
        await other_session.commit()
    assert cached.revoked_at is None
    with pytest.raises(InspectionAccessDenied):
        await authenticate(test_session, credential)
