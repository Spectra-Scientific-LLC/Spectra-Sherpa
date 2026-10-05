from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dataset_registry import (
    DatasetRegistry,
    DatasetRegistryCapacityError,
    estimate_retained_bytes,
)


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


def test_register_snapshot_never_uses_json_projection(monkeypatch):
    registry = DatasetRegistry(ttl_seconds=3600, max_entries=10)
    dataset = _make_dataset()
    monkeypatch.setattr(
        dataset,
        "to_dict",
        lambda: pytest.fail("dataset registry must not box arrays through JSON"),
    )

    dataset_id = registry.register(dataset, owner_user_id=7)
    fetched = registry.get(dataset_id, user_id=7)

    np.testing.assert_array_equal(fetched.X, dataset.X)
    assert fetched.dataset_id == dataset_id


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


def test_clear_discards_all_process_local_handles_and_byte_charges():
    registry = DatasetRegistry(ttl_seconds=3600, max_entries=10)
    handles = [registry.register(_make_dataset(), owner_user_id=9) for _ in range(2)]
    assert registry.retained_bytes > 0

    registry.clear()

    assert registry.retained_bytes == 0
    for handle in handles:
        with pytest.raises(KeyError):
            registry.get(handle, user_id=9)


def test_per_dataset_byte_limit_fails_before_snapshot(monkeypatch):
    dataset = SherpaDataset(X=np.arange(1_000, dtype=float).reshape(10, 100))
    retained = estimate_retained_bytes(dataset)
    registry = DatasetRegistry(
        ttl_seconds=3600,
        max_entries=10,
        max_dataset_bytes=retained - 1,
        max_retained_bytes=retained * 3,
    )
    monkeypatch.setattr(
        dataset,
        "snapshot",
        lambda: pytest.fail("over-budget dataset must fail before copying"),
    )

    with pytest.raises(DatasetRegistryCapacityError, match="per-dataset byte limit"):
        registry.register(dataset, owner_user_id=7)
    assert registry.retained_bytes == 0


def test_registry_evicts_lru_by_retained_bytes():
    datasets = [SherpaDataset(X=np.full((10, 100), index, dtype=float)) for index in range(3)]
    retained = max(estimate_retained_bytes(dataset) for dataset in datasets)
    registry = DatasetRegistry(
        ttl_seconds=3600,
        max_entries=10,
        max_dataset_bytes=retained + 1_024,
        max_retained_bytes=(retained + 1_024) * 2,
    )

    handles = [registry.register(dataset, owner_user_id=7) for dataset in datasets]

    with pytest.raises(KeyError):
        registry.get(handles[0], user_id=7)
    assert registry.get(handles[1], user_id=7).dataset_id == handles[1]
    assert registry.get(handles[2], user_id=7).dataset_id == handles[2]
    assert registry.retained_bytes <= (retained + 1_024) * 2


def test_snapshot_preserves_shared_array_authority_for_byte_accounting():
    datasets = [SherpaDataset(X=np.full((100, 100), index, dtype=np.float64)) for index in range(3)]
    for dataset in datasets:
        dataset.set_extra("test.shared_x", dataset.X)
        dataset.set_extra("test.shared_x_again", dataset.X)
        assert dataset.get_extra("test.shared_x") is dataset.X
        assert dataset.get_extra("test.shared_x_again") is dataset.X
    admitted_bytes = max(estimate_retained_bytes(dataset) for dataset in datasets)
    registry = DatasetRegistry(
        ttl_seconds=3600,
        max_entries=10,
        max_dataset_bytes=admitted_bytes,
        max_retained_bytes=admitted_bytes * 2,
    )

    handles = [registry.register(dataset, owner_user_id=7) for dataset in datasets]

    with pytest.raises(KeyError):
        registry.get(handles[0], user_id=7)
    for handle in handles[1:]:
        retained = registry.get(handle, user_id=7)
        assert retained.get_extra("test.shared_x") is retained.X
        assert retained.get_extra("test.shared_x_again") is retained.X
        assert estimate_retained_bytes(retained) <= admitted_bytes
    assert registry.retained_bytes <= admitted_bytes * 2
