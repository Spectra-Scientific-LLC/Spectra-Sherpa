"""Pydantic schemas for CustomAlgo API requests/responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CustomAlgoCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str | None = None
    code: str = Field(default="result = data  # transform data here")
    mode: str = Field(default="simple", pattern=r"^(simple|advanced)$")
    icon: str = Field(default="\U0001f9ea", max_length=10)


class CustomAlgoUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    code: str | None = None
    mode: str | None = Field(None, pattern=r"^(simple|advanced)$")
    icon: str | None = Field(None, max_length=10)


class CustomAlgoDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    user_id: int
    name: str
    slug: str
    description: str | None = None
    code: str
    mode: str
    icon: str
    node_type: str
    created_at: datetime
    updated_at: datetime
