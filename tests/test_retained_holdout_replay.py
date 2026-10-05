"""Reload event time is distinct from retained source scientific authority."""

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import Provenance, SherpaDataset
from spectra_sherpa.app.services.dag.retained_holdout import retained_holdout_partition, verify_holdout_source


@pytest.fixture
def source():
    data = SherpaDataset(
        X=np.arange(24, dtype=float).reshape(6, 4),
        target=np.arange(6, dtype=float),
        sample_axis=SampleAxis(labels=list("abcdef"), sample_table={"batch": ["a"] * 3 + ["b"] * 3}),
        feature_axis=SpectralAxis(values=np.arange(4) + 1000, units="nm"),
    )
    data.provenance.append("import.reference", {"source_sha256": "a" * 64, "timestamp": "specimen-time"})
    data.provenance.append("data.attach_target", {"column": "response"}, node_id="data_1")
    binding = retained_holdout_partition(
        data,
        source_node_id="data_1",
        split_node_id="split",
        source_run_id=1,
        train_indices=[3, 1, 0, 2],
        test_indices=[5, 4],
    )
    return data, binding


def test_reload_timestamp_is_accepted_without_changing_execution_digest(source):
    data, binding = source
    reload = data.copy()
    entries = reload.provenance.to_list()
    for entry in entries:
        entry["timestamp"] = "2026-10-05T16:00:00+00:00"
    reload.provenance = Provenance.from_list(entries)
    assert data.scientific_digest == binding["source_scientific_digest"]
    assert reload.scientific_digest != binding["source_scientific_digest"]
    assert verify_holdout_source(reload, binding) is reload


@pytest.mark.parametrize(
    "change",
    [
        "data",
        "target",
        "axis",
        "units",
        "sample_ids",
        "sample_table",
        "operation",
        "version",
        "parameters",
        "parameter_timestamp",
        "order",
        "source_hash",
        "node",
        "state_effects",
        "shape",
    ],
)
def test_replay_still_rejects_scientific_or_operation_changes(source, change):
    data, binding = source
    changed = data.copy()
    entries = changed.provenance.to_list()
    if change == "data":
        changed.X[5, 0] += 1
    elif change == "target":
        changed.target[0] += 1
    elif change == "axis":
        changed.feature_axis = SpectralAxis(values=np.arange(4) + 1100, units="nm")
    elif change == "units":
        changed.feature_axis = SpectralAxis(values=np.arange(4) + 1000, units="cm^-1")
    elif change == "sample_ids":
        changed.sample_axis = SampleAxis(labels=list("fedcba"), sample_table={"batch": ["a"] * 3 + ["b"] * 3})
    elif change == "sample_table":
        changed.sample_axis = SampleAxis(labels=list("abcdef"), sample_table={"batch": ["a"] * 6})
    elif change == "operation":
        entries[-1]["op_id"] = "other.operation"
    elif change == "version":
        entries[-1]["op_version"] = "2.0"
    elif change == "parameters":
        entries[-1]["parameters"]["column"] = "other"
    elif change == "parameter_timestamp":
        entries[0]["parameters"]["timestamp"] = "other-specimen-time"
    elif change == "source_hash":
        entries[0]["parameters"]["source_sha256"] = "b" * 64
    elif change == "node":
        entries[-1]["node_id"] = "other"
    elif change == "state_effects":
        entries[-1]["state_effects"] = ["scaled"]
    elif change == "shape":
        entries[-1]["input_shape"] = [3, 8]
    else:
        entries.reverse()
    changed.provenance = Provenance.from_list(entries)
    with pytest.raises(ValueError, match="source has changed"):
        verify_holdout_source(changed, binding)


def test_old_receipt_is_not_silently_reinterpreted(source):
    data, binding = source
    binding["schema_version"] = "spectrasherpa-retained-holdout/1"
    binding.pop("source_replay_digest")
    with pytest.raises(ValueError, match="fields or version"):
        verify_holdout_source(data, binding)
