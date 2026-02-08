from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class NistSearchResult(BaseModel):
    name: str
    cas_number: Optional[str] = None
    nist_id: str


class NistDownloadRequest(BaseModel):
    cas_number: str = Field(..., min_length=1)
    compound_name: Optional[str] = None
    resolution: Optional[str] = None
    index: Optional[int] = Field(default=None, ge=0)


class NistDownloadResponse(BaseModel):
    status: str
    job_id: int


class NistLibraryEntry(BaseModel):
    id: int
    cas_number: str
    compound_name: str
    resolution: str
    file_path: str
    downloaded_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NistSpectrumData(BaseModel):
    """Parsed spectrum data for plotting"""
    wavenumbers: list[float] = Field(description="Wavenumber values (cm^-1)")
    intensities: list[float] = Field(description="Intensity/absorption values")
    compound_name: str
    cas_number: str
    resolution: str
    num_points: int = Field(description="Number of data points")
