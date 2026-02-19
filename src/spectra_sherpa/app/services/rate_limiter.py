from __future__ import annotations

import json
import os
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Deque, Generator

# File locking for multi-process safety
try:
    import fcntl

    HAS_FCNTL = True
except ImportError:
    # Windows doesn't have fcntl
    HAS_FCNTL = False


class RateLimiter:
    """
    Sliding window rate limiter with file-based persistence.

    CONCURRENCY SAFETY:
    - Uses threading.Lock for thread safety within a process
    - Uses fcntl file locking for multi-process safety (Unix)
    - State is persisted to disk and re-read on each operation for cross-worker consistency

    For truly distributed deployments (multiple servers), use Redis-backed rate limiting.
    """

    def __init__(self, max_calls: int, period_sec: int, state_path: Path | None = None):
        if max_calls <= 0 or period_sec <= 0:
            raise ValueError("max_calls and period_sec must be positive")

        self.max_calls = max_calls
        self.period_sec = period_sec
        self.state_path = state_path
        self._lock = Lock()

        # Ensure state file exists
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.state_path.exists():
                self.state_path.write_text("{}")

    @contextmanager
    def _file_lock(self) -> Generator[None, None, None]:
        """Acquire exclusive file lock for multi-process safety."""
        if not self.state_path or not HAS_FCNTL:
            yield
            return

        lock_path = self.state_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def allow(self, key: str = "default") -> bool:
        now = time.time()
        with self._lock:
            with self._file_lock():
                # Always read fresh state for multi-process consistency
                events = self._load_events(key)
                self._prune(events, now)

                if len(events) >= self.max_calls:
                    return False

                events.append(now)
                self._save_events(key, events)
                return True

    def remaining(self, key: str = "default") -> int:
        now = time.time()
        with self._lock:
            with self._file_lock():
                events = self._load_events(key)
                self._prune(events, now)
                return max(0, self.max_calls - len(events))

    def reset(self, key: str = "default") -> None:
        with self._lock:
            with self._file_lock():
                self._save_events(key, deque())

    def _prune(self, events: Deque[float], now: float) -> None:
        cutoff = now - self.period_sec
        while events and events[0] < cutoff:
            events.popleft()

    def _load_events(self, key: str) -> Deque[float]:
        """Load events for a specific key from persistent storage."""
        if not self.state_path or not self.state_path.exists():
            return deque()

        try:
            payload = json.loads(self.state_path.read_text())
            timestamps = payload.get(key, [])
            if isinstance(timestamps, list):
                return deque(float(ts) for ts in timestamps if isinstance(ts, (int, float)))
        except (json.JSONDecodeError, IOError):
            pass

        return deque()

    def _save_events(self, key: str, events: Deque[float]) -> None:
        """Save events for a specific key to persistent storage."""
        if not self.state_path:
            return

        try:
            # Read existing state
            if self.state_path.exists():
                try:
                    payload = json.loads(self.state_path.read_text())
                except (json.JSONDecodeError, IOError):
                    payload = {}
            else:
                payload = {}

            # Update key
            payload[key] = list(events)

            # Atomic write via temp file
            temp_path = self.state_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(payload))
            temp_path.replace(self.state_path)
        except IOError:
            # Best effort - log would be ideal but don't fail the operation
            pass
