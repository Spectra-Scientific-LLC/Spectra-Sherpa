"""Diagnostics redact rendered values and persist safely across processes."""

import io
import logging
import os
import subprocess
import sys
from dataclasses import replace

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

    caplog.set_level(logging.INFO, logger="spectra_sherpa.app.core.request_id")
    response = TestClient(app).get("/items/PRIVATE_ITEM?token=SECRET_TOKEN", headers={"X-Request-ID": "trace-7"})
    assert response.headers["X-Request-ID"] == "trace-7"
    entries = [entry for entry in caplog.records if entry.name.endswith("request_id")]
    assert len(entries) == 1
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
