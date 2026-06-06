from __future__ import annotations

import numpy as np
import pytest


def test_client_data_formats_disclose_scp_boundary(monkeypatch):
    from spectra_sherpa.app.lib import data_formats

    monkeypatch.setattr(data_formats, "HAS_SCP", False)

    config = data_formats.client_data_formats()

    assert config["hasScp"] is False
    assert ".jdx" in config["acceptedExtensions"]
    assert ".npy" in config["acceptedExtensions"]
    assert ".spa" not in config["acceptedExtensions"]
    assert config["installScpCommand"] == "pip install spectra-sherpa[scp]"
    unavailable = {fmt["name"] for fmt in config["formats"] if not fmt["available"]}
    assert {"OMNIC / OMNICxi spectra", "SPC", "WDF", "OPUS"}.issubset(unavailable)


def test_client_data_formats_disclose_thermo_containers_as_export_required(monkeypatch):
    from spectra_sherpa.app.lib import data_formats

    monkeypatch.setattr(data_formats, "HAS_SCP", True)

    config = data_formats.client_data_formats()

    assert ".srsx" in config["knownUnsupportedExtensions"]
    assert ".mapx" in config["knownUnsupportedExtensions"]
    assert ".srsx" not in config["acceptedExtensions"]
    export_required = {fmt["key"]: fmt for fmt in config["formats"] if fmt.get("requiresExport")}
    assert export_required["thermo_paradigm_timeseries"]["available"] is False
    assert export_required["omnicxi_map"]["available"] is False
    assert ".map" in export_required["omnicxi_map"]["extensions"]
    assert "Export spectra as .spa or .spg" in export_required["omnicxi_map"]["unsupportedReason"]


def test_reader_availability_fails_early_for_scp_formats(monkeypatch):
    from spectra_sherpa.app.lib import data_formats

    def missing(_feature: str) -> None:
        raise ImportError("Install with: pip install spectra-sherpa[scp]")

    monkeypatch.setattr(data_formats, "require_scp", missing)

    with pytest.raises(ImportError, match=r"spectra-sherpa\[scp\]"):
        data_formats.ensure_reader_available("sample.spa")

    data_formats.ensure_reader_available("sample.jdx")
    data_formats.ensure_reader_available("sample.npy")


@pytest.mark.parametrize("filename", ["kinetics.srsx", "image.session", "raman.map", "raman.mapx"])
def test_reader_availability_fails_early_for_known_thermo_containers(filename):
    from spectra_sherpa.app.lib import data_formats

    with pytest.raises(ValueError, match="Export spectra as .spa or .spg"):
        data_formats.ensure_reader_available(filename)


def test_jcamp_loads_as_sherpa_without_scp(tmp_path):
    from spectra_sherpa.app.lib.io import load_open_spectral_file_as_sherpa

    path = tmp_path / "acetone.jdx"
    path.write_text(
        "\n".join(
            [
                "##TITLE=Acetone",
                "##XUNITS=1/CM",
                "##YUNITS=ABSORBANCE",
                "##FIRSTX=1000",
                "##DELTAX=1",
                "##NPOINTS=3",
                "##XYDATA=(X++(Y..Y))",
                "1000 0.1 0.2 0.3",
                "##END=",
            ]
        )
    )

    dataset = load_open_spectral_file_as_sherpa(path)

    assert dataset is not None
    assert dataset.shape == (1, 3)
    assert dataset.title == "Acetone"
    assert dataset.feature_axis.title == "Wavenumber"
    np.testing.assert_allclose(dataset.feature_axis.values, np.array([1000, 1001, 1002], dtype=float))


def test_numpy_arrays_load_as_sherpa(tmp_path):
    from spectra_sherpa.app.lib.io import load_open_spectral_file_as_sherpa

    npy_path = tmp_path / "matrix.npy"
    np.save(npy_path, np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]))

    npy_dataset = load_open_spectral_file_as_sherpa(npy_path)
    assert npy_dataset is not None
    assert npy_dataset.shape == (2, 3)
    assert npy_dataset.data_role == "X_features"

    npz_path = tmp_path / "spectra.npz"
    np.savez(
        npz_path,
        X=np.array([[0.1, 0.2, 0.3]]),
        wavenumber=np.array([900.0, 901.0, 902.0]),
        sample_labels=np.array(["sample a"]),
    )

    npz_dataset = load_open_spectral_file_as_sherpa(npz_path)
    assert npz_dataset is not None
    assert npz_dataset.shape == (1, 3)
    assert npz_dataset.data_role == "X_spectra"
    np.testing.assert_allclose(npz_dataset.feature_axis.values, np.array([900.0, 901.0, 902.0]))
