from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dataset_registry import DatasetRegistry


def _make_dataset() -> SherpaDataset:
    return SherpaDataset(X=np.arange(12, dtype=float).reshape(3, 4), title="registry-test")


def test_register_and_get_roundtrip():
    registry = DatasetRegistry(ttl_seconds=3600, max_entries=10)
    ds = _make_dataset()
    dataset_id = registry.register(ds, owner_user_id=7)
    fetched = registry.get(dataset_id, user_id=7)
    assert fetched.dataset_id == dataset_id
    assert fetched.shape == ds.shape
    assert fetched.title == "registry-test"


def test_get_enforces_owner():
    registry = DatasetRegistry(ttl_seconds=3600, max_entries=10)
    dataset_id = registry.register(_make_dataset(), owner_user_id=11)
    with pytest.raises(PermissionError):
        registry.get(dataset_id, user_id=12)


def test_get_denies_ownerless_records_for_authenticated_users():
    registry = DatasetRegistry(ttl_seconds=3600, max_entries=10)
    dataset_id = registry.register(_make_dataset())
    with pytest.raises(PermissionError):
        registry.get(dataset_id, user_id=12)


def test_get_allows_ownerless_records_without_user_context():
    registry = DatasetRegistry(ttl_seconds=3600, max_entries=10)
    dataset_id = registry.register(_make_dataset())
    fetched = registry.get(dataset_id)
    assert fetched.dataset_id == dataset_id


def test_branch_creates_new_handle():
    registry = DatasetRegistry(ttl_seconds=3600, max_entries=10)
    parent = _make_dataset()
    parent_id = registry.register(parent, owner_user_id=9)
    child = registry.branch(parent_id, label="candidate", user_id=9)
    assert child.dataset_id != parent_id
    assert child.branch_info is not None
    assert child.branch_info.parent_dataset_id == parent_id
