"""Bounded, resumable directory scans for continuous folder watches.

The cursor is an optimization, never processing authority. A restarted worker
rescans from the beginning using durable processed-file history. Directory
mutation may defer a new entry until the next complete scan; no directory
position is treated as proof that a file was processed.
"""

from __future__ import annotations

import fnmatch
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from spectra_sherpa.app.services.batch_predict import MAX_DIRECTORY_ENTRIES, validate_folder_path


class _DirectoryIterator(Protocol):
    def __next__(self) -> os.DirEntry[str]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class DiscoveryBatch:
    files: list[Path]
    scan_complete: bool
    entries_examined: int
    entry_error_count: int = 0
    first_entry_error: str | None = None


class WatchDiscovery:
    """One open directory iterator per active watch, with bounded work per poll."""

    def __init__(self) -> None:
        self._iterator: _DirectoryIterator | None = None
        self._identity: tuple | None = None
        self._lock = threading.Lock()

    def _close(self) -> None:
        if self._iterator is not None:
            self._iterator.close()
        self._iterator = None
        self._identity = None

    def close(self) -> None:
        with self._lock:
            self._close()

    def scan(
        self,
        folder_path: str,
        file_pattern: str,
        *,
        generation: int,
        exclude_names: set[str],
        settle_time_seconds: float,
        max_files: int,
        max_entries: int = MAX_DIRECTORY_ENTRIES,
    ) -> DiscoveryBatch:
        if max_files < 1 or max_entries < 1:
            raise ValueError("Watch discovery limits must be positive")
        with self._lock:
            try:
                folder = validate_folder_path(folder_path)
                stat = folder.stat()
                identity = (str(folder), stat.st_dev, stat.st_ino, file_pattern, generation)
                if identity != self._identity:
                    self._close()
                    self._iterator = os.scandir(folder)
                    self._identity = identity
                assert self._iterator is not None
                files: list[Path] = []
                examined = 0
                error_count = 0
                first_error = None
                now = time.time()
                while examined < max_entries and len(files) < max_files:
                    entry = next(self._iterator, None)
                    if entry is None:
                        self._close()
                        return DiscoveryBatch(
                            sorted(files, key=lambda p: p.name.lower()), True, examined, error_count, first_error
                        )
                    examined += 1
                    if entry.name.startswith((".", "__")):
                        continue
                    if entry.path in exclude_names or entry.name in exclude_names:
                        continue
                    if not fnmatch.fnmatch(entry.name.lower(), file_pattern.lower()):
                        continue
                    try:
                        if not entry.is_file() or max(0.0, now - entry.stat().st_mtime) < settle_time_seconds:
                            continue
                    except FileNotFoundError:
                        continue  # A producer may rotate files during a scan.
                    except OSError as exc:
                        # Keep advancing past a poison entry; resetting here
                        # would starve every healthy entry after it forever.
                        error_count += 1
                        if first_error is None:
                            first_error = f"{entry.name}: {exc}"
                        continue
                    files.append(Path(entry.path))
                # Reaching a limit is continuation, never a permanent refusal.
                return DiscoveryBatch(
                    sorted(files, key=lambda p: p.name.lower()), False, examined, error_count, first_error
                )
            except (OSError, ValueError) as exc:
                self._close()
                raise ValueError(f"Cannot scan watched folder: {exc}") from exc
