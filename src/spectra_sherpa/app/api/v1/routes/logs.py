from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from spectra_sherpa.app.core.config import settings, app_config
from spectra_sherpa.app.core.logging import log_buffer, RemoteAuditHandler
from spectra_sherpa.app.core.security import _is_loopback, get_client_host
from spectra_sherpa.app.schemas.logs import LogResponse

router = APIRouter()


@router.get("/logs", response_model=LogResponse)
async def get_logs(request: Request, limit: int = 100) -> LogResponse:
    if not _is_loopback(get_client_host(request)):
        raise HTTPException(status_code=403, detail="Logs only accessible from localhost")

    safe_limit = max(1, min(limit, settings.log_buffer_size))
    entries = list(log_buffer)[-safe_limit:]
    return LogResponse(logs=entries)


@router.get("/logs/sync-status")
async def get_log_sync_status(request: Request):
    """
    Get status of remote log synchronization (HYBRID mode).

    Returns:
    - is_online: Whether remote endpoint is reachable
    - offline_count: Number of logs queued for sync
    - mode: Current app mode
    """
    if not _is_loopback(get_client_host(request)):
        raise HTTPException(status_code=403, detail="Status only accessible from localhost")

    # Find the remote handler
    root_logger = logging.getLogger()
    remote_handler = None
    for handler in root_logger.handlers:
        if isinstance(handler, RemoteAuditHandler):
            remote_handler = handler
            break

    if app_config.mode != "hybrid":
        return {
            "mode": app_config.mode,
            "remote_logging_enabled": False,
            "message": "Remote logging only available in hybrid mode"
        }

    if not remote_handler:
        return {
            "mode": app_config.mode,
            "remote_logging_enabled": False,
            "message": "Remote audit handler not configured (SPECTRASHERPA_LOG_URL not set)"
        }

    return {
        "mode": app_config.mode,
        "remote_logging_enabled": True,
        **remote_handler.get_status()
    }
