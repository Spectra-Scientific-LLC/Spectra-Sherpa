"""Integration tests for the request-ID middleware + log filter.

Two propagation paths are exercised:

1. **Inbound override** — when ``X-Request-ID`` is set on the request,
   the middleware uses it verbatim and echoes it back on the response.
2. **Mint** — when no header is present, the middleware generates a
   fresh UUID4 hex and attaches it to the response.

In both cases, log records emitted from inside the request handler
must carry ``record.request_id`` that matches the response header.
"""

from __future__ import annotations

import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectra_sherpa.app.core.request_id import (
    REQUEST_ID_HEADER,
    RequestIDLogFilter,
    RequestIDMiddleware,
    get_request_id,
    install_request_id_log_factory,
    use_request_id,
)


@pytest.fixture
def captured_records() -> list[logging.LogRecord]:
    """Capture every log record emitted during the test."""
    return []


@pytest.fixture
def app(captured_records: list[logging.LogRecord]) -> FastAPI:
    """Minimal FastAPI app with the middleware and a logging route."""
    test_logger = logging.getLogger("test.request_id")
    test_logger.setLevel(logging.DEBUG)
    test_logger.addFilter(RequestIDLogFilter())

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured_records.append(record)

    test_logger.addHandler(CaptureHandler())

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/echo")
    async def echo() -> dict:
        rid = get_request_id()
        test_logger.info("handling /echo")
        return {"request_id": rid}

    return app


def _records_for(test_logger_name: str, captured_records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in captured_records if r.name == test_logger_name]


# ── Inbound override ──────────────────────────────────────────────────


def test_inbound_x_request_id_is_propagated(app: FastAPI, captured_records: list[logging.LogRecord]) -> None:
    """An inbound X-Request-ID is reused verbatim, on the response and in logs."""
    client = TestClient(app)
    response = client.get("/echo", headers={REQUEST_ID_HEADER: "upstream-correlation-123"})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "upstream-correlation-123"
    assert response.json()["request_id"] == "upstream-correlation-123"

    records = _records_for("test.request_id", captured_records)
    assert records, "expected a captured log record from /echo"
    assert all(getattr(r, "request_id", None) == "upstream-correlation-123" for r in records)


# ── Mint path ─────────────────────────────────────────────────────────


def test_request_id_minted_when_header_absent(app: FastAPI, captured_records: list[logging.LogRecord]) -> None:
    """No inbound header → middleware mints a UUID4 hex."""
    client = TestClient(app)
    response = client.get("/echo")

    assert response.status_code == 200
    minted = response.headers[REQUEST_ID_HEADER]
    # UUID4 hex is exactly 32 lowercase hex chars.
    assert re.fullmatch(r"[0-9a-f]{32}", minted), f"unexpected minted ID: {minted!r}"
    assert response.json()["request_id"] == minted

    records = _records_for("test.request_id", captured_records)
    assert records and all(getattr(r, "request_id", None) == minted for r in records)


# ── Cross-request isolation ───────────────────────────────────────────


def test_request_id_does_not_leak_between_requests(app: FastAPI, captured_records: list[logging.LogRecord]) -> None:
    """Each request gets its own ID; no contextvar leakage."""
    client = TestClient(app)

    r1 = client.get("/echo", headers={REQUEST_ID_HEADER: "req-A"})
    r2 = client.get("/echo", headers={REQUEST_ID_HEADER: "req-B"})

    assert r1.json()["request_id"] == "req-A"
    assert r2.json()["request_id"] == "req-B"
    assert get_request_id() is None, "contextvar must reset after the request finishes"


# ── Outside-request behavior ──────────────────────────────────────────


def test_get_request_id_outside_request_returns_none() -> None:
    """Modules running outside a request (startup, workers) see None."""
    assert get_request_id() is None


def test_log_filter_renders_dash_outside_request() -> None:
    """The log filter renders ``-`` when no request is active."""
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="hi",
        args=(),
        exc_info=None,
    )
    RequestIDLogFilter().filter(record)
    assert record.request_id == "-"


# ── Context manager (used by WS dispatch) ─────────────────────────────


def test_use_request_id_context_manager_binds_and_resets() -> None:
    assert get_request_id() is None
    with use_request_id("ws-msg-1") as bound:
        assert bound == "ws-msg-1"
        assert get_request_id() == "ws-msg-1"
    assert get_request_id() is None


def test_use_request_id_resets_on_exception() -> None:
    """The contextvar resets even if the body raises."""
    try:
        with use_request_id("ws-msg-2"):
            assert get_request_id() == "ws-msg-2"
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert get_request_id() is None


# ── LogRecord factory ────────────────────────────────────────────────


def test_log_record_factory_sets_request_id_on_every_record() -> None:
    """Records created after install have ``request_id`` even on child loggers.

    This is the bug the filter form alone could not fix: filters on a
    logger don't run for records that propagate up from a child
    logger's own handlers. The factory installs at record creation,
    so every handler downstream sees the attribute.
    """
    install_request_id_log_factory()

    child = logging.getLogger("test.request_id.factory.child")

    with use_request_id("factory-test"):
        record = child.makeRecord(child.name, logging.INFO, __file__, 0, "hi", (), None)
    assert record.request_id == "factory-test"

    record_outside = child.makeRecord(child.name, logging.INFO, __file__, 0, "hi", (), None)
    assert record_outside.request_id == "-"


def test_install_request_id_log_factory_is_idempotent() -> None:
    """Repeated installs do not double-wrap the factory."""
    install_request_id_log_factory()
    factory_before = logging.getLogRecordFactory()
    install_request_id_log_factory()
    factory_after = logging.getLogRecordFactory()
    assert factory_before is factory_after
