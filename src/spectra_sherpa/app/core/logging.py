from __future__ import annotations

import errno
import logging
import logging.handlers
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import MethodType
from typing import Any, Deque

from spectra_sherpa.app.core.config import settings

log_buffer: Deque[dict[str, Any]] = deque(maxlen=settings.log_buffer_size)

REDACTION_RULES = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"Bearer\s+[^\s\"',;]+", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"([?&](?:token|code|api_key|key|password|secret)=)[^&\s\"']+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"password[\"\s:=]+[^\"\s]+", re.IGNORECASE), "password=[REDACTED]"),
]


def redact_message(message: str) -> str:
    for pattern, replacement in REDACTION_RULES:
        message = pattern.sub(replacement, message)
    return message


def _safe_sink_error(_handler, _record):
    # logging.Handler.handleError prints raw msg/args when a sink fails.
    # Never expose those through stderr, even in development/debug mode.
    try:
        sys.stderr.write("Diagnostic sink unavailable.\n")
    except Exception:
        pass


class RedactingFormatter(logging.Formatter):
    """Redact the final formatted message, including args and exception text."""

    def __init__(self, formatter: logging.Formatter | None = None):
        super().__init__()
        self.wrapped = formatter or logging.Formatter("%(message)s")

    def format(self, record):
        try:
            rendered = self.wrapped.format(record)
        except Exception:
            # Standard handleError prints raw msg/args. Never enter that path
            # for malformed third-party logging calls.
            return "[Diagnostic omitted: formatting failed]"
        # Never clip a secret before redaction. Oversized diagnostics are omitted.
        if len(rendered) > 32768:
            return "[Diagnostic omitted: exceeds processing limit]"
        return redact_message(rendered)


class LockedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Bounded shared service log; rotation serialized across worker processes.

    POSIX streams stay open until a peer rotates the file; identity is checked
    under the shared lock before every write. Windows closes idle streams so
    peers can rename archives. Lock timeouts fall back to redacted stderr.
    The lock file itself contains no diagnostic data.
    """

    lock_wait_seconds = 0.25

    def _acquire_lock(self, fd: int) -> None:
        deadline = time.monotonic() + self.lock_wait_seconds
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Diagnostic file lock unavailable") from None
                time.sleep(min(0.01, remaining))

    def __init__(self, *args, **kwargs):
        # Do not hold an idle Windows file handle across a peer's rotation.
        kwargs["delay"] = True
        super().__init__(*args, **kwargs)

    def _refresh_stream(self):
        if self.stream is None:
            return
        try:
            current = os.stat(self.baseFilename)
            opened = os.fstat(self.stream.fileno())
            unchanged = (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino)
        except (FileNotFoundError, OSError):
            unchanged = False
        if not unchanged:
            self.stream.close()
            self.stream = None

    def emit(self, record):
        fd = None
        locked = False
        completed = False
        self._write_failed = False
        try:
            fd = os.open(self.baseFilename + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
            self._acquire_lock(fd)
            locked = True
            self._refresh_stream()
            super().emit(record)
            completed = True
        except Exception:
            # A diagnostic sink must not fail scientific work or echo secrets
            # through logging's default raw-record error report.
            self.handleError(record)
        finally:
            try:
                if self.stream and (sys.platform == "win32" or not completed or self._write_failed):
                    try:
                        self.stream.close()
                    finally:
                        self.stream = None
            except Exception:
                self._report_cleanup_error()
            finally:
                if fd is not None:
                    try:
                        if locked:
                            if sys.platform == "win32":
                                import msvcrt

                                os.lseek(fd, 0, os.SEEK_SET)
                                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                            else:
                                import fcntl

                                fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        self._report_cleanup_error()
                    finally:
                        try:
                            os.close(fd)
                        except OSError:
                            self._report_cleanup_error()

    @staticmethod
    def _report_cleanup_error():
        # The write outcome was already reported. Never replay the record for
        # a descriptor/lock cleanup failure after a successful write.
        try:
            error_type = type(sys.exc_info()[1]).__name__
            sys.stderr.write(f"Persistent diagnostic log cleanup failed ({error_type}).\n")
        except Exception:
            pass

    def handleError(self, record):
        self._write_failed = True
        try:
            # Preserve the diagnostic through the console sink on contention
            # without invoking logging's raw-argument/traceback fallback.
            rendered = RedactingFormatter(self.formatter).format(record)
            sys.stderr.write("Persistent diagnostic log write failed. " + rendered + "\n")
        except Exception:
            pass


class AccessPathFilter(logging.Filter):
    """Keep HTTP access diagnostics without recording query-string credentials.

    Uvicorn's access formatter consumes this five-element tuple itself. Keep
    its shape (and status/method/path) rather than flattening the log message.
    This also covers Gunicorn's Uvicorn worker, which uses uvicorn.access.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            address, method, target, version, status = record.args
            if isinstance(target, str):
                record.args = (address, method, target.partition("?")[0], version, status)
        return True


def configure_access_logging() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AccessPathFilter) for item in access_logger.filters):
        access_logger.addFilter(AccessPathFilter())


class BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = redact_message(self.format(record))
            log_buffer.append(
                {
                    "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                    "level": record.levelname,
                    "message": message,
                    "logger": record.name,
                    "request_id": getattr(record, "request_id", "-"),
                }
            )
        except Exception:
            self.handleError(record)


def _is_console_handler(handler: logging.Handler) -> bool:
    if isinstance(handler, logging.FileHandler):
        return False
    if type(handler) is logging.StreamHandler:
        return True
    # Custom consoles may be StreamHandler subclasses or expose a console
    # object (e.g. Rich). Capture buffers and files do not own stdout/stderr.
    stream = getattr(handler, "stream", None)
    console = getattr(handler, "console", None)
    console_stream = getattr(console, "file", None)
    terminals = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)
    return any(
        candidate is terminal
        for candidate in (stream, console_stream)
        for terminal in terminals
        if terminal is not None
    )


def _protect_custom_console(handler: logging.Handler) -> None:
    # Some renderers (Rich tracebacks) bypass Formatter for raw msg/exc_info.
    # Give only that handler a sanitized copy; never mutate a shared/access record.
    if getattr(handler, "_sherpa_safe_console", False):
        return
    original_handle = handler.handle

    def safe_handle(_handler, record):
        safe = logging.makeLogRecord(record.__dict__.copy())
        safe.msg = RedactingFormatter(logging.Formatter("%(message)s")).format(safe)
        safe.args = ()
        safe.exc_info = None
        safe.exc_text = None
        safe.stack_info = None
        return original_handle(safe)

    setattr(handler, "handle", MethodType(safe_handle, handler))
    setattr(handler, "_sherpa_safe_console", True)


def configure_logging(level: int | None = None) -> None:
    from spectra_sherpa.app.core.request_id import install_request_id_log_factory

    if level is None:
        configured = logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO").strip().upper())
        level = configured if isinstance(configured, int) else logging.INFO

    # Install once before any handler is added: this sets
    # ``record.request_id`` at LogRecord creation time, so handler
    # formatters that reference ``%(request_id)s`` always find the
    # attribute even for records that propagate up from child loggers.
    install_request_id_log_factory()
    configure_access_logging()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    buffer_handlers = [h for h in root_logger.handlers if isinstance(h, BufferHandler)]
    if not buffer_handlers:
        buffer_handler = BufferHandler()
        root_logger.addHandler(buffer_handler)
        buffer_handlers = [buffer_handler]
    handler: logging.Handler
    for handler in buffer_handlers:
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter("%(message)s"))

    # An unrelated FileHandler is also a StreamHandler; it must not suppress
    # the application console. Leave third-party capture handlers untouched.
    console_handlers = [h for h in root_logger.handlers if _is_console_handler(h)]
    if not console_handlers:
        console_handler = logging.StreamHandler()
        root_logger.addHandler(console_handler)
        console_handlers = [console_handler]
    for handler in console_handlers:
        handler.setLevel(level)
        if type(handler) is not logging.StreamHandler:
            _protect_custom_console(handler)
        if type(handler) is logging.StreamHandler or handler.formatter is None:
            handler.setFormatter(logging.Formatter("%(levelname)s [req=%(request_id)s] %(name)s: %(message)s"))

    if settings.log_file_path:
        try:
            log_path = Path(os.path.abspath(settings.log_file_path))
            owned_files = [
                h
                for h in root_logger.handlers
                if isinstance(h, LockedRotatingFileHandler) and h.baseFilename == str(log_path)
            ]
            if not owned_files:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = LockedRotatingFileHandler(
                    log_path,
                    maxBytes=settings.log_file_max_bytes,
                    backupCount=settings.log_file_backup_count,
                    encoding="utf-8",
                )
                root_logger.addHandler(file_handler)
                owned_files = [file_handler]
            for handler in owned_files:
                handler.setLevel(level)
                handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s %(levelname)s [req=%(request_id)s] %(name)s: %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S",
                    )
                )
        except (OSError, ValueError):
            logging.getLogger(__name__).warning("Persistent diagnostic log unavailable; using console diagnostics.")

    # Cover handlers installed by Gunicorn/Uvicorn as well as application
    # console/file handlers. Idempotent; do not flatten access logger args.
    for logger in (
        root_logger,
        logging.getLogger("uvicorn.access"),
        logging.getLogger("uvicorn.error"),
        logging.getLogger("gunicorn.access"),
        logging.getLogger("gunicorn.error"),
    ):
        if logger is not root_logger:
            logger.setLevel(level)
        for handler in logger.handlers:
            if logger is not root_logger:
                handler.setLevel(level)
            if not isinstance(handler, LockedRotatingFileHandler):
                setattr(handler, "handleError", MethodType(_safe_sink_error, handler))
            if not isinstance(handler.formatter, RedactingFormatter):
                handler.setFormatter(RedactingFormatter(handler.formatter))
