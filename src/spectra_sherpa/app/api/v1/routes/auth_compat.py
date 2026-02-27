"""OSS-compatible auth routes for hybrid/enterprise modes.

When ``spectra-server`` is installed its full auth module takes priority
(see ``api.py:get_server_routers``).  This fallback provides the minimal
endpoints the frontend needs so that hybrid-mode loopback login works
without the proprietary package.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app import schemas
from spectra_sherpa.app.api.deps import get_current_active_user, get_session
from spectra_sherpa.app.core import security
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.models.user import User

router = APIRouter()

# Constant-time dummy hash to prevent timing-based username enumeration.
_DUMMY_HASH = "$2b$12$LJ3m4ys3Lg2Kl7QLd.OXxuMhT5YEVMxNqXEPmJGxqE4M1ZpOSvSm"


@router.post("/login", response_model=schemas.Token)
async def login_access_token(
    request: Request,
    session: AsyncSession = Depends(get_session),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """OAuth2 compatible token login.

    Validates username/password against the local database and returns
    a JWT access token.
    """
    result = await session.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()

    password_valid = security.verify_password(
        form_data.password,
        user.password_hash if user else _DUMMY_HASH,
    )
    if not user or not password_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect username or password",
        )
    if hasattr(user, "is_active") and not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    return {
        "access_token": security.create_access_token({"sub": str(user.id)}, expires_delta=access_token_expires),
        "token_type": "bearer",
    }


@router.get("/me", response_model=schemas.User)
async def read_current_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Return the current authenticated user.

    Frontend hybrid bootstrap expects ``GET /api/v1/auth/me`` even when
    server-only auth/admin route modules are not packaged in this repo.
    """
    return current_user
