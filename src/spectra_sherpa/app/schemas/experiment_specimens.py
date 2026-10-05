from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExperimentSpecimenFields(BaseModel):
    specimen_key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    specimen_type: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    cas_number: str | None = Field(default=None, max_length=50)
    active: bool = True
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("specimen_key", "name")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must contain non-whitespace characters")
        return value


class ExperimentSpecimenCreate(ExperimentSpecimenFields):
    pass


class ExperimentSpecimenUpdate(BaseModel):
    specimen_key: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    specimen_type: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    cas_number: str | None = Field(default=None, max_length=50)
    active: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("specimen_key", "name")
    @classmethod
    def _strip_required_text(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("cannot be null")
        value = value.strip()
        if not value:
            raise ValueError("must contain non-whitespace characters")
        return value

    @field_validator("active")
    @classmethod
    def _active_cannot_be_null(cls, value: bool | None) -> bool | None:
        if value is None:
            raise ValueError("cannot be null")
        return value


class ExperimentSpecimenOut(ExperimentSpecimenFields):
    model_config = ConfigDict(from_attributes=True)

    specimen_uid: UUID
    experiment_id: int
    created_at: datetime
    updated_at: datetime
