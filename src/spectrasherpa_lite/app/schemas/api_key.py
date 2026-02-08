from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class APIKeyCreate(BaseModel):
    service_name: str = Field(..., min_length=1)
    key: str = Field(..., min_length=1)


class APIKeyInfo(BaseModel):
    service_name: str
    last_used_at: datetime | None = None
