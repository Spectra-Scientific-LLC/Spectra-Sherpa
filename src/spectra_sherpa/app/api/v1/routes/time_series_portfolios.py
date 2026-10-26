"""Create and read immutable named OES portfolios (v0.6.5)."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session, require_project
from spectra_sherpa.app.models.time_series_portfolio import TimeSeriesPortfolioRecord
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.time_series_portfolios import build_portfolio
from spectra_sherpa.core.time_series_portfolio import TimeSeriesPortfolio

router = APIRouter(prefix="/projects/{project_id}/time-series-portfolios")


class StepSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: int = Field(gt=0)
    file_id: int = Field(gt=0)
    process_file_id: int = Field(gt=0)
    asset_id: str = Field(min_length=1, max_length=80)
    step_id: Literal["production", "gas1", "mixed"]


class PortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    selections: list[StepSelection] = Field(min_length=1, max_length=512)


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    name: str
    selection: TimeSeriesPortfolio
    selection_sha256: str
    created_at: datetime


@router.get("", response_model=list[PortfolioOut])
async def list_portfolios(
    project_id: int, session: AsyncSession = Depends(get_session), current_user: User = Depends(get_current_user)
):
    await require_project(project_id, current_user.id, session, operation="read")
    return (
        await session.scalars(
            select(TimeSeriesPortfolioRecord)
            .where(TimeSeriesPortfolioRecord.project_id == project_id)
            .order_by(TimeSeriesPortfolioRecord.id)
        )
    ).all()


@router.post("", response_model=PortfolioOut, status_code=201)
async def save_portfolio(
    project_id: int,
    data: PortfolioCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    await require_project(project_id, current_user.id, session)
    name = data.name.strip()
    if not name:
        raise HTTPException(422, "A nonblank portfolio name is required")
    try:
        receipt = await build_portfolio(session, current_user.id, project_id, data.selections)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    record = TimeSeriesPortfolioRecord(
        project_id=project_id,
        created_by_user_id=current_user.id,
        name=name,
        name_key=name.casefold(),
        selection=receipt.model_dump(mode="json"),
        selection_sha256=receipt.sha256(),
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Portfolio names are immutable; choose a new name") from exc
    await session.refresh(record)
    return record
