"""
In-memory registry for SherpaDataset handles.

This enables handle-based MCP/LLM contracts:
- register dataset snapshots by ``dataset_id``
- fetch by handle without shipping full payloads
- branch datasets by handle

The registry is process-local and intentionally lightweight. Entries are
bounded by TTL and max size to avoid unbounded memory growth.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset


@dataclass
class _DatasetRecord:
    dataset: SherpaDataset
    owner_user_id: int | None
    created_at: float
    last_accessed_at: float


class DatasetRegistry:
    """Thread-safe dataset handle registry."""

    def __init__(self, *, ttl_seconds: int = 6 * 3600, max_entries: int = 512) -> None:
        self._ttl_seconds = int(ttl_seconds)
        self._max_entries = int(max_entries)
        self._entries: OrderedDict[str, _DatasetRecord] = OrderedDict()
        self._lock = RLock()

    def register(self, dataset: SherpaDataset, owner_user_id: int | None = None) -> str:
        """Store a defensive snapshot and return ``dataset_id``."""
        now = time.time()
        # Defensive snapshot to decouple from mutable workflow objects.
        snapshot = SherpaDataset.from_dict(dataset.to_dict())
        record = _DatasetRecord(
            dataset=snapshot,
            owner_user_id=owner_user_id,
            created_at=now,
            last_accessed_at=now,
        )
        with self._lock:
            self._purge_expired_locked(now)
            self._entries[snapshot.dataset_id] = record
            self._entries.move_to_end(snapshot.dataset_id)
            self._evict_lru_locked()
        return snapshot.dataset_id

    def get(self, dataset_id: str, *, user_id: int | None = None) -> SherpaDataset:
        """Fetch a defensive copy of a registered dataset by handle."""
        now = time.time()
        with self._lock:
            self._purge_expired_locked(now)
            record = self._entries.get(dataset_id)
            if record is None:
                raise KeyError(dataset_id)
            if user_id is not None:
                if record.owner_user_id is None or record.owner_user_id != user_id:
                    raise PermissionError(dataset_id)
            record.last_accessed_at = now
            self._entries.move_to_end(dataset_id)
            # Return a defensive copy so callers cannot mutate registry state.
            return SherpaDataset.from_dict(record.dataset.to_dict())

    def branch(self, dataset_id: str, *, label: str, user_id: int | None = None) -> SherpaDataset:
        """Create and register a branch dataset from a handle."""
        owner: int | None = user_id
        with self._lock:
            record = self._entries.get(dataset_id)
            if record is not None:
                owner = record.owner_user_id
        parent = self.get(dataset_id, user_id=user_id)
        child = parent.branch(label)
        self.register(child, owner_user_id=owner)
        return child

    def _purge_expired_locked(self, now: float) -> None:
        if self._ttl_seconds <= 0:
            return
        expired_ids = [
            dataset_id
            for dataset_id, record in self._entries.items()
            if (now - record.last_accessed_at) > self._ttl_seconds
        ]
        for dataset_id in expired_ids:
            self._entries.pop(dataset_id, None)

    def _evict_lru_locked(self) -> None:
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


dataset_registry = DatasetRegistry()
