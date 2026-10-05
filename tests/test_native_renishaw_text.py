"""Qualification tests for Renishaw WiRE single-spectrum text exports."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.core.axis_semantics import AxisQuantity
from spectra_sherpa.ingestion_errors import (
    ParserLimitError,
    UnreadableSpectrumError,
    UnsupportedFormatError,
    UnsupportedFormatVariantError,
)
from spectra_sherpa.io import ingest
from spectra_sherpa.io.types import ParserLimits


def _write(tmp_path: Path, body: str, *, name: str = "source.txt") -> Path:
    path = tmp_path / name
    path.write_bytes(body.encode("ascii"))
    return path


def test_renishaw_single_spectrum_text_is_typed_raman_dataset(tmp_path: Path):
    source = _write(
        tmp_path,
        "#Wave\t\t#Intensity\r\n1362.5\t83.25\r\n1000.0\t120.5\r\n168.9\t225.0\r\n",
    )

    result = ingest(source)
    asset = result.assets[0]
    dataset = asset.dataset

    assert result.format_id == "renishaw-text"
    assert result.variant == "wire-single-spectrum-tab"
    assert result.parser_id == "spectrasherpa.native.renishaw_text"
    assert len(result.source_members) == 1
    assert result.source_members[0].sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert asset.asset_id == "spectrum"
    assert asset.dimension_roles == ("sample", "spectral_feature")
    assert dataset.shape == (1, 3)
    np.testing.assert_array_equal(dataset.X, [[83.25, 120.5, 225.0]])
    np.testing.assert_array_equal(dataset.feature_axis.values, [1362.5, 1000.0, 168.9])
    assert dataset.feature_axis.title == "Raman shift"
    assert dataset.feature_axis.units == "cm-1"
    assert dataset.feature_axis.quantity is AxisQuantity.RAMAN_SHIFT
    assert dataset.domain.technique == "Raman"
    assert dataset.domain.data_quantity == "Raman intensity"
    assert dataset.domain.instrument is None
    assert dataset.units is None
    assert dataset.data_role == "X_spectra"
    assert dataset.target is None
    assert dataset.extra["renishaw_text.axis_order"] == "descending"
    assert dataset.extra["renishaw_text.export_software"] == "Renishaw WiRE"
    assert "original WDF" in result.warnings[0]


def test_renishaw_single_tab_header_is_same_closed_grammar(tmp_path: Path):
    source = _write(tmp_path, "#Wave\t#Intensity\n100\t1\n101\t2\n")

    dataset = ingest(source).assets[0].dataset

    np.testing.assert_array_equal(dataset.feature_axis.values, [100.0, 101.0])
    assert dataset.extra["renishaw_text.axis_order"] == "ascending"


def test_renishaw_text_uses_the_same_canonical_workbench_source_path(tmp_path: Path):
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa
    from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode

    source = _write(tmp_path, "#Wave\t#Intensity\n100\t1\n101\t2\n")
    registry_dataset = ingest(source).assets[0].dataset
    canonical_dataset = load_canonical_file_as_sherpa(source)
    node_dataset = FileLoadNode(
        "renishaw-source",
        {"experiment_id": 1, "file_id": 1, "stage": "raw"},
    )._load_file(source)

    for dataset in (canonical_dataset, node_dataset):
        np.testing.assert_array_equal(dataset.X, registry_dataset.X)
        np.testing.assert_array_equal(dataset.feature_axis.values, registry_dataset.feature_axis.values)
        assert dataset.feature_axis.title == "Raman shift"
        assert dataset.feature_axis.units == "cm-1"
        assert dataset.target is None


@pytest.mark.parametrize(
    "header",
    [
        "#Wave,#Intensity",
        "#Time\t#Wave\t#Intensity",
        "#X\t#Y\t#Wave\t#Intensity",
    ],
)
def test_unknown_or_multidimensional_text_is_not_claimed(tmp_path: Path, header: str):
    source = _write(tmp_path, f"{header}\n100\t1\n101\t2\n")

    with pytest.raises(UnsupportedFormatError, match="No registered parser structurally recognizes"):
        ingest(source)


def test_unmarked_two_column_text_is_a_generic_table_not_renishaw(tmp_path: Path):
    source = _write(tmp_path, "Wave\tIntensity\n100\t1\n101\t2\n")

    assert ingest(source).format_id == "csv"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("#Wave\t#Intensity\n100\t1\n", "at least two numeric rows"),
        ("#Wave\t#Intensity\n100\t1\n101\t2\t3\n", "exactly two tab-separated"),
        ("#Wave\t#Intensity\n100\t1\n101\tnot-a-number\n", "is not numeric"),
        ("#Wave\t#Intensity\n100\t1\n101\tnan\n", "must be finite"),
        ("#Wave\t#Intensity\n100\t1\n99\t2\n100\t3\n", "strictly monotonic"),
    ],
)
def test_malformed_claimed_renishaw_text_fails_closed(tmp_path: Path, body: str, message: str):
    source = _write(tmp_path, body)

    with pytest.raises(UnreadableSpectrumError, match=message):
        ingest(source)


def test_renishaw_text_resource_limit_refuses_before_array_allocation(tmp_path: Path):
    source = _write(tmp_path, "#Wave\t#Intensity\n100\t1\n101\t2\n102\t3\n")

    with pytest.raises(ParserLimitError, match="declares 6 decoded elements"):
        ingest(source, limits=ParserLimits(max_decoded_elements=5))


def test_renishaw_text_parser_options_refuse(tmp_path: Path):
    source = _write(tmp_path, "#Wave\t#Intensity\n100\t1\n101\t2\n")

    with pytest.raises(UnsupportedFormatVariantError, match="does not admit parser options"):
        ingest(source, parser_options={"csv_layout": "headered"})
