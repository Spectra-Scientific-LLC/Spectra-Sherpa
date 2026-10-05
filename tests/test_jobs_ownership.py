"""Adversarial ownership tests for user-visible background jobs."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.job_manager import job_manager


async def _job_for(session: AsyncSession, user_id: int) -> BackgroundJob:
    job = BackgroundJob(user_id=user_id, job_type="import", status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _second_user(session: AsyncSession) -> User:
    user = User(username="other-job-owner")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_cancel_job_service_requires_the_owning_actor(
    test_session: AsyncSession,
    test_user: User,
) -> None:
    job = await _job_for(test_session, test_user.id)
    user2 = await _second_user(test_session)

    cancelled = await job_manager.cancel_job(test_session, job.id, user_id=user2.id)

    assert cancelled is False
    await test_session.refresh(job)
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_jobs_route_cannot_cancel_another_users_job(
    auth_client,
    test_session: AsyncSession,
    test_user: User,
    swap_user,
) -> None:
    job = await _job_for(test_session, test_user.id)
    job_id = job.id
    user2 = await _second_user(test_session)

    swap_user(user2)
    denied = await auth_client.delete(f"/api/v1/jobs/{job_id}")

    assert denied.status_code == 404
    await test_session.refresh(job)
    # The denied conditional update rolls back the shared fixture session and
    # expires ORM instances. Reload the user before using it in the next
    # simulated request; production requests receive a fresh session instead.
    await test_session.refresh(test_user)
    assert job.status == "pending"

    swap_user(test_user)
    allowed = await auth_client.delete(f"/api/v1/jobs/{job_id}")

    assert allowed.status_code == 204
    await test_session.refresh(job)
    assert job.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_job_service_does_not_overwrite_a_completed_job(
    test_session: AsyncSession,
    test_user: User,
) -> None:
    job = await _job_for(test_session, test_user.id)
    job.status = "completed"
    job.error_message = "finished normally"
    await test_session.commit()

    cancelled = await job_manager.cancel_job(test_session, job.id, user_id=test_user.id)

    assert cancelled is False
    await test_session.refresh(job)
    assert job.status == "completed"
    assert job.error_message == "finished normally"
