from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class JobInfo(BaseModel):
    id: int
    job_type: str
    status: str
    progress: int
    progress_message: Optional[str] = None
    result_path: Optional[str] = None
    error_message: Optional[str] = None
    compute_location: str
    compute_node: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
