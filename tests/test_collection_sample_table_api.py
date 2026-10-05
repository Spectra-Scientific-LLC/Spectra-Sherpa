from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date

import numpy as np
import pytest
from httpx import AsyncClient

from spectra_sherpa.app.api.v1.routes import builder as builder_route
from spectra_sherpa.app.api.v1.routes import datasets as datasets_route
from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.collection_definition import (
    scientific_collection_identity_from_digest,
    scientific_dataset_projection,
    scientific_dataset_projection_sha256,
)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.dataset_registry import dataset_registry


def _refresh_source_manifest(dataset: SherpaDataset) -> None:
    source = dataset.meta["source_collection"]
    identity = {"schema_version": source["schema_version"], "files": source["files"]}
    source["file_count"] = len(source["files"])
    source["manifest_digest"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _attach_scientific_identity(dataset: SherpaDataset, definition_digest: str | None = None) -> None:
    source = dataset.meta["source_collection"]
    projection_digest = (
        scientific_dataset_projection_sha256(scientific_dataset_projection(dataset))
        if definition_digest is not None
        else None
    )
    source.update(scientific_collection_identity_from_digest(source, definition_digest, projection_digest))


def _collection_dataset(*, structured: bool = False) -> SherpaDataset:
    labels = ["A__B1", "B__B1", "A__B2", "B__B2"]
    sample_ids: list[object] = list(labels)
    if structured:
        sample_ids[0] = {"unsupported": True}
    files = [
        {
            "file_name": f"raw/member-{index}.spa",
            "size_bytes": 1_024 + index,
            "sha256": f"{index + 1:064x}",
            "prepared_data_sha256": f"{index + 11:064x}",
        }
        for index in range(4)
    ]
    identity = {"schema_version": "spectrasherpa-source-collection/1", "files": files}
    manifest_digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return SherpaDataset(
        X=np.arange(12, dtype=np.float64).reshape(4, 3),
        feature_axis=SpectralAxis(values=np.array([1800.0, 1200.0, 600.0]), units="cm-1"),
        sample_axis=SampleAxis(
            labels=labels,
            sample_table={
                "sample_id": sample_ids,
                "specimen_id": ["A", "B", "A", "B"],
                "block": [1, 1, 2, 2],
            },
        ),
        data_role="X_spectra",
        extra={
            "source_collection": {
                "schema_version": "spectrasherpa-source-collection/1",
                "file_count": 4,
                "files": files,
                "manifest_digest": manifest_digest,
            }
        },
    )


def _large_collection_dataset() -> SherpaDataset:
    row_count = 512
    labels = [f"S{index + 1:04d}" for index in range(row_count)]
    return SherpaDataset(
        X=np.zeros((row_count, 3_000), dtype=np.float64),
        feature_axis=SpectralAxis(values=np.arange(3_000, dtype=np.float64), units="cm-1"),
        sample_axis=SampleAxis(
            labels=labels,
            sample_table={
                "sample_id": labels,
                "specimen_id": [f"group-{index % 11}" for index in range(row_count)],
                "block": [(index % 3) + 1 for index in range(row_count)],
            },
        ),
        data_role="X_spectra",
        extra={"source_collection": deepcopy(_collection_dataset().meta["source_collection"])},
    )


def _with_sample_identity(
    *,
    labels: list[str],
    sample_table: dict[str, list[object]],
) -> SherpaDataset:
    base = _collection_dataset()
    return SherpaDataset(
        X=np.array(base.X, copy=True),
        feature_axis=base.feature_axis,
        sample_axis=SampleAxis(labels=labels, sample_table=sample_table),
        data_role="X_spectra",
        extra={"source_collection": deepcopy(base.meta["source_collection"])},
    )


@pytest.mark.anyio
async def test_complete_collection_sample_table_is_owner_scoped_and_type_preserving(
    auth_client: AsyncClient,
    test_user: User,
) -> None:
    dataset = _collection_dataset()
    _attach_scientific_identity(dataset, "d" * 64)
    handle = dataset_registry.register(dataset, owner_user_id=test_user.id)

    response = await auth_client.get(f"/api/v1/datasets/{handle}/sample-table")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "spectrasherpa-collection-sample-table/1",
        "complete": True,
        "row_count": 4,
        "columns": ["sample_id", "specimen_id", "block"],
        "labels": ["A__B1", "B__B1", "A__B2", "B__B2"],
        "sample_table": {
            "sample_id": ["A__B1", "B__B1", "A__B2", "B__B2"],
            "specimen_id": ["A", "B", "A", "B"],
            "block": [1, 1, 2, 2],
        },
        "source_collection": {
            "schema_version": "spectrasherpa-source-collection/1",
            "file_count": 4,
            "manifest_digest": dataset.meta["source_collection"]["manifest_digest"],
            **scientific_collection_identity_from_digest(
                dataset.meta["source_collection"],
                "d" * 64,
                scientific_dataset_projection_sha256(scientific_dataset_projection(dataset)),
            ),
        },
    }


def test_complete_table_recomputes_combined_scientific_identity() -> None:
    dataset = _collection_dataset()
    _attach_scientific_identity(dataset, "d" * 64)
    payload = datasets_route._complete_collection_sample_table(dataset)
    assert (
        payload["source_collection"]["scientific_collection_sha256"]
        == dataset.meta["source_collection"]["scientific_collection_sha256"]
    )

    mutations = {
        "scientific_collection_schema_version": "unknown/9",
        "source_manifest_sha256": "0" * 64,
        "collection_definition_sha256": "0" * 64,
        "scientific_collection_sha256": "0" * 64,
    }
    for field, value in mutations.items():
        mutated = deepcopy(dataset)
        mutated.meta["source_collection"][field] = value
        with pytest.raises(ValueError, match="does not match its source manifest"):
            datasets_route._complete_collection_sample_table(mutated)

    incomplete = deepcopy(dataset)
    incomplete.meta["source_collection"].pop("scientific_collection_sha256")
    with pytest.raises(ValueError, match="malformed source-collection identity"):
        datasets_route._complete_collection_sample_table(incomplete)


@pytest.mark.anyio
async def test_collection_sample_table_refuses_unsupported_cells_and_declared_row_overflow(
    auth_client: AsyncClient,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structured = _collection_dataset(structured=True)
    structured_handle = dataset_registry.register(structured, owner_user_id=test_user.id)
    structured_response = await auth_client.get(f"/api/v1/datasets/{structured_handle}/sample-table")
    assert structured_response.status_code == 422
    assert "unsupported structured value" in structured_response.json()["detail"]

    malformed_source = _collection_dataset()
    malformed_source.meta["source_collection"]["files"] = []
    malformed_handle = dataset_registry.register(malformed_source, owner_user_id=test_user.id)
    malformed_response = await auth_client.get(f"/api/v1/datasets/{malformed_handle}/sample-table")
    assert malformed_response.status_code == 422
    assert "malformed source-collection identity" in malformed_response.json()["detail"]

    bounded = _collection_dataset()
    bounded_handle = dataset_registry.register(bounded, owner_user_id=test_user.id)
    monkeypatch.setattr(datasets_route, "_COLLECTION_SAMPLE_TABLE_MAX_ROWS", 3)
    bounded_response = await auth_client.get(f"/api/v1/datasets/{bounded_handle}/sample-table")
    assert bounded_response.status_code == 422
    assert "3-row retrieval limit" in bounded_response.json()["detail"]


@pytest.mark.anyio
async def test_builder_bounded_preview_retains_collection_identity_and_recovers_complete_table(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _large_collection_dataset()
    source = dataset.meta["source_collection"]

    async def _loaded(*args, **kwargs):
        return dataset, [object()] * source["file_count"], "Large collection", "raw", source

    monkeypatch.setattr(builder_route, "_experiment_contents_as_sherpa", _loaded)
    response = await auth_client.post("/api/v1/builder/file-info", json={"experiment_id": 42})

    assert response.status_code == 200
    preview = response.json()
    assert preview["metadata"]["api_serialization"]["mode"] == "bounded_preview"
    assert preview["metadata"]["source_collection"] == source
    assert preview["metadata"]["preview_shape"] == [10, 3_000]
    assert len(preview["data"]) == 10
    handle = preview["dataset_id"]
    complete = await auth_client.get(f"/api/v1/datasets/{handle}/sample-table")
    assert complete.status_code == 200
    assert complete.json()["row_count"] == 512
    assert complete.json()["labels"][-1] == "S0512"


@pytest.mark.anyio
async def test_builder_full_preview_refuses_sample_table_values_that_cannot_cross_json_losslessly(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = ["A__B1", "B__B1", "A__B2", "B__B2"]
    specimens = ["A", "B", "A", "B"]
    blocks = [1, 1, 2, 2]
    mutations = [
        (
            _with_sample_identity(
                labels=labels,
                sample_table={
                    "sample_id": labels,
                    "specimen_id": specimens,
                    "block": blocks,
                    "acquisition_id": [2**53, 2**53 + 1, 3, 4],
                },
            ),
            "integer outside the lossless JSON range",
        ),
        (
            _with_sample_identity(
                labels=labels,
                sample_table={
                    "sample_id": labels,
                    "specimen_id": [date(2026, 1, 1), "2026-01-01", "A", "B"],
                    "block": blocks,
                },
            ),
            "unsupported date or datetime value",
        ),
        (
            _with_sample_identity(
                labels=labels,
                sample_table={
                    "sample_id": labels,
                    "specimen_id": specimens,
                    "block": [1, np.nan, 2, 2],
                },
            ),
            "non-finite numeric value",
        ),
    ]

    for dataset, expected in mutations:
        source = dataset.meta["source_collection"]

        async def _loaded(*args, _dataset=dataset, _source=source, **kwargs):
            return _dataset, [object()] * _source["file_count"], "Invalid collection", "raw", _source

        monkeypatch.setattr(builder_route, "_experiment_contents_as_sherpa", _loaded)
        response = await auth_client.post("/api/v1/builder/file-info", json={"experiment_id": 42})
        assert response.status_code == 400
        assert expected in response.json()["detail"]


@pytest.mark.anyio
async def test_complete_table_refuses_misbound_or_incomplete_scientific_identity(
    auth_client: AsyncClient,
    test_user: User,
) -> None:
    mutations = []

    labels = ["A__B1", "B__B1", "A__B2", "B__B2"]
    specimens = ["A", "B", "A", "B"]
    blocks = [1, 1, 2, 2]

    reordered = _with_sample_identity(
        labels=labels,
        sample_table={"sample_id": list(reversed(labels)), "specimen_id": specimens, "block": blocks},
    )
    mutations.append((reordered, "does not match its label"))

    duplicate_labels = ["A__B1", "A__B1", "A__B2", "B__B2"]
    duplicate = _with_sample_identity(
        labels=duplicate_labels,
        sample_table={"sample_id": duplicate_labels, "specimen_id": specimens, "block": blocks},
    )
    mutations.append((duplicate, "unique non-empty strings"))

    empty_group = _with_sample_identity(
        labels=labels,
        sample_table={"sample_id": labels, "specimen_id": [None, "B", "A", "B"], "block": blocks},
    )
    mutations.append((empty_group, "contains an empty identity"))

    nonfinite_group = _with_sample_identity(
        labels=labels,
        sample_table={"sample_id": labels, "specimen_id": specimens, "block": [np.nan, 1, 2, 2]},
    )
    mutations.append((nonfinite_group, "non-finite numeric value"))

    unsafe_integer = _with_sample_identity(
        labels=labels,
        sample_table={
            "sample_id": labels,
            "specimen_id": specimens,
            "block": blocks,
            "acquisition_id": [2**53, 2**53 + 1, 3, 4],
        },
    )
    mutations.append((unsafe_integer, "integer outside the lossless JSON range"))

    date_value = _with_sample_identity(
        labels=labels,
        sample_table={
            "sample_id": labels,
            "specimen_id": specimens,
            "block": blocks,
            "annotation": [date(2026, 1, 1), "2026-01-01", "later", "later"],
        },
    )
    mutations.append((date_value, "unsupported date or datetime value"))

    for dataset, expected in mutations:
        handle = dataset_registry.register(dataset, owner_user_id=test_user.id)
        response = await auth_client.get(f"/api/v1/datasets/{handle}/sample-table")
        assert response.status_code == 422
        assert expected in response.json()["detail"]

    missing_redundant_sample_id = _with_sample_identity(
        labels=labels,
        sample_table={"specimen_id": specimens, "block": blocks},
    )
    handle = dataset_registry.register(missing_redundant_sample_id, owner_user_id=test_user.id)
    response = await auth_client.get(f"/api/v1/datasets/{handle}/sample-table")
    assert response.status_code == 200
    assert response.json()["sample_table"] == {
        "sample_id": labels,
        "specimen_id": specimens,
        "block": blocks,
    }


def test_complete_table_admits_generic_sample_identity_without_grouping_columns() -> None:
    labels = ["sample-1", "sample-2", "sample-3", "sample-4"]
    dataset = _with_sample_identity(
        labels=labels,
        sample_table={"sample_id": labels, "acquired_at": ["t1", "t2", "t3", "t4"]},
    )

    payload = datasets_route._complete_collection_sample_table(dataset)

    assert payload["columns"] == ["sample_id", "acquired_at"]
    assert payload["labels"] == labels
    assert payload["sample_table"] == {
        "sample_id": labels,
        "acquired_at": ["t1", "t2", "t3", "t4"],
    }


def test_complete_table_projects_sample_id_from_typed_labels_without_mutating_science() -> None:
    labels = ["sample-1", "sample-2", "sample-3", "sample-4"]
    base = _collection_dataset()
    dataset = SherpaDataset(
        X=np.array(base.X, copy=True),
        feature_axis=base.feature_axis,
        sample_axis=SampleAxis(labels=labels),
        data_role="X_spectra",
        extra={"source_collection": deepcopy(base.meta["source_collection"])},
    )
    before = dataset.scientific_digest

    payload = datasets_route._complete_collection_sample_table(dataset)

    assert payload["columns"] == ["sample_id"]
    assert payload["labels"] == labels
    assert payload["sample_table"] == {"sample_id": labels}
    assert dataset.sample_axis is not None
    assert dataset.sample_axis.sample_table is None
    assert dataset.scientific_digest == before


def test_complete_table_refuses_invalid_member_semantics_even_with_matching_digest() -> None:
    invalid_values = [
        ("file_name", ""),
        ("file_name", 7),
        ("size_bytes", True),
        ("size_bytes", -1),
        ("sha256", "x"),
        ("prepared_data_sha256", "y"),
    ]
    for field, value in invalid_values:
        dataset = _collection_dataset()
        dataset.meta["source_collection"]["files"][0][field] = value
        _refresh_source_manifest(dataset)
        with pytest.raises(ValueError, match="malformed source-collection member"):
            datasets_route._complete_collection_sample_table(dataset)

    for aliases in [
        ("raw/a.spa", "raw\\a.spa"),
        ("raw/a.spa", "raw//a.spa"),
        ("raw/a.spa", "raw/./a.spa"),
    ]:
        dataset = _collection_dataset()
        dataset.meta["source_collection"]["files"][0]["file_name"] = aliases[0]
        dataset.meta["source_collection"]["files"][1]["file_name"] = aliases[1]
        _refresh_source_manifest(dataset)
        with pytest.raises(ValueError, match="malformed source-collection member"):
            datasets_route._complete_collection_sample_table(dataset)


def test_complete_table_refuses_cumulative_size_before_aggregate_json_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row_count = 2_000
    labels = [f"S{index + 1:04d}" for index in range(row_count)]
    dataset = SherpaDataset(
        X=np.zeros((row_count, 1), dtype=np.float64),
        feature_axis=SpectralAxis(values=np.array([1.0]), units="cm-1"),
        sample_axis=SampleAxis(
            labels=labels,
            sample_table={
                "sample_id": labels,
                "specimen_id": ["x" * 4_096] * row_count,
                "block": [1] * row_count,
            },
        ),
        data_role="X_spectra",
        extra={"source_collection": deepcopy(_collection_dataset().meta["source_collection"])},
    )

    monkeypatch.setattr(
        datasets_route.json,
        "dumps",
        lambda *args, **kwargs: pytest.fail("aggregate json.dumps must be unreachable"),
    )
    with pytest.raises(ValueError, match="4 MiB retrieval limit"):
        datasets_route._complete_collection_sample_table(dataset)
