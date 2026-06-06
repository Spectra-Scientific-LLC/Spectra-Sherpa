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

The header / payload propagation pattern is **separate-mint with
upstream override**: when an inbound ``X-Request-ID`` (HTTP) or
``request_id`` (WebSocket message) is present, the value is used
verbatim; otherwise a fresh UUID hex is minted. This lets the
commercial server forward IDs from upstream traffic when it wants
single-request traceability, without forcing OSS to know anything
about server semantics.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
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
        request_id = incoming or mint_request_id()
        token = _request_id_var.set(request_id)
        try:
            response: Response = await call_next(request)
        finally:
            _request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
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
