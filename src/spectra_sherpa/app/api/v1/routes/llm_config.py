from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session
from spectra_sherpa.app.models.llm_config import LLMConfig
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.llm_config import LLMConfigCreate, LLMConfigResponse, LLMConfigUpdate

router = APIRouter()


@router.get("/llm-config", response_model=LLMConfigResponse | None)
async def get_llm_config(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> LLMConfigResponse | None:
    """Get LLM configuration for the authenticated user."""
    result = await session.execute(
        select(LLMConfig).where(LLMConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        return None
    return LLMConfigResponse.model_validate(config)


@router.post("/llm-config", response_model=LLMConfigResponse, status_code=201, dependencies=[Depends(demo_guard("llm_config"))])
async def create_or_update_llm_config(
    payload: LLMConfigCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> LLMConfigResponse:
    """Create or update LLM configuration for the authenticated user."""
    result = await session.execute(
        select(LLMConfig).where(LLMConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()

    if config:
        # Update existing config
        config.provider = payload.provider
        config.base_url = payload.base_url
        config.model = payload.model
        config.verbose = payload.verbose
    else:
        # Create new config
        config = LLMConfig(
            user_id=current_user.id,
            provider=payload.provider,
            base_url=payload.base_url,
            model=payload.model,
            verbose=payload.verbose,
        )
        session.add(config)

    await session.commit()
    await session.refresh(config)
    return LLMConfigResponse.model_validate(config)


@router.patch("/llm-config", response_model=LLMConfigResponse, dependencies=[Depends(demo_guard("llm_config"))])
async def update_llm_config(
    payload: LLMConfigUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> LLMConfigResponse:
    """Partially update LLM configuration for the authenticated user."""
    result = await session.execute(
        select(LLMConfig).where(LLMConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()

    if config is None:
        raise HTTPException(status_code=404, detail="LLM configuration not found")

    # Update only provided fields
    if payload.provider is not None:
        config.provider = payload.provider
    if payload.base_url is not None:
        config.base_url = payload.base_url
    if payload.model is not None:
        config.model = payload.model
    if payload.verbose is not None:
        config.verbose = payload.verbose

    await session.commit()
    await session.refresh(config)
    return LLMConfigResponse.model_validate(config)


@router.delete("/llm-config", status_code=204, dependencies=[Depends(demo_guard("llm_config"))])
async def delete_llm_config(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete LLM configuration for the authenticated user."""
    result = await session.execute(
        select(LLMConfig).where(LLMConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()

    if config is None:
        raise HTTPException(status_code=404, detail="LLM configuration not found")

    await session.delete(config)
    await session.commit()
