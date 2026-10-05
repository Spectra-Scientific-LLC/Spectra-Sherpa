from __future__ import annotations

import logging
import logging.handlers
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque

from spectra_sherpa.app.core.config import settings

log_buffer: Deque[dict[str, Any]] = deque(maxlen=settings.log_buffer_size)

REDACTION_RULES = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]+"), "Bearer [REDACTED]"),
    (re.compile(r"password[\"\s:=]+[^\"\s]+", re.IGNORECASE), "password=[REDACTED]"),
]


def redact_message(message: str) -> str:
    for pattern, replacement in REDACTION_RULES:
        message = pattern.sub(replacement, message)
    return message


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


def configure_logging(level: int = logging.INFO) -> None:
    from spectra_sherpa.app.core.request_id import install_request_id_log_factory

    # Install once before any handler is added: this sets
    # ``record.request_id`` at LogRecord creation time, so handler
    # formatters that reference ``%(request_id)s`` always find the
    # attribute even for records that propagate up from child loggers.
    install_request_id_log_factory()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not any(isinstance(h, BufferHandler) for h in root_logger.handlers):
        buffer_handler = BufferHandler()
        buffer_handler.setLevel(level)
        buffer_handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger.addHandler(buffer_handler)

    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(logging.Formatter("%(levelname)s [req=%(request_id)s] %(name)s: %(message)s"))
        root_logger.addHandler(stream_handler)

    # Persistent file logging (local audit log)
    if settings.log_file_path:
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root_logger.handlers):
            log_path = Path(settings.log_file_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=settings.log_file_max_bytes,
                backupCount=settings.log_file_backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s [req=%(request_id)s] %(name)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )

            # Add a filter to redact sensitive data before writing to file
            class RedactionFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:
                    record.msg = redact_message(str(record.msg))
                    return True

            file_handler.addFilter(RedactionFilter())
            root_logger.addHandler(file_handler)
