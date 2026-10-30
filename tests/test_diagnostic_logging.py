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

    monkeypatch.setattr("spectra_sherpa.core.diagnostic_logging.configure_logging", lambda: None)
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
    assert (handler.stream is None) == (sys.platform == "win32")
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

    monkeypatch.setattr("spectra_sherpa.core.diagnostic_logging.configure_logging", lambda: None)
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


@pytest.mark.parametrize("kind", ["stream-subclass", "console-object"])
def test_custom_console_is_reused_without_duplicate_or_format_loss(monkeypatch, isolated_log_handlers, kind):
    from types import SimpleNamespace

    output = io.StringIO()
    monkeypatch.setattr(sys, "stderr", output)

    class ColoredStream(logging.StreamHandler):
        pass

    class ConsoleObject(logging.Handler):
        def __init__(self):
            super().__init__()
            self.console = SimpleNamespace(file=output)

        def emit(self, record):
            self.console.file.write(self.format(record) + "\n")

    console = ColoredStream(output) if kind == "stream-subclass" else ConsoleObject()
    console.setFormatter(logging.Formatter("custom %(message)s"))
    isolated_log_handlers.addHandler(console)
    configure_logging()
    configure_logging()
    isolated_log_handlers.warning("custom-console-once Bearer PRIVATE_TOKEN")
    assert output.getvalue().count("custom-console-once") == 1
    assert output.getvalue().startswith("custom ")
    assert "PRIVATE_TOKEN" not in output.getvalue()
    assert [h for h in isolated_log_handlers.handlers if logging_module._is_console_handler(h)] == [console]


def test_capture_subclass_is_not_mistaken_for_console(isolated_log_handlers):
    class Capture(logging.StreamHandler):
        pass

    capture = Capture(io.StringIO())
    isolated_log_handlers.addHandler(capture)
    configure_logging()
    assert not logging_module._is_console_handler(capture)
    assert any(type(handler) is logging.StreamHandler for handler in isolated_log_handlers.handlers)


def test_held_cross_process_file_lock_has_deadline_and_recovers(tmp_path):
    import json

    path = tmp_path / "deadline.log"
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        code = """
import json, logging, sys, time
from spectra_sherpa.app.core.logging import LockedRotatingFileHandler
h = LockedRotatingFileHandler(sys.argv[1], maxBytes=1024, backupCount=1)
h.lock_wait_seconds = 0.05
start = time.monotonic()
h.emit(logging.LogRecord("deadline", logging.INFO, __file__ if "__file__" in globals() else "child", 1,
                         "Bearer PRIVATE_LOCK_TOKEN", (), None))
print(json.dumps({"elapsed":time.monotonic()-start, "closed": h.stream is None}))
"""
        child = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, timeout=10)
        assert child.returncode == 0, child.stderr
        result = json.loads(child.stdout)
        assert 0.04 <= result["elapsed"] < 2
        assert result["closed"]
        assert "Persistent diagnostic log write failed." in child.stderr
        assert "PRIVATE_LOCK_TOKEN" not in child.stderr
        assert "Bearer [REDACTED]" in child.stderr
        assert not path.exists()
    finally:
        if sys.platform == "win32":
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    handler = LockedRotatingFileHandler(path, maxBytes=1024, backupCount=1)
    handler.emit(logging.LogRecord("recovered", logging.INFO, __file__, 1, "after-release", (), None))
    handler.close()
    assert path.read_text().strip() == "after-release"


def test_rich_traceback_console_cannot_bypass_redaction(monkeypatch, isolated_log_handlers):
    try:
        from rich.console import Console
        from rich.logging import RichHandler
    except ImportError:
        from pip._vendor.rich.console import Console
        from pip._vendor.rich.logging import RichHandler

    output = io.StringIO()
    monkeypatch.setattr(sys, "stderr", output)
    rich = RichHandler(console=Console(file=output, force_terminal=False, width=200), rich_tracebacks=True)
    isolated_log_handlers.addHandler(rich)
    configure_logging()
    configure_logging()
    try:
        raise ValueError("Bearer EXCEPTION_PRIVATE")
    except ValueError:
        info = sys.exc_info()
        record = logging.LogRecord("rich", logging.ERROR, __file__, 1, "message %s", ("Bearer MESSAGE_PRIVATE",), info)
        isolated_log_handlers.handle(record)
    assert "EXCEPTION_PRIVATE" not in output.getvalue()
    assert "MESSAGE_PRIVATE" not in output.getvalue()
    assert "ValueError" in output.getvalue() and "[REDACTED]" in output.getvalue()
    assert record.exc_info is info and record.args == ("Bearer MESSAGE_PRIVATE",)


def test_interrupted_file_emit_closes_stream_before_unlock(tmp_path, monkeypatch):
    class InterruptedStream(io.StringIO):
        def write(self, value):
            raise KeyboardInterrupt()

    stream = InterruptedStream()
    handler = LockedRotatingFileHandler(tmp_path / "interrupted.log", maxBytes=1024, backupCount=1)
    monkeypatch.setattr(handler, "_open", lambda: stream)
    with pytest.raises(KeyboardInterrupt):
        handler.emit(logging.LogRecord("interrupt", logging.INFO, __file__, 1, "safe", (), None))
    assert stream.closed and handler.stream is None
    # A new independent descriptor can immediately obtain the released lock.
    fd = os.open(str(tmp_path / "interrupted.log") + ".lock", os.O_RDWR)
    try:
        handler._acquire_lock(fd)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
        handler.close()


def test_same_handler_can_write_after_a_lock_timeout(tmp_path, monkeypatch, capsys):
    path = tmp_path / "retry.log"
    handler = LockedRotatingFileHandler(path, maxBytes=1024, backupCount=1)
    acquire = handler._acquire_lock
    calls = 0

    def once(fd):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("injected contention timeout")
        acquire(fd)

    monkeypatch.setattr(handler, "_acquire_lock", once)
    handler.emit(logging.LogRecord("retry", logging.INFO, __file__, 1, "first", (), None))
    assert handler.stream is None and not path.exists()
    fallback = capsys.readouterr().err
    assert "Persistent diagnostic log write failed." in fallback and "first" in fallback
    handler.emit(logging.LogRecord("retry", logging.INFO, __file__, 1, "second", (), None))
    assert (handler.stream is None) == (sys.platform == "win32")
    assert path.read_text().strip() == "second"
    handler.close()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows intentionally closes idle streams for peer rotation")
def test_posix_stream_is_reused_and_follows_a_peers_rotation(tmp_path, monkeypatch):
    path = tmp_path / "shared.log"
    handler = LockedRotatingFileHandler(path, maxBytes=100, backupCount=10)
    peer = LockedRotatingFileHandler(path, maxBytes=100, backupCount=10)
    opened = []
    original = handler._open

    def counted_open():
        stream = original()
        opened.append(stream)
        return stream

    monkeypatch.setattr(handler, "_open", counted_open)
    try:
        for i in range(3):
            handler.emit(logging.LogRecord("reuse", logging.INFO, __file__, 1, f"first-{i}", (), None))
        assert len(opened) == 1 and handler.stream is opened[0]
        for i in range(8):
            peer.emit(logging.LogRecord("peer", logging.INFO, __file__, 1, f"peer-record-{i}", (), None))
        handler.emit(logging.LogRecord("reuse", logging.INFO, __file__, 1, "after-peer", (), None))
        assert len(opened) == 2 and opened[0].closed
        assert "after-peer" in path.read_text()
        lines = [
            line
            for file in tmp_path.glob("shared.log*")
            if not file.name.endswith(".lock")
            for line in file.read_text().splitlines()
        ]
        assert sorted(lines) == sorted(
            [f"first-{i}" for i in range(3)] + [f"peer-record-{i}" for i in range(8)] + ["after-peer"]
        )
    finally:
        handler.close()
        peer.close()


@pytest.mark.parametrize("failure", ["write", "lock"])
def test_configured_file_handler_preserves_redacted_fallback_and_recovers(
    tmp_path, monkeypatch, isolated_log_handlers, capsys, failure
):
    path = tmp_path / "configured.log"
    monkeypatch.setattr(logging_module, "settings", replace(logging_module.settings, log_file_path=str(path)))
    configure_logging()
    configure_logging()
    handler = next(h for h in isolated_log_handlers.handlers if isinstance(h, LockedRotatingFileHandler))

    class BrokenStream(io.StringIO):
        def write(self, _value):
            raise OSError("Bearer PRIVATE_WRITE_SECRET")

    with monkeypatch.context() as patch:
        if failure == "write":
            broken = BrokenStream()
            patch.setattr(handler, "_open", lambda: broken)
        else:

            def busy(_fd):
                raise TimeoutError("Bearer PRIVATE_LOCK_SECRET")

            patch.setattr(handler, "_acquire_lock", busy)
        isolated_log_handlers.warning("event %s", "Bearer PRIVATE_ARGUMENT")
        assert handler._write_failed
        assert handler.stream is None
        if failure == "write":
            assert broken.closed
    fallback = capsys.readouterr().err
    assert "Persistent diagnostic log write failed." in fallback
    assert "event Bearer [REDACTED]" in fallback
    assert "PRIVATE_" not in fallback
    isolated_log_handlers.warning("recovered")
    assert "recovered" in path.read_text()


@pytest.mark.parametrize("failure", ["unlock", "descriptor_close", "stream_close"])
def test_successful_write_cleanup_failure_does_not_replay_record(tmp_path, monkeypatch, capsys, failure):
    from types import SimpleNamespace

    path = tmp_path / "cleanup.log"
    handler = LockedRotatingFileHandler(path, maxBytes=1024, backupCount=1)
    real_close = os.close
    real_open = handler._open
    # Exercise the Windows stream-close path on every platform without relying
    # on a real Windows lock; lock-failure semantics are covered separately.
    monkeypatch.setattr(logging_module.sys, "platform", "win32")
    monkeypatch.setattr(handler, "_acquire_lock", lambda fd: None)

    def unlock(fd, mode, count):
        if failure == "unlock":
            raise OSError("PRIVATE_UNLOCK_PATH")

    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(locking=unlock, LK_UNLCK=0))

    def close_fd(fd):
        real_close(fd)
        if failure == "descriptor_close":
            raise OSError("PRIVATE_CLOSE_PATH")

    monkeypatch.setattr(logging_module.os, "close", close_fd)

    if failure == "stream_close":

        class CloseFailure:
            def __init__(self, stream):
                self.stream = stream

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def close(self):
                self.stream.close()
                raise OSError("PRIVATE_STREAM_PATH")

        monkeypatch.setattr(handler, "_open", lambda: CloseFailure(real_open()))
    try:
        handler.emit(logging.LogRecord("cleanup", logging.INFO, __file__, 1, "written-exactly-once", (), None))
        assert path.read_text() == "written-exactly-once\n"
        stderr = capsys.readouterr().err
        assert "cleanup failed (OSError)" in stderr
        assert "write failed" not in stderr and "written-exactly-once" not in stderr
        assert "PRIVATE_" not in stderr
    finally:
        handler.close()


def test_host_configuration_resizes_preimported_shared_buffer(monkeypatch, isolated_log_handlers):
    from spectra_sherpa.core import diagnostic_logging as core_logging

    buffer = core_logging.log_buffer
    previous = tuple(buffer)
    previous_limit = buffer.maxlen
    try:
        buffer.clear()
        buffer.extend([{"message": str(index)} for index in range(4)])
        monkeypatch.setattr(
            logging_module, "settings", replace(logging_module.settings, log_buffer_size=2, log_file_path=None)
        )
        configure_logging()
        assert logging_module.log_buffer is buffer
        assert core_logging.log_buffer is buffer
        assert buffer.maxlen == 2
        assert [row["message"] for row in buffer] == ["2", "3"]
    finally:
        buffer.__init__(previous, maxlen=previous_limit)
