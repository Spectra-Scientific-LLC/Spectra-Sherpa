"""Diagnostics redact rendered values and persist safely across processes."""

import io
import logging
import os
import subprocess
import sys
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectra_sherpa.app.core import logging as logging_module
from spectra_sherpa.app.core.logging import LockedRotatingFileHandler, RedactingFormatter, configure_logging
from spectra_sherpa.app.core.request_id import RequestIDMiddleware, get_request_id, use_request_id


def test_redaction_covers_interpolation_exception_and_existing_console(monkeypatch):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root = logging.getLogger()
    previous = root.handlers[:]
    previous_level = root.level
    root.handlers = [handler]
    monkeypatch.setattr(logging_module, "settings", replace(logging_module.settings, log_file_path=None))
    try:
        configure_logging()
        configure_logging()
        try:
            raise OSError("token URL https://local/verify?token=SECRET_QUERY password=SECRET_EXCEPTION")
        except OSError:
            logging.getLogger("test.interpolation").exception("Provider %s", "Bearer SECRET_ARGUMENT")
        text = stream.getvalue()
        assert all(secret not in text for secret in ["SECRET_QUERY", "SECRET_EXCEPTION", "SECRET_ARGUMENT"])
        assert "OSError" in text
        assert "REDACTED" in text
        assert isinstance(handler.formatter, RedactingFormatter)
        assert not isinstance(handler.formatter.wrapped, RedactingFormatter)
    finally:
        root.handlers = previous
        root.setLevel(previous_level)


def test_timing_logs_route_template_and_id_not_query_or_user_path(caplog):
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/items/{item}")
    async def endpoint(item: str):
        return {"ok": True}

    caplog.set_level(logging.DEBUG, logger="spectra_sherpa.app.core.request_id")
    response = TestClient(app).get("/items/PRIVATE_ITEM?token=SECRET_TOKEN", headers={"X-Request-ID": "trace-7"})
    assert response.headers["X-Request-ID"] == "trace-7"
    entries = [entry for entry in caplog.records if entry.name.endswith("request_id")]
    assert len(entries) == 1
    assert entries[0].levelno == logging.DEBUG
    assert "route=/items/{item}" in entries[0].getMessage()
    assert "response_headers_ms=" in entries[0].getMessage()
    assert "PRIVATE_ITEM" not in entries[0].getMessage()
    assert "SECRET_TOKEN" not in entries[0].getMessage()
    assert get_request_id() is None


def test_shared_rotating_log_is_process_safe_and_survives_recreation(tmp_path):
    path = tmp_path / "api.log"
    script = """
import logging,sys
from spectra_sherpa.app.core.logging import LockedRotatingFileHandler, RedactingFormatter
handler=LockedRotatingFileHandler(sys.argv[1],maxBytes=100000,backupCount=2)
handler.setFormatter(RedactingFormatter())
logger=logging.getLogger('child');logger.setLevel(logging.INFO);logger.addHandler(handler)
for i in range(60): logger.info('worker=%s row=%s Bearer SECRET',sys.argv[2],i)
handler.close()
"""
    children = [
        subprocess.Popen([sys.executable, "-c", script, str(path), str(index)], env=os.environ.copy())
        for index in range(2)
    ]
    for child in children:
        assert child.wait(timeout=30) == 0
    before = path.read_text()
    assert len(before.splitlines()) == 120
    assert "SECRET" not in before
    # A replacement process opens the same mounted path and preserves history.
    subprocess.run([sys.executable, "-c", script, str(path), "replacement"], check=True, timeout=30)
    assert path.read_text().startswith(before)
    handler = LockedRotatingFileHandler(path, maxBytes=1024, backupCount=2)
    handler.setFormatter(RedactingFormatter())
    for i in range(100):
        handler.emit(logging.LogRecord("rotate", logging.INFO, __file__, 1, "row %s " + "x" * 100, (i,), None))
    handler.close()
    assert {file.name for file in tmp_path.iterdir()} <= {"api.log", "api.log.lock", "api.log.1", "api.log.2"}
    assert all(file.stat().st_size < 1200 for file in tmp_path.glob("api.log*"))


def test_worker_context_is_correlated_and_cleared(monkeypatch, caplog):
    from spectra_sherpa.app.services.dag.executor_pool import WorkerExecutionContext, _with_worker_logging
    from spectra_sherpa.core.execution_runtime import ExecutionRuntime

    monkeypatch.setattr("spectra_sherpa.app.core.logging.configure_logging", lambda: None)
    caplog.set_level(logging.INFO)
    context = WorkerExecutionContext("execution-1", ExecutionRuntime(), request_id="origin-1")

    @_with_worker_logging
    def task(node_type, node_id, parameters, args, kwargs, worker_context):
        assert get_request_id() == "origin-1"
        return 17

    with use_request_id("outer"):
        assert task("test", "node-1", {}, (), {}, context) == 17
        assert get_request_id() == "outer"
    assert "NODE_WORKER_START" in caplog.text and "NODE_WORKER_DONE" in caplog.text
    assert "execution-1" in caplog.text


def test_malformed_logging_cannot_echo_raw_arguments(capsys):
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter())
    handler.handle(logging.LogRecord("bad", logging.WARNING, __file__, 1, "value=%d", ("Bearer SECRET_FORMAT",), None))
    stderr = capsys.readouterr().err
    assert "SECRET_FORMAT" not in stderr
    assert "formatting failed" in stderr


def test_bearer_redaction_includes_punctuation_and_padding():
    from spectra_sherpa.app.core.logging import redact_message

    assert redact_message("Bearer PREFIX/+SECRET_SUFFIX==") == "Bearer [REDACTED]"


def test_log_path_failure_does_not_prevent_execution(tmp_path, monkeypatch, caplog):
    parent = tmp_path / "ordinary-file"
    parent.write_text("not a directory")
    monkeypatch.setattr(
        logging_module, "settings", replace(logging_module.settings, log_file_path=str(parent / "app.log"))
    )
    root = logging.getLogger()
    previous, level = root.handlers[:], root.level
    try:
        configure_logging()
        assert "using console diagnostics" in caplog.text
        assert str(parent) not in caplog.text
    finally:
        root.handlers = previous
        root.setLevel(level)


def test_file_handler_opens_only_under_emit_lock(tmp_path):
    handler = LockedRotatingFileHandler(tmp_path / "app.log", maxBytes=100, backupCount=1)
    assert handler.stream is None
    handler.emit(logging.LogRecord("test", logging.INFO, __file__, 1, "ok", (), None))
    assert handler.stream is None
    assert (tmp_path / "app.log").read_text() == "ok\n"
    handler.close()


def test_console_write_failure_cannot_echo_raw_arguments(monkeypatch, capsys):
    class BrokenStream:
        def write(self, _text):
            raise OSError("PRIVATE_SINK_PATH")

        def flush(self):
            pass

    handler = logging.StreamHandler(BrokenStream())
    root = logging.getLogger()
    previous, level = root.handlers[:], root.level
    monkeypatch.setattr(logging_module, "settings", replace(logging_module.settings, log_file_path=None))
    try:
        root.handlers = [handler]
        configure_logging()
        root.warning("Provider %s", "Bearer SECRET_WRITE_SENTINEL")
        captured = capsys.readouterr().err
        assert "SECRET_WRITE_SENTINEL" not in captured
        assert "PRIVATE_SINK_PATH" not in captured
        assert "Diagnostic sink unavailable" in captured
    finally:
        root.handlers = previous
        root.setLevel(level)


def test_configured_log_level_applies_to_worker_startup(monkeypatch):
    root = logging.getLogger()
    previous, level = root.handlers[:], root.level
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setattr(logging_module, "settings", replace(logging_module.settings, log_file_path=None))
    try:
        configure_logging()
        assert root.level == logging.WARNING
    finally:
        root.handlers = previous
        root.setLevel(level)


def test_failed_poll_is_visible_at_normal_log_level(caplog):
    from fastapi.responses import JSONResponse

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/health")
    async def endpoint():
        return JSONResponse({"status": "unavailable"}, status_code=503)

    caplog.set_level(logging.INFO, logger="spectra_sherpa.app.core.request_id")
    assert TestClient(app).get("/health").status_code == 503
    records = [r for r in caplog.records if r.name.endswith("request_id")]
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert "status=503" in records[0].getMessage()


@pytest.mark.parametrize(
    "method,status,expected",
    [
        ("GET", 401, logging.DEBUG),
        ("GET", 404, logging.DEBUG),
        ("HEAD", 401, logging.DEBUG),
        ("POST", 401, logging.INFO),
        ("GET", 403, logging.INFO),
        ("POST", 422, logging.INFO),
        ("GET", 429, logging.INFO),
        ("GET", 500, logging.WARNING),
        ("POST", 503, logging.WARNING),
    ],
)
def test_client_refusals_are_not_server_warnings(caplog, method, status, expected):
    from fastapi.responses import Response

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.api_route("/api/config", methods=["GET", "POST", "HEAD"])
    async def endpoint():
        return Response(status_code=status)

    caplog.set_level(logging.DEBUG, logger="spectra_sherpa.app.core.request_id")
    response = TestClient(app).request(method, "/api/config?token=PRIVATE")
    assert response.status_code == status
    records = [r for r in caplog.records if r.name.endswith("request_id")]
    assert len(records) == 1 and records[0].levelno == expected
    assert "PRIVATE" not in records[0].getMessage()


def test_fast_successful_poll_does_not_fill_info_logs(caplog):
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/health")
    async def endpoint():
        return {"ok": True}

    caplog.set_level(logging.INFO, logger="spectra_sherpa.app.core.request_id")
    assert TestClient(app).get("/health").status_code == 200
    assert not [r for r in caplog.records if r.name.endswith("request_id")]


def test_slow_successful_read_keeps_timing_at_info(monkeypatch, caplog):
    from spectra_sherpa.app.core import request_id

    ticks = iter([10.0, 11.2])
    monkeypatch.setattr(request_id, "perf_counter", lambda: next(ticks))
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/items")
    async def endpoint():
        return {"ok": True}

    caplog.set_level(logging.INFO, logger="spectra_sherpa.app.core.request_id")
    assert TestClient(app).get("/items").status_code == 200
    records = [r for r in caplog.records if r.name.endswith("request_id")]
    assert len(records) == 1 and records[0].levelno == logging.INFO
    assert "response_headers_ms=1200.0" in records[0].getMessage()


@pytest.mark.parametrize("raw", ["client\nFORGED_EVENT", "client\r\tentry", "x" * 4096, "sample-\u202eabcd"])
def test_non_http_correlation_is_bounded_in_lines_and_buffer_metadata(raw):
    from spectra_sherpa.app.core.logging import BufferHandler, log_buffer
    from spectra_sherpa.app.core.request_id import diagnostic_identifier, install_request_id_log_factory

    install_request_id_log_factory()
    handler = BufferHandler()
    handler.setFormatter(RedactingFormatter(logging.Formatter("[req=%(request_id)s] %(message)s")))
    with use_request_id(raw):
        record = logging.getLogger("review.correlation").makeRecord(
            "review.correlation", logging.INFO, __file__, 1, "legitimate event", (), None
        )
        handler.handle(record)
        assert get_request_id() == raw  # Protocol identity is not rewritten.
    entry = log_buffer[-1]
    assert entry["request_id"] == diagnostic_identifier(raw)
    assert len(entry["request_id"]) == 71
    assert raw not in entry["message"]
    assert len(entry["message"].splitlines()) == 1
    assert diagnostic_identifier(raw) != diagnostic_identifier(raw + "other")


def test_worker_logs_bound_node_identity_without_changing_execution(monkeypatch, caplog):
    from spectra_sherpa.app.core.request_id import diagnostic_identifier
    from spectra_sherpa.app.services.dag.executor_pool import _with_worker_logging

    monkeypatch.setattr("spectra_sherpa.app.core.logging.configure_logging", lambda: None)
    caplog.set_level(logging.INFO)
    raw = "node\nFORGED_EVENT"

    @_with_worker_logging
    def task(node_type, node_id, parameters, args, kwargs, worker_context):
        assert node_id == raw
        return 17

    assert task("test", raw, {}, (), {}, None) == 17
    records = [record for record in caplog.records if "NODE_WORKER_" in record.getMessage()]
    assert len(records) == 2
    assert all(raw not in record.getMessage() for record in records)
    assert all(diagnostic_identifier(raw) in record.getMessage() for record in records)


@pytest.fixture
def isolated_log_handlers(monkeypatch):
    root = logging.getLogger()
    known = [
        logging.getLogger(name) for name in ("uvicorn.access", "uvicorn.error", "gunicorn.access", "gunicorn.error")
    ]
    saved = [(logger, logger.handlers[:], logger.level) for logger in [root, *known]]
    for logger in [root, *known]:
        logger.handlers = []
    monkeypatch.setattr(logging_module, "settings", replace(logging_module.settings, log_file_path=None))
    yield root
    for logger, handlers, level in saved:
        for handler in logger.handlers:
            if handler not in handlers:
                handler.close()
        logger.handlers = handlers
        logger.setLevel(level)


def test_existing_console_receives_configured_level_and_correlation(isolated_log_handlers):
    root = isolated_log_handlers
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    configure_logging(logging.INFO)
    with use_request_id("worker-trace"):
        root.info("worker started")
    assert "worker started" in stream.getvalue()
    assert "[req=worker-trace]" in stream.getvalue()
    configure_logging(logging.WARNING)
    root.info("not requested")
    assert "not requested" not in stream.getvalue()


def test_server_access_handler_obeys_configured_threshold(isolated_log_handlers):
    stream = io.StringIO()
    logger = logging.getLogger("uvicorn.access")
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    configure_logging(logging.WARNING)
    logger.info("routine access")
    assert not stream.getvalue()
    logger.warning("server fault")
    assert "server fault" in stream.getvalue()


@pytest.mark.parametrize("relative_segments", [False, True])
def test_unrelated_rotating_sink_does_not_suppress_requested_service_log(
    tmp_path, monkeypatch, isolated_log_handlers, relative_segments
):
    root = isolated_log_handlers
    foreign = logging.handlers.RotatingFileHandler(tmp_path / "unrelated.log")
    root.addHandler(foreign)
    path = tmp_path / "api.log"
    configured = tmp_path / "logs" / ".." / "api.log" if relative_segments else path
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr(logging_module, "settings", replace(logging_module.settings, log_file_path=str(configured)))
    configure_logging()
    configure_logging()
    owned = [h for h in root.handlers if isinstance(h, LockedRotatingFileHandler)]
    assert len(owned) == 1 and owned[0].baseFilename == str(path)
    assert any(type(h) is logging.StreamHandler for h in root.handlers)
    with use_request_id("trace-1"):
        root.info("persistent event")
    assert "persistent event" in path.read_text()
    assert "[req=trace-1]" in path.read_text()


def test_fallback_filter_normalizes_preexisting_correlation():
    from spectra_sherpa.app.core.request_id import RequestIDLogFilter, diagnostic_identifier

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "event", (), None)
    record.request_id = "legacy\nFORGED"
    RequestIDLogFilter().filter(record)
    assert record.request_id == diagnostic_identifier("legacy\nFORGED")
