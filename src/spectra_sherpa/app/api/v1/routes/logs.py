from __future__ import annotations

import logging
import time
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Request

from spectra_sherpa.app.api.deps import get_current_user
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.core.logging import log_buffer
from spectra_sherpa.app.core.mode_policy import is_loopback
from spectra_sherpa.app.core.security import get_client_host
from spectra_sherpa.app.schemas.gui_trace import GuiTraceBatch
from spectra_sherpa.app.schemas.logs import LogResponse

router = APIRouter()
_trace_windows: OrderedDict[int, tuple[float, int]] = OrderedDict()


@router.post("/logs/workspace-events", status_code=204, include_in_schema=False)
async def workspace_events(batch: GuiTraceBatch, user=Depends(get_current_user)) -> None:
    if not settings.gui_trace:
        raise HTTPException(status_code=404, detail="Not found")
    now = time.monotonic()
    start, count = _trace_windows.get(user.id, (now, 0))
    if now - start >= 60:
        start, count = now, 0
    if count + len(batch.events) > 600:
        raise HTTPException(status_code=429, detail="Diagnostic event limit reached")
    _trace_windows[user.id] = (start, count + len(batch.events))
    _trace_windows.move_to_end(user.id)
    while len(_trace_windows) > 1024:
        _trace_windows.popitem(last=False)
    # Client observations are explicitly labelled, not scientific/audit evidence.
    logging.getLogger("spectra_sherpa.gui_trace").info(
        "GUI_TRACE actor=%s client_observation=%s", user.id, batch.model_dump_json()
    )


@router.get("/logs", response_model=LogResponse)
async def get_logs(request: Request, limit: int = 100) -> LogResponse:
    if not is_loopback(get_client_host(request)):
        raise HTTPException(status_code=403, detail="Logs only accessible from localhost")

    safe_limit = max(1, min(limit, settings.log_buffer_size))
    entries = list(log_buffer)[-safe_limit:]
    return LogResponse(logs=entries)
