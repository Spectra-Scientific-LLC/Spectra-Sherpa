"""Scientific and custody regressions for gas-driven BOSCH phase comparisons."""

from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.bosch_phases import phase_projection
from spectra_sherpa.io.registry import builtin_registry
from tests.test_bosch_netcdf import files


def process_and_spectra():
    times = np.arange(80, 280, 0.2)
    relative = times - 80
    gas1 = np.where((relative > 170) & (relative < 180), 200.0, 0)
    on = (relative >= 25) & (relative < 165)
    gas5 = np.where(on & ((relative - 25) % 6 < 4.5), 600.0, 0)
    gas4 = np.where(on & (gas5 == 0), 300.0, 0)
    rf = np.where(on | (gas1 > 0), 2000.0, 0)
    process = SherpaDataset(
        X=np.column_stack([gas1, gas4, gas5, rf]),
        feature_axis=FeatureAxis(
            labels=[f"Stat3_Etch_MV_{name}" for name in ["Gas1Flow", "Gas4Flow", "Gas5Flow", "SourceRFLoadPower"]]
        ),
        sample_axis=SampleAxis(values=times, units="s"),
        data_role="X_features",
    )
    ot = np.arange(0, 195, 0.04) + 1722864000
    signal = np.interp(ot - ot[0] + 80, times, gas5) + np.random.default_rng(7).normal(0, 5, len(ot))
    return ot, signal, process


def test_phase_alignment_labels_by_gas_and_keeps_uncertain_edges():
    ot, signal, process = process_and_spectra()
    labels, alignment = phase_projection(ot, signal, process)
    assert alignment["correlation"] > 0.95
    assert abs(alignment["process_time_at_first_oes_s"] - 80) < 0.25
    assert alignment["chemical_mapping_confirmed"] is False
    assert {"etch", "passivation", "gas1_plasma", "transition", "break"} <= set(labels)
    assert labels[np.argmin(abs(ot - ot[0] - 30))] == "passivation"
    assert labels[np.argmin(abs(ot - ot[0] - 172))] == "gas1_plasma"


def test_unrelated_optical_signal_is_not_given_plausible_phase_labels():
    ot, _, process = process_and_spectra()
    with pytest.raises(ValueError, match="Ambiguous"):
        phase_projection(ot, np.random.default_rng(11).normal(size=len(ot)), process)


def test_phase_alignment_rejects_missing_channels_and_bad_clocks():
    ot, signal, process = process_and_spectra()
    with pytest.raises(ValueError, match="increasing"):
        phase_projection(ot[::-1], signal, process)
    process.feature_axis = FeatureAxis(labels=[f"unknown{i}" for i in range(4)])
    with pytest.raises(ValueError, match="Missing required process channel"):
        phase_projection(ot, signal, process)


def test_sparse_native_preview_keeps_original_values_times_and_ids(tmp_path: Path):
    path, _, _, _, timestamps = files(tmp_path)
    full = builtin_registry.ingest(path, asset_id="Wafer_01").assets[0].dataset
    selected = builtin_registry.ingest(path, asset_id="Wafer_01", rows=(0, 3)).assets[0].dataset
    np.testing.assert_array_equal(selected.X, full.X[[0, 3]])
    np.testing.assert_array_equal(selected.sample_axis.values, timestamps[[0, 3]])
    assert selected.sample_axis.sample_table["sample_id"] == [
        full.sample_axis.sample_table["sample_id"][i] for i in (0, 3)
    ]
    assert selected.get_extra("bosch.source_row_indices") == [0, 3]
    for invalid in [(), (3, 0), (1, 1), (-1,), (4,)]:
        with pytest.raises(ValueError):
            builtin_registry.ingest(path, asset_id="Wafer_01", rows=invalid)


@pytest.mark.anyio
async def test_phase_api_requires_owned_distinct_process_companion(auth_client, tmp_path):
    path, _, *_ = files(tmp_path)
    experiment = (await auth_client.post("/api/v1/experiments", json={"name": "BOSCH phase ownership"})).json()
    eid = experiment["id"]
    uploaded = await auth_client.post(
        f"/api/v1/experiments/{eid}/files",
        data={"stage": "raw"},
        files={"file": ("Day_2024_08_05.nc", path.read_bytes(), "application/x-netcdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    fid = uploaded.json()["id"]
    url = f"/api/v1/experiments/{eid}/files/{fid}/bosch-steps"
    assert (await auth_client.get(url)).status_code == 422
    assert (await auth_client.get(url, params={"process_file_id": fid})).status_code == 400
    assert (await auth_client.get(url, params={"process_file_id": fid + 1000})).status_code == 404


def test_process_recording_can_start_long_before_the_first_optical_acquisition():
    ot, signal, process = process_and_spectra()
    # Reproduce a separate relative process origin and a 128-second lead-in,
    # as observed in the actual August 7 wafer 8 source. No fixed start offset.
    values = np.vstack([np.zeros((640, 4)), process.X])
    companion = SherpaDataset(
        X=values,
        feature_axis=process.feature_axis,
        sample_axis=SampleAxis(values=np.arange(len(values)) * 0.2, units="s"),
        data_role="X_features",
    )
    labels, alignment = phase_projection(ot, signal, companion)
    assert abs(alignment["process_time_at_first_oes_s"] - 128) < 0.25
    assert alignment["correlation"] > 0.95
    assert "passivation" in labels


@pytest.mark.anyio
async def test_canonical_node_preserves_values_and_observation_ids_and_rejects_wrong_wafer():
    from spectra_sherpa.app.lib.sherpa_dataset import DatasetSourceIdentity
    from spectra_sherpa.app.services.dag.nodes.bosch_phases import BoschPhaseLabelsNode

    times, signal, process = process_and_spectra()
    ids = [f"original:{i}" for i in range(len(times))]
    spectra = SherpaDataset(
        X=np.column_stack([signal, signal * 0.5]),
        feature_axis=FeatureAxis(values=np.array([685.0, 704.0]), units="nm"),
        sample_axis=SampleAxis(values=times, units="s", sample_table={"sample_id": ids}),
        data_role="X_spectra",
        source_identity=DatasetSourceIdentity(object_name="Wafer_01"),
    )
    process = SherpaDataset(
        X=process.X,
        feature_axis=process.feature_axis,
        sample_axis=process.sample_axis,
        data_role="X_features",
        source_identity=DatasetSourceIdentity(object_name="Day_2024_08_05_Wafer_01"),
    )
    result = await BoschPhaseLabelsNode("phase-test").execute(default=spectra, process=process)
    dataset = result.outputs["default"]
    np.testing.assert_array_equal(dataset.X, spectra.X)
    np.testing.assert_array_equal(dataset.sample_axis.values, times)
    assert dataset.sample_axis.sample_table["sample_id"] == ids
    assert "processing_step" not in spectra.sample_axis.sample_table
    assert {"etch", "passivation"} <= set(dataset.sample_axis.sample_table["processing_step"])
    spectra.meta["supervision_binding"] = {"retained": True}
    with pytest.raises(ValueError, match="before binding"):
        await BoschPhaseLabelsNode("bound-source").execute(default=spectra, process=process)
    del spectra.meta["supervision_binding"]
    process = SherpaDataset(
        X=process.X,
        feature_axis=process.feature_axis,
        sample_axis=process.sample_axis,
        data_role="X_features",
        source_identity=DatasetSourceIdentity(object_name="Day_2024_08_05_Wafer_02"),
    )
    with pytest.raises(ValueError, match="does not match"):
        await BoschPhaseLabelsNode("wrong-wafer").execute(default=spectra, process=process)


def test_step_preview_selects_only_original_phase_rows_and_rejects_changed_companion(tmp_path, monkeypatch):
    from spectra_sherpa.app.services import bosch_step_comparison as service

    daily, _, *_ = files(tmp_path)
    process_dir = tmp_path / "process"
    process_dir.mkdir()
    process, _, *_ = files(process_dir, process=True)
    original = builtin_registry.ingest(daily, asset_id="Wafer_01")
    source_sha = original.source_members[0].sha256
    process_sha = builtin_registry.inspect(process).source_members[0].sha256
    catalog = {
        "source_sha256": source_sha,
        "process_sha256": process_sha,
        "_private": {"Wafer_01": {"labels": np.array(["etch", "passivation", "transition", "etch"])}},
    }
    monkeypatch.setattr(service, "phase_catalog", lambda *args: catalog)
    kwargs = dict(asset_id="Wafer_01", step_id="etch", source_sha256=source_sha, process_sha256=process_sha)
    preview, count = service.step_preview(daily, process, **kwargs)
    assert count == 2
    np.testing.assert_array_equal(preview.X, original.assets[0].dataset.X[[0, 3]])
    assert preview.sample_axis.sample_table["acquisition_number"] == [1, 4]
    with pytest.raises(ValueError, match="Sources changed"):
        service.step_preview(daily, process, **{**kwargs, "source_sha256": "0" * 64})
    # Keep the cached inventory but mutate the companion bytes. A fresh digest
    # must reject it even if a filesystem cache key were reused.
    import h5py

    with h5py.File(process, "a") as root:
        root.attrs["mutation"] = "changed since inventory"
    with pytest.raises(ValueError, match="companion changed"):
        service.step_preview(daily, process, **kwargs)
