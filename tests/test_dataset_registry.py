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


def test_alias_dag_is_bounded_at_the_default_budget():
    visits = 0

    class CountedList(list):
        def __iter__(self):
            nonlocal visits
            visits += 1
            return super().__iter__()

    nested = CountedList(["ppm"])
    for _ in range(30):
        nested = CountedList([nested, nested])
    with pytest.raises(DatasetRegistryCapacityError, match="per-dataset byte limit"):
        estimate_retained_bytes(nested, max_bytes=128 * 1024 * 1024)
    assert visits <= 31


def test_failed_snapshot_keeps_the_previous_record(monkeypatch):
    registry = DatasetRegistry()
    dataset = _make_dataset()
    handle = registry.register(dataset, owner_user_id=7)
    before = registry.retained_bytes

    def fail_snapshot():
        raise ValueError("invalid optional metadata")

    monkeypatch.setattr(dataset, "snapshot", fail_snapshot)
    with pytest.raises(ValueError, match="optional metadata"):
        registry.register(dataset, owner_user_id=7)
    assert registry.retained_bytes == before
    assert registry.get(handle, user_id=7).dataset_id == handle


def test_snapshot_work_does_not_hold_registry_lookup_lock(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    registry = DatasetRegistry()
    handle = registry.register(_make_dataset(), owner_user_id=7)
    pending = _make_dataset()
    entered, release = Event(), Event()
    snapshot = pending.snapshot

    def delayed_snapshot():
        entered.set()
        assert release.wait(5), "test did not release snapshot"
        return snapshot()

    monkeypatch.setattr(pending, "snapshot", delayed_snapshot)
    with ThreadPoolExecutor(max_workers=2) as pool:
        write = pool.submit(registry.register, pending, 7)
        try:
            assert entered.wait(2)
            read = pool.submit(registry.project_for_owner, handle, user_id=7)
            assert read.result(timeout=2) is None
        finally:
            release.set()
        assert write.result(timeout=2) == pending.dataset_id


def test_native_ftir_snapshot_admits_normalized_metadata_aliases():
    from spectra_sherpa.app.lib.synthetic_references import load_synthetic_reference_as_sherpa

    dataset = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    admitted = estimate_retained_bytes(dataset)
    registry = DatasetRegistry(max_dataset_bytes=admitted, max_retained_bytes=admitted * 2)
    handle = registry.register(dataset, owner_user_id=7)
    retained = registry.get(handle, user_id=7)
    assert retained.scientific_digest == dataset.scientific_digest
    np.testing.assert_array_equal(retained.target, dataset.target)
    assert estimate_retained_bytes(retained) <= admitted
    assert registry.retained_bytes <= admitted


def test_container_alias_budget_is_conservative_and_cycles_terminate():
    shared = ["ppm", "ppm"]
    assert estimate_retained_bytes({"a": shared, "b": shared}) == estimate_retained_bytes(
        {"a": list(shared), "b": list(shared)}
    )
    recursive = []
    recursive.append(recursive)
    assert estimate_retained_bytes(recursive) > 0


def test_nested_alias_admission_stops_before_expansion_or_snapshot(monkeypatch):
    visits = []

    class CountedList(list):
        def __iter__(self):
            visits.append(1)
            assert len(visits) < 200, "must stop at the byte budget, not traverse exponentially"
            return super().__iter__()

    nested = CountedList(["ppm"])
    for _ in range(30):
        nested = CountedList([nested, nested])
    dataset = _make_dataset()
    # Inject the adversarial graph directly: the metadata setter itself
    # normalizes containers, before the registry boundary under test.
    dataset._extra["nested"] = nested
    monkeypatch.setattr(dataset, "snapshot", lambda: pytest.fail("must refuse before snapshot"))
    registry = DatasetRegistry(max_dataset_bytes=16384, max_retained_bytes=32768)
    with pytest.raises(DatasetRegistryCapacityError, match="byte limit"):
        registry.register(dataset, owner_user_id=7)
    assert registry.retained_bytes == 0


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
