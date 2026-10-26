import os
from dataclasses import replace

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.partitioned_run_output import retain_dataset


def test_partitioned_roundtrip_identity_quota_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    data = np.random.default_rng(4).normal(size=(1010, 1000))
    ds = SherpaDataset(
        X=data,
        sample_axis=SampleAxis(sample_table={"sample_id": [f"s{i}" for i in range(1010)], "wafer": ["01"] * 1010}),
        feature_axis=FeatureAxis(values=np.arange(1000), units="nm"),
        units="counts",
    )
    item, used = retain_dataset(1, ds, role="default", byte_limit=retention.RUN_BYTES_LIMIT)
    restored = retention.read_output(1, item)
    np.testing.assert_array_equal(restored["data"], data)
    assert restored["y_axis"]["sample_table"] == ds.sample_axis.sample_table
    assert restored["dataset_id"] == ds.dataset_id
    assert restored["shape"] == list(ds.shape)
    native = {**restored, "feature_axis": restored["x_axis"], "sample_axis": restored["y_axis"]}
    for key in ("x_axis", "y_axis", "manifest", "scientific_projection"):
        native.pop(key)
    # API metadata uses display quantities; native wire uses domain receipts.
    native["metadata"] = ds.to_dict()["metadata"]
    assert SherpaDataset.from_dict(native).scientific_digest == ds.scientific_digest
    from spectra_sherpa.app.services.partitioned_run_output import api_projection

    preview = api_projection(restored, 1)
    assert preview["metadata"]["api_serialization"]["mode"] == "bounded_preview"
    assert len(preview["data"]) < len(data)
    assert used == item.byte_count + item.partition_bytes
    manifest = retention.read_output(1, item, expand_partitions=False)
    directory = retention._user_directory(1)
    for path in directory.glob("*.json"):
        os.utime(path, (1, 1))
    retention.prune_unreferenced_outputs(1, {item.sha256})
    np.testing.assert_array_equal(retention.read_output(1, item)["data"], data)
    part = directory / (manifest["partitions"][0]["evidence"]["sha256"] + ".json")
    part.write_bytes(part.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum"):
        retention.read_output(1, item)
    with pytest.raises(ValueError, match="limit"):
        retain_dataset(1, ds, role="default", byte_limit=100)


def test_partitioned_run_budget_counts_previous_children(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    ds = SherpaDataset(X=np.random.default_rng(4).normal(size=(510, 1000)))
    prior = retention.retain_run_outputs(1, {"first": {"default": ds}}, {})
    item = prior["outputs"]["first"]["default"]
    assert item["state"] == "exact"
    monkeypatch.setattr(retention, "RUN_BYTES_LIMIT", item["byte_count"] + item["partition_bytes"] + 50)
    followup = retention.retain_run_outputs(1, {"next": {"default": ds}}, {}, previous=prior)
    assert followup["outputs"]["next"]["default"]["state"] == "missing"
