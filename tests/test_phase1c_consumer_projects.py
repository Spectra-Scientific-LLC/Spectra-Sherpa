"""Executable evidence for current scientist-facing consumer projects."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.core.execution_runtime import ResolvedExperimentFile
from tests._optional_scp import HAS_SCP
from tests.consumer_project_harness import (
    ConsumerProjectSource,
    execute_consumer_project,
    load_consumer_project,
)


def _bind_exact_file_record(
    *,
    data_root,
    relative_path: str,
    experiment_id: int,
    file_id: int,
    extra_parameters: dict[str, object] | None = None,
    prepared_overrides: dict[str, object] | None = None,
) -> ConsumerProjectSource:
    """Grant one exact test-owned file to the consumer-project executor."""

    source_path = data_root / "experiments" / f"exp_{experiment_id:03d}" / relative_path
    assert source_path.is_file()
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    parameters = {"experiment_id": experiment_id, "file_id": file_id, "stage": "raw"}
    for key, value in (extra_parameters or {}).items():
        if key == "target_authority":
            authority = dict(value)  # type: ignore[arg-type]
            authority["source_digest"] = source_sha256
            parameters[key] = authority
        else:
            parameters[key] = value
    return ConsumerProjectSource(
        parameters=parameters,
        resolved_file=ResolvedExperimentFile(
            path=str(source_path),
            original_file_path=relative_path,
            created_datetime="2026-08-12T00:00:00+00:00",
            size_bytes=source_path.stat().st_size,
            sha256=source_sha256,
            prepared_overrides=prepared_overrides or {},
        ),
    )


def _bind_exact_file_records(
    *, data_root, records: list[dict[str, object]]
) -> dict[tuple[int, int, str], ConsumerProjectSource]:
    """Grant an exact, closed set of test-owned files."""

    return {
        (int(record["experiment_id"]), int(record["file_id"]), str(record["stage"])): _bind_exact_file_record(
            data_root=data_root,
            relative_path=str(record["relative_path"]),
            experiment_id=int(record["experiment_id"]),
            file_id=int(record["file_id"]),
        )
        for record in records
    }


@pytest.fixture
def canonical_raman_source(tmp_path) -> ConsumerProjectSource:
    """Bind the Raman project to one deterministic, portable spectral file."""

    sample_count = 18
    feature_count = 81
    axis = np.linspace(400.0, 1800.0, feature_count)
    rng = np.random.default_rng(20260812)
    baseline = 0.15 + 0.00025 * (axis - axis.min())
    peak_a = np.exp(-0.5 * ((axis - 810.0) / 32.0) ** 2)
    peak_b = 0.65 * np.exp(-0.5 * ((axis - 1330.0) / 48.0) ** 2)
    matrix = np.vstack(
        [
            baseline
            + (0.8 + 0.025 * sample) * peak_a
            + (0.5 + 0.015 * sample) * peak_b
            + rng.normal(0.0, 0.002, feature_count)
            for sample in range(sample_count)
        ]
    )
    # Interior, isolated detector spikes exercise the declared Hampel rule.
    matrix[2, 21] += 4.0
    matrix[11, 57] += 5.0

    data_root = tmp_path / "data"
    relative_path = "raw/phase1c-raman.csv"
    source_path = data_root / "experiments" / "exp_007" / relative_path
    source_path.parent.mkdir(parents=True)
    header = ["sample", *(f"{value:.6f}" for value in axis)]
    rows = [",".join(header)]
    for sample, values in enumerate(matrix, start=1):
        rows.append(",".join([f"raman-{sample:02d}", *(f"{value:.12g}" for value in values)]))
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=7,
        file_id=12,
    )


@pytest.fixture
def canonical_hca_source(tmp_path) -> ConsumerProjectSource:
    """Bind the HCA project to three separated spectral cohorts."""

    rng = np.random.default_rng(20260812)
    sample_count = 12
    feature_count = 24
    axis = np.linspace(900.0, 1800.0, feature_count)
    matrix = np.vstack(
        [rng.normal(loc=center, scale=0.08, size=(sample_count, feature_count)) for center in (-2.0, 0.0, 2.0)]
    )
    data_root = tmp_path / "data"
    relative_path = "raw/phase1c-hca.csv"
    source_path = data_root / "experiments" / "exp_019" / relative_path
    source_path.parent.mkdir(parents=True)
    rows = [",".join(["sample", *(f"{value:.6f}" for value in axis)])]
    for sample, values in enumerate(matrix):
        rows.append(",".join([f"cohort-{sample:02d}", *(f"{value:.12g}" for value in values)]))
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=19,
        file_id=23,
    )


@pytest.fixture
def canonical_partition_clustering_source(tmp_path) -> ConsumerProjectSource:
    """Bind the partition-comparison project to three separated cohorts."""

    rng = np.random.default_rng(20260813)
    sample_count = 14
    feature_count = 20
    axis = np.linspace(900.0, 1800.0, feature_count)
    matrix = np.vstack(
        [rng.normal(loc=center, scale=0.06, size=(sample_count, feature_count)) for center in (-3.0, 0.0, 3.0)]
    )
    data_root = tmp_path / "data"
    relative_path = "raw/phase2-partition-clustering.csv"
    source_path = data_root / "experiments" / "exp_026" / relative_path
    source_path.parent.mkdir(parents=True)
    rows = [",".join(["sample", *(f"{value:.6f}" for value in axis)])]
    for sample, values in enumerate(matrix):
        rows.append(",".join([f"partition-{sample:02d}", *(f"{value:.12g}" for value in values)]))
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=26,
        file_id=39,
    )


@pytest.fixture
def canonical_nmf_source(tmp_path) -> ConsumerProjectSource:
    """Bind NMF to a reproducible three-component non-negative mixture."""

    rng = np.random.default_rng(20260813)
    sample_count = 36
    feature_count = 30
    axis = np.linspace(900.0, 1800.0, feature_count)
    concentrations = rng.uniform(0.1, 1.0, size=(sample_count, 3))
    spectra = rng.uniform(0.1, 1.0, size=(3, feature_count))
    matrix = concentrations @ spectra
    data_root = tmp_path / "data"
    relative_path = "raw/phase2-nmf-mixtures.csv"
    source_path = data_root / "experiments" / "exp_027" / relative_path
    source_path.parent.mkdir(parents=True)
    rows = [",".join(["sample", *(f"{value:.6f}" for value in axis)])]
    for sample, values in enumerate(matrix):
        rows.append(",".join([f"mixture-{sample:02d}", *(f"{value:.12g}" for value in values)]))
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=27,
        file_id=40,
    )


@pytest.fixture
def canonical_evolving_mixture_source(tmp_path) -> ConsumerProjectSource:
    """Bind EFA and SIMPLISMA to one measured-order three-component mixture."""

    sample_count = 48
    feature_count = 40
    axis = np.linspace(900.0, 1800.0, feature_count)
    profiles = np.vstack(
        (
            np.exp(-0.5 * ((axis - 1080.0) / 55.0) ** 2),
            np.exp(-0.5 * ((axis - 1360.0) / 75.0) ** 2),
            np.exp(-0.5 * ((axis - 1640.0) / 45.0) ** 2),
        )
    )
    progress = np.linspace(0.0, 1.0, sample_count)
    concentrations = np.column_stack(
        (
            np.clip(1.0 - 1.4 * progress, 0.0, None),
            np.sin(np.pi * progress) ** 2,
            np.clip(1.4 * progress - 0.4, 0.0, None),
        )
    )
    matrix = (concentrations + 0.015) @ profiles + 0.001
    data_root = tmp_path / "data"
    relative_path = "raw/phase2-evolving-mixture.csv"
    source_path = data_root / "experiments" / "exp_028" / relative_path
    source_path.parent.mkdir(parents=True)
    rows = [",".join(["sample", *(f"{value:.6f}" for value in axis)])]
    for sample, values in enumerate(matrix):
        rows.append(",".join([f"evolution-{sample:02d}", *(f"{value:.12g}" for value in values)]))
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=28,
        file_id=41,
        prepared_overrides={"is_time_series": True},
    )


@pytest.fixture
def canonical_pca_source(tmp_path) -> ConsumerProjectSource:
    """Bind the PCA project to one low-rank spectral cohort with one outlier."""

    rng = np.random.default_rng(20260812)
    sample_count = 36
    feature_count = 32
    axis = np.linspace(900.0, 1800.0, feature_count)
    latent = rng.normal(size=(sample_count, 3))
    loadings = rng.normal(size=(3, feature_count))
    matrix = 2.0 + latent @ loadings + rng.normal(0.0, 0.01, size=(sample_count, feature_count))
    matrix[-1] += 4.0
    data_root = tmp_path / "data"
    relative_path = "raw/phase1c-pca.csv"
    source_path = data_root / "experiments" / "exp_021" / relative_path
    source_path.parent.mkdir(parents=True)
    rows = [",".join(["sample", *(f"{value:.6f}" for value in axis)])]
    for sample, values in enumerate(matrix):
        rows.append(",".join([f"pca-{sample:02d}", *(f"{value:.12g}" for value in values)]))
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=21,
        file_id=27,
    )


@pytest.fixture
def canonical_peak_source(tmp_path) -> ConsumerProjectSource:
    """Bind the peak project to spectra with two stable resolved bands."""

    axis = np.linspace(900.0, 1800.0, 301)
    matrix = np.vstack(
        [
            0.15
            + (0.9 + 0.03 * sample) * np.exp(-0.5 * ((axis - 1125.0) / 18.0) ** 2)
            + (0.7 - 0.01 * sample) * np.exp(-0.5 * ((axis - 1575.0) / 24.0) ** 2)
            for sample in range(10)
        ]
    )
    data_root = tmp_path / "data"
    relative_path = "raw/phase2-peaks.csv"
    source_path = data_root / "experiments" / "exp_024" / relative_path
    source_path.parent.mkdir(parents=True)
    rows = [",".join(["sample", *(f"{value:.6f}" for value in axis)])]
    rows.extend(
        ",".join([f"peak-{sample:02d}", *(f"{value:.12g}" for value in values)]) for sample, values in enumerate(matrix)
    )
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=24,
        file_id=35,
    )


@pytest.fixture
def canonical_selection_source(tmp_path) -> ConsumerProjectSource:
    """Bind the comparison project to one quantitative spectral fixture."""

    sample_count = 48
    feature_count = 32
    axis = np.linspace(1000.0, 2500.0, feature_count)
    rng = np.random.default_rng(20260813)
    latent = rng.normal(size=(sample_count, 3))
    loadings = rng.normal(size=(3, feature_count))
    matrix = 1.5 + latent @ loadings + rng.normal(0.0, 0.03, (sample_count, feature_count))
    response = 2.5 * latent[:, 0] - 1.2 * latent[:, 1] + 0.35 * latent[:, 2]
    response += rng.normal(0.0, 0.02, sample_count)

    data_root = tmp_path / "data"
    relative_path = "raw/phase1c-selection.csv"
    source_path = data_root / "experiments" / "exp_008" / relative_path
    source_path.parent.mkdir(parents=True)
    header = ["sample", *(f"{value:.6f}" for value in axis), "response"]
    rows = [",".join(header)]
    for sample, (values, target) in enumerate(zip(matrix, response), start=1):
        rows.append(
            ",".join(
                [
                    f"selection-{sample:02d}",
                    *(f"{value:.12g}" for value in values),
                    f"{target:.12g}",
                ]
            )
        )
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=8,
        file_id=13,
        extra_parameters={
            "target_authority": {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": "response",
                "target_type": "continuous",
                "units": None,
                "source_digest": "0" * 64,
            }
        },
    )


@pytest.fixture
def canonical_peak_calibration_source(tmp_path) -> ConsumerProjectSource:
    """Bind peak-guided PLS to two resolved bands with a quantitative response."""

    sample_count = 48
    axis = np.linspace(900.0, 1800.0, 181)
    rng = np.random.default_rng(20260826)
    factor_a = rng.uniform(0.4, 1.6, size=sample_count)
    factor_b = rng.uniform(0.3, 1.4, size=sample_count)
    band_a = 55.0 * np.exp(-0.5 * ((axis - 1125.0) / 18.0) ** 2)
    band_b = 40.0 * np.exp(-0.5 * ((axis - 1575.0) / 24.0) ** 2)
    matrix = 2.0 + factor_a[:, None] * band_a + factor_b[:, None] * band_b
    matrix += rng.normal(0.0, 0.01, size=matrix.shape)
    response = 2.25 * factor_a - 0.85 * factor_b

    data_root = tmp_path / "data"
    relative_path = "raw/phase2-peak-calibration.csv"
    source_path = data_root / "experiments" / "exp_029" / relative_path
    source_path.parent.mkdir(parents=True)
    rows = [",".join(["sample", *(f"{value:.6f}" for value in axis), "response"])]
    for sample, (values, target) in enumerate(zip(matrix, response), start=1):
        rows.append(
            ",".join(
                [
                    f"peak-calibration-{sample:02d}",
                    *(f"{value:.12g}" for value in values),
                    f"{target:.12g}",
                ]
            )
        )
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=29,
        file_id=42,
        extra_parameters={
            "target_authority": {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": "response",
                "target_type": "continuous",
                "units": None,
                "source_digest": "0" * 64,
            }
        },
    )


@pytest.fixture
def canonical_transfer_sources(tmp_path) -> dict[str, ConsumerProjectSource]:
    """Bind one identity-paired primary/secondary instrument fixture."""

    sample_count = 40
    feature_count = 24
    axis = np.linspace(1000.0, 1800.0, feature_count)
    rng = np.random.default_rng(20260816)
    latent = rng.normal(size=(sample_count, 2))
    secondary = 1.2 + latent @ rng.normal(size=(2, feature_count))
    primary = secondary * np.linspace(0.82, 1.18, feature_count)
    sample_labels = [f"transfer-{index:02d}" for index in range(sample_count)]
    data_root = tmp_path / "data"
    experiment_dir = data_root / "experiments" / "exp_023" / "raw"
    experiment_dir.mkdir(parents=True)

    def _write(path, matrix: np.ndarray) -> None:
        rows = [",".join(["Wavenumber (cm-1)", *sample_labels])]
        rows.extend(
            ",".join([f"{coordinate:.12g}", *(f"{value:.12g}" for value in values)])
            for coordinate, values in zip(axis, matrix.T)
        )
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    records = [
        ("primary_1", 33, "phase2-transfer-primary.csv", primary),
        ("secondary_1", 34, "phase2-transfer-secondary.csv", secondary),
    ]
    source_records: list[dict[str, object]] = []
    for node_id, file_id, filename, matrix in records:
        _write(experiment_dir / filename, matrix)
        relative_path = f"raw/{filename}"
        source_records.append(
            {
                "relative_path": relative_path,
                "experiment_id": 23,
                "file_id": file_id,
                "stage": "raw",
            }
        )
    sources = _bind_exact_file_records(data_root=data_root, records=source_records)
    return {node_id: sources[(23, file_id, "raw")] for node_id, file_id, _filename, _matrix in records}


@pytest.fixture
def canonical_mcr_source(tmp_path) -> ConsumerProjectSource:
    """Bind the MCR project to a deterministic three-component mixture."""

    sample_count = 30
    axis = np.linspace(900.0, 1800.0, 42)
    rng = np.random.default_rng(20260815)
    pure_spectra = np.vstack(
        [
            np.exp(-0.5 * ((axis - 1050.0) / 55.0) ** 2),
            0.8 * np.exp(-0.5 * ((axis - 1370.0) / 70.0) ** 2),
            0.6 * np.exp(-0.5 * ((axis - 1650.0) / 45.0) ** 2),
        ]
    )
    concentrations = rng.uniform(0.05, 1.5, size=(sample_count, 3))
    matrix = concentrations @ pure_spectra + rng.uniform(0.0, 2e-4, size=(sample_count, axis.size))

    data_root = tmp_path / "data"
    relative_path = "raw/phase1c-mcr.csv"
    source_path = data_root / "experiments" / "exp_011" / relative_path
    source_path.parent.mkdir(parents=True)
    header = ["sample", *(f"{value:.6f}" for value in axis)]
    rows = [",".join(header)]
    for sample, values in enumerate(matrix, start=1):
        rows.append(",".join([f"mixture-{sample:02d}", *(f"{value:.12g}" for value in values)]))
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=11,
        file_id=19,
    )


@pytest.fixture
def canonical_knn_source(tmp_path) -> ConsumerProjectSource:
    """Bind the KNN project to one deterministic three-class fixture."""

    rows_per_class = 20
    labels = np.repeat(np.asarray([0, 1, 2], dtype=np.int64), rows_per_class)
    axis = np.linspace(900.0, 1800.0, 12)
    rng = np.random.default_rng(20260815)
    centers = np.asarray(
        [
            [1.2, 0.6, -0.2],
            [-0.4, 1.3, 0.5],
            [0.1, -0.5, 1.4],
        ],
        dtype=np.float64,
    )
    matrix = rng.normal(0.0, 0.12, size=(labels.size, axis.size))
    for class_index in range(3):
        rows = labels == class_index
        matrix[rows, :3] += centers[class_index]

    data_root = tmp_path / "data"
    relative_path = "raw/phase1c-knn.csv"
    source_path = data_root / "experiments" / "exp_011" / relative_path
    source_path.parent.mkdir(parents=True)
    header = ["sample", *(f"{value:.6f}" for value in axis), "material"]
    rows = [",".join(header)]
    for sample, (values, label) in enumerate(zip(matrix, labels), start=1):
        rows.append(",".join([f"knn-{sample:02d}", *(f"{value:.12g}" for value in values), str(label)]))
    source_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    return _bind_exact_file_record(
        data_root=data_root,
        relative_path=relative_path,
        experiment_id=11,
        file_id=19,
        extra_parameters={
            "target_authority": {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": "material",
                "target_type": "categorical",
                "units": None,
                "source_digest": "0" * 64,
            }
        },
    )


@pytest.fixture
def canonical_harmonization_sources(tmp_path) -> dict[str, ConsumerProjectSource]:
    """Bind source and reference instruments to two explicit cm-1 grids."""

    sample_count = 12
    source_axis = np.linspace(4000.0, 600.0, 171)
    reference_axis = np.linspace(3775.0, 825.0, 148)
    rng = np.random.default_rng(20260814)

    def _spectra(axis: np.ndarray) -> np.ndarray:
        peak_a = 0.42 * np.exp(-0.5 * ((axis - 2925.0) / 75.0) ** 2)
        peak_b = 0.75 * np.exp(-0.5 * ((axis - 1710.0) / 55.0) ** 2)
        peak_c = 0.28 * np.exp(-0.5 * ((axis - 1125.0) / 42.0) ** 2)
        baseline = -0.06 + 0.000035 * (4000.0 - axis) + 2.5e-8 * (axis - 2200.0) ** 2
        return np.vstack(
            [
                baseline
                + (0.9 + 0.025 * sample) * peak_a
                + (0.75 + 0.018 * sample) * peak_b
                + (0.8 - 0.012 * sample) * peak_c
                + rng.normal(0.0, 0.0015, axis.size)
                for sample in range(sample_count)
            ]
        )

    data_root = tmp_path / "data"
    experiment_dir = data_root / "experiments" / "exp_009" / "raw"
    experiment_dir.mkdir(parents=True)

    def _write_axis_column(path, axis: np.ndarray, matrix: np.ndarray) -> None:
        header = ["Wavenumber (cm-1)", *(f"sample-{sample:02d}" for sample in range(1, sample_count + 1))]
        rows = [",".join(header)]
        for coordinate, values in zip(axis, matrix.T):
            rows.append(",".join([f"{coordinate:.12g}", *(f"{value:.12g}" for value in values)]))
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    source_relative_path = "raw/phase1c-source-instrument.csv"
    reference_relative_path = "raw/phase1c-reference-instrument.csv"
    _write_axis_column(experiment_dir / "phase1c-source-instrument.csv", source_axis, _spectra(source_axis))
    _write_axis_column(
        experiment_dir / "phase1c-reference-instrument.csv",
        reference_axis,
        _spectra(reference_axis),
    )
    sources = _bind_exact_file_records(
        data_root=data_root,
        records=[
            {
                "relative_path": source_relative_path,
                "experiment_id": 9,
                "file_id": 14,
                "stage": "raw",
            },
            {
                "relative_path": reference_relative_path,
                "experiment_id": 9,
                "file_id": 15,
                "stage": "raw",
            },
        ],
    )
    return {"source_1": sources[(9, 14, "raw")], "reference_1": sources[(9, 15, "raw")]}


@pytest.fixture
def canonical_emsc_sources(tmp_path) -> dict[str, ConsumerProjectSource]:
    """Bind application, reference, and interferent spectra to one exact axis."""

    axis = np.linspace(1000.0, 1800.0, 41)
    normalized = (axis - axis.mean()) / axis.std()
    reference = 0.35 + np.exp(-0.5 * ((axis - 1380.0) / 75.0) ** 2)
    constituent = 0.7 * np.exp(-0.5 * ((axis - 1630.0) / 42.0) ** 2)
    application = np.vstack(
        [
            1.30 * reference + 0.20 - 0.08 * normalized + 0.03 * normalized**2 + 0.45 * constituent,
            0.75 * reference - 0.12 + 0.06 * normalized - 0.02 * normalized**2 - 0.20 * constituent,
            1.05 * reference + 0.04 + 0.02 * normalized + 0.01 * normalized**2 + 0.15 * constituent,
        ]
    )

    data_root = tmp_path / "data"
    experiment_dir = data_root / "experiments" / "exp_010" / "raw"
    experiment_dir.mkdir(parents=True)

    def _write_axis_column(path, matrix: np.ndarray, sample_prefix: str) -> None:
        rows = [
            ",".join(
                [
                    "Wavenumber (cm-1)",
                    *(f"{sample_prefix}-{sample:02d}" for sample in range(1, matrix.shape[0] + 1)),
                ]
            )
        ]
        for coordinate, values in zip(axis, matrix.T):
            rows.append(",".join([f"{coordinate:.12g}", *(f"{value:.12g}" for value in values)]))
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    records = [
        ("application_1", 16, "phase1c-emsc-application.csv", application, "application"),
        ("reference_1", 17, "phase1c-emsc-reference.csv", reference.reshape(1, -1), "reference"),
        ("constituent_1", 18, "phase1c-emsc-constituent.csv", constituent.reshape(1, -1), "interferent"),
    ]
    source_records: list[dict[str, object]] = []
    for node_id, file_id, filename, matrix, prefix in records:
        _write_axis_column(experiment_dir / filename, matrix, prefix)
        relative_path = f"raw/{filename}"
        source_records.append(
            {
                "relative_path": relative_path,
                "experiment_id": 10,
                "file_id": file_id,
                "stage": "raw",
            }
        )
    sources = _bind_exact_file_records(data_root=data_root, records=source_records)
    return {node_id: sources[(10, file_id, "raw")] for node_id, file_id, _filename, _matrix, _prefix in records}


@pytest.fixture
def canonical_msc_sources(tmp_path) -> dict[str, ConsumerProjectSource]:
    """Bind one explicit MSC reference cohort and linearly scattered applications."""

    axis = np.linspace(1000.0, 1800.0, 41)
    reference = 0.35 + np.exp(-0.5 * ((axis - 1380.0) / 75.0) ** 2)
    reference_rows = np.vstack([reference - 0.01, reference + 0.01])
    application = np.vstack([1.30 * reference + 0.20, 0.75 * reference - 0.12, 1.05 * reference + 0.04])
    data_root = tmp_path / "data"
    experiment_dir = data_root / "experiments" / "exp_022" / "raw"
    experiment_dir.mkdir(parents=True)

    def _write(path, matrix: np.ndarray, prefix: str) -> None:
        rows = [",".join(["Wavenumber (cm-1)", *(f"{prefix}-{index:02d}" for index in range(matrix.shape[0]))])]
        rows.extend(
            ",".join([f"{coordinate:.12g}", *(f"{value:.12g}" for value in values)])
            for coordinate, values in zip(axis, matrix.T)
        )
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    records = [
        ("application_1", 31, "phase2-msc-application.csv", application, "application"),
        ("reference_1", 32, "phase2-msc-reference.csv", reference_rows, "reference"),
    ]
    source_records: list[dict[str, object]] = []
    for node_id, file_id, filename, matrix, prefix in records:
        _write(experiment_dir / filename, matrix, prefix)
        relative_path = f"raw/{filename}"
        source_records.append({"relative_path": relative_path, "experiment_id": 22, "file_id": file_id, "stage": "raw"})
    sources = _bind_exact_file_records(data_root=data_root, records=source_records)
    return {node_id: sources[(22, file_id, "raw")] for node_id, file_id, _filename, _matrix, _prefix in records}


@pytest.mark.asyncio
async def test_consumer_project_requires_every_exact_file_source_binding() -> None:
    """The shared proof may not execute an unbound or misidentified source."""

    template = load_consumer_project("raman_processing")
    assert {node["node_id"] for node in template["nodes"] if node["node_type"] == "data.file_load"} == {"data_1"}
    with pytest.raises(AssertionError, match=r"missing=\['data_1'\]"):
        await execute_consumer_project("raman_processing", source_parameters={})
    with pytest.raises(AssertionError, match=r"non_sources=\['preprocess_1'\]"):
        await execute_consumer_project(
            "raman_processing",
            source_parameters={
                "data_1": {"experiment_id": 7, "file_id": 12, "stage": "raw"},
                "preprocess_1": {},
            },
        )
    with pytest.raises(AssertionError, match=r"lack explicit resolved files: \['data_1'\]"):
        await execute_consumer_project(
            "raman_processing",
            source_parameters={"data_1": {"experiment_id": 7, "file_id": 12, "stage": "raw"}},
        )


@pytest.mark.asyncio
async def test_raman_processing_project_executes_and_explains_each_step(
    canonical_raman_source,
) -> None:
    """The ready Raman project executes its exact DAG and explains each change."""

    run = await execute_consumer_project(
        "raman_processing",
        source_parameters={"data_1": canonical_raman_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "preprocess_1": "preprocess.cosmic_ray",
        "preprocess_2": "baseline.penalized_ls",
        "preprocess_3": "preprocess.smooth",
        "preprocess_4": "preprocess.scale",
    }
    source = run.results["data_1"]["default"]
    terminal = run.results["preprocess_4"]["default"]
    assert isinstance(source, SherpaDataset)
    assert isinstance(terminal, SherpaDataset)
    assert terminal.shape == source.shape == (18, 81)
    np.testing.assert_array_equal(terminal.feature_axis.values, source.feature_axis.values)
    assert np.isfinite(terminal.data).all()
    assert not np.array_equal(terminal.data, source.data)

    cosmic = run.executor.diagnostics["preprocess_1"]
    baseline = run.executor.diagnostics["preprocess_2"]
    smooth = run.executor.diagnostics["preprocess_3"]
    scale = run.executor.diagnostics["preprocess_4"]
    assert cosmic["method"] == "hampel_local_median_mad"
    assert cosmic["simultaneous_replacement"] is True
    assert cosmic["corrected_values"] >= 2
    assert cosmic["spectra_with_corrections"] >= 2
    assert cosmic["corrected_fraction"] < 0.05
    assert cosmic["maximum_absolute_correction"] > 3.0
    assert baseline["algorithm"] == "als"
    assert baseline["converged_spectra"] == 18
    assert baseline["nonconverged_spectra"] == 0
    assert smooth["method"] == "whittaker"
    assert scale["method"] == "mean_center"
    np.testing.assert_allclose(
        np.mean(terminal.data, axis=0),
        np.zeros(terminal.shape[1]),
        atol=1e-12,
    )

    operations = [
        step["op_id"]
        for step in terminal.provenance.to_list()
        if step["op_id"].startswith(("preprocess.", "baseline."))
    ]
    assert operations[-4:] == [
        "preprocess.cosmic_ray",
        "baseline.penalized_ls",
        "preprocess.smooth",
        "preprocess.scale",
    ]


@pytest.mark.asyncio
async def test_peak_detection_project_executes_one_canonical_peak_table(canonical_peak_source) -> None:
    """The scientist-facing project produces its table through the canonical node."""

    run = await execute_consumer_project(
        "peaks",
        source_parameters={"data_1": canonical_peak_source},
    )
    result = run.results["analysis_1"]
    assert set(result) == {"peaks", "plots", "per_spectrum"}
    rows = result["peaks"]["data"]
    assert len(rows) == 2
    assert [row["sample_count"] for row in rows] == [10, 10]
    np.testing.assert_allclose([row["median_pos"] for row in rows], [1125.0, 1575.0], atol=3.0)
    assert all(row["median_half_prominence_width"] > 0 for row in rows)
    statistics = run.results["stats_1"]["statistics"]
    assert statistics["summary"]["n_peaks"] == 2
    assert [row["detection_rate"] for row in statistics["data"]] == ["100%", "100%"]
    assert all("half_prominence_width" in row for row in statistics["data"])


@pytest.mark.asyncio
async def test_hierarchical_clustering_project_executes_one_closed_cohort_hierarchy(
    canonical_hca_source,
) -> None:
    """The workbench project clusters, explains, and plots one exact cohort."""

    run = await execute_consumer_project(
        "hierarchical_clustering",
        source_parameters={"data_1": canonical_hca_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "preprocess_1": "preprocess.scale",
        "model_1": "model.hca",
        "viz_1": "output.plot",
    }
    state = run.results["model_1"]["model"]
    assert state["schema_version"] == "spectrasherpa.model.hca-state/1"
    assert state["requested_clusters"] == state["observed_clusters"] == 3
    assert state["label_rule"] == "zero_based_by_first_observation"
    assert len(run.results["model_1"]["labels"]) == 36
    assert [row["count"] for row in run.results["model_1"]["cluster_summary"]] == [12, 12, 12]
    visualization = run.results["viz_1"]["visualization"]
    assert visualization["plot_type"] == "dendrogram"
    assert visualization["data"]
    assert run.executor.diagnostics["model_1"]["n_samples"] == 36


@pytest.mark.asyncio
async def test_partition_clustering_project_compares_two_canonical_cluster_definitions(
    canonical_partition_clustering_source,
) -> None:
    """One project gives scientists two explicit, non-interchangeable partitions."""

    from sklearn.metrics import adjusted_rand_score

    run = await execute_consumer_project(
        "clustering_comparison",
        source_parameters={"data_1": canonical_partition_clustering_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "preprocess_1": "preprocess.scale",
        "kmeans_1": "model.kmeans",
        "dbscan_1": "model.dbscan",
    }
    expected = np.repeat(np.arange(3), 14)
    kmeans = run.results["kmeans_1"]
    dbscan = run.results["dbscan_1"]
    assert adjusted_rand_score(expected, kmeans["labels"]) == pytest.approx(1.0)
    assert adjusted_rand_score(expected, dbscan["labels"]) == pytest.approx(1.0)
    assert kmeans["metadata"]["prediction_rule"] == ("nearest_euclidean_centroid_lowest_canonical_label_on_tie")
    assert dbscan["metadata"]["application_scope"] == "exact_fitted_cohort_only_no_out_of_sample_assignment"


@pytest.mark.asyncio
async def test_nmf_mixture_project_executes_one_replayable_nonnegative_decomposition(
    canonical_nmf_source,
) -> None:
    """The workbench project fits and reapplies one inspectable NMF basis."""

    run = await execute_consumer_project(
        "nmf_mixture_decomposition",
        source_parameters={"data_1": canonical_nmf_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "floor_1": "preprocess.clip_floor",
        "nmf_1": "model.nmf",
    }
    source = run.results["floor_1"]["default"]
    result = run.results["nmf_1"]
    concentrations = np.asarray(result["concentrations"].X, dtype=np.float64)
    components = np.asarray(result["spectra"].X, dtype=np.float64)
    state = result["model"]
    assert state["schema_version"] == "spectrasherpa.model.nmf-state/1"
    assert state["application_rule"] == ("fixed_basis_nonnegative_transform_reestimates_concentrations")
    assert np.all(concentrations >= 0.0)
    assert np.all(components >= 0.0)
    assert result["reconstruction_error"] == pytest.approx(
        np.linalg.norm(np.asarray(source.X) - concentrations @ components, ord="fro"),
        rel=1e-12,
    )
    applied = run.executor.nodes["nmf_1"].apply_fitted_state(source, state)
    repeated = run.executor.nodes["nmf_1"].apply_fitted_state(source, state)
    np.testing.assert_array_equal(applied, repeated)
    assert applied.shape == concentrations.shape
    assert np.all(np.isfinite(applied))
    assert np.all(applied >= 0.0)
    assert run.executor.diagnostics["nmf_1"]["convergence_status"] in {
        "converged",
        "max_iter_reached",
    }
    assert run.executor.diagnostics["nmf_1"]["convergence_status"] == "converged"


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_SCP, reason="EFA execution requires SpectroChemPy")
async def test_efa_project_executes_raw_forward_and_reverse_rank_diagnostics(
    canonical_evolving_mixture_source,
) -> None:
    """The workbench asks the EFA rank question without hidden centering."""

    run = await execute_consumer_project(
        "efa_analysis",
        source_parameters={"data_1": canonical_evolving_mixture_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "model_1": "model.efa",
        "viz_1": "output.plot",
        "viz_2": "output.plot",
    }
    result = run.results["model_1"]
    assert run.results["data_1"]["default"].is_time_series is True
    forward = result["forward_eigenvalues"]
    backward = result["backward_eigenvalues"]
    assert isinstance(forward, SherpaDataset)
    assert isinstance(backward, SherpaDataset)
    assert forward.shape == backward.shape == (48, 10)
    assert np.isfinite(forward.X).all()
    assert np.isfinite(backward.X).all()
    assert "model" not in result and "_model_artifact" not in result
    assert run.executor.diagnostics["model_1"]["n_components"] == 10


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_SCP, reason="SIMPLISMA execution requires SpectroChemPy")
async def test_simplisma_project_executes_raw_pure_variable_estimates(
    canonical_evolving_mixture_source,
) -> None:
    """The workbench exposes pure-variable estimates without a fake model artifact."""

    run = await execute_consumer_project(
        "simplisma",
        source_parameters={"data_1": canonical_evolving_mixture_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "model_1": "model.simplisma",
        "viz_1": "output.plot",
        "viz_2": "output.plot",
        "export_1": "output.export",
    }
    result = run.results["model_1"]
    concentrations = result["concentrations"]
    spectra = result["spectra"]
    assert isinstance(concentrations, SherpaDataset)
    assert isinstance(spectra, SherpaDataset)
    assert concentrations.shape == (48, 3)
    assert spectra.shape == (3, 40)
    assert np.isfinite(concentrations.X).all()
    assert np.isfinite(spectra.X).all()
    purity_values = np.asarray(result["purity_values"])
    assert purity_values.shape == (3,)
    assert np.isfinite(purity_values).all()
    assert run.results["viz_1"]["visualization"]["data"]
    assert "model" not in result and "_model_artifact" not in result
    assert run.executor.diagnostics["model_1"]["n_components"] == 3


@pytest.mark.asyncio
async def test_pca_project_executes_one_closed_fit_application_and_diagnostic_authority(
    canonical_pca_source,
) -> None:
    """The New Analysis project fits, explains, and diagnoses one PCA state."""

    run = await execute_consumer_project(
        "pca",
        source_parameters={"data_1": canonical_pca_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "inclusion_1": "data.filter_samples",
        "preprocess_1": "preprocess.scale",
        "model_1": "model.pca",
        "viz_1": "output.plot",
        "viz_2": "output.plot",
        "viz_3": "output.plot",
        "stats_1": "stats.summary",
        "outliers_1": "diagnostics.outliers",
    }
    inclusion = run.results["inclusion_1"]["default"]
    assert inclusion.shape == (36, 32)
    assert inclusion.data_role == "X_spectra"
    assert inclusion.provenance[-1].op_id == "data.filter_samples"
    assert inclusion.provenance[-1].parameters["no_filter"] is True
    state = run.results["model_1"]["fitted_state"]
    assert state["schema_version"] == "spectrasherpa.model.pca-state/4"
    assert state["metadata"]["n_components"] == 3
    assert run.results["model_1"]["model"] == state
    assert run.results["model_1"]["scores"].shape == (36, 3)
    assert run.results["model_1"]["loadings"].shape[0] == 3
    assert len(run.results["model_1"]["explained_variance"]) == 3
    assert len(run.results["model_1"]["eigenvalues"]) == 3
    assert all(run.results[node_id]["visualization"]["data"] for node_id in ("viz_1", "viz_2", "viz_3"))
    assert len(run.results["outliers_1"]["T2"]) == 36
    assert len(run.results["outliers_1"]["Q"]) == 36
    assert run.results["outliers_1"]["T2_limit"] > 0.0
    assert run.results["outliers_1"]["Q_limit"] >= 0.0
    assert run.executor.diagnostics["model_1"]["explained_variance_ratio"]


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_SCP, reason="MCR-ALS execution requires SpectroChemPy")
async def test_mcr_project_executes_one_replayable_constrained_decomposition(
    canonical_mcr_source,
) -> None:
    """The New Analysis project fits, explains, and plots one exact MCR state."""

    run = await execute_consumer_project(
        "mcr_als",
        source_parameters={"data_1": canonical_mcr_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "model_1": "model.mcr_als",
        "viz_1": "output.plot",
        "viz_2": "output.plot",
        "stats_1": "stats.summary",
    }
    source = run.results["data_1"]["default"]
    concentrations = run.results["model_1"]["C"]
    spectra = run.results["model_1"]["St"]
    residuals = run.results["model_1"]["residuals"]
    state = run.results["model_1"]["fitted_state"]

    assert isinstance(source, SherpaDataset)
    assert isinstance(concentrations, SherpaDataset)
    assert isinstance(spectra, SherpaDataset)
    assert isinstance(residuals, SherpaDataset)
    assert source.shape == residuals.shape == (30, 42)
    assert concentrations.shape == (30, 3)
    assert spectra.shape == (3, 42)
    assert np.isfinite(concentrations.data).all()
    assert np.isfinite(spectra.data).all()
    assert np.min(concentrations.data) >= 0.0
    assert np.min(spectra.data) >= 0.0
    np.testing.assert_allclose(
        residuals.data,
        source.data - concentrations.data @ spectra.data,
        rtol=0.0,
        atol=1e-12,
    )
    assert state["serializer"] == "spectrasherpa.model-artifact.mcr-als/1"
    assert state["metadata"]["concentration_solver"] == "nnls"
    assert run.executor.diagnostics["model_1"]["residual_definition"] == "observed_minus_reconstructed"
    assert run.results["viz_1"]["visualization"]["plot_type"] == "spectra"
    assert run.results["viz_2"]["visualization"]["plot_type"] == "profiles"


@pytest.mark.asyncio
async def test_ica_project_executes_one_seeded_replayable_decomposition(
    canonical_mcr_source,
) -> None:
    """The New Analysis project exposes scores, mixing profiles, and residuals."""

    run = await execute_consumer_project(
        "ica_decomposition",
        source_parameters={"data_1": canonical_mcr_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "model_1": "model.ica",
        "sources_plot": "output.plot",
        "profiles_plot": "output.plot",
        "residual_summary": "stats.summary",
    }
    source = run.results["data_1"]["default"]
    scores = run.results["model_1"]["sources"]
    profiles = run.results["model_1"]["components"]
    mixing = run.results["model_1"]["mixing_matrix"]
    residuals = run.results["model_1"]["residuals"]
    state = run.results["model_1"]["fitted_state"]

    assert isinstance(source, SherpaDataset)
    assert isinstance(scores, SherpaDataset)
    assert isinstance(profiles, SherpaDataset)
    assert isinstance(residuals, SherpaDataset)
    assert source.shape == residuals.shape == (30, 42)
    assert scores.shape == (30, 3)
    assert profiles.shape == (3, 42)
    assert mixing.shape == (42, 3)
    reconstructed = scores.data @ mixing.T + np.asarray(state["arrays"]["mean"])
    np.testing.assert_allclose(residuals.data, source.data - reconstructed, rtol=0.0, atol=1e-12)
    assert state["serializer"] == "spectrasherpa.model-artifact.fastica/1"
    assert state["metadata"]["random_seed"] == 42
    assert run.executor.diagnostics["model_1"]["sign_rule"] == "largest_absolute_mixing_loading_positive"
    assert run.results["sources_plot"]["visualization"]["plot_type"] == "scores"
    assert run.results["profiles_plot"]["visualization"]["plot_type"] == "spectra"


@pytest.mark.asyncio
async def test_variable_selection_comparison_project_executes_training_owned_agreement(
    canonical_selection_source,
) -> None:
    """Five selectors use one calibration partition without a performance claim."""

    run = await execute_consumer_project(
        "variable_selection_comparison",
        source_parameters={"data_1": canonical_selection_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "partition_1": "data.train_test_split",
        "pls_1": "model.fitted_pls",
        "vip_1": "selection.variable_select",
        "cars_1": "selection.cars",
        "mcuve_1": "selection.mcuve",
        "spa_1": "selection.spa",
        "stability_1": "selection.stability",
        "compare_1": "selection.compare",
    }
    edges = {
        (
            edge["from_node_id"],
            edge.get("from_output", "default"),
            edge["to_node_id"],
            edge.get("to_input", "default"),
        )
        for edge in run.template["edges"]
    }
    assert {
        ("partition_1", "X_train", "pls_1", "default"),
        ("partition_1", "y_train", "pls_1", "y"),
        ("partition_1", "X_train", "vip_1", "X"),
        ("partition_1", "X_train", "cars_1", "X"),
        ("partition_1", "y_train", "cars_1", "y"),
        ("partition_1", "X_train", "mcuve_1", "X"),
        ("partition_1", "y_train", "mcuve_1", "y"),
        ("partition_1", "X_train", "spa_1", "X"),
        ("partition_1", "y_train", "spa_1", "y"),
        ("partition_1", "X_train", "stability_1", "X"),
        ("partition_1", "y_train", "stability_1", "y"),
        ("partition_1", "X_train", "compare_1", "X"),
    } <= edges
    assert not any(from_output in {"X_test", "y_test"} for _, from_output, _, _ in edges)
    source = run.results["data_1"]["default"]
    partition = run.results["partition_1"]
    assert isinstance(source, SherpaDataset)
    assert source.shape == (48, 32)
    assert np.asarray(source.target).shape == (48,)
    train_indices = np.asarray(partition["train_indices"], dtype=int)
    test_indices = np.asarray(partition["test_indices"], dtype=int)
    assert train_indices.shape == (36,)
    assert test_indices.shape == (12,)
    assert set(train_indices).isdisjoint(test_indices)
    assert sorted(np.concatenate([train_indices, test_indices]).tolist()) == list(range(48))

    vip_mask = np.asarray(run.results["vip_1"]["mask"])
    cars_mask = np.asarray(run.results["cars_1"]["mask"])
    mcuve_mask = np.asarray(run.results["mcuve_1"]["mask"])
    spa_mask = np.asarray(run.results["spa_1"]["mask"])
    stability_mask = np.asarray(run.results["stability_1"]["mask"])
    consensus = np.asarray(run.results["compare_1"]["consensus_mask"])
    masks = (vip_mask, cars_mask, mcuve_mask, spa_mask, stability_mask)
    assert all(mask.dtype == np.dtype(bool) and mask.shape == (32,) for mask in masks)
    assert all(0 < np.count_nonzero(mask) < 32 for mask in masks)
    compared_votes = np.sum(np.vstack(masks[:4]), axis=0)
    np.testing.assert_array_equal(consensus, compared_votes >= 2)

    vip_report = run.results["vip_1"]["selection_report"]
    agreement = run.results["compare_1"]["report"]
    assert vip_report["method"] == "vip"
    assert vip_report["reference_samples"] == 36
    assert vip_report["predictive_performance_claimed"] is False
    assert agreement["method_count"] == 4
    assert agreement["required_votes"] == 2
    assert agreement["consensus_count"] == int(np.count_nonzero(consensus))
    assert agreement["scope"] == "selector_agreement_record_not_predictive_performance_evidence"
    assert run.executor.diagnostics["cars_1"]["n_iterations_run"] == 20
    assert run.executor.diagnostics["mcuve_1"]["n_resamples"] == 20
    assert run.executor.diagnostics["spa_1"]["candidate_chain_count"] > 0
    assert run.executor.diagnostics["stability_1"]["n_resamples"] == 20
    assert run.executor.diagnostics["compare_1"]["scope"] == agreement["scope"]


@pytest.mark.asyncio
async def test_preprocessing_project_executes_the_declared_chain_and_exports_exact_result(
    canonical_raman_source,
) -> None:
    """The starter applies every advertised transform and exports its final dataset."""

    run = await execute_consumer_project(
        "preprocessing",
        source_parameters={"data_1": canonical_raman_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "preprocess_1": "baseline.penalized_ls",
        "preprocess_2": "preprocess.smooth",
        "preprocess_3": "preprocess.normalize",
        "export_1": "output.export",
    }
    source = run.results["data_1"]["default"]
    transformed = run.results["preprocess_3"]["default"]
    artifact = run.results["export_1"]["artifact"]
    assert isinstance(source, SherpaDataset)
    assert isinstance(transformed, SherpaDataset)
    assert source.shape == transformed.shape == (18, 81)
    assert np.isfinite(transformed.X).all()
    np.testing.assert_array_equal(transformed.sample_axis.labels, source.sample_axis.labels)
    np.testing.assert_array_equal(transformed.feature_axis.values, source.feature_axis.values)
    assert transformed.target is source.target is None
    assert artifact["format"] == "csv"
    assert artifact["shape"] == [18, 81]
    assert artifact["source_digest"] == transformed.scientific_digest


async def _assert_calibration_project_fits_once_and_scores_only_held_out_rows(
    slug: str,
    expected_model_components: int,
    canonical_selection_source,
) -> None:
    run = await execute_consumer_project(
        slug,
        source_parameters={"data_1": canonical_selection_source},
    )

    partition = run.results["partition_1"]
    train_indices = np.asarray(partition["train_indices"], dtype=np.int64)
    test_indices = np.asarray(partition["test_indices"], dtype=np.int64)
    predictions = run.results["predict_1"]["default"]
    metrics = run.results["eval_1"]["default"]
    state = run.results["model_1"]["fitted_state"]
    assert train_indices.shape == (36,)
    assert test_indices.shape == (12,)
    assert set(train_indices).isdisjoint(test_indices)
    assert sorted(np.concatenate((train_indices, test_indices)).tolist()) == list(range(48))
    assert predictions.shape == (12, 1)
    assert state["state"]["n_components"] == expected_model_components
    assert metrics["n_samples"] == 12
    assert metrics["rmse"] >= 0.0
    assert metrics["r2"] is not None
    assert run.results["table_1"]["visualization"]["data"]
    assert run.results["viz_1"]["visualization"]["data"]


@pytest.mark.asyncio
async def test_pls_calibration_project_fits_once_and_scores_only_the_held_out_partition(
    canonical_selection_source,
) -> None:
    """The ordinary PLS starter retains one disjoint partition and fitted state."""

    await _assert_calibration_project_fits_once_and_scores_only_held_out_rows(
        "pls_calibration", 3, canonical_selection_source
    )


@pytest.mark.asyncio
async def test_representative_calibration_project_scores_only_its_kennard_stone_holdout(
    canonical_selection_source,
) -> None:
    """The representative starter scores only its disjoint Kennard-Stone holdout."""

    await _assert_calibration_project_fits_once_and_scores_only_held_out_rows(
        "representative_calibration", 4, canonical_selection_source
    )


async def _assert_vip_project_applies_one_training_owned_mask(
    slug: str,
    canonical_selection_source,
) -> None:
    run = await execute_consumer_project(
        slug,
        source_parameters={"data_1": canonical_selection_source},
    )

    training_mask = np.asarray(run.results["select_train"]["mask"])
    applied_mask = np.asarray(run.results["select_test"]["mask"])
    selected_train = run.results["select_train"]["X_selected"]
    selected_test = run.results["select_test"]["X_selected"]
    metrics = run.results["eval_1"]["default"]
    assert training_mask.dtype == np.dtype(bool)
    assert training_mask.shape == applied_mask.shape == (32,)
    np.testing.assert_array_equal(applied_mask, training_mask)
    assert 0 < np.count_nonzero(training_mask) < 32
    assert selected_train.shape == (36, int(np.count_nonzero(training_mask)))
    assert selected_test.shape == (12, int(np.count_nonzero(training_mask)))
    assert run.results["predict_1"]["default"].shape == (12, 1)
    assert metrics["n_samples"] == 12
    assert metrics["rmse"] >= 0.0
    assert run.results["table_1"]["visualization"]["data"]
    assert run.results["viz_1"]["visualization"]["data"]


@pytest.mark.asyncio
async def test_variable_selection_pls_project_applies_one_training_owned_mask(
    canonical_selection_source,
) -> None:
    """Variable-selection PLS reuses its training-owned VIP mask on held-out rows."""

    await _assert_vip_project_applies_one_training_owned_mask("variable_selection_pls", canonical_selection_source)


@pytest.mark.asyncio
async def test_vip_assisted_pls_project_applies_one_training_owned_mask(
    canonical_selection_source,
) -> None:
    """VIP-assisted PLS reuses its training-owned mask on held-out rows."""

    await _assert_vip_project_applies_one_training_owned_mask("vip_assisted_pls", canonical_selection_source)


@pytest.mark.asyncio
async def test_nested_cv_project_reports_two_complete_out_of_fold_comparisons(
    canonical_selection_source,
) -> None:
    """The starter compares VIP and full-spectrum PLS through closed outer folds."""

    run = await execute_consumer_project(
        "nested_cv_validation",
        source_parameters={"data_1": canonical_selection_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "preprocess_1": "preprocess.smooth",
        "nested_cv_1": "selection.nested_cv",
        "nested_cv_2": "selection.nested_cv",
        "viz_1": "output.plot",
        "viz_2": "output.plot",
    }
    vip = run.results["nested_cv_1"]["cv_metrics"]
    full = run.results["nested_cv_2"]["cv_metrics"]
    assert vip["selection_method"] == "vip"
    assert full["selection_method"] == "none"
    assert len(vip["per_fold_n_selected"]) == len(full["per_fold_n_selected"]) == 5
    assert all(count == 32 for count in full["per_fold_n_selected"])
    assert 0 < min(vip["per_fold_n_selected"]) <= max(vip["per_fold_n_selected"]) < 32
    assert np.isfinite([vip["rmsecv"], vip["r2"], vip["q2"]]).all()
    assert np.isfinite([full["rmsecv"], full["r2"], full["q2"]]).all()
    assert vip["split_plan_digest"] == full["split_plan_digest"]
    assert run.results["viz_1"]["visualization"]["data"]
    assert run.results["viz_2"]["visualization"]["data"]


@pytest.mark.asyncio
async def test_peak_guided_pls_project_reuses_one_training_peak_mask_for_held_out_rows(
    canonical_peak_calibration_source,
) -> None:
    """Peak windows are derived from training spectra and applied once to test spectra."""

    run = await execute_consumer_project(
        "peak_guided_pls",
        source_parameters={"data_1": canonical_peak_calibration_source},
    )

    training_mask = np.asarray(run.results["peak_select_train"]["mask"])
    applied_mask = np.asarray(run.results["peak_select_test"]["mask"])
    selected_count = int(np.count_nonzero(training_mask))
    assert training_mask.dtype == np.dtype(bool)
    assert training_mask.shape == applied_mask.shape == (181,)
    np.testing.assert_array_equal(applied_mask, training_mask)
    assert 0 < selected_count < 181
    assert run.results["peak_select_train"]["X_selected"].shape == (36, selected_count)
    assert run.results["peak_select_test"]["X_selected"].shape == (12, selected_count)
    assert run.results["predict_1"]["default"].shape == (12, 1)
    evaluation = run.results["eval_1"]
    assert evaluation["default"]["n_samples"] == 12
    authority = evaluation["comparison"]["metadata"]["population_authority"]
    assert authority == {
        "schema_version": "spectrasherpa-population-authority/1",
        "role": "held_out_test",
        "population": ["partition_1", "test"],
        "fitted_populations": [["partition_1", "train"]],
        "qualification": "graph_verified",
    }
    assert evaluation["default"]["population_authority"] == authority
    assert evaluation["comparison"]["metadata"]["role"] == "held_out_test"
    assert all(row["role"] == "held_out_test" for row in evaluation["comparison"]["data"])
    assert run.results["table_1"]["visualization"]["data"]
    assert run.results["viz_1"]["visualization"]["data"]


@pytest.mark.asyncio
async def test_osc_project_executes_one_target_fitted_projection(
    canonical_selection_source,
) -> None:
    """The scientist-facing OSC project fits one frozen Fearn projection."""

    run = await execute_consumer_project(
        "osc_target_orthogonal_correction",
        source_parameters={"data_1": canonical_selection_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "osc_1": "preprocess.osc",
    }
    source = run.results["data_1"]["default"]
    corrected = run.results["osc_1"]["default"]
    assert isinstance(source, SherpaDataset)
    assert isinstance(corrected, SherpaDataset)
    assert corrected.shape == source.shape == (48, 32)
    np.testing.assert_array_equal(corrected.feature_axis.values, source.feature_axis.values)
    assert corrected.target is not None
    np.testing.assert_array_equal(corrected.target, source.target)
    diagnostics = run.executor.diagnostics["osc_1"]
    assert diagnostics["algorithm"] == "fearn-direct-orthogonal-signal-correction"
    assert diagnostics["n_components"] == 1
    assert 0.0 < diagnostics["training_centered_variance_removed_percent"] < 100.0
    assert diagnostics["training_target_covariance_relative_error"] <= 1.0e-10


@pytest.mark.asyncio
async def test_calibration_transfer_project_fits_and_reuses_three_explicit_states(
    canonical_transfer_sources,
) -> None:
    """The comparison project fits paired standards and applies frozen states."""

    run = await execute_consumer_project(
        "calibration_transfer",
        source_parameters=canonical_transfer_sources,
    )
    assert run.node_types == {
        "primary_1": "data.file_load",
        "secondary_1": "data.file_load",
        "primary_split_1": "data.train_test_split",
        "secondary_split_1": "data.train_test_split",
        "pds_fit_1": "transfer.pds",
        "ds_fit_1": "transfer.ds",
        "sws_fit_1": "transfer.sws",
        "pds_apply_1": "transfer.apply_fitted",
        "ds_apply_1": "transfer.apply_fitted",
        "sws_apply_1": "transfer.apply_fitted",
        "pds_plot_1": "output.plot",
        "ds_plot_1": "output.plot",
        "sws_plot_1": "output.plot",
        "pds_table_1": "output.data_table",
        "ds_table_1": "output.data_table",
        "sws_table_1": "output.data_table",
    }
    primary_test = run.results["primary_split_1"]["X_test"]
    secondary_test = run.results["secondary_split_1"]["X_test"]
    assert primary_test.sample_axis.labels == secondary_test.sample_axis.labels
    for prefix, operation_id in (("pds", "transfer.pds"), ("ds", "transfer.ds"), ("sws", "transfer.sws")):
        state = run.results[f"{prefix}_fit_1"]["fitted_state"]
        standardized = run.results[f"{prefix}_apply_1"]["default"]
        assert state["source_operation_id"] == operation_id
        assert standardized.shape == primary_test.shape == (10, 24)
        np.testing.assert_array_equal(standardized.sample_axis.labels, primary_test.sample_axis.labels)
        np.testing.assert_array_equal(standardized.feature_axis.values, primary_test.feature_axis.values)
        assert np.isfinite(standardized.data).all()
        assert run.executor.diagnostics[f"{prefix}_apply_1"]["state_content_digest"] == state["state_content_digest"]
        assert run.results[f"{prefix}_plot_1"]["visualization"]["plot_type"] == "spectra"
        assert run.results[f"{prefix}_table_1"]["visualization"]["data"]


@pytest.mark.asyncio
async def test_knn_classification_project_executes_explicit_fit_apply_and_heldout_evaluation(
    canonical_knn_source,
) -> None:
    """The current KNN project applies only its explicit state to held-out rows."""

    run = await execute_consumer_project(
        "knn_classification",
        source_parameters={"data_1": canonical_knn_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "partition_1": "data.train_test_split",
        "model_1": "classification.knn",
        "predict_1": "classification.apply_knn",
        "eval_1": "diagnostics.classification_evaluator",
    }
    partition = run.results["partition_1"]
    fitted_state = run.results["model_1"]["fitted_state"]
    predictions = np.asarray(run.results["predict_1"]["y_pred"], dtype=object)
    probabilities = np.asarray(run.results["predict_1"]["y_prob"], dtype=np.float64)
    held_out = np.asarray(partition["y_test"], dtype=object)
    evaluation = run.results["eval_1"]["default"]

    assert fitted_state["serializer"] == "spectrasherpa.model-artifact.knn/1"
    assert predictions.shape == held_out.shape == (15,)
    assert probabilities.shape == (15, 3)
    np.testing.assert_allclose(np.sum(probabilities, axis=1), np.ones(15), rtol=0.0, atol=1e-12)
    assert evaluation["n_samples"] == 15
    assert sum(sum(row) for row in evaluation["confusion_matrix"]) == 15
    assert evaluation["accuracy"] >= 0.9
    assert run.executor.diagnostics["predict_1"]["serializer"] == "spectrasherpa.model-artifact.knn/1"


@pytest.mark.asyncio
async def test_simca_classification_project_executes_explicit_fit_apply_and_heldout_evaluation(
    canonical_knn_source,
) -> None:
    """The SIMCA starter applies only its closed state to held-out rows."""

    run = await execute_consumer_project(
        "simca_classification",
        source_parameters={"data_1": canonical_knn_source},
    )

    assert run.node_types == {
        "data_1": "data.file_load",
        "partition_1": "data.train_test_split",
        "model_1": "classification.simca",
        "predict_1": "classification.apply_simca",
        "eval_1": "diagnostics.classification_evaluator",
    }
    partition = run.results["partition_1"]
    fitted_state = run.results["model_1"]["fitted_state"]
    predictions = np.asarray(run.results["predict_1"]["y_pred"], dtype=object)
    affinity = np.asarray(run.results["predict_1"]["class_affinity"], dtype=np.float64)
    held_out = np.asarray(partition["y_test"], dtype=object)
    evaluation = run.results["eval_1"]["default"]

    assert fitted_state["serializer"] == "spectrasherpa.model-artifact.simca/1"
    assert predictions.shape == held_out.shape == (15,)
    assert affinity.shape == (15, 3)
    assert np.isfinite(affinity).all()
    assert evaluation["n_samples"] == 15
    assert sum(sum(row) for row in evaluation["confusion_matrix"]) == 15
    assert run.executor.diagnostics["predict_1"]["serializer"] == "spectrasherpa.model-artifact.simca/1"


@pytest.mark.asyncio
async def test_harmonized_nonnegative_project_retains_distinct_preparation_branches(
    canonical_harmonization_sources,
) -> None:
    """Grid alignment, baseline correction, and a literal floor stay distinct."""

    run = await execute_consumer_project(
        "harmonized_nonnegative_spectra",
        source_parameters=canonical_harmonization_sources,
    )

    assert run.node_types == {
        "source_1": "data.file_load",
        "reference_1": "data.file_load",
        "align_1": "preprocess.wavenumber_align",
        "range_1": "preprocess.clip_range",
        "rubberband_1": "baseline.rubberband",
        "floor_1": "preprocess.clip_floor",
    }
    edges = {
        (
            edge["from_node_id"],
            edge.get("from_output", "default"),
            edge["to_node_id"],
            edge.get("to_input", "default"),
        )
        for edge in run.template["edges"]
    }
    assert edges == {
        ("source_1", "default", "align_1", "spectra"),
        ("reference_1", "default", "align_1", "reference"),
        ("align_1", "default", "range_1", "default"),
        ("range_1", "default", "rubberband_1", "default"),
        ("range_1", "default", "floor_1", "default"),
    }
    assert not any(from_node == "rubberband_1" and to_node == "floor_1" for from_node, _, to_node, _ in edges)

    source = run.results["source_1"]["default"]
    reference = run.results["reference_1"]["default"]
    aligned = run.results["align_1"]["default"]
    selected_range = run.results["range_1"]["default"]
    baseline_corrected = run.results["rubberband_1"]["default"]
    floor_clipped = run.results["floor_1"]["default"]
    assert all(
        isinstance(value, SherpaDataset)
        for value in (source, reference, aligned, selected_range, baseline_corrected, floor_clipped)
    )
    assert source.shape == (12, 171)
    assert reference.shape == (12, 148)
    assert aligned.shape == (12, 148)
    np.testing.assert_allclose(aligned.feature_axis.values, reference.feature_axis.values, rtol=0.0, atol=0.0)
    assert aligned.feature_axis.units == reference.feature_axis.units == "cm-1"
    selected_axis = np.asarray(selected_range.feature_axis.values, dtype=np.float64)
    assert selected_range.n_samples == baseline_corrected.n_samples == floor_clipped.n_samples == 12
    assert selected_range.n_features == baseline_corrected.n_features == floor_clipped.n_features
    assert float(selected_axis.min()) >= 1000.0
    assert float(selected_axis.max()) <= 3200.0

    align_diagnostics = run.executor.diagnostics["align_1"]
    range_diagnostics = run.executor.diagnostics["range_1"]
    floor_diagnostics = run.executor.diagnostics["floor_1"]
    assert align_diagnostics["method"] == "pchip"
    assert align_diagnostics["source_axis_units"] == align_diagnostics["reference_axis_units"] == "cm-1"
    assert range_diagnostics["output_features"] == selected_range.n_features
    assert range_diagnostics["axis_units"] == "cm-1"
    assert floor_diagnostics["floor"] == 0.0
    assert floor_diagnostics["clipped_values"] > 0
    assert np.min(np.asarray(floor_clipped.data, dtype=np.float64)) == 0.0

    baseline_operations = baseline_corrected.provenance.operations
    floor_operations = floor_clipped.provenance.operations
    assert baseline_operations[-1] == "baseline.rubberband"
    assert floor_operations[-1] == "preprocess.clip_floor"
    assert "preprocess.clip_floor" not in baseline_operations
    assert "baseline.rubberband" not in floor_operations


@pytest.mark.asyncio
async def test_emsc_reference_correction_project_uses_explicit_fitted_sources(
    canonical_emsc_sources,
) -> None:
    """The saved project fits one explicit EMSC state and applies it once."""

    run = await execute_consumer_project(
        "emsc_reference_correction",
        source_parameters=canonical_emsc_sources,
    )

    assert run.node_types == {
        "application_1": "data.file_load",
        "reference_1": "data.file_load",
        "constituent_1": "data.file_load",
        "emsc_1": "preprocess.emsc",
    }
    edges = {
        (
            edge["from_node_id"],
            edge.get("from_output", "default"),
            edge["to_node_id"],
            edge.get("to_input", "default"),
        )
        for edge in run.template["edges"]
    }
    assert edges == {
        ("application_1", "default", "emsc_1", "default"),
        ("reference_1", "default", "emsc_1", "reference"),
        ("constituent_1", "default", "emsc_1", "constituents"),
    }

    reference = run.results["reference_1"]["default"]
    corrected = run.results["emsc_1"]["default"]
    assert isinstance(reference, SherpaDataset)
    assert isinstance(corrected, SherpaDataset)
    assert corrected.shape == (3, 41)
    np.testing.assert_allclose(
        corrected.data,
        np.repeat(np.asarray(reference.data), corrected.n_samples, axis=0),
        rtol=1e-9,
        atol=1e-9,
    )
    np.testing.assert_allclose(corrected.feature_axis.values, reference.feature_axis.values, rtol=0.0, atol=0.0)
    assert corrected.feature_axis.units == reference.feature_axis.units == "cm-1"

    diagnostics = run.executor.diagnostics["emsc_1"]
    assert diagnostics == {
        "reference_method": "first",
        "poly_order": 2,
        "n_constituents": 1,
        "fitted_state_serializer": "spectra.emsc-reference-json.v1",
    }
    step = corrected.provenance[-1]
    assert step.op_id == "preprocess.emsc"
    assert step.parameters["reference_method"] == "first"
    assert step.parameters["poly_order"] == 2
    assert step.parameters["state_serializer"] == "spectra.emsc-reference-json.v1"
    state = step.parameters["transform_state"]
    assert state["reference_spectrum"] == pytest.approx(np.asarray(reference.data)[0].tolist())
    assert len(state["constituent_spectra"]) == 1


@pytest.mark.asyncio
async def test_msc_reference_correction_project_uses_one_frozen_reference(
    canonical_msc_sources,
) -> None:
    """The saved MSC project fits its declared cohort and applies it once."""

    run = await execute_consumer_project(
        "msc_reference_correction",
        source_parameters=canonical_msc_sources,
    )

    assert run.node_types == {
        "application_1": "data.file_load",
        "reference_1": "data.file_load",
        "msc_1": "preprocess.msc",
    }
    reference = run.results["reference_1"]["default"]
    corrected = run.results["msc_1"]["default"]
    assert isinstance(reference, SherpaDataset)
    assert isinstance(corrected, SherpaDataset)
    np.testing.assert_allclose(
        corrected.X,
        np.repeat(np.mean(reference.X, axis=0, keepdims=True), corrected.shape[0], axis=0),
        rtol=1e-10,
        atol=1e-10,
    )
    assert run.executor.diagnostics["msc_1"] == {
        "reference_method": "mean",
        "fitted_state_serializer": "spectra.msc-reference-json.v2",
    }
