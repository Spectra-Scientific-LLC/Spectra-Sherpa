from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CalibrationCreate(BaseModel):
    compound_name: str = Field(..., min_length=1)
    concentration_mode: str = Field(..., min_length=1)
    x_unit: str = Field(..., min_length=1)
    pathlength_m: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CalibrationSummary(BaseModel):
    id: int
    compound_name: str
    concentration_mode: str
    x_unit: str
    pathlength_m: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CalibrationDetail(CalibrationSummary):
    metadata: Dict[str, Any]


class CalibrationFileOut(BaseModel):
    id: int
    file_path: str
    concentration: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CalibrationFitRequest(BaseModel):
    model_type: str = Field(default="hybrid")
    settings: Dict[str, Any] = Field(default_factory=dict)
    version_name: Optional[str] = None


class CalibrationFitResponse(BaseModel):
    status: str
    job_id: int


class CalModelInfo(BaseModel):
    id: int
    version_name: str
    model_type: str
    model_path: str
    r_squared: Optional[float] = None
    rmse: Optional[float] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
