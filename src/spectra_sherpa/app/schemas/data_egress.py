"""
Pydantic schemas for Data Egress Permissions API
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DataEgressPermissionBase(BaseModel):
    """Base schema for data egress permission"""

    data_type: str = Field(
        ..., description="Type of data: spectra, models, metadata, workflows, experiments, audit_logs"
    )
    destination: str = Field(..., description="Destination: spectrasherpa, llm_context, export, nist")
    allowed: bool = Field(..., description="Whether this data type can be sent to this destination")


class DataEgressPermissionCreate(DataEgressPermissionBase):
    """Schema for creating a permission"""

    pass


class DataEgressPermissionUpdate(BaseModel):
    """Schema for updating a permission"""

    allowed: bool


class DataEgressPermission(DataEgressPermissionBase):
    """Schema for permission response"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class UserEgressDefaultsBase(BaseModel):
    """Base schema for user egress defaults"""

    allow_spectrasherpa_sync: bool = Field(default=False, description="Allow syncing data to SpectraSherpa cloud")
    allow_llm_context: bool = Field(default=False, description="Allow sending data as context to LLM providers")
    allow_export: bool = Field(default=False, description="Allow exporting data to files")
    allow_nist_queries: bool = Field(default=False, description="Allow NIST WebBook queries")


class UserEgressDefaultsCreate(UserEgressDefaultsBase):
    """Schema for creating defaults"""

    pass


class UserEgressDefaultsUpdate(BaseModel):
    """Schema for partial update of defaults"""

    allow_spectrasherpa_sync: Optional[bool] = None
    allow_llm_context: Optional[bool] = None
    allow_export: Optional[bool] = None
    allow_nist_queries: Optional[bool] = None


class UserEgressDefaults(UserEgressDefaultsBase):
    """Schema for defaults response"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class EgressSettingsSummary(BaseModel):
    """Summary of all egress settings for a user"""

    model_config = ConfigDict(from_attributes=True)

    defaults: Optional[UserEgressDefaults] = None
    permissions: list[DataEgressPermission] = []


class BulkPermissionUpdate(BaseModel):
    """Schema for bulk updating permissions"""

    permissions: list[DataEgressPermissionCreate]
