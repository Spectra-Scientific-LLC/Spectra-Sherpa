"""DOE Configuration Profile API routes"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.doe_config import DOEConfig
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.doe_config import (
    DOEConfig as DOEConfigSchema,
)
from spectra_sherpa.app.schemas.doe_config import (
    DOEConfigCreate,
    DOEConfigList,
    DOEConfigUpdate,
)

router = APIRouter()


@router.get("", response_model=DOEConfigList)
async def list_doe_configs(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List all DOE configuration profiles for the current user"""
    user_id = current_user.id

    result = await session.execute(
        select(DOEConfig).where(DOEConfig.user_id == user_id).order_by(DOEConfig.is_default.desc(), DOEConfig.name)
    )
    configs = result.scalars().all()
    return DOEConfigList(configs=configs, total=len(configs))


@router.get("/{config_id}", response_model=DOEConfigSchema)
async def get_doe_config(
    config_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get a specific DOE configuration profile"""
    user_id = current_user.id

    result = await session.execute(select(DOEConfig).where(DOEConfig.id == config_id, DOEConfig.user_id == user_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="DOE config not found")
    return config


@router.post("", response_model=DOEConfigSchema, status_code=201)
async def create_doe_config(
    config_data: DOEConfigCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new DOE configuration profile"""
    user_id = current_user.id

    # If this is marked as default, unset any existing default
    if config_data.is_default:
        stmt = select(DOEConfig).where(DOEConfig.user_id == user_id, DOEConfig.is_default.is_(True))
        existing_defaults = (await session.execute(stmt)).scalars().all()

        for existing in existing_defaults:
            existing.is_default = False

    config = DOEConfig(
        user_id=user_id,
        name=config_data.name,
        description=config_data.description,
        is_default=config_data.is_default,
        folder_batch_rules=config_data.folder_batch_rules,
        filename_patterns=config_data.filename_patterns,
        scan_defaults=config_data.scan_defaults,
        run_sequence_template=config_data.run_sequence_template,
        match_settings=config_data.match_settings,
    )

    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


@router.put("/{config_id}", response_model=DOEConfigSchema)
async def update_doe_config(
    config_id: int,
    config_data: DOEConfigUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update a DOE configuration profile"""
    user_id = current_user.id

    result = await session.execute(select(DOEConfig).where(DOEConfig.id == config_id, DOEConfig.user_id == user_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="DOE config not found")

    # If setting this as default, unset other defaults
    if config_data.is_default is True and not config.is_default:
        existing_defaults = (
            (
                await session.execute(
                    select(DOEConfig).where(
                        DOEConfig.user_id == user_id, DOEConfig.is_default.is_(True), DOEConfig.id != config_id
                    )
                )
            )
            .scalars()
            .all()
        )

        for existing in existing_defaults:
            existing.is_default = False

    # Update only provided fields
    update_data = config_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    await session.commit()
    await session.refresh(config)
    return config


from fastapi import Response


@router.delete("/{config_id}", status_code=204, response_class=Response)
async def delete_doe_config(
    config_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a DOE configuration profile"""
    user_id = current_user.id

    result = await session.execute(select(DOEConfig).where(DOEConfig.id == config_id, DOEConfig.user_id == user_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="DOE config not found")

    await session.execute(delete(DOEConfig).where(DOEConfig.id == config_id))
    await session.commit()
    return None


@router.get("/default/current", response_model=DOEConfigSchema | None)
async def get_default_config(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get the default DOE configuration profile for the current user"""
    user_id = current_user.id

    stmt = select(DOEConfig).where(DOEConfig.user_id == user_id, DOEConfig.is_default.is_(True))
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()
    return config
