"""Advisor acquisition facts come from the same parsed source as Data inspection."""

import hashlib
import json
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.dataset_summarizer import DatasetSummarizer
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dataset_registry import DatasetRegistry
from spectra_sherpa.app.services.tools.builtin.datasets import describe_dataset


def lavender():
    dataset = SherpaDataset(X=np.zeros((33, 8)), title="Lavender")
    dataset.domain.instrument = "Thermo Nicolet Avatar 370"
    dataset.meta["source_member_metadata"] = [
        {
            "file_name": f"private-{index}.spa",
            "metadata": {
                "omnic.acquisition": {
                    "scan_count": 16,
                    "background_scan_count": 16,
                    "reference_frequency_cm-1": 15798.78,
                    "token": "never-forward",
                }
            },
        }
        for index in range(33)
    ]
    return dataset


def test_tool_reports_acquisition_without_processing_steps(monkeypatch):
    registry = DatasetRegistry()
    monkeypatch.setattr("spectra_sherpa.app.services.dataset_registry.dataset_registry", registry)
    dataset = lavender()
    dataset_id = registry.register(dataset, owner_user_id=910, project_id=73)
    result = describe_dataset(dataset_id, user=SimpleNamespace(id=910))
    acquisition = result["structured"]["acquisition"]
    assert acquisition["instrument"] == "Thermo Nicolet Avatar 370"
    assert acquisition["source_records"] == acquisition["records_with_acquisition"] == 33
    assert acquisition["fields"]["scan_count"]["values"] == [{"value": 16, "count": 33}]
    assert acquisition["fields"]["background_scan_count"]["values"] == [{"value": 16, "count": 33}]
    assert '"scan_count"' in result["summary"]
    assert "Avatar 370" in result["summary"]
    assert not dataset.provenance
    assert "private-" not in json.dumps(result)
    assert "never-forward" not in json.dumps(result)
    with pytest.raises(ValueError, match="not accessible"):
        describe_dataset(dataset_id, user=SimpleNamespace(id=911))


def test_member_headers_do_not_double_count_or_hide_variation():
    dataset = lavender()
    members = dataset.get_extra("source_member_metadata")
    members[0]["metadata"]["omnic.acquisition"]["scan_count"] = 32
    members[1]["metadata"] = {}
    dataset.set_extra("omnic.acquisition", {"scan_count": 999})
    acquisition = DatasetSummarizer().to_structured(dataset)["acquisition"]
    assert acquisition["source_records"] == 33
    assert acquisition["records_with_acquisition"] == 32
    counts = acquisition["fields"]["scan_count"]
    assert counts["records_with_value"] == 32
    assert counts["values"] == [{"value": 32, "count": 1}, {"value": 16, "count": 31}]


def test_single_source_unknown_settings_and_tier_boundary():
    dataset = SherpaDataset(X=np.zeros((2, 3)))
    summarizer = DatasetSummarizer()
    assert "acquisition" not in summarizer.to_structured(dataset, tier=0)
    assert summarizer.to_structured(dataset)["acquisition"]["availability"] == "not_recorded"
    dataset.set_extra(
        "omnic.acquisition",
        {
            "scan_count": 8,
            "background_scan_count": float("nan"),
            "resolution": None,
            "raw_data": [1, 2],
            "path": "/private/source.spa",
        },
    )
    acquisition = summarizer.to_structured(dataset)["acquisition"]
    assert acquisition["instrument"] is None
    assert set(acquisition["fields"]) == {"scan_count"}
    assert acquisition["fields"]["scan_count"]["values"] == [{"value": 8, "count": 1}]
    assert "source.spa" not in json.dumps(acquisition, allow_nan=False)


def test_timestamp_examples_are_bounded_and_never_claim_duration():
    dataset = lavender()
    for index, member in enumerate(dataset.get_extra("source_member_metadata")):
        member["metadata"]["omnic.acquisition"]["acquired_at"] = f"2026-08-23T23:{index:02d}:00Z"
    acquisition = DatasetSummarizer().to_structured(dataset)["acquisition"]
    timestamps = acquisition["fields"]["acquired_at"]
    assert timestamps["distinct_values"] == 33
    assert len(timestamps["values"]) == 12
    assert timestamps["omitted_distinct_values"] == 21
    assert "not a complete range or instrument scan duration" in acquisition["scope"]


def test_spg_timestamp_list_counts_observations_not_source_records():
    dataset = SherpaDataset(X=np.zeros((2, 3)))
    dataset.set_extra(
        "omnic.acquisition",
        {
            "scan_count": 8,
            "acquired_at": ["2026-08-23T23:00:00Z", "2026-08-23T23:01:00Z"],
        },
    )
    acquisition = DatasetSummarizer().to_structured(dataset)["acquisition"]
    timestamps = acquisition["fields"]["acquired_at"]
    assert acquisition["source_records"] == 1
    assert timestamps["records_with_value"] == 1
    assert timestamps["distinct_values"] == 2
    assert sum(value["count"] for value in timestamps["values"]) == 2
    assert "not current-row coverage" in acquisition["scope"]


def test_nested_collection_preserves_inner_headers_without_parent_duplicates():
    dataset = SherpaDataset(
        X=np.zeros((3, 3)),
        extra={
            "source_member_metadata": [
                {
                    "metadata": {
                        "omnic.acquisition": {"scan_count": 999},
                        "source_member_metadata": [
                            {"metadata": {"omnic.acquisition": {"scan_count": 16}}},
                            {"metadata": {"omnic.acquisition": {"scan_count": 32}}},
                        ],
                    }
                },
                {"metadata": {"omnic.acquisition": {"scan_count": 64}}},
            ]
        },
    )
    acquisition = DatasetSummarizer().to_structured(dataset)["acquisition"]
    assert acquisition["source_metadata_complete"]
    assert acquisition["source_records"] == 3
    assert acquisition["fields"]["scan_count"]["values"] == [
        {"value": 16, "count": 1},
        {"value": 32, "count": 1},
        {"value": 64, "count": 1},
    ]


def test_unexamined_nested_sources_are_partial_not_falsely_absent():
    metadata = {"omnic.acquisition": {"scan_count": 16}}
    for _ in range(10):
        metadata = {"source_member_metadata": [{"metadata": metadata}]}
    dataset = SherpaDataset(X=np.zeros((1, 3)), extra=metadata)
    acquisition = DatasetSummarizer().to_structured(dataset)["acquisition"]
    assert acquisition["availability"] == "partial"
    assert not acquisition["source_metadata_complete"]


def test_many_spg_timestamps_disclose_observation_limit():
    dataset = SherpaDataset(X=np.zeros((300, 3)))
    dataset.set_extra("omnic.acquisition", {"acquired_at": [f"timestamp-{n}" for n in range(300)]})
    timestamps = DatasetSummarizer().to_structured(dataset)["acquisition"]["fields"]["acquired_at"]
    assert timestamps["records_with_value"] == 1
    assert timestamps["omitted_observations"] == 44
    assert len(timestamps["values"]) == 12


def test_real_packaged_lavender_acquisition_survives_canonical_assembly(tmp_path):
    from spectra_sherpa.app.lib.builtin_lavender import PACKAGED_LAVENDER_ARCHIVE
    from spectra_sherpa.app.lib.collection_assembly import CollectionMember
    from spectra_sherpa.app.lib.collection_definition import apply_collection_definition, validate_collection_definition
    from spectra_sherpa.io import ingest

    members = []
    root = "lavender-essential-oil-v1/"
    with zipfile.ZipFile(PACKAGED_LAVENDER_ARCHIVE) as archive:
        definition = validate_collection_definition(json.loads(archive.read(root + "collection-definition.json")))
        manifest = json.loads(archive.read(root + "manifest.json"))
        for row in manifest["files"]:
            content = archive.read(root + row["path"])
            path = tmp_path / row["path"].split("/")[-1]
            path.write_bytes(content)
            asset = ingest(path).assets[0]
            members.append(
                CollectionMember(
                    dataset=asset.dataset,
                    file_name="raw/" + path.name,
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    asset_id=asset.asset_id,
                )
            )
    dataset = apply_collection_definition(members, definition)
    assert dataset.shape == (33, 1868)
    acquisition = DatasetSummarizer().to_structured(dataset)["acquisition"]
    assert acquisition["source_metadata_complete"]
    assert acquisition["instrument"] == "Thermo Nicolet Avatar 370"
    assert acquisition["source_records"] == 33
    assert acquisition["fields"]["scan_count"]["values"] == [{"value": 16, "count": 33}]
    assert acquisition["fields"]["background_scan_count"]["values"] == [{"value": 16, "count": 33}]
    assert acquisition["fields"]["reference_frequency_cm-1"]["values"][0]["value"] == pytest.approx(15798.78, abs=0.01)
