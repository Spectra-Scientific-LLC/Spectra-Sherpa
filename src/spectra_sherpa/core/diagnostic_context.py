"""Framework-independent request correlation shared by hosts and scientific workers."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

REQUEST_ID_HEADER = "X-Request-ID"

# Default ``None`` means "no request context" — startup, background
# workers, ad-hoc scripts. The logging filter renders that as ``-`` so
# formatters with ``%(request_id)s`` don't crash outside a request.
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def diagnostic_identifier(value: object) -> str:
    """Bound user-controlled correlation fields without changing wire identity."""
    if value is None:
        return "-"
    if not isinstance(value, str):
        return "invalid"
    if not value:
        return "-"
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        return value
    # Preserve deterministic correlation without copying arbitrary content into
    # rendered lines or structured browser-buffer fields.
    return "sha256:" + hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


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
        record.request_id = diagnostic_identifier(getattr(record, "request_id", get_request_id()))
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
        record.request_id = diagnostic_identifier(get_request_id())
        return record

    factory._request_id_factory_installed = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
