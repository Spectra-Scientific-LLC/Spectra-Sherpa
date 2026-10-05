from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from scipy.io import loadmat, savemat

from spectra_sherpa.app.lib.process_log import WAFER_TIME_AVERAGE_SCHEMA, wafer_time_average
from spectra_sherpa.app.lib.reference_artifacts import (
    ReferenceArtifact,
    ReferenceArtifactRegistry,
    ReferenceProjection,
)
from spectra_sherpa.app.lib.reference_datasets import feature_axis_values_digest
from spectra_sherpa.app.lib.reference_materialization import (
    materialize_reference_member,
    reference_source_projection_digest,
)
from spectra_sherpa.core.dimension_roles import DimensionRole
from spectra_sherpa.ingestion_errors import ParserLimitError, UnreadableSpectrumError
from spectra_sherpa.io import ParserLimits, ingest
from spectra_sherpa.io.formats.dso import scipy_struct_fields
from spectra_sherpa.io.formats.process_log import process_log_footprint


def _cells(values: list[np.ndarray]) -> np.ndarray:
    result = np.empty((len(values), 1), dtype=object)
    for index, value in enumerate(values):
        result[index, 0] = np.asfortranarray(value, dtype=np.float64)
    return result


def _write_process_log(
    path: Path,
    *,
    calibration: list[np.ndarray] | None = None,
    test: list[np.ndarray] | None = None,
) -> tuple[Path, list[np.ndarray], list[np.ndarray]]:
    calibration = calibration or [
        np.asarray([[1.0, 10.0], [3.0, 30.0]]),
        np.asarray([[2.0, 20.0], [4.0, 40.0], [8.0, 80.0]]),
    ]
    test = test or [np.asarray([[5.0, 50.0], [7.0, 70.0]])]
    feature_count = int(calibration[0].shape[1])
    savemat(
        path,
        {
            "OESDATA": {
                "INFORMATION": np.asarray(["Generated process log", ""]),
                "calibration": _cells(calibration),
                "calib_names": np.asarray(["cal-1", "cal-2"]),
                "test": _cells(test),
                "test_names": np.asarray(["test-1"]),
                "fault_names": np.asarray(["fault-a"]),
                "wave_axis": np.linspace(250.0, 300.0, feature_count).reshape(1, -1),
            }
        },
        do_compression=True,
    )
    return path, calibration, test


def test_matlab_process_log_preserves_wafer_time_feature_authority(tmp_path: Path) -> None:
    source, _calibration, _test = _write_process_log(tmp_path / "oes.mat")

    result = ingest(source)

    assert result.parser_version == "6"
    assert result.raw_metadata["matlab.process_log_variables"] == ["OESDATA"]
    assert len(result.warnings) == 1
    assert "structural padding" in result.warnings[0]
    assert [asset.asset_id for asset in result.assets] == ["OESDATA"]
    asset = result.assets[0]
    dataset = asset.dataset
    assert dataset.shape == (3, 3, 2)
    assert asset.dimension_roles == (
        DimensionRole.SAMPLE,
        DimensionRole.TIME_POINT,
        DimensionRole.SPECTRAL_FEATURE,
    )
    assert dataset.layout.kind == "batch"
    assert dataset.axis(1).title == "Process time point"
    assert dataset.feature_axis.values.tolist() == [250.0, 300.0]
    assert dataset.sample_axis.labels == ["cal-1", "cal-2", "test-1"]
    assert dataset.sample_axis.sample_table == {
        "sample_id": ["cal-1", "cal-2", "test-1"],
        "source_partition": ["calibration", "calibration", "test"],
        "fault_name": ["normal", "normal", "fault-a"],
        "time_point_count": [2, 3, 2],
    }
    assert np.isnan(dataset.X[0, 2]).all()
    assert dataset.provenance.operations == ["import.matlab_process_log"]


def test_wafer_time_average_is_explicit_and_reproduces_source_column_order(tmp_path: Path) -> None:
    source, calibration, test = _write_process_log(tmp_path / "oes.mat")
    raw = ingest(source).assets[0].dataset

    averaged = wafer_time_average(raw, node_id="average-1")

    expected = np.vstack([np.mean(wafer, axis=0) for wafer in (*calibration, *test)])
    assert np.array_equal(averaged.X, expected)
    assert averaged.shape == (3, 2)
    assert averaged.layout.mode_roles == (DimensionRole.SAMPLE, DimensionRole.SPECTRAL_FEATURE)
    assert averaged.sample_axis.sample_table["time_point_count"] == [2, 3, 2]
    assert averaged.provenance.operations == ["import.matlab_process_log", "preprocess.wafer_time_average"]
    operation = averaged.provenance[-1]
    assert operation.node_id == "average-1"
    assert operation.timestamp == ""
    assert operation.parameters == {
        "schema_version": WAFER_TIME_AVERAGE_SCHEMA,
        "reduction_order": "source-column-major",
        "time_dimension": 1,
        "time_point_counts": (2, 3, 2),
    }
    assert averaged.extra["sherpa.wafer_time_average"]["input_scientific_digest"] == raw.scientific_digest
    repeated = wafer_time_average(raw, node_id="average-1")
    assert repeated.scientific_digest == averaged.scientific_digest


def test_wafer_time_average_refuses_values_outside_governed_source_length(tmp_path: Path) -> None:
    source, _calibration, _test = _write_process_log(tmp_path / "oes.mat")
    raw = ingest(source).assets[0].dataset
    raw.X[0, 2, 0] = 999.0

    with pytest.raises(ValueError, match="outside the governed time-point count"):
        wafer_time_average(raw)


def test_process_log_nested_output_is_parser_limit_bound(tmp_path: Path) -> None:
    source, _calibration, _test = _write_process_log(tmp_path / "oes.mat")

    with pytest.raises(ParserLimitError, match="decoded elements"):
        ingest(source, limits=ParserLimits(max_decoded_elements=32))


def test_process_log_numeric_axis_is_included_in_decoded_limits(tmp_path: Path) -> None:
    features = 10
    calibration = [np.ones((2, features)), np.ones((2, features))]
    test = [np.ones((2, features))]
    source, _calibration, _test = _write_process_log(
        tmp_path / "axis-budget.mat",
        calibration=calibration,
        test=test,
    )
    payload = loadmat(source, squeeze_me=False, struct_as_record=True)
    footprint = process_log_footprint(scipy_struct_fields(payload["OESDATA"]))

    source_elements = 3 * 2 * features
    padded_output_elements = source_elements
    assert footprint.elements == source_elements + padded_output_elements + features
    assert footprint.decoded_bytes == footprint.elements * np.dtype(np.float64).itemsize
    assert footprint.blocks == 10

    outer_struct_bytes = 64
    previously_undercharged_budget = (
        source.stat().st_size
        + outer_struct_bytes
        + (source_elements + padded_output_elements) * np.dtype(np.float64).itemsize
    )
    previously_undercharged_elements = 1 + source_elements + padded_output_elements
    with pytest.raises(ParserLimitError, match="decoded elements"):
        ingest(source, limits=ParserLimits(max_decoded_elements=previously_undercharged_elements))
    with pytest.raises(ParserLimitError, match="decoded bytes"):
        ingest(source, limits=ParserLimits(max_decoded_bytes=previously_undercharged_budget))


def test_process_log_refuses_mismatched_feature_counts(tmp_path: Path) -> None:
    source, _calibration, _test = _write_process_log(
        tmp_path / "oes.mat",
        calibration=[np.ones((2, 2)), np.ones((2, 3))],
    )

    with pytest.raises(UnreadableSpectrumError, match="feature counts differ"):
        ingest(source)


def test_registered_process_log_materialization_records_repeatable_explicit_average(tmp_path: Path) -> None:
    source, calibration, test = _write_process_log(tmp_path / "oes.mat")
    member_bytes = source.read_bytes()
    expected = np.vstack([np.mean(wafer, axis=0) for wafer in (*calibration, *test)])
    member_sha256 = hashlib.sha256(member_bytes).hexdigest()
    artifact = ReferenceArtifact(
        {
            "artifact_id": "process-log-fixture-v1",
            "title": "Process log fixture",
            "description": "Test-only process log",
            "provider": "Eigenvector Research",
            "provider_page": "https://eigenvector.com/resources/data-sets/",
            "download_url": "https://eigenvector.com/process-log-fixture.zip",
            "expected_size_bytes": 1,
            "sha256": "0" * 64,
            "media_type": "application/zip",
            "redistribution": "upstream_only_not_redistributed",
            "attribution": "Test attribution",
            "no_endorsement": "No endorsement",
            "qualification_status": "qualified",
            "reviewed_at": "2026-09-12",
            "members": [
                {
                    "path": source.name,
                    "expected_size_bytes": len(member_bytes),
                    "sha256": member_sha256,
                }
            ],
        }
    )
    projection = ReferenceProjection(
        {
            "projection_id": "process-log-projection-v1",
            "artifact_id": artifact.artifact_id,
            "title": "Process log projection",
            "member_path": source.name,
            "native_reader_contract": "spectrasherpa.matlab-process-log/1",
            "object_name": "OESDATA",
            "target_object_name": None,
            "target_index": None,
            "target_name": None,
            "target_units": None,
            "n_samples": 3,
            "n_features": 2,
            "feature_axis_title": "Wavelength",
            "feature_axis_units": "nm",
            "feature_axis_sha256": feature_axis_values_digest(np.asarray([250.0, 300.0])),
            "scientific_sha256": reference_source_projection_digest(expected),
            "qualification_status": "qualified",
            "analysis": {
                "primary_role": "X_spectra",
                "modality": "spectra",
                "technique": "OES",
                "target_type": None,
                "target_fields": [],
                "identity_fields": [],
                "group_fields": [],
                "ordered_samples": False,
            },
        }
    )
    registry = ReferenceArtifactRegistry(artifacts=(artifact,), projections=(projection,))

    first = materialize_reference_member(source, projection.projection_id, registry=registry)
    second = materialize_reference_member(source, projection.projection_id, registry=registry)

    assert np.array_equal(first.dataset.X, expected)
    assert first.dataset.provenance.operations == [
        "import.matlab_process_log",
        "preprocess.wafer_time_average",
        "import.registered_reference",
    ]
    assert first.dataset.scientific_digest == second.dataset.scientific_digest
    assert first.portable_reference["native_reader_contract"] == "spectrasherpa.matlab-process-log/1"
