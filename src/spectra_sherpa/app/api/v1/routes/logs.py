from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.core.logging import log_buffer
from spectra_sherpa.app.core.mode_policy import is_loopback
from spectra_sherpa.app.core.security import get_client_host
from spectra_sherpa.app.schemas.logs import LogResponse

router = APIRouter()


@router.get("/logs", response_model=LogResponse)
async def get_logs(request: Request, limit: int = 100) -> LogResponse:
    if not is_loopback(get_client_host(request)):
        raise HTTPException(status_code=403, detail="Logs only accessible from localhost")

    safe_limit = max(1, min(limit, settings.log_buffer_size))
    entries = list(log_buffer)[-safe_limit:]
    return LogResponse(logs=entries)
