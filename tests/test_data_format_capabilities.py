from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


def test_client_data_formats_disclose_native_pending_boundary():
    from spectra_sherpa.app.lib import data_formats

    config = data_formats.client_data_formats()

    assert ".jdx" in config["acceptedExtensions"]
    assert ".jcamp" in config["acceptedExtensions"]
    assert ".npy" in config["acceptedExtensions"]
    assert ".opus" in config["acceptedExtensions"]
    assert ".0" in config["acceptedExtensions"]
    assert "numeric-extension" in config["acceptedFilenamePatterns"]
    assert {".spa", ".spg", ".srs"}.issubset(config["acceptedExtensions"])
    assert ".txt" in config["acceptedExtensions"]
    assert ".wdf" in config["acceptedExtensions"]
    assert config["canonicalFileLoadExtensions"] == [
        ".0",
        ".csv",
        ".dat",
        ".dx",
        ".jcamp",
        ".jdx",
        ".json",
        ".mat",
        ".npy",
        ".npz",
        ".opus",
        ".spa",
        ".spc",
        ".spg",
        ".srs",
        ".tsv",
        ".txt",
        ".wdf",
    ]
    assert "hasScp" not in config
    assert "installScpCommand" not in config
    unavailable = {fmt["name"] for fmt in config["formats"] if not fmt["available"]}
    assert "WDF" not in unavailable
    assert "OMNIC / OMNICxi spectra" not in unavailable
    assert "SPC" not in unavailable
    assert "OPUS" not in unavailable


def test_client_data_formats_disclose_thermo_containers_as_export_required():
    from spectra_sherpa.app.lib import data_formats

    config = data_formats.client_data_formats()

    assert ".srsx" in config["knownUnsupportedExtensions"]
    assert ".mapx" in config["knownUnsupportedExtensions"]
    assert ".srsx" not in config["acceptedExtensions"]
    export_required = {fmt["key"]: fmt for fmt in config["formats"] if fmt.get("requiresExport")}
    assert export_required["thermo_paradigm_timeseries"]["available"] is False
    assert export_required["omnicxi_map"]["available"] is False
    assert ".map" in export_required["omnicxi_map"]["extensions"]
    assert "Export spectra as .spa or .spg" in export_required["omnicxi_map"]["unsupportedReason"]


def test_reader_availability_matches_native_and_pending_formats():
    from spectra_sherpa.app.lib import data_formats

    data_formats.ensure_reader_available("sample.spa")
    data_formats.ensure_reader_available("sample.spg")
    data_formats.ensure_reader_available("sample.srs")
    data_formats.ensure_reader_available("sample.jdx")
    data_formats.ensure_reader_available("sample.npy")
    data_formats.ensure_reader_available("sample.opus")
    data_formats.ensure_reader_available("sample.0000")
    data_formats.ensure_reader_available("sample.txt")
    data_formats.ensure_reader_available("sample.wdf")


def test_application_projection_does_not_define_a_second_pending_format_table():
    from spectra_sherpa.app.lib import data_formats

    source = Path(data_formats.__file__).read_text(encoding="utf-8")
    assert "NATIVE_PENDING_FORMATS" not in source
    assert "A qualified native SPC reader" not in source
    assert "pending_format_capabilities" in source


def test_backend_capabilities_are_exact_registry_projection():
    from spectra_sherpa.app.lib import data_formats
    from spectra_sherpa.io import builtin_registry

    config = data_formats.client_data_formats()
    registry = builtin_registry.capability_report()

    assert config["acceptedExtensions"] == registry["acceptedExtensions"]
    assert [item["key"] for item in config["formats"] if item.get("available")] == [
        item["key"] for item in registry["formats"]
    ]


def test_spectral_upload_storage_admits_every_registry_filename() -> None:
    from spectra_sherpa.app.lib.data_formats import client_data_formats
    from spectra_sherpa.app.services.file_storage import validate_ingestion_filename

    for extension in client_data_formats()["acceptedExtensions"]:
        assert validate_ingestion_filename(f"spectrum{extension}") == extension


def test_spectral_upload_storage_uses_registry_pattern_authority(monkeypatch) -> None:
    from spectra_sherpa.app.services import file_storage

    monkeypatch.setattr(
        file_storage.builtin_registry,
        "accepts_filename",
        lambda filename: Path(filename).suffix.lstrip(".").isdigit(),
    )
    assert file_storage.validate_ingestion_filename("spectrum.42") == ".42"
    with pytest.raises(file_storage.FileValidationError, match="Unsupported file type"):
        file_storage.validate_ingestion_filename("spectrum.exe")


def test_retired_settings_extension_list_cannot_override_registry() -> None:
    from spectra_sherpa.app.core.config import Settings
    from spectra_sherpa.app.services import file_storage

    assert not hasattr(Settings, "allowed_extensions")
    source = Path(file_storage.__file__).read_text(encoding="utf-8")
    assert "settings.allowed_extensions" not in source


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["guess.xyz", "guess.exe"])
async def test_unavailable_or_unregistered_upload_is_rejected_before_bytes_are_read(tmp_path, filename: str) -> None:
    from spectra_sherpa.app.services.file_storage import FileValidationError, save_upload_file

    class UnreadUpload:
        def __init__(self) -> None:
            self.filename = filename
            self.closed = False

        async def read(self, _size: int) -> bytes:
            raise AssertionError("rejected filename reached upload byte materialization")

        async def close(self) -> None:
            self.closed = True

    upload = UnreadUpload()
    with pytest.raises(FileValidationError, match="Unsupported file type"):
        await save_upload_file(upload, tmp_path / "destination", max_file_size_mb=1)  # type: ignore[arg-type]
    assert not (tmp_path / "destination").exists()


def test_current_guidance_never_expands_the_three_operation_scp_boundary() -> None:
    package_root = Path(__file__).parents[1]
    export_path = package_root / "src" / "spectra_sherpa" / "app" / "api" / "v1" / "routes" / "workflows" / "export.py"
    sources = [
        package_root / "README.md",
        package_root / "requirements.txt",
        package_root / "src" / "spectra_sherpa" / "app" / "core" / "startup.py",
        export_path,
        *sorted(
            path
            for path in (package_root / "frontend" / "src").rglob("*")
            if path.is_file() and path.suffix in {".ts", ".vue"} and "test" not in path.parts
        ),
        *sorted((package_root / "docs").rglob("*.md")),
    ]
    forbidden = (
        "SpectroChemPy-backed readers",
        "SpectroChemPy-backed vendor formats",
        "optional SpectroChemPy formats",
        "extra adds vendor readers",
        "unlocks SpectroChemPy-backed readers",
        "native .scp/.spg/.omnic file support",
        "SpectroChemPy (.scp)",
        "SPC (.spc)",
        "algorithms and readers enabled by [scp]",
        "optional extras for vendor readers",
        "SpectroChemPy-backed vendor file support",
        "SpectroChemPy-backed vendor readers",
        "plus instrument-file readers",
        "enables vendor/scientific readers",
        "Native Thermo OMNIC and Renishaw WDF readers are pending",
        "Thermo OMNIC (`.spa`, `.spg`, `.srs`) and Renishaw WDF (`.wdf`) do not have",
        "For Thermo OMNIC/OMNICxi or Renishaw WDF sources, export",
        "Native readers for Thermo OMNIC and Renishaw WDF are pending",
        "OMNIC and WDF require export",
        "pending: OMNIC and WDF",
        "Renishaw WDF reader is pending qualification",
        "Renishaw WDF (`.wdf`) does not yet have a qualified native reader",
        "Renishaw WDF and Thermo Paradigm/OMNICxi containers still require export",
        "SCP dataset not found",
        "SpectroChemPy bundled datasets",
        "selected reference datasets, and explicit dataset adaptation",
        "references, and dataset adaptation",
        "references and dataset adaptation",
        "SCP reference catalog",
        "Generate Python code using SpectroChemPy",
        "Import spectrochempy as scp",
        "SpectroChemPy code generation",
        "SpectroChemPy and scikit-learn code",
        "produces SpectrochemPy/scikit-learn code",
        "spectrochempy>=0.8.1,<0.9.0",
        "spectrochempy >=0.8.1,<0.9.0",
        "`>=0.8.1,<0.9.0`",
    )
    for path in sources:
        source = path.read_text(encoding="utf-8")
        normalized_source = " ".join(source.split())
        for claim in forbidden:
            normalized_claim = " ".join(claim.split())
            assert (
                normalized_claim not in normalized_source
            ), f"{path} restores retired SpectroChemPy product authority: {claim}"
    export_source = export_path.read_text(encoding="utf-8")
    assert "client_data_formats" in export_source
    from spectra_sherpa.io import builtin_registry

    omnic = next(item for item in builtin_registry.capability_report()["formats"] if item["key"] == "omnic")
    assert omnic["available"] is True
    assert omnic["extensions"] == [".spa", ".spg", ".srs"]
    wdf = next(item for item in builtin_registry.capability_report()["formats"] if item["key"] == "wdf")
    assert wdf["available"] is True
    assert wdf["extensions"] == [".wdf"]


def test_current_plan_capability_block_matches_live_registry_and_contracts() -> None:
    package_root = Path(__file__).parents[1]
    repository_root = package_root.parents[1]
    plan = (repository_root / "docs" / "plan" / "spectral-format-coverage-and-scp-exit-plan.md").read_text(
        encoding="utf-8"
    )
    start = "<!-- live-ingestion-contract:start -->"
    end = "<!-- live-ingestion-contract:end -->"
    assert plan.count(start) == plan.count(end) == 1
    block = plan.split(start, 1)[1].split(end, 1)[0]
    payload = json.loads(block.split("```json", 1)[1].split("```", 1)[0])

    from spectra_sherpa.app.services.dag import nodes as _nodes  # noqa: F401
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.io import builtin_registry

    nodes = node_registry.list_nodes()
    optional = sorted(item.node_type for item in nodes if item.requires_scp)
    assert payload["registered_operations"] == len(nodes) == 101
    assert payload["base_ready_operations"] == len(nodes) - len(optional) == 98
    assert (
        payload["optional_scp_operations"]
        == optional
        == [
            "model.efa",
            "model.mcr_als",
            "model.simplisma",
        ]
    )
    live_formats = {}
    for item in builtin_registry.capability_report()["formats"]:
        projection = {
            "parser_id": item["parserId"],
            "extensions": sorted(item["extensions"]),
        }
        if item["filenamePatterns"]:
            projection["filename_patterns"] = sorted(item["filenamePatterns"])
        live_formats[item["key"]] = projection
    assert payload["native_formats"] == live_formats
    assert payload["retired_scp_product_authorities"] == [
        "reader fallback",
        "reference catalog",
        "testdata discovery",
        "download",
        "bootstrap",
    ]
    assert not (package_root / "src" / "spectra_sherpa" / "data" / "scp_reference_catalog.json").exists()


def test_frontend_consumes_generated_capability_without_extension_fallback_registry():
    frontend = Path(__file__).parents[1] / "frontend" / "src"
    # FileLoadModal.vue and TemplateWizardModal.vue were removed as dead code:
    # nothing imported or routed them. DataContent.vue is the live upload
    # surface and the only module that reads the generated registry.
    consumers = (frontend / "views" / "data" / "DataContent.vue",)
    for path in consumers:
        source = path.read_text(encoding="utf-8")
        assert "dataFormats" in source
        assert '".csv,.mat,.jdx,.dx,.npy,.npz"' not in source
        assert '".csv",\n      ".jdx"' not in source
    assert not (frontend / "components" / "data" / "SpectraFileUpload.vue").exists()


def test_frontend_distinguishes_upload_size_from_decoded_text_safety_limit():
    frontend = Path(__file__).parents[1] / "frontend" / "src"
    consumers = (frontend / "views" / "data" / "DataContent.vue",)
    for path in consumers:
        source = path.read_text(encoding="utf-8")
        assert "decoded-data safety limit" in source
        assert "use NPY/NPZ for large numeric matrices" in source


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
