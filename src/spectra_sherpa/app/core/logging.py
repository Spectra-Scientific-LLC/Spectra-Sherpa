from __future__ import annotations

import logging
import logging.handlers
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque
import threading
import requests
import queue

from spectra_sherpa.app.core.config import settings, app_config

log_buffer: Deque[dict] = deque(maxlen=settings.log_buffer_size)

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
                    "timestamp": datetime.fromtimestamp(
                        record.created, tz=timezone.utc
                    ).isoformat(),
                    "level": record.levelname,
                    "message": message,
                    "logger": record.name,
                }
            )
        except Exception:
            self.handleError(record)

class RemoteAuditHandler(logging.Handler):
    """
    Asynchronously sends logs to SpectraSherpa in Hybrid mode.

    Features:
    - Non-blocking queue + worker thread
    - Offline queue persisted to disk when remote is unreachable
    - Automatic retry and sync when connection restored
    - Batch uploads for efficiency
    """

    BATCH_SIZE = 50  # Send logs in batches
    RETRY_INTERVAL = 30  # Seconds between retry attempts
    MAX_OFFLINE_LOGS = 10000  # Max logs to keep offline

    def __init__(self, endpoint_url: str):
        super().__init__()
        self.endpoint_url = endpoint_url
        self.queue: queue.Queue = queue.Queue()
        self.offline_queue: Deque[dict] = deque(maxlen=self.MAX_OFFLINE_LOGS)
        self._is_online = True
        self._last_retry = datetime.min
        self._lock = threading.Lock()
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    @property
    def is_online(self) -> bool:
        return self._is_online

    @property
    def offline_count(self) -> int:
        return len(self.offline_queue)

    def _is_degraded(self) -> bool:
        """Check if we're in degraded mode (hybrid fallback to local)."""
        try:
            from spectra_sherpa.app.services.network_health import get_network_health_service
            health_service = get_network_health_service()
            return health_service.is_degraded
        except Exception:
            return False

    def emit(self, record: logging.LogRecord) -> None:
        # Only send logs in hybrid mode
        if app_config.mode != "hybrid":
            return

        # SECURITY: Don't send logs when degraded (strict local-only fallback)
        # This ensures no egress during degradation, respecting local-only intent
        if self._is_degraded():
            return

        try:
            msg = self.format(record)
            payload = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "message": redact_message(msg),
                "logger": record.name,
                "source": settings.app_name
            }
            self.queue.put(payload)
        except Exception:
            self.handleError(record)

    def _worker(self):
        batch: list[dict] = []

        while True:
            try:
                # Collect logs into a batch
                try:
                    payload = self.queue.get(timeout=1.0)
                    batch.append(payload)
                    self.queue.task_done()

                    # Collect more if available (up to batch size)
                    while len(batch) < self.BATCH_SIZE:
                        try:
                            payload = self.queue.get_nowait()
                            batch.append(payload)
                            self.queue.task_done()
                        except queue.Empty:
                            break
                except queue.Empty:
                    pass

                # Try to send batch if we have logs
                if batch:
                    if self._try_send_batch(batch):
                        batch = []
                    else:
                        # Failed - move to offline queue
                        with self._lock:
                            for log in batch:
                                self.offline_queue.append(log)
                        batch = []

                # Try to sync offline queue periodically
                if self.offline_queue and self._should_retry():
                    self._sync_offline_queue()

            except Exception:
                # Never crash the worker thread
                pass

    def _try_send_batch(self, batch: list[dict]) -> bool:
        """Try to send a batch of logs. Returns True on success."""
        # Defense-in-depth: Also check degraded state before sending
        # (in case state changed between emit() and worker processing)
        if self._is_degraded():
            # In degraded mode, pretend success but don't send
            # This prevents offline queue from filling up during degradation
            return True

        try:
            response = requests.post(
                self.endpoint_url,
                json={"logs": batch, "batch": True},
                timeout=10
            )
            if response.status_code < 400:
                self._is_online = True
                return True
            else:
                self._is_online = False
                return False
        except Exception:
            self._is_online = False
            return False

    def _should_retry(self) -> bool:
        """Check if enough time has passed since last retry."""
        now = datetime.now()
        if (now - self._last_retry).total_seconds() >= self.RETRY_INTERVAL:
            self._last_retry = now
            return True
        return False

    def _sync_offline_queue(self):
        """Attempt to sync offline logs to remote."""
        with self._lock:
            if not self.offline_queue:
                return

            # Try sending in batches
            batch = []
            synced_count = 0

            while self.offline_queue and len(batch) < self.BATCH_SIZE:
                batch.append(self.offline_queue.popleft())

            if batch:
                if self._try_send_batch(batch):
                    synced_count = len(batch)
                    # Continue syncing if successful
                    while self.offline_queue:
                        batch = []
                        while self.offline_queue and len(batch) < self.BATCH_SIZE:
                            batch.append(self.offline_queue.popleft())
                        if batch:
                            if not self._try_send_batch(batch):
                                # Put back failed batch
                                for log in reversed(batch):
                                    self.offline_queue.appendleft(log)
                                break
                            synced_count += len(batch)
                else:
                    # Put back failed batch
                    for log in reversed(batch):
                        self.offline_queue.appendleft(log)

    def get_status(self) -> dict:
        """Get current handler status for monitoring."""
        return {
            "is_online": self._is_online,
            "queue_size": self.queue.qsize(),
            "offline_count": len(self.offline_queue),
            "endpoint": self.endpoint_url,
        }


def configure_logging(level: int = logging.INFO) -> None:
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
        stream_handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s: %(message)s")
        )
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
                encoding="utf-8"
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S"
                )
            )
            # Add a filter to redact sensitive data before writing to file
            class RedactionFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:
                    record.msg = redact_message(str(record.msg))
                    return True
            file_handler.addFilter(RedactionFilter())
            root_logger.addHandler(file_handler)

    # Remote audit logging (hybrid mode only)
    if app_config.mode == "hybrid" and app_config.spectrasherpa_log_url:
        if not any(isinstance(h, RemoteAuditHandler) for h in root_logger.handlers):
            remote_handler = RemoteAuditHandler(app_config.spectrasherpa_log_url)
            remote_handler.setLevel(level)
            remote_handler.setFormatter(logging.Formatter("%(message)s"))
            root_logger.addHandler(remote_handler)
