from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset


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
def test_source_preview_file_loader_delegates_instrument_formats_to_native_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    import spectra_sherpa.io as native_io
    from spectra_sherpa.app.api.v1.routes import builder

    path = tmp_path / f"instrument{suffix}"
    path.write_bytes(b"not parsed by this unit test")
    expected = SherpaDataset(
        np.array([[1.0, 2.0, 3.0]]),
        feature_axis=FeatureAxis(labels=["a", "b", "c"]),
        data_role="X_features",
    )
    calls: list[str] = []

    def fake_ingest(source_path: Path, *, parser_options: object | None = None):
        calls.append(str(source_path))
        assert parser_options is None
        return SimpleNamespace(assets=(SimpleNamespace(dataset=expected),))

    monkeypatch.setattr(builder, "ensure_reader_available", lambda _path: None)
    monkeypatch.setattr(native_io, "ingest", fake_ingest)

    dataset = builder._file_as_sherpa(path)

    assert dataset is expected
    assert calls == [str(path)]


def test_registered_multiasset_reference_previews_its_verified_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import spectra_sherpa.io as native_io
    from spectra_sherpa.app.api.v1.routes import builder
    from spectra_sherpa.app.lib import reference_materialization, registered_reference_storage

    path = tmp_path / "corn.mat"
    path.write_bytes(b"registered multi-asset source")
    expected = SherpaDataset(
        np.array([[1.0, 2.0, 3.0]]),
        feature_axis=FeatureAxis(labels=["a", "b", "c"]),
        data_role="X_features",
    )
    reference = {
        "projection_id": "public-corn-m5-moisture-v1",
        "member_size_bytes": path.stat().st_size,
        "member_sha256": "a" * 64,
    }
    calls: list[str] = []

    def materialize(_path: Path, projection_id: str) -> SimpleNamespace:
        calls.append(projection_id)
        return SimpleNamespace(dataset=expected, portable_reference=reference)

    monkeypatch.setattr(registered_reference_storage, "read_registered_reference_sidecar", lambda _path: reference)
    monkeypatch.setattr(reference_materialization, "materialize_reference_member", materialize)
    monkeypatch.setattr(native_io, "ingest", lambda _path: pytest.fail("must not select an arbitrary MAT asset"))

    inspected = builder._file_as_sherpa(path)
    member = builder._file_as_collection_member(
        path,
        file_name="raw/corn.mat",
        asset_id=None,
        prepared_overrides=None,
    )

    np.testing.assert_array_equal(inspected.X, expected.X)
    np.testing.assert_array_equal(member.dataset.X, expected.X)
    assert member.asset_id == reference["projection_id"]
    assert member.sha256 == reference["member_sha256"]
    assert calls == [reference["projection_id"], reference["projection_id"]]
    with pytest.raises(ValueError, match="requested asset differs"):
        builder._file_as_sherpa(path, asset_id="m5spec")
