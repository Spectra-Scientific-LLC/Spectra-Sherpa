from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session
from spectra_sherpa.app.models.api_key import APIKey
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.api_key import APIKeyCreate, APIKeyInfo
from spectra_sherpa.app.services.encryption import encrypt_value

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


@router.post("/api-keys", status_code=201, dependencies=[Depends(demo_guard("api_key_management"))])
async def set_api_key(
    payload: APIKeyCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Create or update API key for the authenticated user."""
    result = await session.execute(
        select(APIKey).where(
            APIKey.user_id == current_user.id, APIKey.service_name == payload.service_name
        )
    )
    api_key = result.scalar_one_or_none()
    encrypted = encrypt_value(payload.key)

    if api_key:
        api_key.key_encrypted = encrypted
    else:
        api_key = APIKey(
            user_id=current_user.id,
            service_name=payload.service_name,
            key_encrypted=encrypted,
        )
        session.add(api_key)

    await session.commit()
    return {"status": "stored"}


@router.delete("/api-keys/{service_name}", status_code=204, dependencies=[Depends(demo_guard("api_key_management"))])
async def delete_api_key(
    service_name: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete API key for the authenticated user."""
    result = await session.execute(
        select(APIKey).where(
            APIKey.user_id == current_user.id, APIKey.service_name == service_name
        )
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")

    await session.delete(api_key)
    await session.commit()
