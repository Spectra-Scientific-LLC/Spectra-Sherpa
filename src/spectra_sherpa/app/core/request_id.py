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
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from time import perf_counter
from typing import Iterator

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"

# Default ``None`` means "no request context" — startup, background
# workers, ad-hoc scripts. The logging filter renders that as ``-`` so
# formatters with ``%(request_id)s`` don't crash outside a request.
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the current request's ID, or ``None`` outside a request."""
    return _request_id_var.get()


def set_request_id(request_id: str | None) -> Token[str | None]:
    """Bind ``request_id`` in the current context. Returns a reset token.

    Used by the HTTP middleware and the WebSocket dispatch loop. Tests
    can also call this directly to simulate an in-request log.
    """
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Reset the request ID using a token from :func:`set_request_id`."""
    _request_id_var.reset(token)


def mint_request_id() -> str:
    """Mint a fresh request ID. Plain UUID4 hex (32 chars)."""
    return uuid.uuid4().hex


@contextmanager
def use_request_id(request_id: str | None) -> Iterator[str | None]:
    """Bind ``request_id`` for the duration of a ``with`` block.

    Used by the WebSocket dispatch loop so that the per-message
    request ID is reset cleanly across ``continue`` / ``break`` /
    exception flows without manual ``finally`` blocks at every site.
    """
    token = _request_id_var.set(request_id)
    try:
        yield request_id
    finally:
        _request_id_var.reset(token)


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
        token = _request_id_var.set(request_id)
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
            _request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        from spectra_sherpa.app.core.config import settings

        if settings.gui_trace:
            response.headers["X-Sherpa-Gui-Trace"] = "1"
        return response


class RequestIDLogFilter(logging.Filter):
    """Inject ``request_id`` onto every log record passing through.

    Use ``%(request_id)s`` in formatters. Records emitted outside a
    request (startup, background workers) get ``-``.

    This filter is suitable when attached to a *handler*. For
    application-wide coverage (every LogRecord, regardless of which
    logger created it), prefer :func:`install_request_id_log_factory`
    — filters on a logger don't run for records that propagate up
    from child loggers' own handlers.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id() or "-"
        return True


def install_request_id_log_factory() -> None:
    """Wrap the active ``LogRecord`` factory so every record gets a ``request_id``.

    Idempotent — calling this twice does not double-wrap. Safe to call
    once at application startup. Records created before installation
    are unaffected (the filter form is the fallback for those cases).
    """
    current = logging.getLogRecordFactory()
    if getattr(current, "_request_id_factory_installed", False):
        return

    def factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        record = current(*args, **kwargs)
        record.request_id = get_request_id() or "-"
        return record

    factory._request_id_factory_installed = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
