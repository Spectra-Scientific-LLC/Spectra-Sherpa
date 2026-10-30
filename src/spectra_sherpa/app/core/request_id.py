"""Request-ID propagation for HTTP and WebSocket connections.

A FastAPI middleware reads the ``X-Request-ID`` header (if present) or
mints a new UUID hex; the value is exposed as a ``ContextVar`` that
logging filters and route code can read.

Why a contextvar?
- Threading the ID as an explicit parameter would change
  ``WebSocketActionHandler`` (a stable contract surface) and break every
  server-extension-registered handler.
- Logging filters cannot reach explicit handler parameters anyway —
  they operate on ``LogRecord``, not call frames. A contextvar is
  the only mechanism the filter sees.

HTTP accepts a bounded, log-safe upstream request ID or mints a fresh UUID.
WebSocket handlers bind their message correlation through the same ContextVar.
The commercial server can therefore forward correlation identifiers without
requiring OSS to know server semantics.
"""

from __future__ import annotations

import logging
import re
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from spectra_sherpa.core.diagnostic_context import (
    REQUEST_ID_HEADER as REQUEST_ID_HEADER,
)
from spectra_sherpa.core.diagnostic_context import (
    RequestIDLogFilter as RequestIDLogFilter,
)
from spectra_sherpa.core.diagnostic_context import (
    diagnostic_identifier as diagnostic_identifier,
)
from spectra_sherpa.core.diagnostic_context import (
    get_request_id as get_request_id,
)
from spectra_sherpa.core.diagnostic_context import (
    install_request_id_log_factory as install_request_id_log_factory,
)
from spectra_sherpa.core.diagnostic_context import (
    mint_request_id as mint_request_id,
)
from spectra_sherpa.core.diagnostic_context import (
    reset_request_id as reset_request_id,
)
from spectra_sherpa.core.diagnostic_context import (
    set_request_id as set_request_id,
)
from spectra_sherpa.core.diagnostic_context import (
    use_request_id as use_request_id,
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """ASGI middleware binding a request ID to the current context.

    Reads ``X-Request-ID`` from the incoming request when present;
    mints a fresh UUID hex otherwise. Attaches the ID to the response
    on the same header on the way out, so HTTP clients can correlate
    server logs with their request.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", incoming) else mint_request_id()
        token = set_request_id(request_id)
        started = perf_counter()
        status = 500
        try:
            response: Response = await call_next(request)
            status = response.status_code
        finally:
            # Route templates exclude user paths, queries, tokens and bodies.
            route = getattr(request.scope.get("route"), "path", "unmatched")
            duration_ms = (perf_counter() - started) * 1000
            # Routine reads, signed-out configuration probes and missing URLs
            # must not crowd warnings. Keep client refusals at INFO, except
            # fast read-only 401/404 probes at DEBUG. Server faults stay visible.
            fast_read = request.method in {"GET", "HEAD"} and duration_ms < 1000
            if status >= 500:
                level = logging.WARNING
            elif fast_read and (status < 400 or status in {401, 404}):
                level = logging.DEBUG
            else:
                level = logging.INFO
            logging.getLogger(__name__).log(
                level,
                "HTTP_REQUEST method=%s route=%s status=%s response_headers_ms=%.1f",
                request.method,
                route,
                status,
                duration_ms,
            )
            reset_request_id(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        from spectra_sherpa.app.core.config import settings

        if settings.gui_trace:
            response.headers["X-Sherpa-Gui-Trace"] = "1"
        return response
