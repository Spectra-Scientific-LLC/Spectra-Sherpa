from typing import Any, List, Optional
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.api import deps
from app.api.deps import invalidate_api_key_cache
from app.core import security
from app.core.config import app_config
from app.services.encryption import encrypt_value
from app.core.llm_registry import PROVIDERS
from app.models.api_key import APIKey
from app.models.data_egress import UserEgressDefaults
from app.models.user import User

router = APIRouter()


# ============================================================================
# Request/Response Models for System Keys
# ============================================================================

class SystemKeyCreate(BaseModel):
    """Request to add a system-wide LLM API key"""
    provider: str = Field(..., description="Provider ID (openai, anthropic, deepseek, gemini, custom_llm)")
    api_key: str = Field(..., min_length=10, description="The API key value")


class SystemKeyResponse(BaseModel):
    """Response for system key operations"""
    id: int
    provider: str
    provider_name: str
    created_at: str
    last_used_at: Optional[str] = None


class SystemKeyList(BaseModel):
    """List of system keys (without actual key values)"""
    keys: List[SystemKeyResponse]
    count: int


def require_non_local_mode() -> None:
    """
    Dependency that blocks admin routes in Local mode.

    Admin features (user management, API key rotation) are only relevant
    in multi-user deployments (hybrid, demo, cloud modes).
    """
    if app_config.mode == "local":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin features are disabled in Local mode. "
                   "Use hybrid or cloud mode for multi-user management.",
        )


# Dependency to check for superuser (and non-local mode)
async def get_current_superuser(
    _: None = Depends(require_non_local_mode),
    current_user: User = Depends(deps.get_current_user),
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges",
        )
    return current_user


def _ensure_mutable_standard_user(user: User) -> None:
    """Reject status/delete operations for protected accounts."""
    if user.username == "local":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify the local system user.",
        )
    if user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify superuser accounts.",
        )


@router.get("/users", response_model=List[schemas.User])
async def read_users(
    session: AsyncSession = Depends(deps.get_session),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_superuser),
) -> Any:
    """
    Retrieve users.
    """
    result = await session.execute(select(User).offset(skip).limit(limit))
    return result.scalars().all()


@router.post("/users", response_model=schemas.User)
async def create_user(
    *,
    session: AsyncSession = Depends(deps.get_session),
    user_in: schemas.UserCreate,
    current_user: User = Depends(get_current_superuser),
) -> Any:
    """
    Create new user.
    """
    result = await session.execute(select(User).where(User.username == user_in.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    
    user = User(
        username=user_in.username,
        password_hash=security.get_password_hash(user_in.password),
        is_superuser=user_in.is_superuser,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    # Create default egress permissions for the new user
    egress_defaults = UserEgressDefaults(
        user_id=user.id,
        allow_spectrasherpa_sync=False,
        allow_llm_context=True,
        allow_export=True,
        allow_nist_queries=True,
    )
    session.add(egress_defaults)
    await session.commit()

    return user


@router.post("/users/{user_id}/rotate-key", response_model=dict)
async def rotate_api_key(
    user_id: int,
    session: AsyncSession = Depends(deps.get_session),
    current_user: User = Depends(get_current_superuser),
) -> Any:
    """
    Generate a new API key for a user. returns the key ONCE.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Generate a strong API key
    new_key = f"sk_{secrets.token_urlsafe(32)}"
    # In a real system, you might hash this. 
    # For now, per requirements, we store it or a hash. 
    # Let's verify if `api_key_hash` is intended for actual storage or just hash.
    # Given the quick requirements, we'll store the hash of it for security.
    
    # Actually, deps.py checks `if api_key == settings.api_key`. 
    # We need to update deps.py to check USER api keys too. 
    # For this implementation step, we store the full key in a field or hash it.
    # Assuming we update deps.py later to check this table.
    
    # We'll store the plain key hash for now.
    user.api_key_hash = security.get_password_hash(new_key)
    session.add(user)
    await session.commit()

    # Invalidate all cached API keys for this user to ensure old keys stop working immediately
    invalidate_api_key_cache()

    return {"api_key": new_key, "note": "Save this key now. It will not be shown again."}


@router.patch("/users/{user_id}", response_model=schemas.User)
async def update_user_status(
    user_id: int,
    status_update: schemas.UserStatusUpdate,
    session: AsyncSession = Depends(deps.get_session),
    current_user: User = Depends(get_current_superuser),
) -> Any:
    """
    Toggle an account's active status.

    Protected accounts ("local" user and superusers) cannot be modified.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    _ensure_mutable_standard_user(user)
    user.is_active = status_update.is_active
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(deps.get_session),
    current_user: User = Depends(get_current_superuser),
) -> None:
    """
    Delete a user account.

    Protected accounts ("local" user and superusers) cannot be deleted.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    _ensure_mutable_standard_user(user)
    await session.delete(user)
    await session.commit()
    invalidate_api_key_cache()


# ============================================================================
# System LLM Key Management
# ============================================================================

@router.get("/system-keys", response_model=SystemKeyList)
async def list_system_keys(
    session: AsyncSession = Depends(deps.get_session),
    current_user: User = Depends(get_current_superuser),
) -> Any:
    """
    List all system-wide LLM API keys (without exposing actual key values).

    System keys have user_id=None and are available to all users when
    no user-specific key is configured.
    """
    result = await session.execute(
        select(APIKey).where(APIKey.user_id == None)
    )
    keys = result.scalars().all()

    return SystemKeyList(
        keys=[
            SystemKeyResponse(
                id=k.id,
                provider=k.service_name,
                provider_name=PROVIDERS.get(k.service_name, {}).get("name", k.service_name),
                created_at=k.created_at.isoformat() if k.created_at else "",
                last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            )
            for k in keys
        ],
        count=len(keys)
    )


@router.post("/system-keys", response_model=SystemKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_system_key(
    key_in: SystemKeyCreate,
    session: AsyncSession = Depends(deps.get_session),
    current_user: User = Depends(get_current_superuser),
) -> Any:
    """
    Add or update a system-wide LLM API key.

    This key will be used for all users who don't have their own BYOK key
    configured for this provider.

    Example:
        POST /admin/system-keys
        {"provider": "anthropic", "api_key": "sk-ant-..."}
    """
    # Validate provider
    if key_in.provider not in PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider. Must be one of: {', '.join(PROVIDERS.keys())}"
        )

    # Check if system key already exists for this provider
    result = await session.execute(
        select(APIKey).where(
            APIKey.user_id == None,
            APIKey.service_name == key_in.provider
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing key
        existing.key_encrypted = encrypt_value(key_in.api_key)
        await session.commit()
        await session.refresh(existing)
        key = existing
    else:
        # Create new system key
        key = APIKey(
            user_id=None,  # System key
            service_name=key_in.provider,
            key_encrypted=encrypt_value(key_in.api_key),
        )
        session.add(key)
        await session.commit()
        await session.refresh(key)

    return SystemKeyResponse(
        id=key.id,
        provider=key.service_name,
        provider_name=PROVIDERS[key.service_name]["name"],
        created_at=key.created_at.isoformat() if key.created_at else "",
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
    )


@router.delete("/system-keys/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system_key(
    provider: str,
    session: AsyncSession = Depends(deps.get_session),
    current_user: User = Depends(get_current_superuser),
) -> None:
    """
    Remove a system-wide LLM API key.
    """
    result = await session.execute(
        select(APIKey).where(
            APIKey.user_id == None,
            APIKey.service_name == provider
        )
    )
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail=f"System key for {provider} not found")

    await session.delete(key)
    await session.commit()
