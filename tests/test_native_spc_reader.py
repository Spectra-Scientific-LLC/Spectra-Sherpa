from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.ingestion_errors import ParserLimitError, UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io import ParserLimits, ingest, select_asset

REPO_ROOT = Path(__file__).parents[3]
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "spc"
CONFORMANCE_PATH = REPO_ROOT / "docs" / "evidence" / "native-spc-reader-conformance.json"


def _conformance() -> dict:
    return json.loads(CONFORMANCE_PATH.read_text())


def _science_digest(result) -> str:
    digest = hashlib.sha256()
    for asset in result.assets:
        dataset = asset.dataset
        digest.update(asset.asset_id.encode())
        digest.update(b"\0")
        digest.update(np.asarray(dataset.X.shape, dtype="<i8").tobytes())
        digest.update(np.ascontiguousarray(np.asarray(dataset.X, dtype="<f8")).tobytes())
        digest.update(np.ascontiguousarray(np.asarray(dataset.feature_axis.values, dtype="<f8")).tobytes())
    return digest.hexdigest()


@pytest.mark.parametrize("record", _conformance()["fixtures"], ids=lambda item: item["fixture_id"])
def test_spc_golden_fixture_matches_independently_verified_science(record: dict) -> None:
    path = REPO_ROOT / record["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]

    result = ingest(path)

    assert result.format_id == "spc"
    assert result.variant == record["variant"]
    assert result.parser_id == "spectrasherpa.spc"
    assert result.parser_version == "1"
    assert len(result.assets) == record["asset_count"]
    assert sum(asset.dataset.X.size for asset in result.assets) == record["total_values"]
    assert _science_digest(result) == record["aggregate_science_sha256"]
    first = result.assets[0]
    last = result.assets[-1]
    assert first.asset_id == record["first_asset_id"]
    assert list(first.dataset.shape) == record["first_shape"]
    assert last.asset_id == record["last_asset_id"]
    assert list(last.dataset.shape) == record["last_shape"]
    assert first.dataset.X[0, 0] == record["first_value"]
    assert first.dataset.X[0, -1] == record["last_value"]
    assert first.dataset.feature_axis.values[0] == record["first_axis"]
    assert first.dataset.feature_axis.values[-1] == record["last_axis"]
    assert first.dataset.feature_axis.units == record["axis_units"]
    assert first.dataset.domain.data_quantity == record["data_quantity"]
    assert (result.raw_metadata["spc.log"] is not None) is record["has_log"]


def test_spc_conformance_record_is_closed_and_structurally_independent() -> None:
    record = _conformance()
    assert set(record) == {
        "schema_version",
        "format_id",
        "parser_id",
        "parser_version",
        "specification",
        "source_authorities",
        "known_reference_divergences",
        "retained_scope",
        "fixtures",
    }
    assert record["schema_version"] == "spectrasherpa-native-spc-conformance/1"
    assert record["specification"]["revision"] == "4.50"
    assert {(item["project"], item["license"]) for item in record["source_authorities"]} == {
        ("spc-io", "MIT"),
        ("spc-parser", "MIT"),
    }
    variants = {item["structural_variant"] for item in record["fixtures"]}
    assert len(variants) == len(record["fixtures"]) == 6
    assert any("0x4D" in value for value in variants)
    assert any("XYXY" in value for value in variants)
    assert any("log" in value for value in variants)
    divergence = record["known_reference_divergences"]
    assert len(divergence) == 1
    assert divergence[0]["reference"] == "SpectroChemPy 0.8.1 read_spc"
    assert divergence[0]["fixtures"]["nir.spc"]["complete_matrix_max_abs_difference"] == 3.78125
    assert divergence[0]["fixtures"]["m_ordz.spc"]["complete_matrix_max_abs_difference"] == pytest.approx(
        5.724968679249287
    )


def test_independent_xyxy_requires_one_exact_asset_and_preserves_directory_relocation() -> None:
    result = ingest(FIXTURE_ROOT / "m_xyxy.spc")
    with pytest.raises(ValueError, match="select one exact asset_id"):
        select_asset(result)
    selected = select_asset(result, asset_id="spectrum_1")
    np.testing.assert_array_equal(
        selected.dataset.X, [[6823.0, 3188.0, 2498.0, 3654.0, 5490.0, 17704.0, 2826.0, 3144.0]]
    )
    assert selected.raw_metadata["spc.storage_bytes"] == 96
    assert selected.raw_metadata["spc.trailing_padding_bytes"] == 16
    with pytest.raises(ValueError, match="Available assets"):
        select_asset(result, asset_id="absorbance")


def test_sequential_xyxy_without_directory_preserves_exact_assets(tmp_path: Path) -> None:
    source = bytearray((FIXTURE_ROOT / "m_xyxy.spc").read_bytes())
    expected = ingest(FIXTURE_ROOT / "m_xyxy.spc").assets[:2]
    directory_offset = struct.unpack_from("<I", source, 4)[0]
    records: list[bytes] = []
    for index in range(2):
        position = struct.unpack_from("<I", source, directory_offset + index * 12)[0]
        point_count = struct.unpack_from("<I", source, position + 16)[0]
        actual_size = 32 + point_count * 4 + point_count * 2
        records.append(bytes(source[position : position + actual_size]))

    header = source[:512]
    struct.pack_into("<I", header, 4, 0)  # UDF: zero means no SSFSTC directory.
    struct.pack_into("<I", header, 24, 2)
    struct.pack_into("<I", header, 248, 0)
    path = tmp_path / "sequential-independent-xyxy.spc"
    path.write_bytes(bytes(header) + b"".join(records))

    actual = ingest(path)
    assert actual.variant == "new-lsb-multi-independent-xyxy"
    assert len(actual.assets) == 2
    for actual_asset, expected_asset in zip(actual.assets, expected, strict=True):
        np.testing.assert_array_equal(actual_asset.dataset.X, expected_asset.dataset.X)
        np.testing.assert_array_equal(
            actual_asset.dataset.feature_axis.values,
            expected_asset.dataset.feature_axis.values,
        )
        assert actual_asset.dataset.sample_axis.sample_table["spc_directory_time"] == [None]


@pytest.mark.asyncio
async def test_file_load_and_group_use_one_exact_spc_asset(tmp_path: Path) -> None:
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa
    from spectra_sherpa.app.services.dag.nodes.data.loaders import LoadGroupNode

    path = FIXTURE_ROOT / "m_xyxy.spc"
    with pytest.raises(ValueError, match="select one exact asset_id"):
        load_canonical_file_as_sherpa(path)
    selected = load_canonical_file_as_sherpa(path, asset_id="spectrum_1")
    assert selected.shape == (1, 8)

    for name in ("sample_1.spc", "sample_2.spc"):
        shutil.copyfile(path, tmp_path / name)
    grouped = await LoadGroupNode(
        "spc-group",
        {
            "folder_path": str(tmp_path),
            "pattern": "*.spc",
            "recursive": False,
            "sort_by": "filename",
            "group_title": "SPC mass spectra",
            "asset_id": "spectrum_1",
        },
    ).execute()
    assert grouped.shape == (2, 8)
    assert grouped.feature_axis.units == "m/z"


def test_spc_declared_elements_fail_before_signal_decode(monkeypatch) -> None:
    from spectra_sherpa.io.formats import spc

    decoded = False

    def _unexpected(*_args, **_kwargs):
        nonlocal decoded
        decoded = True
        raise AssertionError("SPC values must not decode before the declared resource gate")

    monkeypatch.setattr(spc, "_decode_y", _unexpected)
    with pytest.raises(ParserLimitError, match="decoded elements"):
        ingest(FIXTURE_ROOT / "nir.spc", limits=ParserLimits(max_decoded_elements=100))
    assert decoded is False


def test_single_file_uses_header_exponent_and_ignores_subheader_exponent(tmp_path: Path) -> None:
    source = FIXTURE_ROOT / "s_xy.spc"
    expected = ingest(source).assets[0].dataset.X.copy()
    payload = bytearray(source.read_bytes())
    point_count = struct.unpack_from("<I", payload, 4)[0]
    subheader_exponent_offset = 512 + point_count * 4 + 1
    payload[subheader_exponent_offset] = 23
    path = tmp_path / "single-subheader-exponent-is-not-authority.spc"
    path.write_bytes(payload)

    actual = ingest(path).assets[0].dataset.X
    np.testing.assert_array_equal(actual, expected)


def test_multifile_zero_subheader_exponent_is_not_an_inheritance_sentinel(tmp_path: Path) -> None:
    source = FIXTURE_ROOT / "nir.spc"
    expected_first_row = ingest(source).assets[0].dataset.X[0].copy()
    payload = bytearray(source.read_bytes())
    payload[3] = 7  # Contradictory global exponent must not govern TMULTI Y.
    payload[513] = 0  # Valid signed per-subfile exponent, not a sentinel.
    path = tmp_path / "multi-zero-subheader-exponent.spc"
    path.write_bytes(payload)

    actual_first_row = ingest(path).assets[0].dataset.X[0]
    np.testing.assert_array_equal(actual_first_row, expected_first_row / 16.0)


def test_old_nonmultifile_cannot_hide_multiple_records(tmp_path: Path) -> None:
    payload = bytearray((FIXTURE_ROOT / "m_ordz.spc").read_bytes())
    payload[0] &= ~0x04
    path = tmp_path / "old-cardinality-contradiction.spc"
    path.write_bytes(payload)
    with pytest.raises(UnreadableSpectrumError, match="non-multifile.*beyond.*single"):
        ingest(path)


def test_new_multifile_must_declare_multiple_records(tmp_path: Path) -> None:
    payload = bytearray((FIXTURE_ROOT / "nir.spc").read_bytes())
    struct.pack_into("<I", payload, 24, 1)
    path = tmp_path / "new-cardinality-contradiction.spc"
    path.write_bytes(payload)
    with pytest.raises(UnreadableSpectrumError, match="TMULTI.*at least two"):
        ingest(path)


def test_custom_axis_labels_replace_stale_type_semantics(tmp_path: Path) -> None:
    from spectra_sherpa.app.lib.axes import FeatureAxis, SpectralAxis

    payload = bytearray((FIXTURE_ROOT / "s_evenx.spc").read_bytes())
    payload[0] |= 0x20
    payload[28] = 1  # Stale wavenumber code must be ignored.
    payload[29] = 2  # Stale absorbance code must be ignored.
    labels = b"Pixel\x00Detector counts\x00Batch\x00"
    payload[218:248] = labels.ljust(30, b"\x00")
    path = tmp_path / "custom-axis-labels.spc"
    path.write_bytes(payload)

    dataset = ingest(path).assets[0].dataset
    assert isinstance(dataset.feature_axis, FeatureAxis)
    assert not isinstance(dataset.feature_axis, SpectralAxis)
    assert dataset.feature_axis.title == "Pixel"
    assert dataset.feature_axis.units is None
    assert dataset.domain.data_quantity == "Detector counts"
    assert dataset.units is None
    assert dataset.data_role == "X_features"
    assert dataset.sample_axis.sample_table["spc_z_label"] == ["Batch"]
    assert dataset.sample_axis.sample_table["spc_z_units"] == [None]


def test_xyxy_even_z_sequence_uses_first_subheader_and_preserves_directory_time(tmp_path: Path) -> None:
    payload = bytearray((FIXTURE_ROOT / "m_xyxy.spc").read_bytes())
    payload[0] &= ~0x10  # Evenly spaced Z authority, not TORDRD.
    directory_offset = struct.unpack_from("<I", payload, 4)[0]
    first_position = struct.unpack_from("<I", payload, directory_offset)[0]
    second_position = struct.unpack_from("<I", payload, directory_offset + 12)[0]
    first_z, next_z = struct.unpack_from("<ff", payload, first_position + 4)
    struct.pack_into("<ff", payload, second_position + 4, 9_999.0, -8_888.0)
    struct.pack_into("<f", payload, directory_offset + 12 + 8, 123.25)
    path = tmp_path / "xyxy-even-z-with-stale-later-subtime.spc"
    path.write_bytes(payload)

    result = ingest(path)
    first_table = result.assets[0].dataset.sample_axis.sample_table
    second_table = result.assets[1].dataset.sample_axis.sample_table
    assert first_table["spc_z"] == [first_z]
    assert second_table["spc_z"] == [pytest.approx(first_z + (next_z - first_z))]
    assert second_table["spc_directory_time"] == [123.25]
    assert result.assets[1].raw_metadata["spc.z"] == 9_999.0
    assert result.assets[1].raw_metadata["spc.resolved_z"] == pytest.approx(first_z + (next_z - first_z))


def test_xyxy_nonzero_header_z_increment_is_authoritative(tmp_path: Path) -> None:
    payload = bytearray((FIXTURE_ROOT / "m_xyxy.spc").read_bytes())
    payload[0] &= ~0x10
    struct.pack_into("<f", payload, 312, 2.0)
    directory_offset = struct.unpack_from("<I", payload, 4)[0]
    first_position = struct.unpack_from("<I", payload, directory_offset)[0]
    struct.pack_into("<ff", payload, first_position + 4, 0.0, 1.0)
    path = tmp_path / "xyxy-authoritative-fzinc.spc"
    path.write_bytes(payload)

    result = ingest(path)
    assert [result.assets[index].dataset.sample_axis.sample_table["spc_z"][0] for index in range(3)] == [
        0.0,
        2.0,
        4.0,
    ]


def test_shared_x_nonzero_header_z_increment_is_authoritative(tmp_path: Path) -> None:
    payload = bytearray((FIXTURE_ROOT / "nir.spc").read_bytes())
    struct.pack_into("<f", payload, 312, 2.0)
    struct.pack_into("<ff", payload, 512 + 4, 0.0, 1.0)
    path = tmp_path / "shared-x-authoritative-fzinc.spc"
    path.write_bytes(payload)

    table = ingest(path).assets[0].dataset.sample_axis.sample_table
    assert table["spc_z"][:3] == [0.0, 2.0, 4.0]


def test_independent_asset_ceiling_fails_before_layout_objects(monkeypatch, tmp_path: Path) -> None:
    from spectra_sherpa.io.formats import spc

    payload = bytearray((FIXTURE_ROOT / "m_xyxy.spc").read_bytes())
    struct.pack_into("<I", payload, 24, 4_097)
    path = tmp_path / "too-many-independent-assets.spc"
    path.write_bytes(payload)

    monkeypatch.setattr(
        spc,
        "_subheader",
        lambda *_args, **_kwargs: pytest.fail("asset ceiling must precede layout construction"),
    )
    with pytest.raises(ParserLimitError, match="asset count 4,097.*ceiling 4,096"):
        ingest(path)


def test_sequential_independent_asset_ceiling_fails_before_layout_objects(monkeypatch, tmp_path: Path) -> None:
    from spectra_sherpa.io.formats import spc

    payload = bytearray((FIXTURE_ROOT / "m_xyxy.spc").read_bytes())
    struct.pack_into("<I", payload, 4, 0)
    struct.pack_into("<I", payload, 24, 4_097)
    path = tmp_path / "too-many-sequential-independent-assets.spc"
    path.write_bytes(payload)

    monkeypatch.setattr(
        spc,
        "_subheader",
        lambda *_args, **_kwargs: pytest.fail("asset ceiling must precede sequential layout construction"),
    )
    with pytest.raises(ParserLimitError, match="asset count 4,097.*ceiling 4,096"):
        ingest(path)


def test_spc_rejects_truncated_subfile_before_decode(tmp_path: Path) -> None:
    payload = (FIXTURE_ROOT / "s_evenx.spc").read_bytes()[:-8]
    path = tmp_path / "truncated.spc"
    path.write_bytes(payload)
    with pytest.raises(UnreadableSpectrumError, match="extends beyond|ends at"):
        ingest(path)


def test_spc_rejects_overlapping_xyxy_directory_records(tmp_path: Path) -> None:
    payload = bytearray((FIXTURE_ROOT / "m_xyxy.spc").read_bytes())
    directory_offset = struct.unpack_from("<I", payload, 4)[0]
    first_position, first_size = struct.unpack_from("<II", payload, directory_offset)
    struct.pack_into("<II", payload, directory_offset + 12, first_position, first_size)
    path = tmp_path / "overlap.spc"
    path.write_bytes(payload)
    with pytest.raises(UnreadableSpectrumError, match="overlapping"):
        ingest(path)


def test_spc_rejects_unqualified_big_endian_variant_explicitly(tmp_path: Path) -> None:
    payload = bytearray((FIXTURE_ROOT / "s_evenx.spc").read_bytes())
    payload[1] = 0x4C
    path = tmp_path / "big-endian.spc"
    path.write_bytes(payload)
    with pytest.raises(UnsupportedFormatVariantError, match="0x4C.*independent conformance fixture"):
        ingest(path)


@pytest.mark.parametrize(
    ("offset", "value", "message"),
    [
        (0, 0x08, "Random-order"),
        (0, 0x02, "experiment-extension"),
        (28, 250, "X unit type 250"),
        (29, 250, "Y unit type 250"),
    ],
)
def test_spc_unqualified_scientific_header_dimensions_fail_closed(
    tmp_path: Path,
    offset: int,
    value: int,
    message: str,
) -> None:
    payload = bytearray((FIXTURE_ROOT / "s_evenx.spc").read_bytes())
    payload[offset] = value
    path = tmp_path / "unqualified.spc"
    path.write_bytes(payload)
    with pytest.raises(UnsupportedFormatVariantError, match=message):
        ingest(path)


def test_spc_tsprec_cannot_silently_relabel_float_storage(tmp_path: Path) -> None:
    payload = bytearray((FIXTURE_ROOT / "s_evenx.spc").read_bytes())
    payload[0] |= 0x01
    payload[3] = 0x80
    path = tmp_path / "contradictory-precision.spc"
    path.write_bytes(payload)
    with pytest.raises(UnsupportedFormatVariantError, match="TSPREC contradicts"):
        ingest(path)


def test_spc_unqualified_w_plane_does_not_flatten_to_samples(tmp_path: Path) -> None:
    payload = bytearray((FIXTURE_ROOT / "nir.spc").read_bytes())
    struct.pack_into("<I", payload, 316, 2)
    path = tmp_path / "four-dimensional.spc"
    path.write_bytes(payload)
    with pytest.raises(UnsupportedFormatVariantError, match="Four-dimensional.*W-plane"):
        ingest(path)


def test_native_spc_import_and_execution_do_not_load_scp() -> None:
    import os
    import subprocess
    import sys

    script = f"""
import sys
from spectra_sherpa.io import ingest
r = ingest({str(FIXTURE_ROOT / "s_evenx.spc")!r})
assert r.format_id == 'spc'
assert not any(name == 'spectrochempy' or name.startswith('spectrochempy.') for name in sys.modules)
assert 'spectra_sherpa.app.lib.scp_adapter' not in sys.modules
assert 'spectra_sherpa.app.lib.scp_compat' not in sys.modules
"""
    env = dict(os.environ)
    env["SPECTRA_DAG_SKIP_BUILTIN_REGISTRATION"] = "1"
    completed = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
