from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from numpy.lib import format as npformat

from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.core.axis_semantics import AxisQuantity
from spectra_sherpa.io import (
    AmbiguousFormatError,
    FormatIdentityError,
    FormatUnavailableError,
    IngestionResult,
    ParserLimitError,
    ParserLimits,
    ProbeConfidence,
    ProbeResult,
    UnreadableSpectrumError,
    UnsupportedFormatError,
    builtin_registry,
    ingest,
)
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._text_limits import (
    require_csv_working_set,
    require_jcamp_working_set,
)
from spectra_sherpa.io.formats.csv import PLUGIN as CSV_PLUGIN
from spectra_sherpa.io.invariants import INGESTION_AUTHORITY_SCHEMA, INGESTION_INVARIANTS
from spectra_sherpa.io.registry import FormatRegistry
from spectra_sherpa.io.types import SpectralAsset

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "formats"


def _protected_symbol_references(source: str, protected: set[str]) -> set[str]:
    """Resolve direct, imported-alias, and module-qualified parser references."""
    tree = ast.parse(source)
    imported_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for imported in node.names:
            if imported.name in protected:
                imported_aliases[imported.asname or imported.name] = imported.name

    references: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in protected:
            references.add(node.attr)
        elif isinstance(node, ast.Name):
            if node.id in protected:
                references.add(node.id)
            elif node.id in imported_aliases:
                references.add(imported_aliases[node.id])
    return references


def _manifest() -> dict:
    return json.loads((FIXTURE_ROOT / "manifest.json").read_text())


def _materialize(entry: dict, tmp_path: Path) -> Path:
    retained = FIXTURE_ROOT / entry["path"]
    if entry["encoding"] == "identity":
        payload = retained.read_bytes()
        suffix = retained.suffix
    elif entry["encoding"] == "base64":
        payload = base64.b64decode(retained.read_text().strip(), validate=True)
        suffix = retained.name.removesuffix(".b64").split(".", 1)[-1]
        suffix = f".{suffix}"
    else:
        raise AssertionError(f"unknown fixture encoding {entry['encoding']}")
    assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
    path = tmp_path / f"{entry['fixture_id']}{suffix}"
    path.write_bytes(payload)
    return path


@pytest.mark.parametrize("entry", _manifest()["fixtures"], ids=lambda item: item["fixture_id"])
def test_manifested_native_fixture_matches_declared_science(entry: dict, tmp_path: Path):
    path = _materialize(entry, tmp_path)

    result = ingest(path)

    assert result.format_id == entry["format_id"]
    assert result.variant == entry["variant"]
    assert dict(result.raw_metadata) == entry["expected_result_metadata"]
    assert [asset.asset_id for asset in result.assets] == [item["asset_id"] for item in entry["expected_assets"]]
    expected_missing_assets = {
        item["asset_id"] for item in entry["expected_assets"] if np.any(np.asarray(item["missing"], dtype=bool))
    }
    missingness_warnings = [warning for warning in result.warnings if warning.startswith("Missing data preserved:")]
    assert len(missingness_warnings) == len(expected_missing_assets)
    for asset_id in expected_missing_assets:
        assert any(f"asset {asset_id!r}" in warning for warning in missingness_warnings)
    for asset, expected in zip(result.assets, entry["expected_assets"], strict=True):
        dataset = asset.dataset
        assert list(dataset.shape) == expected["shape"]
        assert asset.dimension_roles[0] == "sample"
        actual = np.asarray(dataset.X, dtype=float)
        missing = np.asarray(expected["missing"], dtype=bool)
        assert np.array_equal(np.isnan(actual), missing)
        np.testing.assert_allclose(actual[~missing], np.asarray(expected["values"], dtype=float)[~missing])
        axis = dataset.feature_axis
        actual_axis = None if axis is None or axis.values is None else np.asarray(axis.values, dtype=float)
        if expected["feature_axis"] is None:
            assert actual_axis is None
        else:
            np.testing.assert_allclose(actual_axis, np.asarray(expected["feature_axis"], dtype=float))
        assert (None if axis is None else axis.units) == expected["feature_axis_units"]
        if entry["format_id"] == "jcamp-dx":
            assert axis is not None
            expected_quantity = (
                AxisQuantity.RAMAN_SHIFT
                if expected["raw_metadata"]["data_type"] == "RAMAN SPECTRUM"
                else AxisQuantity.WAVENUMBER
            )
            assert axis.quantity is expected_quantity
            assert axis.display_units == "1/CM"
            assert dataset.domain.expected_units == "cm-1"
        assert (None if axis is None else axis.labels) == expected["feature_labels"]
        assert (None if dataset.sample_axis is None else dataset.sample_axis.labels) == expected["sample_labels"]
        for key, value in expected["raw_metadata"].items():
            assert asset.raw_metadata[key] == value
        authority = dataset.get_extra("ingestion.authority")
        assert authority == {
            "schema": INGESTION_AUTHORITY_SCHEMA,
            "format_id": result.format_id,
            "variant": result.variant,
            "parser_id": result.parser_id,
            "parser_version": result.parser_version,
            "asset_id": asset.asset_id,
            "source_members": [
                {
                    "name": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size_bytes": path.stat().st_size,
                }
            ],
            "warnings": list(dict.fromkeys((*result.warnings, *asset.warnings))),
            "invariants": [invariant.value for invariant in INGESTION_INVARIANTS],
        }
        restored = type(dataset).from_dict(dataset.to_dict())
        assert restored.get_extra("ingestion.authority") == authority
        assert str(tmp_path) not in json.dumps(dataset.to_dict(), default=str)


def test_missing_source_error_never_discloses_parent_path(tmp_path: Path):
    source = tmp_path / "private-storage" / "missing.csv"

    with pytest.raises(UnreadableSpectrumError) as raised:
        ingest(source)

    message = str(raised.value)
    assert source.name in message
    assert str(source.parent) not in message


def test_delegated_parser_oserror_never_discloses_snapshot_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from spectra_sherpa.app.lib import io as app_io

    source = tmp_path / "private-storage" / "spectrum.csv"
    source.parent.mkdir()
    source.write_text("sample,1000,1001\nA,1,2\n", encoding="utf-8")
    observed_snapshot: list[Path] = []

    def _fail(snapshot_path: Path, **_kwargs: object) -> None:
        observed_snapshot.append(Path(snapshot_path))
        raise OSError(5, "synthetic delegated reader failure", str(snapshot_path))

    monkeypatch.setattr(app_io, "parse_csv_snapshot_as_sherpa", _fail)
    with pytest.raises(UnreadableSpectrumError) as raised:
        ingest(source)

    assert observed_snapshot
    message = str(raised.value)
    assert source.name in message
    assert str(source.parent) not in message
    assert str(observed_snapshot[0].parent) not in message


def test_ingestion_missingness_warning_is_one_based_and_bounded(tmp_path: Path):
    source = tmp_path / "many-missing-rows.npy"
    matrix = np.ones((15, 2), dtype=np.float64)
    matrix[:, 0] = np.nan
    np.save(source, matrix)

    result = ingest(source)

    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert "15 missing or non-finite values" in warning
    assert "sample row(s) 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, and 3 more" in warning
    assert "does not impute values implicitly" in warning


def test_native_csv_supplier_profile_preserves_missing_signal_with_visible_warning(tmp_path: Path):
    source = tmp_path / "supplier-export.csv"
    source.write_text("400.0,#NaN\n401.0,0.20\n402.0,0.30\n", encoding="ascii")

    result = ingest(source, parser_options={"csv_layout": "headerless_two_column_spectrum"})

    assert np.isnan(result.assets[0].dataset.X[0, 0])
    assert result.raw_metadata == {}
    assert len(result.warnings) == 1
    assert "Missing data preserved" in result.warnings[0]
    assert "does not impute values implicitly" in result.warnings[0]


def test_fixture_manifest_is_closed_complete_and_digest_bound():
    manifest = _manifest()
    assert set(manifest) == {"schema_version", "fixtures"}
    assert manifest["schema_version"] == "spectrasherpa-format-fixture-manifest/2"
    required = {
        "fixture_id",
        "format_id",
        "path",
        "encoding",
        "source",
        "verification",
        "sha256",
        "variant",
        "expected_result_metadata",
        "expected_assets",
    }
    format_ids = [entry["format_id"] for entry in manifest["fixtures"]]
    assert set(format_ids) == {"csv", "jcamp-dx", "numpy", "matlab"}
    assert {format_id: format_ids.count(format_id) for format_id in set(format_ids)} == {
        "csv": 3,
        "jcamp-dx": 3,
        "numpy": 3,
        "matlab": 3,
    }
    assert len({entry["fixture_id"] for entry in manifest["fixtures"]}) == len(manifest["fixtures"])
    for entry in manifest["fixtures"]:
        assert set(entry) == required
        assert (FIXTURE_ROOT / entry["path"]).is_file()
        assert len(entry["sha256"]) == 64
        assert entry["source"] and entry["verification"]
        assert entry["expected_assets"]


def test_registry_is_deterministic_and_capability_report_is_derived():
    assert [plugin.format_id for plugin in builtin_registry.plugins] == sorted(
        plugin.format_id for plugin in builtin_registry.plugins
    )
    report = builtin_registry.capability_report()
    assert {item["key"] for item in report["formats"]} == {plugin.format_id for plugin in builtin_registry.plugins}
    assert ".csv" in report["acceptedExtensions"]
    assert {".spa", ".spg", ".srs"}.issubset(report["acceptedExtensions"])
    assert all("requiresScp" not in item and "temporary" not in item for item in report["formats"])


@dataclass(frozen=True)
class _ClaimingPlugin:
    format_id: str
    display_name: str
    description: str = "test"
    extensions: tuple[str, ...] = (".x",)
    parser_id: str = ""
    parser_version: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "parser_id", f"test.{self.format_id}")

    def probe(self, source: BoundedSource) -> ProbeResult:
        return ProbeResult(self.format_id, "test", ProbeConfidence.EXACT, ("test structural claim",), 1)

    def read(self, source: BoundedSource, *, limits: ParserLimits) -> IngestionResult:
        del source, limits
        raise AssertionError("ambiguous registry must not call a parser")


def test_equal_strong_structural_claims_fail_ambiguous_before_read(tmp_path: Path):
    path = tmp_path / "ambiguous.x"
    path.write_bytes(b"x")
    registry = FormatRegistry((_ClaimingPlugin("one", "One"), _ClaimingPlugin("two", "Two")))

    with pytest.raises(AmbiguousFormatError, match="one, two"):
        registry.ingest(path)


class _ContradictoryRolePlugin:
    format_id = "contradictory-role"
    display_name = "Contradictory role"
    description = "test-only malformed parser"
    extensions = (".role",)
    parser_id = "test.contradictory-role"
    parser_version = "1"

    def probe(self, source: BoundedSource) -> ProbeResult:
        return ProbeResult(self.format_id, "test", ProbeConfidence.EXACT, ("test structural claim",), 1)

    def read(self, source: BoundedSource, *, limits: ParserLimits) -> IngestionResult:
        del limits
        dataset = SherpaDataset(
            np.ones((2, 3), dtype=np.float64),
            feature_axis=SpectralAxis(values=np.asarray([1000.0, 1001.0, 1002.0]), units="cm-1"),
            data_role="X_features",
        )
        return IngestionResult(
            format_id=self.format_id,
            variant="test",
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            source_members=(source.member(),),
            assets=(
                SpectralAsset(
                    asset_id="contradiction",
                    dataset=dataset,
                    dimension_roles=("sample", "spectral_feature"),
                ),
            ),
        )


def test_ingestion_invariants_refuse_parser_role_contradiction(tmp_path: Path) -> None:
    path = tmp_path / "contradiction.role"
    path.write_bytes(b"x")

    with pytest.raises(FormatIdentityError, match="invariant 'data_role'.*contradicts"):
        FormatRegistry((_ContradictoryRolePlugin(),)).ingest(path)


def test_bounded_source_rejects_corrupt_offset_before_read(tmp_path: Path):
    path = tmp_path / "tiny.bin"
    path.write_bytes(b"1234")
    source = BoundedSource(path, limits=ParserLimits())

    with pytest.raises(UnreadableSpectrumError, match="byte offset 3"):
        source.read_at(3, 2, format_id="fixture")


def test_npy_declared_array_limit_fails_before_payload_allocation(tmp_path: Path):
    stream = io.BytesIO()
    npformat.write_array_header_1_0(stream, {"descr": "<f8", "fortran_order": False, "shape": (1000, 1000)})
    path = tmp_path / "oversized.npy"
    path.write_bytes(stream.getvalue())

    with pytest.raises(ParserLimitError, match="1000000 decoded elements"):
        ingest(path, limits=ParserLimits(max_decoded_elements=100))


def test_npz_aggregate_declared_array_limit_fails_before_payload_load(tmp_path: Path):
    path = tmp_path / "aggregate-limit.npz"
    np.savez(
        path,
        X=np.arange(6, dtype=np.float64).reshape(2, 3),
        C=np.arange(6, dtype=np.float64).reshape(2, 3),
    )

    with pytest.raises(ParserLimitError, match="12 decoded elements"):
        ingest(path, limits=ParserLimits(max_decoded_elements=10))


def test_matlab_declared_shape_limit_fails_before_workspace_load(monkeypatch, tmp_path: Path):
    import spectra_sherpa.io.formats.matlab as matlab_format

    path = tmp_path / "declared-large.mat"
    path.write_bytes(b"MATLAB 5.0 MAT-file" + b" " * 128)
    load_called = False

    monkeypatch.setattr(matlab_format, "whosmat", lambda _path: [("X", (100, 100), "double")])

    def _unexpected_load(*_args, **_kwargs):
        nonlocal load_called
        load_called = True
        raise AssertionError("loadmat must not run after the declared shape exceeds the limit")

    monkeypatch.setattr(matlab_format, "loadmat", _unexpected_load)

    with pytest.raises(ParserLimitError, match="10000 decoded elements"):
        ingest(path, limits=ParserLimits(max_decoded_elements=100))
    assert load_called is False


def test_compressed_wide_numpy_dtype_hits_decoded_byte_limit_before_np_load(monkeypatch, tmp_path: Path):
    import spectra_sherpa.io.formats.numpy as numpy_format

    path = tmp_path / "wide-metadata.npz"
    np.savez_compressed(path, X=np.ones((1, 1)), sample_labels=np.asarray(["x"], dtype="U100000"))
    load_called = False

    def _unexpected_load(*_args, **_kwargs):
        nonlocal load_called
        load_called = True
        raise AssertionError("np.load must not run after decoded-byte admission fails")

    monkeypatch.setattr(numpy_format.np, "load", _unexpected_load)
    with pytest.raises(ParserLimitError, match="decoded bytes"):
        ingest(path, limits=ParserLimits(max_decoded_bytes=1024))
    assert load_called is False


def test_compressed_complex_matlab_hits_decoded_byte_limit_before_loadmat(monkeypatch, tmp_path: Path):
    from scipy.io import savemat

    import spectra_sherpa.io.formats.matlab as matlab_format

    path = tmp_path / "compressed-complex.mat"
    savemat(path, {"spectra": np.ones((10, 10), dtype=np.complex128)}, do_compression=True)
    load_called = False

    def _unexpected_load(*_args, **_kwargs):
        nonlocal load_called
        load_called = True
        raise AssertionError("loadmat must not run after decoded-byte admission fails")

    monkeypatch.setattr(matlab_format, "loadmat", _unexpected_load)
    with pytest.raises(ParserLimitError, match="decoded bytes"):
        ingest(path, limits=ParserLimits(max_decoded_bytes=1024))
    assert load_called is False


def test_numpy_rejects_unapproved_non_numeric_payload_before_np_load(monkeypatch, tmp_path: Path):
    import spectra_sherpa.io.formats.numpy as numpy_format

    path = tmp_path / "unapproved-text.npz"
    np.savez_compressed(path, X=np.ones((1, 1)), executable=np.asarray(["not science"]))
    load_called = False

    def _unexpected_load(*_args, **_kwargs):
        nonlocal load_called
        load_called = True
        raise AssertionError("np.load must not run for unsupported dtype")

    monkeypatch.setattr(numpy_format.np, "load", _unexpected_load)
    with pytest.raises(UnreadableSpectrumError, match="unsupported dtype"):
        ingest(path)
    assert load_called is False


def test_truncated_npy_fails_without_partial_result(tmp_path: Path):
    stream = io.BytesIO()
    np.save(stream, np.arange(20, dtype=np.float64), allow_pickle=False)
    path = tmp_path / "truncated.npy"
    path.write_bytes(stream.getvalue()[:-8])

    with pytest.raises(UnreadableSpectrumError, match="failed to read|EOF|expected|cannot reshape"):
        ingest(path)


def test_npz_never_silently_selects_one_of_multiple_numeric_assets(tmp_path: Path):
    path = tmp_path / "multiple-assets.npz"
    np.savez(
        path,
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        second_matrix=np.arange(8, dtype=np.float64).reshape(2, 4),
    )

    with pytest.raises(UnreadableSpectrumError, match="additional numeric assets.*second_matrix"):
        ingest(path)


def test_npz_declares_known_synthesis_auxiliary_arrays_without_selecting_them(tmp_path: Path):
    path = tmp_path / "synthesis.npz"
    np.savez(
        path,
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        C=np.arange(6, dtype=np.float64).reshape(3, 2),
        S=np.arange(8, dtype=np.float64).reshape(2, 4),
    )

    result = ingest(path)

    assert len(result.assets) == 1
    assert result.raw_metadata["numpy.auxiliary_arrays"] == ["C", "S"]


def test_matlab_returns_every_numeric_data_asset_with_named_primary_first(tmp_path: Path):
    from scipy.io import savemat

    path = tmp_path / "multiple-assets.mat"
    savemat(
        path,
        {
            "spectra": np.arange(12, dtype=np.float64).reshape(3, 4),
            "auxiliary": np.arange(8, dtype=np.float64).reshape(2, 4),
        },
    )

    result = ingest(path)

    assert [asset.asset_id for asset in result.assets] == ["spectra", "auxiliary"]
    assert [asset.dataset.shape for asset in result.assets] == [(3, 4), (2, 4)]
    first_authority = result.assets[0].dataset.get_extra("ingestion.authority")
    second_authority = result.assets[1].dataset.get_extra("ingestion.authority")
    assert first_authority["source_members"] == second_authority["source_members"]
    assert first_authority["source_members"] is not second_authority["source_members"]
    first_authority["source_members"][0]["name"] = "locally-annotated.mat"
    assert second_authority["source_members"][0]["name"] == path.name


def test_native_registry_and_open_reads_do_not_import_scp():
    code = """
import sys
from pathlib import Path
from spectra_sherpa.io import ingest
path = Path(sys.argv[1])
result = ingest(path)
assert result.assets[0].dataset.shape == (2, 3)
for name in sys.modules:
    assert not name.startswith('spectrochempy'), name
assert 'spectra_sherpa.app.lib.scp_compat' not in sys.modules
assert 'spectra_sherpa.app.lib.adapters.scp_adapter' not in sys.modules
"""
    fixture = FIXTURE_ROOT / "csv" / "simple-spectrum.csv"
    env = dict(os.environ)
    source_root = Path(__file__).parents[1] / "src"
    env["PYTHONPATH"] = str(source_root)
    completed = subprocess.run(
        [sys.executable, "-c", code, str(fixture)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_headerless_two_column_csv_is_one_spectrum_with_declared_axis(tmp_path: Path):
    path = tmp_path / "axis-intensity.csv"
    path.write_text("400,-0.1\n401,3.5\n402,5.25\n", encoding="utf-8")

    result = ingest(path, parser_options={"csv_layout": "headerless_two_column_spectrum"})
    dataset = result.assets[0].dataset

    assert result.variant == "delimited-text"
    assert dataset.shape == (1, 3)
    np.testing.assert_array_equal(dataset.X, [[-0.1, 3.5, 5.25]])
    np.testing.assert_array_equal(dataset.feature_axis.values, [400.0, 401.0, 402.0])
    assert dataset.extra["csv.layout"] == "headerless_two_column_spectrum"


def test_headerless_decimal_comma_csv_profile_is_explicit_and_exact(tmp_path: Path):
    path = tmp_path / "axis-intensity.csv"
    path.write_text("400,0;-0,1\n401,0;3,5\n402,0;5,25\n", encoding="utf-8")

    result = ingest(
        path,
        parser_options={"csv_layout": "headerless_two_column_spectrum_decimal_comma"},
    )
    dataset = result.assets[0].dataset

    np.testing.assert_array_equal(dataset.X, [[-0.1, 3.5, 5.25]])
    np.testing.assert_array_equal(dataset.feature_axis.values, [400.0, 401.0, 402.0])
    assert dataset.extra["csv.profile"] == "headerless_two_column_spectrum_decimal_comma"
    assert dataset.extra["csv.delimiter"] == ";"
    assert dataset.extra["csv.decimal"] == ","


def test_ambiguous_two_column_csv_requires_explicit_layout(tmp_path: Path):
    path = tmp_path / "ambiguous.csv"
    path.write_text("100,200\n90,1\n80,2\n70,3\n", encoding="utf-8")

    with pytest.raises(AmbiguousFormatError, match="bind csv_layout explicitly"):
        ingest(path)

    headered = ingest(path, parser_options={"csv_layout": "headered"}).assets[0].dataset
    assert headered.shape == (3, 2)
    np.testing.assert_array_equal(headered.feature_axis.values, [100.0, 200.0])


def test_duplicate_numeric_csv_headers_remain_exact_generic_feature_labels(tmp_path: Path):
    path = tmp_path / "repeated-features.csv"
    path.write_text("100,200,100,200\n1,2,3,4\n5,6,7,8\n", encoding="utf-8")

    dataset = ingest(path).assets[0].dataset

    assert dataset.data_role == "X_features"
    assert dataset.feature_axis.values is None
    assert dataset.feature_axis.labels == ["100", "200", "100", "200"]
    np.testing.assert_array_equal(dataset.X, [[1, 2, 3, 4], [5, 6, 7, 8]])


@pytest.mark.parametrize("headers", ["100,100,200", "300,200,300"])
def test_all_duplicate_numeric_headers_are_read_from_declared_bytes(tmp_path: Path, headers: str):
    path = tmp_path / "duplicate-headers.csv"
    path.write_text(f"{headers}\n1,2,3\n4,5,6\n", encoding="utf-8")

    dataset = ingest(path).assets[0].dataset

    assert dataset.data_role == "X_features"
    assert dataset.feature_axis.values is None
    assert dataset.feature_axis.labels == headers.split(",")


def test_text_parser_working_set_projection_rejects_global_maxima() -> None:
    limits = ParserLimits()
    with pytest.raises(ParserLimitError, match="projected text-parser working set"):
        require_csv_working_set(
            source_bytes=limits.max_source_bytes,
            cell_count=limits.max_decoded_elements,
            limits=limits,
            format_id="csv",
        )
    with pytest.raises(ParserLimitError, match="projected text-parser working set"):
        require_jcamp_working_set(
            source_bytes=limits.max_source_bytes,
            point_count=limits.max_decoded_elements,
            limits=limits,
            format_id="jcamp-dx",
        )


def test_csv_working_set_admits_measured_2000_by_1500_envelope() -> None:
    projected = require_csv_working_set(
        source_bytes=27_007_500,
        cell_count=3_001_500,
        limits=ParserLimits(),
        format_id="csv",
    )

    assert projected < 512 * 1024 * 1024


def test_realistic_1000_by_1500_csv_executes_through_registry(tmp_path: Path) -> None:
    columns = 1500
    path = tmp_path / "realistic-nir.csv"
    header = ",".join(str(4000 - index) for index in range(columns)) + "\n"
    row = ",".join(["0.123456"] * columns) + "\n"
    with path.open("w", encoding="utf-8") as stream:
        stream.write(header)
        for _ in range(1000):
            stream.write(row)

    dataset = ingest(path, parser_options={"csv_layout": "headered"}).assets[0].dataset

    assert dataset.shape == (1000, 1500)
    assert dataset.X[0, 0] == pytest.approx(0.123456)
    assert dataset.X[-1, -1] == pytest.approx(0.123456)


def test_csv_working_set_error_gives_scientist_remediation() -> None:
    with pytest.raises(ParserLimitError, match="Split the CSV.*NPY/NPZ"):
        require_csv_working_set(
            source_bytes=ParserLimits().max_source_bytes,
            cell_count=ParserLimits().max_decoded_elements,
            limits=ParserLimits(),
            format_id="csv",
        )


def test_text_parser_working_set_rejects_before_parser_materialization(monkeypatch, tmp_path: Path):
    import spectra_sherpa.io.formats.csv as csv_format

    path = tmp_path / "bounded.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    called = False

    def _unexpected_parser(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("dataframe parser must not run after working-set admission fails")

    monkeypatch.setattr(
        csv_format, "require_csv_working_set", lambda **_kwargs: (_ for _ in ()).throw(ParserLimitError("budget"))
    )
    monkeypatch.setattr("spectra_sherpa.app.lib.io.parse_csv_snapshot_as_sherpa", _unexpected_parser)
    with pytest.raises(ParserLimitError, match="budget"):
        ingest(path)
    assert called is False


def test_dense_jcamp_line_is_rejected_before_packed_token_expansion(monkeypatch, tmp_path: Path):
    import spectra_sherpa.app.lib.jcamp_reader as reader

    path = tmp_path / "dense.jdx"
    path.write_text(
        "##TITLE=Dense\n##XYDATA=(X++(Y..Y))\n0 " + "A" * 250_000 + "\n##END=\n",
        encoding="utf-8",
    )
    expanded = False

    def _unexpected_expand(*_args, **_kwargs):
        nonlocal expanded
        expanded = True
        raise AssertionError("oversized line must fail before packed-token expansion")

    monkeypatch.setattr(reader, "_expand_packed_parts", _unexpected_expand)
    with pytest.raises(ParserLimitError, match="data line.*limit"):
        ingest(path)
    assert expanded is False


def test_text_limit_authority_is_bound_into_native_contract_closures() -> None:
    from spectra_sherpa.io.registry import jcamp_implementation_modules, native_implementation_modules

    assert "spectra_sherpa.io.formats._text_limits" in {module.__name__ for module in native_implementation_modules()}
    assert "spectra_sherpa.io.formats.dso" in {module.__name__ for module in native_implementation_modules()}
    assert "spectra_sherpa.io.formats.matlab_v73" in {module.__name__ for module in native_implementation_modules()}
    assert "spectra_sherpa.io.formats._text_limits" in {module.__name__ for module in jcamp_implementation_modules()}


def _first_party_runtime_imports(module_names: set[str]) -> set[str]:
    """Project imports that can execute, excluding typing-only declarations."""

    source_root = Path(__file__).resolve().parents[1] / "src"

    def module_path(name: str) -> Path | None:
        parts = name.split(".")
        module_file = source_root.joinpath(*parts).with_suffix(".py")
        if module_file.is_file():
            return module_file
        package_file = source_root.joinpath(*parts, "__init__.py")
        return package_file if package_file.is_file() else None

    def nodes_outside_type_checking(nodes):
        for node in nodes:
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                yield from nodes_outside_type_checking(node.orelse)
                continue
            yield node
            # Function-local imports are conditional call-path dependencies.
            # Native reader adapters are asserted explicitly below;
            # application-only branches must not inflate parser identity.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for field in ("body", "orelse", "finalbody"):
                children = getattr(node, field, None)
                if isinstance(children, list):
                    yield from nodes_outside_type_checking(children)

    imported: set[str] = set()
    for module_name in module_names:
        path = module_path(module_name)
        assert path is not None, f"implementation module {module_name!r} has no in-tree source"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in nodes_outside_type_checking(tree.body):
            if isinstance(node, ast.Import):
                imported.update(
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("spectra_sherpa") and module_path(alias.name) is not None
                )
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("spectra_sherpa"):
                for alias in node.names:
                    candidate = f"{node.module}.{alias.name}"
                    imported.add(candidate if module_path(candidate) is not None else node.module)
    return imported


def test_native_implementation_authority_is_transitively_closed() -> None:
    """A new first-party reader dependency must enter the digest authority."""

    from spectra_sherpa.io.registry import native_implementation_modules

    declared = {module.__name__ for module in native_implementation_modules()}
    # The registry module owns and returns this closure; callers bind it as the
    # root component immediately before the returned dependencies.
    assert _first_party_runtime_imports(declared) <= declared | {"spectra_sherpa.io.registry"}
    assert {
        "spectra_sherpa.app.lib.io",  # CSV projection adapter
        "spectra_sherpa.app.lib.synthetic_npz",  # signed synthetic NPZ branch
        "spectra_sherpa.io.formats.matlab_v73",  # MATLAB v7.3 branch
    } <= declared


def test_csv_plugin_rejects_binary_contradiction(tmp_path: Path):
    path = tmp_path / "not-csv.csv"
    path.write_bytes(b"a,b\x00c")
    source = BoundedSource(path, limits=ParserLimits())
    assert CSV_PLUGIN.probe(source).confidence is ProbeConfidence.NO_MATCH


def test_canonical_loader_cannot_bypass_frozen_registry(monkeypatch, tmp_path: Path):
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

    path = tmp_path / "spectrum.csv"
    path.write_text("sample,1000,1001\nA,1,2\n", encoding="utf-8")

    def _blocked(*_args, **_kwargs):
        raise RuntimeError("registry authority reached")

    monkeypatch.setattr(builtin_registry, "ingest", _blocked)
    with pytest.raises(RuntimeError, match="registry authority reached"):
        load_canonical_file_as_sherpa(path)


def test_generic_csv_target_selection_is_a_leakage_safe_projection_of_one_registry_result(tmp_path: Path):
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

    path = tmp_path / "features.csv"
    path.write_text("sample,target,feature_a,feature_b\na,10,1,2\nb,20,3,4\n", encoding="utf-8")

    parsed = ingest(path).assets[0].dataset
    assert parsed.target is None
    assert parsed.feature_axis.labels == ["target", "feature_a", "feature_b"]
    np.testing.assert_array_equal(parsed.X, [[10, 1, 2], [20, 3, 4]])

    selected = load_canonical_file_as_sherpa(path, selected_target="target", target_type="continuous")
    np.testing.assert_array_equal(selected.X, [[1, 2], [3, 4]])
    np.testing.assert_array_equal(selected.target, [10, 20])
    assert selected.feature_axis.labels == ["feature_a", "feature_b"]
    assert selected.target_context.selected_target == "target"


def test_csv_registry_parse_is_independent_of_application_prepared_overrides(monkeypatch, tmp_path: Path):
    from spectra_sherpa.app.services import prepared_data
    from spectra_sherpa.core.prepared_data import PreparedDataOverrides

    path = tmp_path / "prepared.csv"
    path.write_text("sample,target,feature\na,10,1\nb,20,2\n", encoding="utf-8")
    monkeypatch.setattr(
        prepared_data,
        "load_prepared_data_overrides",
        lambda **_kwargs: PreparedDataOverrides(
            target_column="target",
            selected_target="target",
            target_type="continuous",
            target_mode="single",
        ),
    )

    parsed = ingest(path).assets[0].dataset

    assert parsed.target is None
    assert parsed.feature_axis.labels == ["target", "feature"]
    np.testing.assert_array_equal(parsed.X, [[10, 1], [20, 2]])


def test_signed_synthetic_npz_has_identical_science_through_every_production_projection():
    from spectra_sherpa.app.api.v1.routes.builder import _file_as_sherpa
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa
    from spectra_sherpa.app.services.dag.nodes.data.loaders import _load_registry_asset

    path = Path(__file__).parents[1] / "src" / "spectra_sherpa" / "data" / "synthetic" / "Synthetic_atmospheric-6.npz"
    registry_dataset = ingest(path).assets[0].dataset
    projections = (
        load_canonical_file_as_sherpa(path),
        _file_as_sherpa(path),
        _load_registry_asset(path).dataset,
    )
    for projected in projections:
        assert projected.get_extra("ingestion.authority") == registry_dataset.get_extra("ingestion.authority")
        np.testing.assert_array_equal(projected.X, registry_dataset.X)
        np.testing.assert_array_equal(projected.target, registry_dataset.target)
        assert projected.target_context == registry_dataset.target_context
        np.testing.assert_array_equal(
            projected.get_extra("ground_truth.spectra"),
            registry_dataset.get_extra("ground_truth.spectra"),
        )
        spectra = projected.get_extra("ground_truth.spectra")
        spectra_axis = projected.get_extra("ground_truth.spectra_x")
        assert isinstance(spectra, np.ndarray)
        assert isinstance(spectra_axis, np.ndarray)
        assert projected.get_extra("synthetic.S") is None
        assert projected.get_extra("synthetic.C") is None


def test_signed_synthetic_npz_preserves_ftir_technique_at_native_ingestion() -> None:
    path = Path(__file__).parents[1] / "src" / "spectra_sherpa" / "data" / "synthetic" / "Synthetic_atmospheric-6.npz"

    dataset = ingest(path).assets[0].dataset

    assert dataset.domain.technique == "FTIR"
    assert dataset.domain.data_quantity == "Absorbance"


def test_large_synthetic_workflow_result_uses_handle_and_bounded_preview(monkeypatch):
    import json

    from spectra_sherpa.app.services import serialization
    from spectra_sherpa.app.services.dag import serialize as dag_serialize

    path = Path(__file__).parents[1] / "src" / "spectra_sherpa" / "data" / "synthetic" / "Synthetic_atmospheric-6.npz"
    dataset = ingest(path).assets[0].dataset

    class NoListArray(np.ndarray):
        def tolist(self):
            raise AssertionError("oversized metadata array reached tolist")

    sentinel = np.arange(64, dtype=np.float64).view(NoListArray)
    dataset.set_extra("test.oversized_array", sentinel)
    monkeypatch.setattr(dag_serialize, "API_DATASET_FULL_PAYLOAD_MAX_NUMERIC_ELEMENTS", 100)
    monkeypatch.setattr(dag_serialize, "API_DATASET_PREVIEW_MAX_NUMERIC_ELEMENTS", 256)
    monkeypatch.setattr(dag_serialize, "API_DATASET_PREVIEW_CORE_MAX_NUMERIC_ELEMENTS", 16)
    monkeypatch.setattr(dag_serialize, "API_DATASET_PREVIEW_TARGET_MAX_NUMERIC_ELEMENTS", 8)
    monkeypatch.setattr(dag_serialize, "API_METADATA_ARRAY_MAX_NUMERIC_ELEMENTS", 16)
    monkeypatch.setattr(dag_serialize, "API_METADATA_AGGREGATE_MAX_NUMERIC_ELEMENTS", 16)
    monkeypatch.setattr(
        dataset,
        "to_dict",
        lambda: pytest.fail("oversized dataset reached full to_dict serialization"),
    )
    monkeypatch.setattr(
        serialization,
        "_register_application_dataset",
        lambda value, owner_user_id, project_id=None: value.dataset_id,
    )

    payload = serialization.serialize_result(dataset, owner_user_id=7)

    assert payload["dataset_id"] == dataset.dataset_id
    assert payload["shape"] == list(dataset.shape)
    assert np.asarray(payload["data"]).size <= 16
    assert payload["metadata"]["data_truncated"] is True
    assert payload["metadata"]["api_serialization"] == {
        "mode": "bounded_preview",
        "full_payload_numeric_element_ceiling": 100,
        "preview_numeric_element_ceiling": 256,
        "metadata_array_numeric_element_ceiling": 16,
        "metadata_aggregate_numeric_element_ceiling": 16,
        "full_dataset_handle": dataset.dataset_id,
        "full_dataset_handle_unavailable_reason": None,
    }
    assert payload["extra"]["test.oversized_array"] == {
        "_truncated_array": True,
        "shape": "64",
        "dtype": "float64",
        "reason": "api_aggregate_numeric_ceiling",
    }
    assert payload["extra"]["ground_truth.spectra"]["_truncated_array"] is True
    json.dumps(payload)


def test_small_dataset_still_bounds_large_metadata_before_json_boxing(monkeypatch):
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import serialization
    from spectra_sherpa.app.services.dag import serialize as dag_serialize

    class NoListArray(np.ndarray):
        def tolist(self):
            raise AssertionError("oversized metadata array reached tolist")

    dataset = SherpaDataset(X=np.arange(12, dtype=float).reshape(3, 4))
    dataset.set_extra("test.oversized_array", np.arange(64, dtype=float).view(NoListArray))
    monkeypatch.setattr(dag_serialize, "API_DATASET_FULL_PAYLOAD_MAX_NUMERIC_ELEMENTS", 1_000)
    monkeypatch.setattr(dag_serialize, "API_METADATA_ARRAY_MAX_NUMERIC_ELEMENTS", 16)
    monkeypatch.setattr(
        serialization,
        "_register_application_dataset",
        lambda value, owner_user_id, project_id=None: value.dataset_id,
    )

    payload = serialization.serialize_result(dataset, owner_user_id=7)

    assert payload["metadata"]["api_serialization"]["mode"] == "full"
    assert np.asarray(payload["data"]).shape == (3, 4)
    assert payload["extra"]["test.oversized_array"] == {
        "_truncated_array": True,
        "shape": "64",
        "dtype": "float64",
        "reason": "api_aggregate_numeric_ceiling",
    }


def test_preview_ceiling_counts_final_axes_targets_and_metadata(monkeypatch):
    from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset, TargetContext
    from spectra_sherpa.app.services import serialization

    def count_numeric(value):
        if isinstance(value, bool) or value is None:
            return 0
        if isinstance(value, (int, float)):
            return 1
        if isinstance(value, dict):
            return sum(count_numeric(item) for item in value.values())
        if isinstance(value, list):
            return sum(count_numeric(item) for item in value)
        return 0

    feature_count = 1_000_001
    dataset = SherpaDataset(
        X=np.zeros((1, feature_count), dtype=np.float64),
        feature_axis=FeatureAxis(values=np.arange(feature_count, dtype=np.float64)),
    )
    payload = serialization.serialize_result(dataset, owner_user_id=7)
    assert payload["metadata"]["api_serialization"]["mode"] == "bounded_preview"
    assert "wavenumbers" not in payload["metadata"]
    assert count_numeric(payload) <= 100_000

    multi = SherpaDataset(
        X=np.zeros((200, 6_000), dtype=np.float64),
        feature_axis=FeatureAxis(values=np.arange(6_000, dtype=np.float64)),
        target=np.zeros((200, 3_000), dtype=np.float64),
        target_context=TargetContext(kind="continuous", target_names=[f"y{i}" for i in range(3_000)]),
    )
    for index in range(3):
        multi.set_extra(f"aggregate.{index}", np.arange(20_000, dtype=np.float64))
    payload = serialization.serialize_result(multi, owner_user_id=7)
    assert payload["metadata"]["target_truncated"] is True
    assert "target" not in payload
    assert any(isinstance(value, dict) and value.get("_truncated_array") is True for value in payload["extra"].values())
    assert count_numeric(payload) <= 100_000


def test_unregistered_full_result_never_advertises_a_false_handle(monkeypatch):
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import serialization

    dataset = SherpaDataset(X=np.arange(12, dtype=float).reshape(3, 4))
    monkeypatch.setattr(
        serialization,
        "_register_application_dataset",
        lambda value, owner_user_id, project_id=None: None,
    )

    payload = serialization.serialize_result(dataset, owner_user_id=7)

    authority = payload["metadata"]["api_serialization"]
    assert authority["full_dataset_handle"] is None
    assert authority["full_dataset_handle_unavailable_reason"] == ("dataset_exceeds_in_memory_handle_budget")


def test_matlab_complex_values_are_rejected_without_silent_real_cast(tmp_path: Path):
    from scipy.io import savemat

    path = tmp_path / "complex.mat"
    savemat(path, {"spectra": np.asarray([[1 + 2j, 3 + 4j]])})

    with pytest.raises(UnreadableSpectrumError, match="complex values.*real, or imaginary"):
        ingest(path)


def test_source_digest_and_parsed_bytes_share_one_immutable_snapshot(monkeypatch, tmp_path: Path):
    from spectra_sherpa.app.lib import io as app_io

    path = tmp_path / "mutable.csv"
    path.write_text("sample,1000,1001\nA,0.1,0.2\n", encoding="utf-8")
    original = app_io.parse_csv_snapshot_as_sherpa

    original_bytes = path.read_bytes()
    original_digest = hashlib.sha256(original_bytes).hexdigest()

    def _replace_then_restore_original(source_path, **kwargs):
        assert Path(source_path) != path
        path.write_bytes(original_bytes.replace(b"0.1", b"9.1", 1))
        dataset = original(source_path, **kwargs)
        path.write_bytes(original_bytes)
        return dataset

    monkeypatch.setattr(
        app_io,
        "parse_csv_snapshot_as_sherpa",
        _replace_then_restore_original,
    )
    result = ingest(path)
    assert result.assets[0].dataset.X[0, 0] == pytest.approx(0.1)
    assert result.source_members[0].sha256 == original_digest


def test_selected_synthetic_response_preserves_target_units():
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

    path = Path(__file__).parents[1] / "src" / "spectra_sherpa" / "data" / "synthetic" / "Synthetic_atmospheric-6.npz"
    selected = load_canonical_file_as_sherpa(
        path,
        selected_target="Carbon dioxide",
        target_type="continuous",
    )
    assert selected.target_context.target_units == "ppm"
    assert selected.target_context.target_name == "Carbon dioxide"
    assert selected.target.dtype == np.float64


def test_explicit_continuous_target_rejects_text_values(tmp_path: Path):
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

    path = tmp_path / "categorical-as-continuous.csv"
    path.write_text("sample,target,f1\na,A,1\nb,B,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="declared continuous.*non-numeric value 'A'"):
        load_canonical_file_as_sherpa(path, selected_target="target", target_type="continuous")


def test_explicit_categorical_target_preserves_missing_values(tmp_path: Path):
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

    path = tmp_path / "categorical-missing.csv"
    path.write_text("sample,target,f1\na,A,1\nb,,2\n", encoding="utf-8")
    selected = load_canonical_file_as_sherpa(path, selected_target="target", target_type="categorical")
    assert selected.target[0] == "A"
    assert pd.isna(selected.target[1])


@pytest.mark.parametrize(
    ("suffix", "payload", "module_name", "loader_name"),
    [
        (
            ".csv",
            b"sample,1000,1001\nA,1,2\n",
            "spectra_sherpa.app.lib.io",
            "parse_csv_snapshot_as_sherpa",
        ),
        (
            ".jdx",
            b"##TITLE=X\n##FIRSTX=1\n##DELTAX=1\n##NPOINTS=2\n##XYDATA=(X++(Y..Y))\n1 1 2\n##END=\n",
            "spectra_sherpa.io.formats.jcamp",
            "_dataset",
        ),
    ],
)
def test_text_parser_limits_fail_before_numeric_materialization(
    monkeypatch,
    tmp_path: Path,
    suffix: str,
    payload: bytes,
    module_name: str,
    loader_name: str,
):
    import importlib

    path = tmp_path / f"oversized{suffix}"
    path.write_bytes(payload)
    called = False

    def _unexpected_loader(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("numeric loader must not run after the structural count exceeds the limit")

    monkeypatch.setattr(importlib.import_module(module_name), loader_name, _unexpected_loader)
    with pytest.raises(ParserLimitError):
        ingest(path, limits=ParserLimits(max_decoded_elements=1))
    assert called is False


def test_wdf_reader_does_not_accept_extension_only(tmp_path: Path):
    path = tmp_path / "spectrum.wdf"
    path.write_bytes(b"arbitrary received bytes")

    with pytest.raises(UnsupportedFormatError, match="No registered parser structurally recognizes"):
        ingest(path)


def test_low_level_parsers_have_no_unregistered_production_callsites():
    """Fail closed if a new caller bypasses the frozen ingestion registry."""
    source_root = Path(__file__).parents[1] / "src" / "spectra_sherpa"
    allowed = {
        "load_csv_as_sherpa": set(),
        "parse_csv_snapshot_as_sherpa": {"app/lib/io.py", "io/formats/csv.py"},
        "parse_jcamp": {"app/lib/jcamp_reader.py", "io/formats/jcamp.py"},
        "read_jcamp": set(),
        "load_synthetic_npz": {"io/formats/numpy.py"},
    }
    actual: dict[str, set[str]] = {name: set() for name in allowed}
    legacy_reader_calls: list[str] = []
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root).as_posix()
        source = path.read_text(encoding="utf-8")
        for name in _protected_symbol_references(source, set(allowed)):
            actual[name].add(relative)
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name == "get_reader_for_extension":
                legacy_reader_calls.append(f"{relative}:{node.lineno}")
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "read"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "scp"
            ):
                legacy_reader_calls.append(f"{relative}:{node.lineno}:scp.read")
    assert actual == allowed
    assert legacy_reader_calls == []


def test_numpy_format_reader_does_not_depend_on_application_io_adapter() -> None:
    """Keep the native NumPy reader below the application adapter layer."""
    path = Path(__file__).parents[1] / "src" / "spectra_sherpa" / "io" / "formats" / "numpy.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "spectra_sherpa.app.lib.io" not in imported_modules


def test_native_ingestion_never_projects_absolute_source_paths() -> None:
    """Keep filesystem identity private at the one native ingestion boundary."""

    io_root = Path(__file__).parents[1] / "src" / "spectra_sherpa" / "io"
    forbidden: list[str] = []
    for path in io_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for marker in ("detail=str(exc)", "str(source.path)"):
            if marker in source:
                forbidden.append(f"{path.relative_to(io_root)}:{marker}")
    assert forbidden == []


@pytest.mark.parametrize(
    "source",
    [
        "from spectra_sherpa.app.lib import io as app_io\napp_io.parse_csv_snapshot_as_sherpa(path)\n",
        (
            "from spectra_sherpa.app.lib.io import parse_csv_snapshot_as_sherpa as parse_snapshot\n"
            "parse_snapshot(path)\n"
        ),
        "parser = app_io.parse_csv_snapshot_as_sherpa\nparser(path)\n",
    ],
)
def test_low_level_parser_gate_detects_qualified_and_aliased_references(source: str):
    assert _protected_symbol_references(source, {"parse_csv_snapshot_as_sherpa"}) == {"parse_csv_snapshot_as_sherpa"}


@pytest.mark.parametrize(
    "imports",
    [
        "import spectra_sherpa.app.lib.jcamp_reader as reader; import spectra_sherpa.io as native_io",
        "import spectra_sherpa.io as native_io; import spectra_sherpa.app.lib.jcamp_reader as reader",
    ],
)
def test_jcamp_reader_and_native_io_are_import_order_independent(imports: str):
    code = f"{imports}; assert reader.ParserLimitError is native_io.ParserLimitError"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert completed.returncode == 0, completed.stderr


def test_public_io_identity_is_import_order_independent():
    code = """
import spectra_sherpa
first = spectra_sherpa.io
import spectra_sherpa.io
second = spectra_sherpa.io
assert first is second
assert first.__name__ == 'spectra_sherpa.io'
"""
    subprocess.run([sys.executable, "-c", code], check=True, env=os.environ.copy())


def test_enterprise_registry_text_parsers_do_not_reauthorize_internal_snapshot(tmp_path: Path):
    csv_path = tmp_path / "outside-data-root.csv"
    csv_path.write_text("sample,1000,1001\nA,1,2\n", encoding="utf-8")
    jcamp_path = tmp_path / "outside-data-root.jcamp"
    jcamp_path.write_text(
        "\n".join(
            [
                "##TITLE=Enterprise fixture",
                "##FIRSTX=1",
                "##DELTAX=1",
                "##NPOINTS=2",
                "##XYPOINTS=(XY..XY)",
                "1, 1",
                "2, 2",
                "##END=",
            ]
        ),
        encoding="utf-8",
    )
    code = """
from pathlib import Path
from spectra_sherpa.io import ingest
for raw in __import__('sys').argv[1:]:
    result = ingest(Path(raw))
    assert len(result.assets) == 1
"""
    env = {**os.environ, "APP_MODE": "enterprise"}
    subprocess.run([sys.executable, "-c", code, str(csv_path), str(jcamp_path)], check=True, env=env)


def test_matlab_v73_is_recognized_and_reaches_bounded_hdf5_admission(tmp_path: Path):
    import h5py

    path = tmp_path / "workspace.mat"
    with h5py.File(path, "w", userblock_size=512):
        pass
    with path.open("r+b") as stream:
        stream.write(b"MATLAB 7.3 MAT-file, Platform: fixture".ljust(128, b" "))

    with pytest.raises(UnreadableSpectrumError, match="contains no supported numeric arrays"):
        ingest(path)


def test_truncated_matlab_v73_reports_the_missing_userblock_signature(tmp_path: Path):
    path = tmp_path / "truncated-v73.mat"
    path.write_bytes(b"MATLAB 7.3 MAT-file, Platform: GLNXA64".ljust(512, b" "))

    with pytest.raises(UnreadableSpectrumError, match="missing its HDF5 signature at byte offset 512"):
        ingest(path)


def test_bare_hdf5_renamed_mat_is_not_misidentified_as_matlab_v73(tmp_path: Path):
    path = tmp_path / "renamed-hdf5.mat"
    path.write_bytes(b"\x89HDF\r\n\x1a\n" + b"0" * 64)

    with pytest.raises(UnreadableSpectrumError) as raised:
        ingest(path)

    assert "MATLAB v7.3/HDF5 is a valid MATLAB format" not in str(raised.value)


def test_numpy_magic_and_extension_must_identify_the_same_container(tmp_path: Path):
    npz_path = tmp_path / "payload.npz"
    np.savez(npz_path, X=np.ones((2, 2)))
    contradictory = tmp_path / "payload.npy"
    contradictory.write_bytes(npz_path.read_bytes())

    with pytest.raises(FormatIdentityError, match="extension.*NPZ|NPZ.*extension"):
        ingest(contradictory)


def test_known_pending_zip_container_precedes_generic_numpy_probe(tmp_path: Path):
    path = tmp_path / "kinetics.srsx"
    with zipfile.ZipFile(path, mode="w") as archive:
        buffer = io.BytesIO()
        np.save(buffer, np.ones((2, 2)))
        archive.writestr("spectra.npy", buffer.getvalue())

    with pytest.raises(FormatUnavailableError, match=r"Export spectra as \.spa or \.spg") as raised:
        ingest(path)

    assert "NPZ bytes contradict" not in str(raised.value)
