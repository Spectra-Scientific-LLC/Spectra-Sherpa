"""Stable array-content identity shared by partitioning and retained evidence."""

from __future__ import annotations

import hashlib
import json

import numpy as np


def array_content_digest(value: np.ndarray) -> str:
    """Digest an admitted array with explicit shape, kind, and stable bytes."""

    array = np.asarray(value)
    identity: dict[str, object] = {"shape": list(array.shape)}
    if np.issubdtype(array.dtype, np.number):
        canonical = np.ascontiguousarray(array, dtype="<f8")
        identity.update({"kind": "numeric_float64_le", "data_sha256": hashlib.sha256(canonical.tobytes()).hexdigest()})
    else:
        identity.update({"kind": "categorical_json", "values": array.tolist()})
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
