"""User-owned defaults and retained presets for multi-well experiments."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.acquisition_plan import AcquisitionPlanPreset, UserWorkbenchPreferences
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.acquisition_plans import (
    AcquisitionPlanPresetOut,
    WorkbenchPreferencesOut,
    WorkbenchPreferencesUpdate,
)

router = APIRouter(prefix="/acquisition-preferences", dependencies=[Depends(get_current_user)])


@router.get("", response_model=WorkbenchPreferencesOut)
async def get_acquisition_preferences(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkbenchPreferencesOut:
    result = await session.execute(
        select(UserWorkbenchPreferences).where(UserWorkbenchPreferences.user_id == current_user.id)
    )
    preferences = result.scalar_one_or_none()
    return WorkbenchPreferencesOut(
        default_plate_format_id=preferences.default_plate_format_id if preferences else "plate-96"
    )


@router.put("", response_model=WorkbenchPreferencesOut)
async def update_acquisition_preferences(
    payload: WorkbenchPreferencesUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkbenchPreferencesOut:
    result = await session.execute(
        select(UserWorkbenchPreferences).where(UserWorkbenchPreferences.user_id == current_user.id)
    )
    preferences = result.scalar_one_or_none()
    if preferences is None:
        preferences = UserWorkbenchPreferences(
            user_id=current_user.id,
            default_plate_format_id=payload.default_plate_format_id,
        )
        session.add(preferences)
    else:
        preferences.default_plate_format_id = payload.default_plate_format_id
    await session.commit()
    return WorkbenchPreferencesOut(default_plate_format_id=preferences.default_plate_format_id)


@router.get("/presets", response_model=list[AcquisitionPlanPresetOut])
async def list_acquisition_plan_presets(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[AcquisitionPlanPresetOut]:
    result = await session.execute(
        select(AcquisitionPlanPreset)
        .where(AcquisitionPlanPreset.user_id == current_user.id)
        .order_by(AcquisitionPlanPreset.is_default.desc(), AcquisitionPlanPreset.name)
    )
    return [AcquisitionPlanPresetOut.model_validate(row, from_attributes=True) for row in result.scalars()]
