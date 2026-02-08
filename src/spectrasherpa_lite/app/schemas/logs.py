from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class LogEntry(BaseModel):
    timestamp: str
    level: str
    message: str
    logger: Optional[str] = None


class LogResponse(BaseModel):
    logs: List[LogEntry]
