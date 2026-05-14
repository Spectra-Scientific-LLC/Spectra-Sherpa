from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session
from spectra_sherpa.app.models.api_key import APIKey
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.api_key import APIKeyCreate, APIKeyInfo
from spectra_sherpa.app.services.encryption import encrypt_value


class _StatusResponse(BaseModel):
    status: str


router = APIRouter()


@router.get("/api-keys", response_model=list[APIKeyInfo])
async def list_api_keys(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[APIKeyInfo]:
    """List API keys for the authenticated user."""
    result = await session.execute(select(APIKey).where(APIKey.user_id == current_user.id))
    keys = result.scalars().all()
    return [APIKeyInfo(service_name=key.service_name, last_used_at=key.last_used_at) for key in keys]


@router.post(
    "/api-keys",
    status_code=201,
    response_model=_StatusResponse,
    dependencies=[Depends(demo_guard("api_key_management"))],
)
async def set_api_key(
    payload: APIKeyCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Create or update API key for the authenticated user."""
    result = await session.execute(
        select(APIKey).where(APIKey.user_id == current_user.id, APIKey.service_name == payload.service_name)
    )
    api_key = result.scalar_one_or_none()
    encrypted = encrypt_value(payload.key)

    if api_key:
        action = "api_key.updated"
        api_key.key_encrypted = encrypted
    else:
        action = "api_key.created"
        api_key = APIKey(
            user_id=current_user.id,
            service_name=payload.service_name,
            key_encrypted=encrypted,
        )
        session.add(api_key)

    await session.flush()  # ensure api_key.id is assigned for both branches

    # ISO 17025 audit — Phase 3 coverage. The plaintext key is never
    # written to the audit log; the audit event records only the
    # service_name and api_key.id so an investigator can correlate
    # "who configured the X integration" without leaking secrets.
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action=action,
        target_type="APIKey",
        target_id=api_key.id,
        after={"service_name": api_key.service_name, "user_id": api_key.user_id},
    )

    await session.commit()
    return {"status": "stored"}


from fastapi import Response


@router.delete(
    "/api-keys/{service_name}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(demo_guard("api_key_management"))],
)
async def delete_api_key(
    service_name: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete API key for the authenticated user."""
    result = await session.execute(
        select(APIKey).where(APIKey.user_id == current_user.id, APIKey.service_name == service_name)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")

    # ISO 17025 audit — emit BEFORE delete (Phase 3 coverage).
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="api_key.deleted",
        target_type="APIKey",
        target_id=api_key.id,
        before={"service_name": api_key.service_name, "user_id": api_key.user_id},
    )

    await session.delete(api_key)
    await session.commit()
