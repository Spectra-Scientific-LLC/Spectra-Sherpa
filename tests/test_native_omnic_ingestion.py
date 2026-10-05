from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.core.axis_semantics import AxisQuantity
from spectra_sherpa.ingestion_errors import ParserLimitError, UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io import ingest
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats.omnic import PLUGIN
from spectra_sherpa.io.types import ParserLimits, ProbeConfidence


def _header(*, nx: int, first_x: float, last_x: float, x_code: int = 1, y_code: int = 17) -> bytes:
    payload = bytearray(140)
    struct.pack_into("<I", payload, 4, nx)
    payload[8] = x_code
    payload[12] = y_code
    struct.pack_into("<ff", payload, 16, first_x, last_x)
    struct.pack_into("<III", payload, 28, nx, nx // 2, 32)
    struct.pack_into("<I", payload, 52, 16)
    struct.pack_into("<I", payload, 68, 250)
    struct.pack_into("<f", payload, 80, 15798.0)
    return bytes(payload)


def _entry(key: int, offset: int, size: int) -> bytes:
    payload = bytearray(16)
    payload[0] = key
    struct.pack_into("<II", payload, 2, offset, size)
    return bytes(payload)


def _kinetics_entry(key: int, offset: int, size: int, *, multiplicity: int = 1, reserved: int = 0) -> bytes:
    payload = bytearray(22)
    struct.pack_into("<HQIII", payload, 0, key, offset, size, multiplicity, reserved)
    return bytes(payload)


def _spa_bytes(
    *,
    y_code: int = 17,
    values: tuple[float, float, float] = (1.25, 2.5, 3.75),
) -> bytes:
    header_offset = 336
    data_offset = header_offset + 140
    payload = bytearray(data_offset + 12)
    payload[:18] = b"Spectral Data File"
    payload[30:39] = b"demo.spa\0"
    struct.pack_into("<H", payload, 294, 2)
    struct.pack_into("<I", payload, 296, 3_500_000_000)
    payload[304:320] = _entry(2, header_offset, 140)
    payload[320:336] = _entry(3, data_offset, 12)
    payload[header_offset:data_offset] = _header(nx=3, first_x=4000.0, last_x=1000.0, y_code=y_code)
    struct.pack_into("<fff", payload, data_offset, *values)
    return bytes(payload)


def _metadata_spa_bytes(*, linked_size_delta: int = 1) -> bytes:
    experiment = bytearray(573)
    for offset, value in (
        (10, b"qualification.exp\0"),
        (90, b"Apex qualification\0"),
        (254, b"no correction\0"),
        (413, b"ATR accessory\0"),
    ):
        experiment[offset : offset + len(value)] = value
    linked = _spa_bytes()
    blocks: list[tuple[int, bytes, int | None]] = [
        (2, _header(nx=3, first_x=4000.0, last_x=1000.0), None),
        (3, struct.pack("<fff", 1.25, 2.5, 3.75), None),
        (4, b"operator comment\0", None),
        (27, b"Final format: Absorbance\r\nCorrection: None\0", None),
        (130, bytes(experiment), None),
        (78, linked, len(linked) + linked_size_delta),
    ]
    table_end = 304 + len(blocks) * 16
    offset = table_end
    entries: list[bytes] = []
    positioned: list[tuple[int, bytes]] = []
    for key, block, declared_size in blocks:
        entries.append(_entry(key, offset, len(block) if declared_size is None else declared_size))
        positioned.append((offset, block))
        offset += len(block)
    payload = bytearray(offset)
    payload[:18] = b"Spectral Data File"
    name = b"qualified-demo.spa\0"
    payload[30 : 30 + len(name)] = name
    struct.pack_into("<H", payload, 294, len(entries))
    struct.pack_into("<I", payload, 296, 3_500_000_000)
    for index, entry in enumerate(entries):
        start = 304 + index * 16
        payload[start : start + 16] = entry
    for start, block in positioned:
        payload[start : start + len(block)] = block
    return bytes(payload)


def _blanked_transmittance_spa_bytes(
    *,
    values: tuple[float, float, float] = (1.25, float("nan"), float("nan")),
    blank_from: float = 800.0,
    blank_to: float = 400.0,
) -> bytes:
    history = (
        "Collected on Wed Dec 16 17:22:42 1998\r\n"
        "\t Final format:\tSingle Beam\r\n"
        f"Blank on Wed Feb 17 12:51:29 1999\r\n\t From {blank_from} to {blank_to}\0"
    ).encode("latin-1")
    blocks = [
        (2, _header(nx=3, first_x=1000.0, last_x=500.0, y_code=23)),
        (3, struct.pack("<fff", *values)),
        (27, history),
    ]
    table_end = 304 + len(blocks) * 16
    offset = table_end
    payload = bytearray(table_end + sum(len(block) for _, block in blocks))
    payload[:18] = b"Spectral Data File"
    payload[30:48] = b"blanked-demo.spa\0"
    struct.pack_into("<H", payload, 294, len(blocks))
    struct.pack_into("<I", payload, 296, 3_500_000_000)
    for index, (key, block) in enumerate(blocks):
        row = 304 + index * 16
        payload[row : row + 16] = _entry(key, offset, len(block))
        payload[offset : offset + len(block)] = block
        offset += len(block)
    return bytes(payload)


def _spg_bytes() -> bytes:
    header_offset = 352
    data_offset = header_offset + 140
    title_offset = data_offset + 12
    payload = bytearray(title_offset + 260)
    payload[:18] = b"Spectral Data File"
    payload[30:39] = b"demo.spg\0"
    struct.pack_into("<H", payload, 294, 3)
    payload[304:320] = _entry(2, header_offset, 140)
    payload[320:336] = _entry(3, data_offset, 12)
    payload[336:352] = _entry(107, title_offset, 260)
    payload[header_offset:data_offset] = _header(nx=3, first_x=4000.0, last_x=1000.0)
    struct.pack_into("<fff", payload, data_offset, 1.25, 2.5, 3.75)
    title = b"sample-1\0"
    payload[title_offset : title_offset + len(title)] = title
    struct.pack_into("<I", payload, title_offset + 256, 3_500_000_000)
    return bytes(payload)


def _two_record_spg_bytes() -> bytes:
    table_end = 304 + 6 * 16
    blocks: list[tuple[int, bytes]] = []
    for index, (timestamp, values) in enumerate(((3_500_000_600, (4.0, 5.0, 6.0)), (3_500_000_000, (1.0, 2.0, 3.0)))):
        blocks.append((2, _header(nx=3, first_x=4000.0, last_x=1000.0)))
        blocks.append((3, struct.pack("<fff", *values)))
        title = bytearray(260)
        label = f"sample-{index + 1}".encode()
        title[: len(label)] = label
        struct.pack_into("<I", title, 256, timestamp)
        blocks.append((107, bytes(title)))
    offset = table_end
    entries = []
    for key, block in blocks:
        entries.append(_entry(key, offset, len(block)))
        offset += len(block)
    payload = bytearray(offset)
    payload[:18] = b"Spectral Data File"
    payload[30:39] = b"demo.spg\0"
    struct.pack_into("<H", payload, 294, len(entries))
    position = 304
    block_offset = table_end
    for entry, (_key, block) in zip(entries, blocks):
        payload[position : position + 16] = entry
        position += 16
        payload[block_offset : block_offset + len(block)] = block
        block_offset += len(block)
    return bytes(payload)


def _srs_bytes() -> bytes:
    marker = b"\x02\x00\x00\x00\x18\x00\x00\x00\x00\x00"
    header_offset = 512
    marker_offsets = (header_offset + 152, 1800, 2940)
    data_offset = marker_offsets[-1] + 60
    point_count = 3
    sample_count = 2
    row_bytes = 84 + point_count * 4
    payload = bytearray(data_offset + sample_count * row_bytes + 16)
    payload[:18] = b"Spectral Exte File"
    for offset in marker_offsets:
        payload[offset : offset + len(marker)] = marker
    header = bytearray(_header(nx=point_count, first_x=4000.0, last_x=1000.0, y_code=16))
    payload[header_offset : header_offset + len(header)] = header
    title = b"demo-series\0"
    payload[header_offset + 938 : header_offset + 938 + len(title)] = title
    struct.pack_into("<fff", payload, header_offset + 1002, 0.5, 2.0, 1.0)
    struct.pack_into("<I", payload, header_offset + 1026, sample_count)
    position = data_offset
    for index, values in enumerate(((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))):
        if index:
            position += 16
        label = f"row-{index + 1}".encode()
        payload[position : position + len(label)] = label
        position += 84
        struct.pack_into("<fff", payload, position, *values)
        position += 12
    return bytes(payload)


def _kinetics_srs_bytes(*, repeated_description: bytes | None = None) -> bytes:
    entries_offset = 304
    block_offset = 512
    header = _header(nx=3, first_x=4000.0, last_x=1000.0, x_code=32, y_code=31)
    descriptor = bytearray(64)
    descriptor[8 : 8 + len(b"Spectral Exte File")] = b"Spectral Exte File"
    metadata = bytearray(94)
    struct.pack_into("<fff", metadata, 66, 1.0, 2.0, 0.5)
    struct.pack_into("<I", metadata, 90, 3)
    text = bytearray(128)
    description = b"Series title:\tdemo-kinetics\r\n\t Data collection type:\tKinetics\r\n"
    text[: len(description)] = description
    rows = bytearray(212 + 3 * (84 + 3 * 4) + 2 * 16)
    position = 212
    for index, values in enumerate(((3.0, 2.0, 1.0), (6.0, 5.0, 4.0), (9.0, 8.0, 7.0))):
        if index:
            position += 16
        label = f"Linked spectrum at {1.0 + index * 0.5:.3f} min.".encode()
        rows[position : position + len(label)] = label
        position += 84
        struct.pack_into("<fff", rows, position, *values)
        position += 12
    blocks: list[tuple[int, bytes, int]] = [
        (2, bytes(header), 1),
        (146, bytes(descriptor), 1),
        (325, bytes(metadata), 1),
        (27, bytes(text), 1),
        (301, bytes(rows), 1),
    ]
    if repeated_description is not None:
        repeated = bytearray(128)
        repeated[: len(repeated_description)] = repeated_description
        blocks.append((27, bytes(repeated), 2))
    entries: list[bytes] = []
    positioned: list[tuple[int, bytes]] = []
    for key, block, multiplicity in blocks:
        entries.append(_kinetics_entry(key, block_offset, len(block), multiplicity=multiplicity))
        positioned.append((block_offset, block))
        block_offset += len(block)
    payload = bytearray(block_offset)
    payload[:18] = b"Spectral Exte File"
    struct.pack_into("<H", payload, 294, len(entries))
    for index, entry in enumerate(entries):
        start = entries_offset + index * 22
        payload[start : start + 22] = entry
    for offset, block in positioned:
        payload[offset : offset + len(block)] = block
    return bytes(payload)


@pytest.mark.parametrize(
    ("name", "payload", "variant", "shape", "asset_id"),
    [
        ("sample.spa", _spa_bytes(), "spa-single-spectrum", (1, 3), "spectrum"),
        ("sample.spg", _spg_bytes(), "spg-compatible-spectrum-group", (1, 3), "spectra"),
        ("sample.srs", _srs_bytes(), "srs-qualified-series", (2, 3), "series"),
    ],
)
def test_native_omnic_variants_preserve_declared_science(
    tmp_path: Path,
    name: str,
    payload: bytes,
    variant: str,
    shape: tuple[int, int],
    asset_id: str,
) -> None:
    source = tmp_path / name
    source.write_bytes(payload)
    result = ingest(source)
    assert result.format_id == "omnic"
    assert result.variant == variant
    assert result.assets[0].asset_id == asset_id
    assert result.assets[0].dataset.shape == shape
    np.testing.assert_allclose(result.assets[0].dataset.feature_axis.values, [4000.0, 2500.0, 1000.0])


def test_srs_preserves_declared_axis_and_time_order(tmp_path: Path) -> None:
    source = tmp_path / "sample.srs"
    source.write_bytes(_srs_bytes())
    dataset = ingest(source).assets[0].dataset
    np.testing.assert_allclose(dataset.X, [[1, 2, 3], [4, 5, 6]])
    np.testing.assert_allclose(dataset.sample_axis.values, [1.0, 2.0])
    assert dataset.sample_axis.labels == ["row-1", "row-2"]
    assert dataset.units == "percent"


def test_kinetics_srs_preserves_declared_axis_series_order_and_time(tmp_path: Path) -> None:
    source = tmp_path / "kinetics.srs"
    source.write_bytes(_kinetics_srs_bytes())
    result = ingest(source)
    dataset = result.assets[0].dataset
    assert result.raw_metadata["series_layout"] == "srs-kinetics"
    assert result.raw_metadata["feature_storage_order"] == "ascending_reversed_to_declared_axis"
    assert result.raw_metadata["collection_interval_seconds"] == 30.0
    assert dataset.title == "demo-kinetics: Raman intensity series"
    assert dataset.shape == (3, 3)
    np.testing.assert_array_equal(dataset.feature_axis.values, [4000.0, 2500.0, 1000.0])
    np.testing.assert_array_equal(dataset.X, [[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    np.testing.assert_array_equal(dataset.sample_axis.values, [1.0, 1.5, 2.0])
    assert dataset.sample_axis.labels == [
        "Linked spectrum at 1.000 min.",
        "Linked spectrum at 1.500 min.",
        "Linked spectrum at 2.000 min.",
    ]
    assert dataset.sample_axis.sample_table == {
        "series_time_minutes": [1.0, 1.5, 2.0],
        "recorded_series_time_minutes": [1.0, 1.5, 2.0],
    }
    assert dataset.feature_axis.units == "cm-1"
    assert dataset.feature_axis.quantity is AxisQuantity.RAMAN_SHIFT
    assert dataset.domain.technique == "Raman"
    assert dataset.domain.data_quantity == "Raman intensity"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("collection-type", "not a qualified Kinetics"),
        ("row-block-size", "row block size contradicts"),
        ("ascending-axis", "ascending or degenerate"),
        ("time-interval", "time endpoints contradict"),
        ("missing-descriptor", "exactly one key 146"),
        ("reserved-descriptor", "unqualified reserved value"),
        ("overlapping-directory", "directory blocks overlap"),
        ("row-label", "linked-spectrum grammar"),
        ("row-time", "row-label times contradict"),
        ("nonmonotonic-row-time", "not finite and strictly increasing"),
    ],
)
def test_kinetics_srs_refuses_unqualified_or_contradictory_structure(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    payload = bytearray(_kinetics_srs_bytes())
    if mutation == "collection-type":
        marker = b"Data collection type:\tKinetics"
        start = payload.index(marker)
        payload[start : start + len(marker)] = b"Data collection type:\tUnknown!"
    elif mutation == "row-block-size":
        row = 304 + 4 * 22
        size = struct.unpack_from("<I", payload, row + 10)[0]
        struct.pack_into("<I", payload, row + 10, size - 1)
    elif mutation == "ascending-axis":
        header_offset = struct.unpack_from("<Q", payload, 304 + 2)[0]
        struct.pack_into("<ff", payload, header_offset + 16, 1000.0, 4000.0)
    elif mutation == "time-interval":
        metadata_row = 304 + 2 * 22
        metadata_offset = struct.unpack_from("<Q", payload, metadata_row + 2)[0]
        struct.pack_into("<f", payload, metadata_offset + 66 + 8, 0.25)
    elif mutation == "missing-descriptor":
        descriptor_row = 304 + 22
        struct.pack_into("<H", payload, descriptor_row, 301)
    elif mutation == "reserved-descriptor":
        descriptor_row = 304 + 22
        struct.pack_into("<I", payload, descriptor_row + 18, 1)
    elif mutation == "overlapping-directory":
        row_block_row = 304 + 4 * 22
        text_row = 304 + 3 * 22
        text_offset = struct.unpack_from("<Q", payload, text_row + 2)[0]
        struct.pack_into("<Q", payload, row_block_row + 2, text_offset)
    elif mutation in {"row-label", "row-time", "nonmonotonic-row-time"}:
        row_block_row = 304 + 4 * 22
        row_block_offset = struct.unpack_from("<Q", payload, row_block_row + 2)[0]
        label_offset = row_block_offset + 212
        if mutation == "nonmonotonic-row-time":
            label_offset += 84 + 3 * 4 + 16
        if mutation == "row-label":
            payload[label_offset] = ord("X")
        elif mutation == "nonmonotonic-row-time":
            original = b"Linked spectrum at 1.500 min."
            replacement = b"Linked spectrum at 2.500 min."
            assert payload[label_offset : label_offset + len(original)] == original
            payload[label_offset : label_offset + len(original)] = replacement
        else:
            original = b"Linked spectrum at 1.000 min."
            replacement = b"Linked spectrum at 0.000 min."
            assert payload[label_offset : label_offset + len(original)] == original
            payload[label_offset : label_offset + len(original)] = replacement
    source = tmp_path / f"{mutation}.srs"
    source.write_bytes(payload)
    with pytest.raises((UnreadableSpectrumError, UnsupportedFormatVariantError), match=message):
        ingest(source)


def test_kinetics_srs_refuses_contradictory_repeated_descriptions(tmp_path: Path) -> None:
    source = tmp_path / "contradictory-description.srs"
    source.write_bytes(_kinetics_srs_bytes(repeated_description=b"Data collection type:\tKinetics\r\nchanged"))
    with pytest.raises(UnreadableSpectrumError, match="contradictory repeated descriptions"):
        ingest(source)


def test_kinetics_srs_rejects_row_count_before_allocation(tmp_path: Path) -> None:
    payload = bytearray(_kinetics_srs_bytes())
    metadata_row = 304 + 2 * 22
    metadata_offset = struct.unpack_from("<Q", payload, metadata_row + 2)[0]
    struct.pack_into("<I", payload, metadata_offset + 90, 65_537)
    source = tmp_path / "too-many-kinetics-rows.srs"
    source.write_bytes(payload)
    with pytest.raises(ParserLimitError, match="65537 blocks"):
        ingest(source)


def test_spg_orders_explicit_timestamps_and_retains_directory_identity(tmp_path: Path) -> None:
    source = tmp_path / "reverse-directory.spg"
    source.write_bytes(_two_record_spg_bytes())
    dataset = ingest(source).assets[0].dataset
    np.testing.assert_allclose(dataset.X, [[1, 2, 3], [4, 5, 6]])
    assert dataset.sample_axis.labels == ["sample-2", "sample-1"]
    assert dataset.sample_axis.sample_table["source_directory_index"] == [1, 0]


@pytest.mark.parametrize("orphan_key", [3, 107])
def test_spg_rejects_orphan_scientific_blocks(tmp_path: Path, orphan_key: int) -> None:
    payload = bytearray(_spg_bytes())
    payload[304] = orphan_key
    source = tmp_path / "ambiguous.spg"
    source.write_bytes(payload)
    with pytest.raises(UnreadableSpectrumError, match="before any spectral header"):
        ingest(source)


def test_omnic_probe_requires_structural_magic_and_filename_family(tmp_path: Path) -> None:
    wrong = tmp_path / "not-omnic.spa"
    wrong.write_bytes(b"not omnic" * 100)
    with BoundedSource(wrong, limits=ParserLimits()) as source:
        assert PLUGIN.probe(source).confidence is ProbeConfidence.NO_MATCH


def test_literal_extension_filename_uses_the_registry_extension_authority(tmp_path: Path) -> None:
    source = tmp_path / ".SPA"
    source.write_bytes(_spa_bytes())

    result = ingest(source)

    assert result.format_id == "omnic"
    assert result.variant == "spa-single-spectrum"
    np.testing.assert_array_equal(result.assets[0].dataset.X, [[1.25, 2.5, 3.75]])


def test_omnic_rejects_unknown_scientific_unit_code(tmp_path: Path) -> None:
    payload = bytearray(_spa_bytes())
    payload[336 + 12] = 255
    source = tmp_path / "unknown-unit.spa"
    source.write_bytes(payload)
    with pytest.raises(UnsupportedFormatVariantError, match="data-unit code 255"):
        ingest(source)


def test_omnic_rejects_declared_data_size_mismatch(tmp_path: Path) -> None:
    payload = bytearray(_spa_bytes())
    struct.pack_into("<I", payload, 320 + 6, 8)
    source = tmp_path / "short-data.spa"
    source.write_bytes(payload)
    with pytest.raises(Exception, match="requires exactly 12"):
        ingest(source)


def test_omnic_rejects_overlapping_directory_blocks(tmp_path: Path) -> None:
    payload = bytearray(_spa_bytes())
    struct.pack_into("<I", payload, 320 + 2, 400)
    source = tmp_path / "overlap.spa"
    source.write_bytes(payload)
    with pytest.raises(UnreadableSpectrumError, match="overlap"):
        ingest(source)


@pytest.mark.parametrize(
    ("name", "payload", "value_offset", "value"),
    [
        ("infinite.spa", _spa_bytes(), 476, float("inf")),
        ("nan.srs", _srs_bytes(), 3084, float("nan")),
    ],
)
def test_omnic_rejects_unqualified_non_finite_signal(
    tmp_path: Path,
    name: str,
    payload: bytes,
    value_offset: int,
    value: float,
) -> None:
    mutated = bytearray(payload)
    struct.pack_into("<f", mutated, value_offset, value)
    source = tmp_path / name
    source.write_bytes(mutated)
    with pytest.raises(UnreadableSpectrumError, match="infinite|non-finite"):
        ingest(source)


def test_spa_preserves_missing_transmittance_with_explicit_warning_and_refuses_implicit_imputation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "transmittance.spa"
    source.write_bytes(_blanked_transmittance_spa_bytes())

    result = ingest(source)
    dataset = result.assets[0].dataset

    assert dataset.domain.data_quantity == "Transmittance"
    assert result.raw_metadata["header"]["y_code"] == 23
    assert result.raw_metadata["missing_value_count"] == 2
    np.testing.assert_array_equal(dataset.X[0, :1], [1.25])
    assert np.isnan(dataset.X[0, 1:]).all()
    assert result.raw_metadata["blanked_range_cm-1"] == {"from": 800.0, "to": 400.0}
    assert result.raw_metadata["missing_value_policy"] == "explicit_processing_blank_preserved_no_imputation"
    assert result.raw_metadata["quantity_interpretation"] == {
        "displayed_quantity": "Transmittance",
        "display_authority": "qualified_nicolet_apex_omnic_9.16.233_observation",
        "ratio_units": "unresolved",
        "processing_final_format": "Single Beam",
    }
    assert len(result.warnings) == 1
    assert "Missing data preserved" in result.warnings[0]
    assert "does not impute values implicitly" in result.warnings[0]


@pytest.mark.parametrize(
    "payload",
    [
        _spa_bytes(y_code=23, values=(float("nan"), 2.5, 3.75)),
        _blanked_transmittance_spa_bytes(values=(1.25, float("nan"), 3.75)),
        _blanked_transmittance_spa_bytes(blank_from=700.0, blank_to=400.0),
    ],
)
def test_spa_refuses_nan_without_the_exact_qualified_processing_blank(tmp_path: Path, payload: bytes) -> None:
    source = tmp_path / "unqualified-missing.spa"
    source.write_bytes(payload)

    with pytest.raises(UnreadableSpectrumError, match="blank-range|blank range"):
        ingest(source)


def test_spa_projects_bounded_comments_history_experiment_and_linked_source_identity(tmp_path: Path) -> None:
    source = tmp_path / "metadata.spa"
    source.write_bytes(_metadata_spa_bytes())

    result = ingest(source)
    dataset = result.assets[0].dataset
    linked = result.raw_metadata["embedded_linked_sources"]

    assert result.raw_metadata["comments"] == ["operator comment"]
    assert result.raw_metadata["processing_history"] == ["Final format: Absorbance\r\nCorrection: None"]
    assert result.raw_metadata["experiment_information"] == [
        {
            "experiment_file": "qualification.exp",
            "experiment_title": "Apex qualification",
            "custom_text": "no correction",
            "accessory": "ATR accessory",
        }
    ]
    assert linked == [
        {
            "title": "demo.spa",
            "size_bytes": len(_spa_bytes()),
            "sha256": hashlib.sha256(_spa_bytes()).hexdigest(),
        }
    ]
    assert dataset.extra["omnic.comments"] == ["operator comment"]
    assert dataset.extra["omnic.processing_history"] == ["Final format: Absorbance\r\nCorrection: None"]
    assert dataset.extra["omnic.experiment_information"][0]["accessory"] == "ATR accessory"


def test_spa_refuses_nonqualified_linked_source_endpoint_encoding(tmp_path: Path) -> None:
    source = tmp_path / "bad-linked-source.spa"
    source.write_bytes(_metadata_spa_bytes(linked_size_delta=2))

    with pytest.raises(UnreadableSpectrumError, match="outside the source"):
        ingest(source)


def test_spa_refuses_key78_arithmetic_match_with_invalid_embedded_directory(tmp_path: Path) -> None:
    payload = bytearray(_metadata_spa_bytes())
    key78_row = 304 + 5 * 16
    linked_offset = struct.unpack_from("<I", payload, key78_row + 2)[0]
    nested_data_row = linked_offset + 320
    struct.pack_into("<I", payload, nested_data_row + 6, 13)
    source = tmp_path / "invalid-embedded-directory.spa"
    source.write_bytes(payload)

    with pytest.raises(UnsupportedFormatVariantError, match="embedded directory points outside"):
        ingest(source)


def test_wavelength_axis_does_not_fabricate_ir_technique(tmp_path: Path) -> None:
    payload = bytearray(_spa_bytes())
    payload[336 + 8] = 3
    source = tmp_path / "wavelength.spa"
    source.write_bytes(payload)
    dataset = ingest(source).assets[0].dataset
    assert dataset.feature_axis.units == "nm"
    assert dataset.feature_axis.quantity is AxisQuantity.WAVELENGTH
    assert dataset.domain.technique is None


def test_srs_rejects_sample_object_count_before_data_allocation(tmp_path: Path) -> None:
    payload = bytearray(_srs_bytes())
    struct.pack_into("<I", payload, 512 + 1026, 65_537)
    source = tmp_path / "too-many-rows.srs"
    source.write_bytes(payload)
    with pytest.raises(ParserLimitError, match="65537 blocks"):
        ingest(source)


def test_srs_never_materializes_the_complete_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = tmp_path / "streamed.srs"
    source_path.write_bytes(_srs_bytes())
    limits = ParserLimits()
    with BoundedSource(source_path, limits=limits) as source:
        reads: list[int] = []
        original = source.read_at

        def bounded_read(offset: int, length: int, *, format_id: str = "unknown") -> bytes:
            reads.append(length)
            return original(offset, length, format_id=format_id)

        monkeypatch.setattr(source, "read_at", bounded_read)
        result = PLUGIN.read(source, limits=limits)
    assert result.assets[0].dataset.shape == (2, 3)
    assert max(reads) <= 1024 * 1024


_REFERENCE_CASES = (
    {
        "relative": "irdata/carroucell_samp/10-Z22-Si-S7_0.SPA",
        "source_sha256": "fa4aa7961488fd521dacba1aa9ff4dea7fc3fc7475d1ed7a2e415c742be9604c",
        "shape": (1, 11098),
        "values_sha256": "002c44f46f3b250010fe055a1c3680b21fc2e9da7ecee32336475501e3d040ae",
        "axis_sha256": "1eb1d39242e6e0ab77685549cedceb5625bd54f63a89ab5976865bb638b9ce30",
        "sample_sha256": "56ab7790d5165ced03b28f1d279aa5687b8725b88462c219674cb253b67d58c9",
        "sample_identity_sha256": "31a4d3474c105a1e08c764a60b50e1c998bec3bdf46e0d202a7d79ddc5d8aca8",
        "variant": "spa-single-spectrum",
        "layout": None,
        "asset_id": "spectrum",
        "roles": ("sample", "spectral_feature"),
        "axis_units": "cm-1",
        "value_units": "absorbance",
        "quantity": "Absorbance",
    },
    {
        "relative": "irdata/nh4y-activation.spg",
        "source_sha256": "2631df843527782eb50e9c81eac54c59a113d16eb72c8ac0c7b427a3e79dd0ff",
        "shape": (55, 5549),
        "values_sha256": "42123a6324e34607c56a5c9659de9133eaab993d840322f169f7aedd34edf417",
        "axis_sha256": "508184be012d2db65fded343777464c2ac9f9a6e9ba09a3aa2b93fd9604ec879",
        "sample_sha256": "c7f151c3b0e4219da1276be09dca86dc5531ca959675e22aa33691e7a67eff63",
        "sample_identity_sha256": "145844a108091bbba6b611891f2c3540725b62cc4dc4dfbb35d02bbfa0ae54b4",
        "variant": "spg-compatible-spectrum-group",
        "layout": None,
        "asset_id": "spectra",
        "roles": ("sample", "spectral_feature"),
        "axis_units": "cm-1",
        "value_units": "absorbance",
        "quantity": "Absorbance",
    },
    {
        "relative": "irdata/CO@Mo_Al2O3.SPG",
        "source_sha256": "c128d65f9f655b07163b4adf4b4b2ceb3f701f95887d5cf466011db62d1ea1ae",
        "shape": (19, 3112),
        "values_sha256": "3867e3099e35e02429b8b68baa7a242e83bfcc193fcdf7c1d0725a40524bf59e",
        "axis_sha256": "9b9133dc3000742d005efa0b61a7b1581ea6e1f01a2dc38e886df04ca4868a44",
        "sample_sha256": "f247668ebcbbb0491551b12b1a13ad4442429a3d2028c938a94e5543daa171d5",
        "sample_identity_sha256": "09f23ee3ce881bbab7befcacddb557452bc13edbf4ea3d9a055cebf8521c6499",
        "variant": "spg-compatible-spectrum-group",
        "layout": None,
        "asset_id": "spectra",
        "roles": ("sample", "spectral_feature"),
        "axis_units": "cm-1",
        "value_units": "absorbance",
        "quantity": "Absorbance",
    },
    {
        "relative": "irdata/omnic_series/GC_Demo.srs",
        "source_sha256": "9e56ce5876b5f4d095a0dace87ce20e7a38802bb553b1f135ae8facf353e6c26",
        "shape": (788, 1738),
        "values_sha256": "30a89201acd15e61e707bace1892263c4b921ed753091ce88fc0d02fabc5aba1",
        "axis_sha256": "dab2998b3af9685f21d775526d55cf58fd63c48dbd73a4d85f5213a90d13bc00",
        "sample_sha256": "0def533543114f788cc89bb445908aa625584f08ecd2657925deda603dcd7053",
        "sample_identity_sha256": "91ef3af13d1630cfc9e6f0c046a3612c6062e9241a5bd28c82bd1ee814468f59",
        "variant": "srs-qualified-series",
        "layout": "srs-gc-tga",
        "asset_id": "series",
        "roles": ("sample", "spectral_feature"),
        "axis_units": "cm-1",
        "value_units": "percent",
        "quantity": "Transmittance",
    },
    {
        "relative": "irdata/omnic_series/TGA_demo.srs",
        "source_sha256": "a8adf8ce134a0e4327a88b4206b873dd7c4f3f480057f66c29755facb5ac5dbd",
        "shape": (485, 3630),
        "values_sha256": "aa64591ab718c4183453ef2f9212746052225c30a41cb7406c1e252a712868b3",
        "axis_sha256": "4bddc8eafdae0a66bb324bb0e41f045587a6128cb2b5afc28903ae054a2d3533",
        "sample_sha256": "de766e7c3f58fd6d98ce79a3e400d46e46fb53330cf1b372acc4f3ebaf843342",
        "sample_identity_sha256": "fdf1c100081777d436617fc4eb4e64c3b1981b1b2e4cb25d79f5e5e82fd771bb",
        "variant": "srs-qualified-series",
        "layout": "srs-gc-tga",
        "asset_id": "series",
        "roles": ("sample", "spectral_feature"),
        "axis_units": "cm-1",
        "value_units": "absorbance",
        "quantity": "Absorbance",
    },
    {
        "relative": "irdata/omnic_series/high_speed.srs",
        "source_sha256": "b5f0e4bab44f3de957300b1374e0b8e7459e5a4bc2b13aeafdf1f804ddf6f885",
        "shape": (897, 13898),
        "values_sha256": "df3442e932d3d7677b3baf7abb9ca61b061a1a2949015be29c92f95594d1da1a",
        "axis_sha256": "019d4bc2bcc3d61f00f248072a81ef2fed504cd6a7d1f3fc172b349d87c1095e",
        "sample_sha256": "b043379c25730488937b10a7acb2399956c1b85ee12731bf0119285d3b11439c",
        "sample_identity_sha256": "d8918b33011b359036ea43fccb4265ae413601b311fa50e8f170e7d6d24f058a",
        "variant": "srs-qualified-series",
        "layout": "srs-high-speed",
        "asset_id": "series",
        "roles": ("sample", "spectral_feature"),
        "axis_units": "cm-1",
        "value_units": "absorbance",
        "quantity": "Absorbance",
    },
    {
        "relative": "irdata/omnic_series/rapid_scan.srs",
        "source_sha256": "b5b579096efbdd9dfda72e009a749e4cd85e6d05c099b1264e3de01384a9e96e",
        "shape": (643, 4160),
        "values_sha256": "a045495406015661874ce50fcffd2343b27fc7eb20cbd11e08eaa07307bbd38b",
        "axis_sha256": "807da4dedcda208fb82fac83537c412fda225d6026c26e3539cbb7c5c5b77826",
        "sample_sha256": "41d775a397bf08a4cc9ec635b109ea4653ebe0b0d9bf9d18dfef845c48fd9ba6",
        "sample_identity_sha256": "7f5fe59bfe65992dd9d7fc8e28770aa00af3441017beaacbeb43c1e2be32a78a",
        "variant": "srs-qualified-series",
        "layout": "srs-rapid-scan-pristine",
        "asset_id": "series",
        "roles": ("sample", "feature"),
        "axis_units": None,
        "value_units": "V",
        "quantity": "Detector signal",
    },
    {
        "relative": "irdata/omnic_series/rapid_scan_reprocessed.srs",
        "source_sha256": "f36b16e2eb6f010220200de3eb70f847a698091327e4cf8a1700248bd3f0313a",
        "shape": (643, 3734),
        "values_sha256": "24fd9db0d806d4ab140a4df6d4ac58c419a80df6c6aee3c0bddf7911b631b586",
        "axis_sha256": "5378c389d19f6509647be6080eed55c9f5c8dc6d0d8e65192716fb44b945dca5",
        "sample_sha256": "41d775a397bf08a4cc9ec635b109ea4653ebe0b0d9bf9d18dfef845c48fd9ba6",
        "sample_identity_sha256": "7f5fe59bfe65992dd9d7fc8e28770aa00af3441017beaacbeb43c1e2be32a78a",
        "variant": "srs-qualified-series",
        "layout": "srs-rapid-scan-reprocessed",
        "asset_id": "series",
        "roles": ("sample", "spectral_feature"),
        "axis_units": "cm-1",
        "value_units": "absorbance",
        "quantity": "Absorbance",
    },
)


def _float64_digest(value: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(value, dtype="<f8").tobytes()).hexdigest()


def _source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sample_identity_digest(dataset) -> str:
    payload = json.dumps(
        {
            "labels": dataset.sample_axis.labels or [],
            "sample_table": dataset.sample_axis.sample_table or {},
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_checked_omnic_conformance_record_matches_executable_expectations() -> None:
    repository_root = Path(__file__).parents[3]
    manifest = json.loads((repository_root / "docs/evidence/native-omnic-reader-conformance.json").read_text())
    assert manifest["schema_version"] == "spectrasherpa-native-omnic-conformance/3"
    assert manifest["external_corpus_source"] == {
        "repository": "https://github.com/spectrochempy/spectrochempy_data",
        "commit": "08bb9b0cbff8f4363c48b6bff7ccb743f8140e0a",
        "path_root": "testdata",
        "license": None,
        "use_boundary": (
            "Exact-hash files are retrieved from the named public upstream commit only into an ephemeral "
            "qualification directory. They are not redistributed, cached, bundled, or downloaded by "
            "SpectraSherpa tests or runtime code."
        ),
    }
    expected_by_path = {str(item["relative"]): item for item in _REFERENCE_CASES}
    assert len(manifest["fixtures"]) == len(expected_by_path) == 8
    for fixture in manifest["fixtures"]:
        expected = expected_by_path[fixture["external_locator"]]
        assert fixture["source_sha256"] == expected["source_sha256"]
        assert tuple(fixture["shape"]) == expected["shape"]
        assert fixture["values_sha256"] == expected["values_sha256"]
        assert fixture["axis_sha256"] == expected["axis_sha256"]
        assert fixture["sample_sha256"] == expected["sample_sha256"]
        assert fixture["sample_identity_sha256"] == expected["sample_identity_sha256"]
        assert tuple(fixture["dimension_roles"]) == expected["roles"]
        assert fixture["asset_id"] == expected["asset_id"]
        assert fixture["series_layout"] == expected["layout"]
        assert fixture["axis_units"] == expected["axis_units"]
        assert fixture["value_units"] == expected["value_units"]
        assert fixture["data_quantity"] == expected["quantity"]

    kinetics = manifest["private_kinetics_qualification"]
    assert kinetics == {
        "status": "qualified_exact_private_archive_not_redistributed",
        "source_boundary": (
            "One operator-supplied Nicolet NXR archive is admitted only from an explicitly configured private "
            "path. The archive, extracted members, private path, and instrument-exported data are not committed, "
            "bundled, downloaded, or projected into public evidence."
        ),
        "redistribution_authority": None,
        "archive_sha256": "d62736e9dc277e072e84867e1b3ed2161ae0666d7dd27aba055a41a0c9c7f2f8",
        "archive_size_bytes": 1_036_973,
        "archive_member_count": 125,
        "archive_member_census": {"srs": 1, "spa": 62, "csv": 62, "decoded_member_bytes": 2_306_306},
        "srs_source_sha256": "327a915fb773e74a3b25684646218765d263c37ca2196060f6434b89f5d39055",
        "variant": "srs-qualified-series",
        "series_layout": "srs-kinetics",
        "asset_id": "series",
        "shape": [62, 935],
        "values_sha256": "a6545c842f8eff98e97994a309e5df1b47496188764bf3c4a69f2ad2f7f3b4a4",
        "axis_sha256": "8bfef7ca12cf55695667ae1d40839c287414114f538055bf1c18eddc1480d4a0",
        "sample_sha256": "135817187ec281d9ccd0524431180f34c89dfd2046fae24826d7c5870090a2fc",
        "sample_identity_sha256": "30a29a016b2e84affc3917ac97ecfff110c1ab54415971c0559b7942c717c7ec",
        "axis": {
            "title": "Raman shift",
            "units": "cm-1",
            "first": 3700.7177734375,
            "last": 98.28515625,
            "declared_order": "strictly_descending",
        },
        "sample_time": {
            "units": "min",
            "first": 4.196333408355713,
            "last": 370.2668151855469,
            "interval_seconds": 360.06932258605957,
        },
        "data_quantity": "Raman intensity",
        "value_units": None,
        "cross_format_oracles": {
            "spa_rows_compared": 62,
            "srs_row_vs_spa": "bit_exact_float64_after_exact_float32_promotion",
            "csv_rows_compared": 62,
            "observed_csv_axis_max_abs_error_cm-1": 0.0006609676129301079,
            "observed_csv_value_max_abs_error": 4.998168945391512e-7,
            "csv_axis_max_abs_tolerance_cm-1": 0.000661,
            "csv_value_max_abs_tolerance": 5e-7,
            "csv_note": (
                "CSV precision is text-rounded; each exported ascending row is reversed once before comparison "
                "with the declared descending source axis."
            ),
        },
        "claim_boundary": (
            "This qualifies only the closed extended-directory Kinetics grammar and this exact private source "
            "triplet. It does not redistribute the source, certify every SRS variant, or add support for Thermo "
            "Paradigm/OMNICxi containers."
        ),
    }


REPO_ROOT = Path(__file__).resolve().parents[3]
BUNDLED_ROOT = Path(__file__).parent / "fixtures" / "omnic"


def _bundled_omnic_cases() -> list[dict]:
    record = json.loads((REPO_ROOT / "docs" / "evidence" / "native-omnic-reader-conformance.json").read_text())
    return list(record["bundled_fixtures"])


@pytest.mark.parametrize("expected", _bundled_omnic_cases(), ids=lambda item: item["filename"])
def test_bundled_omnic_reference_science_is_exact(expected: dict) -> None:
    """Redistributable OMNIC conformance runs on every checkout, never skipped."""
    source = BUNDLED_ROOT / expected["filename"]
    assert source.is_file(), f"bundled OMNIC conformance fixture is missing: {source}"
    assert _source_digest(source) == expected["source_sha256"]
    result = ingest(source)
    assert result.variant == expected["variant"]
    assert result.raw_metadata.get("series_layout") == expected["layout"]
    assert len(result.assets) == 1
    asset = result.assets[0]
    dataset = asset.dataset
    assert asset.asset_id == expected["asset_id"]
    assert list(asset.dimension_roles) == expected["roles"]
    assert list(dataset.shape) == expected["shape"]
    assert _float64_digest(dataset.X) == expected["values_sha256"]
    assert _float64_digest(dataset.feature_axis.values) == expected["axis_sha256"]
    assert _float64_digest(dataset.sample_axis.values) == expected["sample_sha256"]
    assert _sample_identity_digest(dataset) == expected["sample_identity_sha256"]
    assert dataset.feature_axis.units == expected["axis_units"]
    assert dataset.units == expected["value_units"]
    assert dataset.domain.data_quantity == expected["quantity"]
    assert dataset.title == expected["title"]


@pytest.mark.parametrize("expected", _REFERENCE_CASES, ids=lambda item: Path(item["relative"]).name)
def test_external_exact_hash_omnic_reference_science_when_available(expected: dict[str, object]) -> None:
    configured = os.environ.get("SPECTRA_EXTERNAL_VENDOR_CORPUS")
    corpus_root = Path(configured) if configured else Path.home() / ".spectrochempy/testdata"
    source = corpus_root / str(expected["relative"])
    if not source.exists():
        if os.environ.get("SPECTRA_REQUIRE_EXTERNAL_VENDOR_CORPUS") == "1":
            pytest.fail(f"required external exact-hash OMNIC reference is missing: {expected['relative']}")
        pytest.skip(
            "OMNIC SPG/SRS conformance uses files SpectraSherpa is not licensed to redistribute; "
            "bundled SPA conformance always runs"
        )
    assert _source_digest(source) == expected["source_sha256"]
    result = ingest(source)
    assert result.variant == expected["variant"]
    assert result.raw_metadata.get("series_layout") == expected["layout"]
    assert len(result.assets) == 1
    asset = result.assets[0]
    dataset = asset.dataset
    assert asset.asset_id == expected["asset_id"]
    assert asset.dimension_roles == expected["roles"]
    assert dataset.shape == expected["shape"]
    assert _float64_digest(dataset.X) == expected["values_sha256"]
    assert _float64_digest(dataset.feature_axis.values) == expected["axis_sha256"]
    assert _float64_digest(dataset.sample_axis.values) == expected["sample_sha256"]
    assert _sample_identity_digest(dataset) == expected["sample_identity_sha256"]
    assert dataset.feature_axis.units == expected["axis_units"]
    assert dataset.units == expected["value_units"]
    assert dataset.domain.data_quantity == expected["quantity"]


def test_private_nxr_kinetics_archive_matches_every_spa_and_csv_export(tmp_path: Path) -> None:
    """Qualify the private 62-row NXR Kinetics source without redistributing it."""

    configured = os.environ.get("SPECTRA_PRIVATE_NXR_SRS_ARCHIVE")
    if not configured:
        pytest.skip("private NXR Kinetics SRS archive is not configured")
    archive_path = Path(configured)
    assert _source_digest(archive_path) == "d62736e9dc277e072e84867e1b3ed2161ae0666d7dd27aba055a41a0c9c7f2f8"
    assert archive_path.stat().st_size == 1_036_973
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        srs_names = sorted(name for name in names if name.lower().endswith(".srs"))
        spa_by_stem = {Path(name).stem: name for name in names if name.lower().endswith(".spa")}
        csv_by_stem = {Path(name).stem: name for name in names if name.lower().endswith(".csv")}
        assert len(infos) == 125
        assert len({info.filename for info in infos}) == len(infos)
        assert all(Path(info.filename).name == info.filename for info in infos)
        assert all(not info.is_dir() and 0 < info.file_size <= 512 * 1024 for info in infos)
        assert sum(info.file_size for info in infos) == 2_306_306
        assert len(srs_names) == 1
        assert len(spa_by_stem) == len(csv_by_stem) == 62
        assert set(spa_by_stem) == set(csv_by_stem)

        srs_bytes = archive.read(srs_names[0])
        assert hashlib.sha256(srs_bytes).hexdigest() == (
            "327a915fb773e74a3b25684646218765d263c37ca2196060f6434b89f5d39055"
        )
        srs_path = tmp_path / "qualified-private-series.srs"
        srs_path.write_bytes(srs_bytes)
        srs_result = ingest(srs_path)
        srs_dataset = srs_result.assets[0].dataset
        assert srs_result.raw_metadata["series_layout"] == "srs-kinetics"
        assert srs_dataset.shape == (62, 935)
        assert srs_dataset.feature_axis.units == "cm-1"
        assert srs_dataset.domain.technique == "Raman"
        assert srs_dataset.domain.data_quantity == "Raman intensity"
        assert srs_dataset.sample_axis.units == "min"
        assert srs_dataset.sample_axis.labels[0] == "Linked spectrum at 4.196 min."
        assert srs_dataset.sample_axis.labels[-1] == "Linked spectrum at 370.267 min."
        assert _float64_digest(srs_dataset.X) == ("a6545c842f8eff98e97994a309e5df1b47496188764bf3c4a69f2ad2f7f3b4a4")
        assert _float64_digest(srs_dataset.feature_axis.values) == (
            "8bfef7ca12cf55695667ae1d40839c287414114f538055bf1c18eddc1480d4a0"
        )
        assert _float64_digest(srs_dataset.sample_axis.values) == (
            "135817187ec281d9ccd0524431180f34c89dfd2046fae24826d7c5870090a2fc"
        )
        assert _sample_identity_digest(srs_dataset) == (
            "30a29a016b2e84affc3917ac97ecfff110c1ab54415971c0559b7942c717c7ec"
        )

        max_axis_csv_error = 0.0
        max_value_csv_error = 0.0
        for index, stem in enumerate(sorted(spa_by_stem)):
            spa_path = tmp_path / f"paired-{index:04d}.spa"
            spa_path.write_bytes(archive.read(spa_by_stem[stem]))
            spa_dataset = ingest(spa_path).assets[0].dataset
            csv_values = np.loadtxt(io.BytesIO(archive.read(csv_by_stem[stem])), delimiter=",")
            np.testing.assert_array_equal(srs_dataset.X[index], spa_dataset.X[0])
            np.testing.assert_array_equal(srs_dataset.feature_axis.values, spa_dataset.feature_axis.values)
            max_axis_csv_error = max(
                max_axis_csv_error,
                float(np.max(np.abs(spa_dataset.feature_axis.values - csv_values[::-1, 0]))),
            )
            max_value_csv_error = max(
                max_value_csv_error,
                float(np.max(np.abs(spa_dataset.X[0] - csv_values[::-1, 1]))),
            )
        assert max_axis_csv_error == 0.0006609676129301079
        assert max_value_csv_error == 4.998168945391512e-7
        assert max_axis_csv_error <= 6.61e-4
        assert max_value_csv_error <= 5.0e-7
