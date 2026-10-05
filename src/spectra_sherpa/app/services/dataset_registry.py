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

import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset


@dataclass
class _DatasetRecord:
    dataset: SherpaDataset
    owner_user_id: int | None
    project_id: int | None
    created_at: float
    last_accessed_at: float
    retained_bytes: int


DEFAULT_MAX_DATASET_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_RETAINED_BYTES = 256 * 1024 * 1024
_ARRAY_HEADER_BYTES = 256
_MAPPING_BASE_BYTES = 256
_MAPPING_ENTRY_BYTES = 64
_SEQUENCE_BASE_BYTES = 128
_SEQUENCE_ENTRY_BYTES = 16
_SET_BASE_BYTES = 256
_SET_ENTRY_BYTES = 64
_OBJECT_BASE_BYTES = 128


class DatasetRegistryCapacityError(RuntimeError):
    """Raised before copying when a typed dataset exceeds handle memory policy."""


def estimate_retained_bytes(value: object, *, _seen: set[int] | None = None) -> int:
    """Conservatively estimate unique retained memory with stable container costs.

    Python container allocation capacity can differ between an original object
    and its deep copy even when their logical structures are identical. Stable,
    deliberately generous per-entry costs make the admission estimate
    reproducible across the source and retained snapshot while ndarray buffers
    remain accounted from their exact ``nbytes``.
    """

    seen = _seen if _seen is not None else set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    if value is None:
        return 0
    if isinstance(value, np.ndarray):
        size = int(value.nbytes) + _ARRAY_HEADER_BYTES
        if value.dtype.hasobject:
            size += sum(estimate_retained_bytes(item, _seen=seen) for item in value.flat)
        return size
    if isinstance(value, dict):
        return (
            _MAPPING_BASE_BYTES
            + (_MAPPING_ENTRY_BYTES * len(value))
            + sum(
                estimate_retained_bytes(key, _seen=seen) + estimate_retained_bytes(item, _seen=seen)
                for key, item in value.items()
            )
        )
    if isinstance(value, (list, tuple)):
        return (
            _SEQUENCE_BASE_BYTES
            + (_SEQUENCE_ENTRY_BYTES * len(value))
            + sum(estimate_retained_bytes(item, _seen=seen) for item in value)
        )
    if isinstance(value, (set, frozenset)):
        return (
            _SET_BASE_BYTES
            + (_SET_ENTRY_BYTES * len(value))
            + sum(estimate_retained_bytes(item, _seen=seen) for item in value)
        )
    instance_dict = getattr(value, "__dict__", None)
    if isinstance(instance_dict, dict):
        return _OBJECT_BASE_BYTES + estimate_retained_bytes(instance_dict, _seen=seen)
    return sys.getsizeof(value)


class DatasetRegistry:
    """Thread-safe dataset handle registry."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 6 * 3600,
        max_entries: int = 512,
        max_dataset_bytes: int = DEFAULT_MAX_DATASET_BYTES,
        max_retained_bytes: int = DEFAULT_MAX_RETAINED_BYTES,
    ) -> None:
        self._ttl_seconds = int(ttl_seconds)
        self._max_entries = int(max_entries)
        self._max_dataset_bytes = int(max_dataset_bytes)
        self._max_retained_bytes = int(max_retained_bytes)
        if self._max_dataset_bytes <= 0 or self._max_retained_bytes <= 0:
            raise ValueError("dataset registry byte limits must be positive")
        if self._max_dataset_bytes > self._max_retained_bytes:
            raise ValueError("per-dataset byte limit cannot exceed total retained-byte limit")
        self._retained_bytes = 0
        self._entries: OrderedDict[str, _DatasetRecord] = OrderedDict()
        self._lock = RLock()

    def register(
        self, dataset: SherpaDataset, owner_user_id: int | None = None, *, project_id: int | None = None
    ) -> str:
        """Store a defensive snapshot and return ``dataset_id``."""
        now = time.time()
        retained_bytes = estimate_retained_bytes(dataset)
        if retained_bytes > self._max_dataset_bytes:
            raise DatasetRegistryCapacityError(
                "dataset exceeds the in-memory handle per-dataset byte limit "
                f"({retained_bytes} > {self._max_dataset_bytes})"
            )
        # Preserve typed arrays while decoupling from mutable workflow objects.
        # A JSON round trip would expand large arrays into Python object graphs
        # before the API serializer can enforce its output ceiling.
        with self._lock:
            self._purge_expired_locked(now)
            existing = self._entries.pop(dataset.dataset_id, None)
            if existing is not None:
                self._retained_bytes -= existing.retained_bytes
            self._evict_for_bytes_locked(retained_bytes)
            snapshot = dataset.snapshot()
            snapshot_bytes = estimate_retained_bytes(snapshot)
            if snapshot_bytes > retained_bytes:
                raise DatasetRegistryCapacityError(
                    "dataset snapshot exceeds its pre-copy retained-byte estimate "
                    f"({snapshot_bytes} > {retained_bytes})"
                )
            record = _DatasetRecord(
                dataset=snapshot,
                owner_user_id=owner_user_id,
                project_id=project_id,
                created_at=now,
                last_accessed_at=now,
                retained_bytes=snapshot_bytes,
            )
            self._entries[snapshot.dataset_id] = record
            self._retained_bytes += snapshot_bytes
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
            return record.dataset.snapshot()

    def project_for_owner(self, dataset_id: str, *, user_id: int) -> int | None:
        """Return server-recorded custody without trusting dataset metadata."""
        with self._lock:
            self._purge_expired_locked(time.time())
            record = self._entries.get(dataset_id)
            if record is None:
                raise KeyError(dataset_id)
            if record.owner_user_id != user_id:
                raise PermissionError(dataset_id)
            return record.project_id

    def branch(self, dataset_id: str, *, label: str, user_id: int | None = None) -> SherpaDataset:
        """Create and register a branch dataset from a handle."""
        owner: int | None = user_id
        project_id: int | None = None
        with self._lock:
            record = self._entries.get(dataset_id)
            if record is not None:
                owner = record.owner_user_id
                project_id = record.project_id
        parent = self.get(dataset_id, user_id=user_id)
        child = parent.branch(label)
        self.register(child, owner_user_id=owner, project_id=project_id)
        return child

    def clear(self) -> None:
        """Discard every process-local handle and its retained-byte charge."""

        with self._lock:
            self._entries.clear()
            self._retained_bytes = 0

    def _purge_expired_locked(self, now: float) -> None:
        if self._ttl_seconds <= 0:
            return
        expired_ids = [
            dataset_id
            for dataset_id, record in self._entries.items()
            if (now - record.last_accessed_at) > self._ttl_seconds
        ]
        for dataset_id in expired_ids:
            record = self._entries.pop(dataset_id, None)
            if record is not None:
                self._retained_bytes -= record.retained_bytes

    def _evict_for_bytes_locked(self, incoming_bytes: int) -> None:
        while self._entries and (self._retained_bytes + incoming_bytes) > self._max_retained_bytes:
            _, record = self._entries.popitem(last=False)
            self._retained_bytes -= record.retained_bytes

    def _evict_lru_locked(self) -> None:
        while len(self._entries) > self._max_entries:
            _, record = self._entries.popitem(last=False)
            self._retained_bytes -= record.retained_bytes

    @property
    def retained_bytes(self) -> int:
        with self._lock:
            return self._retained_bytes


dataset_registry = DatasetRegistry()
