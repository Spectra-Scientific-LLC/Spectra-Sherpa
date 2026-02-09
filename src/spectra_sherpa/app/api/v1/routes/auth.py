from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.api import deps
from app.core import security
from app.core.config import settings, app_config
from app.models.data_egress import UserEgressDefaults
from app.models.user import User

router = APIRouter()


class RegisterRequest(BaseModel):
    """User registration request"""
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=100)


class RegisterResponse(BaseModel):
    """User registration response"""
    id: int
    username: str
    message: str


@router.post("/login", response_model=schemas.Token)
async def login_access_token(
    session: AsyncSession = Depends(deps.get_session),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    # 1. Fetch user by username
    result = await session.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()

    # 2. Authenticate — always run bcrypt to prevent timing-based username enumeration.
    # When user is None, verify against a dummy hash so the response time is constant.
    _DUMMY_HASH = "$2b$12$LJ3m4ys3Lg2Kl7QLd.OXxuMhT5YEVMxNqXEPmJGxqE4M1ZpOSvSm"
    password_valid = security.verify_password(
        form_data.password,
        user.password_hash if user else _DUMMY_HASH,
    )
    if not user or not password_valid:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if hasattr(user, "is_active") and not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    # 3. Generate token
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    return {
        "access_token": security.create_access_token(
            {"sub": str(user.id)}, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }


@router.get("/me", response_model=schemas.User)
async def read_users_me(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Get current user.
    """
    return current_user


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    request: RegisterRequest,
    session: AsyncSession = Depends(deps.get_session),
) -> Any:
    """
    Register a new user.

    Available in DEMO and HYBRID modes. In LOCAL mode, the "local" user
    is auto-created and registration is not needed.

    In DEMO mode with a demo_password configured, the X-Demo-Password
    header must be provided (enforced by DemoEnforcementMiddleware).
    """
    # Check if registration is allowed
    if app_config.mode == "local":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration disabled in local mode. Use the 'local' user account."
        )

    # Check if username already exists
    result = await session.execute(
        select(User).where(User.username == request.username)
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    # Create new user
    password_hash = security.get_password_hash(request.password)
    new_user = User(
        username=request.username,
        password_hash=password_hash,
        is_superuser=False
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    # Create default egress permissions for the new user
    # This ensures LLM access works immediately in HYBRID/DEMO modes
    egress_defaults = UserEgressDefaults(
        user_id=new_user.id,
        allow_spectrasherpa_sync=False,  # Opt-in for cloud sync
        allow_llm_context=True,  # Allow LLM by default
        allow_export=True,  # Allow export by default
        allow_nist_queries=True,  # Allow NIST by default
    )
    session.add(egress_defaults)
    await session.commit()

    return RegisterResponse(
        id=new_user.id,
        username=new_user.username,
        message="Registration successful. You can now log in."
    )
