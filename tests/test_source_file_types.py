from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.scp_compat import is_scp_testdata_file
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset


@pytest.mark.parametrize(
    "filename",
    [
        "spectrum.csv",
        "spectrum.jdx",
        "spectrum.dx",
        "spectrum.spc",
        "spectrum.spa",
        "series.spg",
        "time_series.srs",
        "renishaw.wdf",
        "table.txt",
        "dataset.mat",
        "ion_currents.asc",
        "sample.dat",
        "sample.opus",
        "sample.0",
        "sample.0000",
        "0",
    ],
)
def test_scp_testdata_file_type_detection_covers_importable_formats(filename: str) -> None:
    assert is_scp_testdata_file(Path(filename))


@pytest.mark.parametrize(
    "filename",
    [
        "README.md",
        "report.pdf",
        "sample.xlsx",
        "not_a_numeric_opus_name",
        "paradigm_time_series.srsx",
        "microscopy.session",
        "raman.map",
        "raman.mapx",
    ],
)
def test_scp_testdata_file_type_detection_rejects_non_data_files(filename: str) -> None:
    assert not is_scp_testdata_file(Path(filename))


def test_source_preview_file_loader_handles_scientist_axis_column_csv(tmp_path: Path) -> None:
    from spectra_sherpa.app.api.v1.routes.builder import _file_as_sherpa

    csv_path = tmp_path / "raman_conditions.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Condition A,Condition B\n" "200,10,20\n" "201,11,21\n" "202,12,22\n",
        encoding="ascii",
    )

    dataset = _file_as_sherpa(csv_path)

    assert dataset.data_role == "X_spectra"
    assert dataset.X.shape == (2, 3)
    assert dataset.feature_axis is not None
    assert dataset.feature_axis.title == "Wavenumber"
    assert dataset.feature_axis.units == "cm-1"
    np.testing.assert_allclose(dataset.feature_axis.values, np.array([200.0, 201.0, 202.0]))
    assert dataset.sample_axis is not None
    assert dataset.sample_axis.labels == ["Condition A", "Condition B"]


@pytest.mark.parametrize("suffix", [".spa", ".spg", ".srs", ".wdf", ".0"])
def test_source_preview_file_loader_delegates_instrument_formats_to_scp_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    from spectra_sherpa.app.api.v1.routes import builder
    from spectra_sherpa.app.lib.adapters import scp_adapter

    path = tmp_path / f"instrument{suffix}"
    path.write_bytes(b"not parsed by this unit test")
    expected = SherpaDataset(
        np.array([[1.0, 2.0, 3.0]]),
        feature_axis=FeatureAxis(labels=["a", "b", "c"]),
        data_role="X_features",
    )
    calls: list[str] = []

    class FakeService:
        @staticmethod
        def _load_datasets_from_file(payload: dict[str, str]) -> list[object]:
            calls.append(payload["file_path"])
            return [object()]

    monkeypatch.setattr(builder, "ensure_reader_available", lambda _path: None)
    monkeypatch.setattr(builder, "service", FakeService())
    monkeypatch.setattr(scp_adapter, "from_nddataset", lambda _dataset: expected)

    dataset = builder._file_as_sherpa(path)

    assert dataset is expected
    assert calls == [str(path)]
