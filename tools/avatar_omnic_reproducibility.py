#!/usr/bin/env python3
"""Build and verify the Avatar three-block acquisition-reproducibility evidence.

The public JSON contains bounded numerical QC projections and exact source/
science bindings.  Scientist-facing plots remain under an ignored private root
until the separate corpus-publication phase authorizes their distribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

from avatar_omnic_corpus import (  # noqa: E402
    DATASET_ID,
    CorpusError,
    _array_sha256,
    _native_arrays,
    _require_private_worktree_path,
    _sha256_bytes,
)

SCHEMA_VERSION = "spectrasherpa-avatar-essential-oils-reproducibility/1"
STATUS = "phase3_acquisition_reproducibility_complete_private_figures_not_distributed"
CORRELATION_THRESHOLD = 0.990
RMS_THRESHOLD = 0.005
CLIPPING_EXACT_RUN_THRESHOLD = 4
EXPECTED_SHAPE = (33, 1868)
PRIVATE_FIGURE_NAMES = (
    "all-spectra-by-block.png",
    "all-spectra-by-specimen.png",
    "block-means-and-differences.png",
    "specimen-difference-spectra.png",
    "pairwise-repeatability.png",
)
CLAIM_BOUNDARY = (
    "Acquisition repeatability of this exact 11-specimen, three-block Avatar corpus; investigation "
    "triggers are not exclusions, and no botanical, authenticity, lot, supplier, or population claim is made."
)
INCLUSION_RULE = (
    "No spectrum is excluded from Phase 3; any later exclusion requires a pre-model measurement reason "
    "and paired reruns."
)
OPTIONAL_DIAGNOSTICS = {
    "atmospheric_regions": "not_run_optional",
    "edge_regions": "not_run_optional",
}
PCA_BLOCK_DRIFT = "deferred_to_phase_6_without_retroactive_exclusion"
FIGURE_STATUS = "generated_private_not_redistributed_pending_phase9_permission"
CHECKED_REPORT_SHA256 = "2bb67c57f0dd380c33383e99f20b601835f1210b99707b3e7f9d95d6c5c1fbb9"

_ROOT_FIELDS = {
    "schema_version",
    "dataset_id",
    "dataset_version",
    "status",
    "source_manifest_sha256",
    "source_parser_qualification_sha256",
    "claim_boundary",
    "thresholds",
    "matrix",
    "spectra",
    "pairwise_repeatability",
    "specimens",
    "blocks",
    "summary",
    "optional_diagnostics",
    "pca_block_drift",
    "inclusion_decision",
    "private_figures",
}
_SPECTRUM_FIELDS = {
    "sample_id",
    "specimen_id",
    "block",
    "acquisition_order",
    "acquired_at",
    "curated_sha256",
    "values_sha256",
    "axis_sha256",
    "minimum_absorbance",
    "maximum_absorbance",
    "mean_absorbance",
    "standard_deviation_absorbance",
    "integrated_absolute_signal_absorbance_cm-1",
    "finite_value_count",
    "nonfinite_value_count",
    "maximum_exact_extreme_plateau_run",
    "clipping_suspected",
    "identity_discrepancy",
    "axis_mismatch",
    "difference_to_specimen_mean_sha256",
    "difference_to_specimen_mean_minimum",
    "difference_to_specimen_mean_maximum",
    "difference_to_specimen_mean_rms",
}
_PAIR_FIELDS = {
    "specimen_id",
    "sample_id_a",
    "sample_id_b",
    "block_a",
    "block_b",
    "pearson_correlation",
    "rms_absorbance_difference",
    "correlation_below_investigation_threshold",
    "rms_above_investigation_threshold",
}


def _json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha256_bytes(payload)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _finite_float(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(np.asarray(values, dtype=np.float64)))))


def _sha256_regular_file(path: Path, expected_size: int) -> str:
    """Hash one exact regular file without materializing it or following links."""

    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 1:
        raise CorpusError(f"{path.name}: manifest source size is invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CorpusError(f"{path.name}: exact private curated source is absent, linked, or unreadable") from exc
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as source:
        source_stat = os.fstat(source.fileno())
        if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size != expected_size:
            raise CorpusError(f"{path.name}: curated source size differs from the manifest")
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _pearson(left: np.ndarray, right: np.ndarray) -> float:
    left_centered = left - np.mean(left)
    right_centered = right - np.mean(right)
    denominator = float(np.sqrt(np.dot(left_centered, left_centered) * np.dot(right_centered, right_centered)))
    if denominator == 0.0 or not math.isfinite(denominator):
        raise CorpusError("a constant or non-finite spectrum has undefined Pearson correlation")
    return float(np.dot(left_centered, right_centered) / denominator)


def _maximum_exact_extreme_plateau_run(values: np.ndarray) -> int:
    """Return the longest exact run occurring at the spectrum minimum or maximum."""

    vector = np.asarray(values, dtype=np.float64)
    extreme = (vector == np.min(vector)) | (vector == np.max(vector))
    longest = current = 0
    previous_value: float | None = None
    for value, is_extreme in zip(vector, extreme, strict=True):
        numeric = float(value)
        if is_extreme and previous_value is not None and numeric == previous_value:
            current += 1
        elif is_extreme:
            current = 1
        else:
            current = 0
        longest = max(longest, current)
        previous_value = numeric
    return longest


def _trapz_absolute(values: np.ndarray, axis: np.ndarray) -> float:
    ascending_axis = np.asarray(axis, dtype=np.float64)[::-1]
    ascending_values = np.abs(np.asarray(values, dtype=np.float64)[::-1])
    if hasattr(np, "trapezoid"):
        return float(np.trapezoid(ascending_values, ascending_axis))
    return float(np.trapz(ascending_values, ascending_axis))  # pragma: no cover - NumPy < 2 fallback


def _load_exact_sources(
    manifest: Mapping[str, Any],
    qualification: Mapping[str, Any],
    curated_dir: Path,
) -> tuple[list[Mapping[str, Any]], np.ndarray, np.ndarray]:
    rows = manifest.get("files")
    qualified_rows = qualification.get("files")
    if not isinstance(rows, list) or len(rows) != 33:
        raise CorpusError("Phase 3 requires the exact 33-row public manifest")
    if not isinstance(qualified_rows, list) or len(qualified_rows) != 33:
        raise CorpusError("Phase 3 requires the exact 33-row parser qualification")
    qualified_by_id = {row.get("sample_id"): row for row in qualified_rows if isinstance(row, Mapping)}
    if len(qualified_by_id) != 33:
        raise CorpusError("Phase-2 qualification identities are missing or duplicated")

    ordered_rows = sorted(rows, key=lambda row: (int(row["block"]), int(row["acquisition_order"])))
    values: list[np.ndarray] = []
    common_axis: np.ndarray | None = None
    seen_ids: set[str] = set()
    for row in ordered_rows:
        if not isinstance(row, Mapping):
            raise CorpusError("every manifest row must be an object")
        sample_id = str(row.get("sample_id"))
        if sample_id in seen_ids:
            raise CorpusError("manifest sample identities must be unique")
        seen_ids.add(sample_id)
        qualified = qualified_by_id.get(sample_id)
        if qualified is None or qualified.get("external_converter_full_array_equal") is not True:
            raise CorpusError(f"{sample_id}: Phase-2 full-array qualification is absent")
        filename = row.get("distribution_filename")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise CorpusError(f"{sample_id}: distribution filename is not a basename")
        path = curated_dir / filename
        if _sha256_regular_file(path, row.get("size_bytes")) != row.get("curated_sha256"):
            raise CorpusError(f"{sample_id}: curated source digest differs from the manifest")
        spectrum, axis, _dataset = _native_arrays(path)
        if _array_sha256(spectrum) != row.get("values_sha256"):
            raise CorpusError(f"{sample_id}: native ordinate digest differs from the manifest")
        if _array_sha256(axis) != row.get("axis_sha256"):
            raise CorpusError(f"{sample_id}: native axis digest differs from the manifest")
        if qualified.get("values_sha256") != row.get("values_sha256") or qualified.get("axis_sha256") != row.get(
            "axis_sha256"
        ):
            raise CorpusError(f"{sample_id}: Phase-2 science binding differs from the manifest")
        if common_axis is None:
            common_axis = axis
        elif not np.array_equal(common_axis, axis):
            raise CorpusError(f"{sample_id}: feature axis differs from the corpus authority")
        values.append(spectrum)
    if len(seen_ids) != 33 or common_axis is None:
        raise CorpusError("Phase 3 did not admit the exact 33 source identities")
    matrix = np.vstack(values)
    if matrix.shape != EXPECTED_SHAPE:
        raise CorpusError(f"Phase-3 matrix has unexpected shape {matrix.shape}")
    return ordered_rows, matrix, common_axis


def _private_figure_record(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CorpusError(f"private figure {path.name} is not a regular file")
    os.chmod(path, 0o600)
    return {
        "filename": path.name,
        "sha256": _sha256_bytes(path.read_bytes()),
        "size_bytes": path.stat().st_size,
        "status": FIGURE_STATUS,
    }


def _save_private_figure(figure: Any, target: Path, *, dpi: int, metadata: Mapping[str, Any]) -> None:
    """Save one private plot through a restricted same-directory atomic file."""

    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file():
            raise CorpusError(f"private figure target {target.name} is linked or non-regular")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{target.stem}.",
            suffix=".png",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        figure.savefig(temporary_path, dpi=dpi, metadata=metadata)
        os.chmod(temporary_path, 0o600)
        with temporary_path.open("rb") as saved:
            os.fsync(saved.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
        os.chmod(target, 0o600)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _render_private_figures(
    output_dir: Path,
    rows: Sequence[Mapping[str, Any]],
    matrix: np.ndarray,
    axis: np.ndarray,
    pair_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output_dir = _require_private_worktree_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    for child in output_dir.iterdir():
        if child.is_symlink() or not child.is_file() or child.name not in PRIVATE_FIGURE_NAMES:
            raise CorpusError(f"private figure directory contains unexpected file {child.name}")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8, "legend.fontsize": 6})
    specimen_ids = sorted({str(row["specimen_id"]) for row in rows})
    block_colors = {1: "#0072B2", 2: "#D55E00", 3: "#009E73"}
    save_metadata = {"Software": "SpectraSherpa Avatar Phase 3", "Creation Time": None}

    figure, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True, sharey=True)
    for block, panel in zip((1, 2, 3), axes, strict=True):
        for index, row in enumerate(rows):
            if int(row["block"]) == block:
                panel.plot(axis, matrix[index], linewidth=0.7, alpha=0.75, label=str(row["specimen_id"]))
        panel.set_title(f"Block {block}: all 11 spectra")
        panel.set_ylabel("Absorbance")
        panel.legend(ncol=6, loc="upper right")
    axes[-1].set_xlabel("Wavenumber (cm⁻¹)")
    axes[-1].set_xlim(float(axis[0]), float(axis[-1]))
    figure.tight_layout()
    path = output_dir / PRIVATE_FIGURE_NAMES[0]
    _save_private_figure(figure, path, dpi=150, metadata=save_metadata)
    plt.close(figure)

    figure, axes = plt.subplots(4, 3, figsize=(11, 11), sharex=True, sharey=True)
    flat_axes = list(axes.flat)
    for panel, specimen in zip(flat_axes, specimen_ids, strict=False):
        for index, row in enumerate(rows):
            if row["specimen_id"] == specimen:
                block = int(row["block"])
                panel.plot(axis, matrix[index], color=block_colors[block], linewidth=0.8, label=f"B{block}")
        panel.set_title(specimen)
    for panel in flat_axes[len(specimen_ids) :]:
        panel.axis("off")
    flat_axes[0].legend(loc="upper right")
    flat_axes[0].set_xlim(float(axis[0]), float(axis[-1]))
    figure.supxlabel("Wavenumber (cm⁻¹)")
    figure.supylabel("Absorbance")
    figure.tight_layout()
    path = output_dir / PRIVATE_FIGURE_NAMES[1]
    _save_private_figure(figure, path, dpi=150, metadata=save_metadata)
    plt.close(figure)

    block_means = {block: np.mean(matrix[[int(row["block"]) == block for row in rows]], axis=0) for block in (1, 2, 3)}
    grand_mean = np.mean(matrix, axis=0)
    figure, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for block in (1, 2, 3):
        axes[0].plot(axis, block_means[block], color=block_colors[block], label=f"Block {block}")
        axes[1].plot(axis, block_means[block] - grand_mean, color=block_colors[block], label=f"B{block} − grand")
    axes[0].set_ylabel("Mean absorbance")
    axes[1].set_ylabel("Difference")
    axes[1].set_xlabel("Wavenumber (cm⁻¹)")
    for panel in axes:
        panel.legend()
    axes[-1].set_xlim(float(axis[0]), float(axis[-1]))
    figure.tight_layout()
    path = output_dir / PRIVATE_FIGURE_NAMES[2]
    _save_private_figure(figure, path, dpi=150, metadata=save_metadata)
    plt.close(figure)

    figure, axes = plt.subplots(4, 3, figsize=(11, 11), sharex=True, sharey=True)
    flat_axes = list(axes.flat)
    for panel, specimen in zip(flat_axes, specimen_ids, strict=False):
        indices = [index for index, row in enumerate(rows) if row["specimen_id"] == specimen]
        mean = np.mean(matrix[indices], axis=0)
        for index in indices:
            block = int(rows[index]["block"])
            panel.plot(axis, matrix[index] - mean, color=block_colors[block], linewidth=0.8, label=f"B{block}")
        panel.axhline(0.0, color="#777777", linewidth=0.4)
        panel.set_title(specimen)
    for panel in flat_axes[len(specimen_ids) :]:
        panel.axis("off")
    flat_axes[0].legend(loc="upper right")
    flat_axes[0].set_xlim(float(axis[0]), float(axis[-1]))
    figure.supxlabel("Wavenumber (cm⁻¹)")
    figure.supylabel("Spectrum − specimen mean")
    figure.tight_layout()
    path = output_dir / PRIVATE_FIGURE_NAMES[3]
    _save_private_figure(figure, path, dpi=150, metadata=save_metadata)
    plt.close(figure)

    figure, axis_panel = plt.subplots(figsize=(8, 5))
    for pair in pair_rows:
        axis_panel.scatter(
            pair["rms_absorbance_difference"],
            pair["pearson_correlation"],
            s=18,
            alpha=0.75,
            label=pair["specimen_id"],
        )
    axis_panel.axhline(CORRELATION_THRESHOLD, color="#D55E00", linestyle="--", label="correlation trigger")
    axis_panel.axvline(RMS_THRESHOLD, color="#CC79A7", linestyle="--", label="RMS trigger")
    axis_panel.set_xlabel("Pairwise RMS absorbance difference")
    axis_panel.set_ylabel("Pearson correlation")
    handles, labels = axis_panel.get_legend_handles_labels()
    unique = dict(zip(labels, handles, strict=True))
    axis_panel.legend(unique.values(), unique.keys(), ncol=3, loc="lower left")
    figure.tight_layout()
    path = output_dir / PRIVATE_FIGURE_NAMES[4]
    _save_private_figure(figure, path, dpi=150, metadata=save_metadata)
    plt.close(figure)

    return [_private_figure_record(output_dir / name) for name in PRIVATE_FIGURE_NAMES]


def build_phase3_report(
    manifest_path: Path,
    qualification_path: Path,
    curated_dir: Path,
    private_figure_dir: Path,
) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    qualification_bytes = qualification_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    qualification = json.loads(qualification_bytes)
    if manifest.get("dataset_id") != DATASET_ID or qualification.get("dataset_id") != DATASET_ID:
        raise CorpusError("Phase 3 sources do not identify the Avatar oil corpus")
    if qualification.get("source_manifest_sha256") != _sha256_bytes(manifest_bytes):
        raise CorpusError("Phase-2 qualification is not bound to the exact manifest")
    if (
        qualification.get("structural_ingestion_passed") is not True
        or qualification.get("external_converter_parity_verified") is not True
    ):
        raise CorpusError("Phase 3 requires structural and full-array external Phase-2 qualification")

    rows, matrix, axis = _load_exact_sources(manifest, qualification, curated_dir)
    specimen_indices: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        specimen_indices.setdefault(str(row["specimen_id"]), []).append(index)
    if len(specimen_indices) != 11 or any(len(indices) != 3 for indices in specimen_indices.values()):
        raise CorpusError("Phase 3 requires exactly three blocks for each of 11 specimens")

    specimen_means = {specimen: np.mean(matrix[indices], axis=0) for specimen, indices in specimen_indices.items()}
    spectrum_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        values = matrix[index]
        specimen = str(row["specimen_id"])
        difference = values - specimen_means[specimen]
        plateau_run = _maximum_exact_extreme_plateau_run(values)
        spectrum_rows.append(
            {
                "sample_id": row["sample_id"],
                "specimen_id": specimen,
                "block": row["block"],
                "acquisition_order": row["acquisition_order"],
                "acquired_at": row["acquired_at"],
                "curated_sha256": row["curated_sha256"],
                "values_sha256": row["values_sha256"],
                "axis_sha256": row["axis_sha256"],
                "minimum_absorbance": float(np.min(values)),
                "maximum_absorbance": float(np.max(values)),
                "mean_absorbance": float(np.mean(values)),
                "standard_deviation_absorbance": float(np.std(values)),
                "integrated_absolute_signal_absorbance_cm-1": _trapz_absolute(values, axis),
                "finite_value_count": int(np.count_nonzero(np.isfinite(values))),
                "nonfinite_value_count": int(np.count_nonzero(~np.isfinite(values))),
                "maximum_exact_extreme_plateau_run": plateau_run,
                "clipping_suspected": plateau_run >= CLIPPING_EXACT_RUN_THRESHOLD,
                "identity_discrepancy": False,
                "axis_mismatch": False,
                "difference_to_specimen_mean_sha256": _array_sha256(difference),
                "difference_to_specimen_mean_minimum": float(np.min(difference)),
                "difference_to_specimen_mean_maximum": float(np.max(difference)),
                "difference_to_specimen_mean_rms": _rms(difference),
            }
        )

    pair_rows: list[dict[str, Any]] = []
    for specimen in sorted(specimen_indices):
        for left_index, right_index in combinations(specimen_indices[specimen], 2):
            correlation = _pearson(matrix[left_index], matrix[right_index])
            rms = _rms(matrix[left_index] - matrix[right_index])
            pair_rows.append(
                {
                    "specimen_id": specimen,
                    "sample_id_a": rows[left_index]["sample_id"],
                    "sample_id_b": rows[right_index]["sample_id"],
                    "block_a": rows[left_index]["block"],
                    "block_b": rows[right_index]["block"],
                    "pearson_correlation": correlation,
                    "rms_absorbance_difference": rms,
                    "correlation_below_investigation_threshold": correlation < CORRELATION_THRESHOLD,
                    "rms_above_investigation_threshold": rms > RMS_THRESHOLD,
                }
            )

    specimen_rows = [
        {
            "specimen_id": specimen,
            "sample_ids": [rows[index]["sample_id"] for index in indices],
            "three_block_mean_sha256": _array_sha256(specimen_means[specimen]),
            "maximum_difference_to_mean_rms": max(
                row["difference_to_specimen_mean_rms"] for row in spectrum_rows if row["specimen_id"] == specimen
            ),
        }
        for specimen, indices in sorted(specimen_indices.items())
    ]

    grand_mean = np.mean(matrix, axis=0)
    block_rows: list[dict[str, Any]] = []
    for block in (1, 2, 3):
        indices = [index for index, row in enumerate(rows) if int(row["block"]) == block]
        block_mean = np.mean(matrix[indices], axis=0)
        difference = block_mean - grand_mean
        block_rows.append(
            {
                "block": block,
                "sample_ids": [rows[index]["sample_id"] for index in indices],
                "mean_spectrum_sha256": _array_sha256(block_mean),
                "difference_to_grand_mean_sha256": _array_sha256(difference),
                "difference_to_grand_mean_rms": _rms(difference),
            }
        )

    correlations = [float(row["pearson_correlation"]) for row in pair_rows]
    pairwise_rms = [float(row["rms_absorbance_difference"]) for row in pair_rows]
    figures = _render_private_figures(private_figure_dir, rows, matrix, axis, pair_rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "dataset_version": manifest["dataset_version"],
        "status": STATUS,
        "source_manifest_sha256": _sha256_bytes(manifest_bytes),
        "source_parser_qualification_sha256": _sha256_bytes(qualification_bytes),
        "claim_boundary": CLAIM_BOUNDARY,
        "thresholds": {
            "pearson_correlation_below": CORRELATION_THRESHOLD,
            "rms_absorbance_difference_above": RMS_THRESHOLD,
            "nonfinite_value_count_above": 0,
            "axis_or_identity_discrepancy": "any",
            "clipping_detector": {
                "method": "exact repeated values at the spectrum minimum or maximum",
                "minimum_consecutive_points": CLIPPING_EXACT_RUN_THRESHOLD,
                "interpretation": "investigation trigger only",
            },
        },
        "matrix": {
            "shape": list(matrix.shape),
            "values_sha256": _array_sha256(matrix),
            "axis_sha256": _array_sha256(axis),
            "axis_units": "cm^-1",
            "axis_order": "strictly_descending",
            "sample_order": [row["sample_id"] for row in rows],
        },
        "spectra": spectrum_rows,
        "pairwise_repeatability": pair_rows,
        "specimens": specimen_rows,
        "blocks": block_rows,
        "summary": {
            "spectrum_count": 33,
            "specimen_count": 11,
            "block_count": 3,
            "pairwise_comparison_count": 33,
            "minimum_same_specimen_pearson_correlation": min(correlations),
            "median_pairwise_rms_absorbance_difference": float(np.median(pairwise_rms)),
            "maximum_pairwise_rms_absorbance_difference": max(pairwise_rms),
            "correlation_investigation_trigger_count": sum(value < CORRELATION_THRESHOLD for value in correlations),
            "rms_investigation_trigger_count": sum(value > RMS_THRESHOLD for value in pairwise_rms),
            "nonfinite_investigation_trigger_count": sum(
                int(row["nonfinite_value_count"] > 0) for row in spectrum_rows
            ),
            "clipping_investigation_trigger_count": sum(bool(row["clipping_suspected"]) for row in spectrum_rows),
            "axis_mismatch_count": 0,
            "identity_discrepancy_count": 0,
        },
        "optional_diagnostics": OPTIONAL_DIAGNOSTICS,
        "pca_block_drift": PCA_BLOCK_DRIFT,
        "inclusion_decision": {
            "included_sample_ids": [row["sample_id"] for row in rows],
            "excluded_sample_ids": [],
            "rule": INCLUSION_RULE,
        },
        "private_figures": figures,
    }
    failures = validate_phase3_evidence_links(report, manifest_bytes, qualification_bytes)
    if failures:
        raise CorpusError("Phase-3 evidence-link validation failed: " + "; ".join(failures))
    return report


def validate_phase3_evidence_links(  # noqa: C901 - closed evidence schema is intentionally exhaustive
    report: Mapping[str, Any],
    manifest_bytes: bytes,
    qualification_bytes: bytes,
) -> list[str]:
    failures: list[str] = []
    try:
        manifest = json.loads(manifest_bytes)
        qualification = json.loads(qualification_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"Phase-3 source evidence is unreadable: {type(exc).__name__}"]
    if set(report) != _ROOT_FIELDS:
        failures.append("Phase-3 root schema is not closed")
    if report.get("schema_version") != SCHEMA_VERSION or report.get("dataset_id") != DATASET_ID:
        failures.append("Phase-3 identity or schema is invalid")
    if report.get("status") != STATUS:
        failures.append("Phase-3 status is not the exact private-figure completion state")
    if report.get("dataset_version") != manifest.get("dataset_version"):
        failures.append("Phase-3 dataset version differs from the source manifest")
    if report.get("claim_boundary") != CLAIM_BOUNDARY:
        failures.append("Phase-3 claim boundary is not the exact bounded acquisition claim")
    expected_thresholds = {
        "pearson_correlation_below": CORRELATION_THRESHOLD,
        "rms_absorbance_difference_above": RMS_THRESHOLD,
        "nonfinite_value_count_above": 0,
        "axis_or_identity_discrepancy": "any",
        "clipping_detector": {
            "method": "exact repeated values at the spectrum minimum or maximum",
            "minimum_consecutive_points": CLIPPING_EXACT_RUN_THRESHOLD,
            "interpretation": "investigation trigger only",
        },
    }
    if report.get("thresholds") != expected_thresholds:
        failures.append("Phase-3 investigation thresholds or interpretation differ")
    if report.get("source_manifest_sha256") != _sha256_bytes(manifest_bytes):
        failures.append("Phase-3 report is not bound to the exact manifest")
    if report.get("source_parser_qualification_sha256") != _sha256_bytes(qualification_bytes):
        failures.append("Phase-3 report is not bound to the exact parser qualification")
    if qualification.get("source_manifest_sha256") != _sha256_bytes(manifest_bytes):
        failures.append("Phase-2 qualification is not bound to the Phase-3 manifest")

    manifest_rows = manifest.get("files")
    qualification_rows = qualification.get("files")
    spectra = report.get("spectra")
    pairs = report.get("pairwise_repeatability")
    if not all(isinstance(value, list) for value in (manifest_rows, qualification_rows, spectra, pairs)):
        return [*failures, "Phase-3 row collections are malformed"]
    manifest_by_id = {row.get("sample_id"): row for row in manifest_rows if isinstance(row, Mapping)}
    qualified_by_id = {row.get("sample_id"): row for row in qualification_rows if isinstance(row, Mapping)}
    spectra_by_id = {row.get("sample_id"): row for row in spectra if isinstance(row, Mapping)}
    if not (len(manifest_by_id) == len(qualified_by_id) == len(spectra_by_id) == 33):
        failures.append("Phase-3 sample identities are missing, duplicated, or substituted")
        return failures
    if not (set(manifest_by_id) == set(qualified_by_id) == set(spectra_by_id)):
        failures.append("Phase-3 sample identity sets disagree")
        return failures
    expected_order = [
        row["sample_id"]
        for row in sorted(manifest_rows, key=lambda row: (int(row["block"]), int(row["acquisition_order"])))
    ]
    for sample_id, row in spectra_by_id.items():
        if set(row) != _SPECTRUM_FIELDS:
            failures.append(f"{sample_id}: spectrum schema is not closed")
            continue
        manifest_row = manifest_by_id[sample_id]
        qualified_row = qualified_by_id[sample_id]
        bindings = (
            (row.get("curated_sha256"), manifest_row.get("curated_sha256"), "source"),
            (row.get("values_sha256"), manifest_row.get("values_sha256"), "values"),
            (row.get("axis_sha256"), manifest_row.get("axis_sha256"), "axis"),
            (qualified_row.get("values_sha256"), manifest_row.get("values_sha256"), "qualified values"),
            (qualified_row.get("axis_sha256"), manifest_row.get("axis_sha256"), "qualified axis"),
        )
        for observed, expected, field in bindings:
            if observed != expected:
                failures.append(f"{sample_id}: {field} binding differs")
        if row.get("specimen_id") != manifest_row.get("specimen_id") or row.get("block") != manifest_row.get("block"):
            failures.append(f"{sample_id}: specimen/block identity differs")
        if row.get("acquisition_order") != manifest_row.get("acquisition_order") or row.get(
            "acquired_at"
        ) != manifest_row.get("acquired_at"):
            failures.append(f"{sample_id}: acquisition identity differs")
        numeric_fields = _SPECTRUM_FIELDS - {
            "sample_id",
            "specimen_id",
            "acquired_at",
            "curated_sha256",
            "values_sha256",
            "axis_sha256",
            "difference_to_specimen_mean_sha256",
            "clipping_suspected",
            "identity_discrepancy",
            "axis_mismatch",
        }
        if any(not _finite_float(row.get(field)) for field in numeric_fields):
            failures.append(f"{sample_id}: numerical QC field is not finite")
        if row.get("finite_value_count") != 1868 or row.get("nonfinite_value_count") != 0:
            failures.append(f"{sample_id}: finite/nonfinite count is invalid")
        plateau = row.get("maximum_exact_extreme_plateau_run")
        if row.get("clipping_suspected") is not (isinstance(plateau, int) and plateau >= CLIPPING_EXACT_RUN_THRESHOLD):
            failures.append(f"{sample_id}: clipping flag disagrees with the detector")
        if row.get("identity_discrepancy") is not False or row.get("axis_mismatch") is not False:
            failures.append(f"{sample_id}: an identity/axis discrepancy is not reconciled")
        if not _is_sha256(row.get("difference_to_specimen_mean_sha256")):
            failures.append(f"{sample_id}: difference spectrum digest is invalid")

    pairs_closed = len(pairs) == 33 and all(isinstance(row, Mapping) and set(row) == _PAIR_FIELDS for row in pairs)
    if not pairs_closed:
        failures.append("Phase-3 pairwise repeatability rows are not the exact closed 33-row set")
    else:
        pair_keys: set[tuple[str, int, int]] = set()
        for row in pairs:
            correlation = row.get("pearson_correlation")
            rms = row.get("rms_absorbance_difference")
            if not _finite_float(correlation) or not _finite_float(rms):
                failures.append("Phase-3 pairwise metric is non-finite")
                continue
            if row.get("correlation_below_investigation_threshold") is not (float(correlation) < CORRELATION_THRESHOLD):
                failures.append("Phase-3 correlation trigger disagrees with its threshold")
            if row.get("rms_above_investigation_threshold") is not (float(rms) > RMS_THRESHOLD):
                failures.append("Phase-3 RMS trigger disagrees with its threshold")
            key = (str(row.get("specimen_id")), int(row.get("block_a", 0)), int(row.get("block_b", 0)))
            pair_keys.add(key)
            sample_a = spectra_by_id.get(row.get("sample_id_a"))
            sample_b = spectra_by_id.get(row.get("sample_id_b"))
            if (
                sample_a is None
                or sample_b is None
                or sample_a.get("specimen_id") != row.get("specimen_id")
                or sample_b.get("specimen_id") != row.get("specimen_id")
                or sample_a.get("block") != row.get("block_a")
                or sample_b.get("block") != row.get("block_b")
            ):
                failures.append("Phase-3 pairwise row is not bound to its exact samples and blocks")
        expected_pair_keys = {
            (specimen, left, right)
            for specimen in {r["specimen_id"] for r in manifest_rows}
            for left, right in combinations((1, 2, 3), 2)
        }
        if pair_keys != expected_pair_keys:
            failures.append("Phase-3 pairwise block/specimen coverage is incomplete")

    matrix = report.get("matrix")
    matrix_fields = {"shape", "values_sha256", "axis_sha256", "axis_units", "axis_order", "sample_order"}
    if not isinstance(matrix, Mapping) or set(matrix) != matrix_fields or matrix.get("shape") != [33, 1868]:
        failures.append("Phase-3 matrix projection has the wrong shape")
    else:
        if matrix.get("sample_order") != expected_order:
            failures.append("Phase-3 matrix sample order differs from the manifest")
        if not _is_sha256(matrix.get("values_sha256")) or matrix.get("axis_sha256") != manifest_rows[0].get(
            "axis_sha256"
        ):
            failures.append("Phase-3 matrix science digest is invalid")
        if matrix.get("axis_units") != "cm^-1" or matrix.get("axis_order") != "strictly_descending":
            failures.append("Phase-3 matrix axis semantics are invalid")

    specimens = report.get("specimens")
    expected_specimen_ids = [spectra_by_id[sample_id]["specimen_id"] for sample_id in expected_order[:11]]
    specimen_fields = {
        "specimen_id",
        "sample_ids",
        "three_block_mean_sha256",
        "maximum_difference_to_mean_rms",
    }
    if not isinstance(specimens, list) or [
        row.get("specimen_id") for row in specimens if isinstance(row, Mapping)
    ] != sorted(expected_specimen_ids):
        failures.append("Phase-3 specimen summary identities are incomplete or reordered")
    else:
        for row in specimens:
            specimen_id = row.get("specimen_id")
            expected_ids = [
                sample_id for sample_id in expected_order if spectra_by_id[sample_id]["specimen_id"] == specimen_id
            ]
            expected_max = max(
                float(spectra_by_id[sample_id]["difference_to_specimen_mean_rms"]) for sample_id in expected_ids
            )
            if (
                set(row) != specimen_fields
                or row.get("sample_ids") != expected_ids
                or not _is_sha256(row.get("three_block_mean_sha256"))
                or row.get("maximum_difference_to_mean_rms") != expected_max
            ):
                failures.append(f"{specimen_id}: specimen summary is malformed or disagrees with its spectra")

    blocks = report.get("blocks")
    block_fields = {
        "block",
        "sample_ids",
        "mean_spectrum_sha256",
        "difference_to_grand_mean_sha256",
        "difference_to_grand_mean_rms",
    }
    if not isinstance(blocks, list) or [row.get("block") for row in blocks if isinstance(row, Mapping)] != [1, 2, 3]:
        failures.append("Phase-3 block summary identities are incomplete or reordered")
    else:
        for row in blocks:
            block = row.get("block")
            expected_ids = [sample_id for sample_id in expected_order if spectra_by_id[sample_id]["block"] == block]
            if (
                set(row) != block_fields
                or row.get("sample_ids") != expected_ids
                or not _is_sha256(row.get("mean_spectrum_sha256"))
                or not _is_sha256(row.get("difference_to_grand_mean_sha256"))
                or not _finite_float(row.get("difference_to_grand_mean_rms"))
            ):
                failures.append(f"Block {block}: summary is malformed or disagrees with its spectra")

    summary = report.get("summary")
    correlations = [row.get("pearson_correlation") for row in pairs] if pairs_closed else []
    pairwise_rms = [row.get("rms_absorbance_difference") for row in pairs] if pairs_closed else []
    if not pairs_closed or not all(_finite_float(value) for value in [*correlations, *pairwise_rms]):
        failures.append("Phase-3 summary cannot be recomputed from non-finite pairwise metrics")
    else:
        expected_summary = {
            "spectrum_count": 33,
            "specimen_count": 11,
            "block_count": 3,
            "pairwise_comparison_count": 33,
            "minimum_same_specimen_pearson_correlation": min(float(value) for value in correlations),
            "median_pairwise_rms_absorbance_difference": float(np.median([float(value) for value in pairwise_rms])),
            "maximum_pairwise_rms_absorbance_difference": max(float(value) for value in pairwise_rms),
            "correlation_investigation_trigger_count": sum(
                float(value) < CORRELATION_THRESHOLD for value in correlations
            ),
            "rms_investigation_trigger_count": sum(float(value) > RMS_THRESHOLD for value in pairwise_rms),
            "nonfinite_investigation_trigger_count": sum(int(row["nonfinite_value_count"] > 0) for row in spectra),
            "clipping_investigation_trigger_count": sum(bool(row["clipping_suspected"]) for row in spectra),
            "axis_mismatch_count": sum(bool(row["axis_mismatch"]) for row in spectra),
            "identity_discrepancy_count": sum(bool(row["identity_discrepancy"]) for row in spectra),
        }
        if summary != expected_summary:
            failures.append("Phase-3 summary does not exactly recompute from its bounded QC rows")

    inclusion = report.get("inclusion_decision")
    if (
        not isinstance(inclusion, Mapping)
        or set(inclusion) != {"included_sample_ids", "excluded_sample_ids", "rule"}
        or inclusion.get("excluded_sample_ids") != []
        or inclusion.get("included_sample_ids") != expected_order
        or inclusion.get("rule") != INCLUSION_RULE
    ):
        failures.append("Phase 3 silently excludes or substitutes a source row")
    if report.get("optional_diagnostics") != OPTIONAL_DIAGNOSTICS or report.get("pca_block_drift") != PCA_BLOCK_DRIFT:
        failures.append("Phase-3 optional diagnostics or PCA deferral state differs")
    figures = report.get("private_figures")
    if not isinstance(figures, list) or [row.get("filename") for row in figures if isinstance(row, Mapping)] != list(
        PRIVATE_FIGURE_NAMES
    ):
        failures.append("Phase-3 private figure inventory is incomplete or reordered")
    else:
        for row in figures:
            if (
                set(row) != {"filename", "sha256", "size_bytes", "status"}
                or not _is_sha256(row.get("sha256"))
                or not isinstance(row.get("size_bytes"), int)
                or row.get("size_bytes") <= 0
            ):
                failures.append("Phase-3 private figure record is malformed")
            if row.get("status") != FIGURE_STATUS:
                failures.append("Phase-3 private figure publication boundary is overstated")

    serialized = json.dumps(report, sort_keys=True, ensure_ascii=False)
    if "/Users/" in serialized or "private-input" in serialized or "EO_Lavender_" in serialized:
        failures.append("Phase-3 public evidence contains a private path or acquisition identifier")
    return failures


def validate_checked_phase3_evidence(
    report_path: Path,
    manifest_path: Path,
    qualification_path: Path,
) -> list[str]:
    """Validate the immutable public report where private arrays are unavailable."""

    try:
        report_bytes = report_path.read_bytes()
        manifest_bytes = manifest_path.read_bytes()
        qualification_bytes = qualification_path.read_bytes()
        report = json.loads(report_bytes)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"checked Phase-3 evidence is unreadable: {type(exc).__name__}"]
    if _sha256_bytes(report_bytes) != CHECKED_REPORT_SHA256:
        return ["checked Phase-3 report digest differs from the exact reviewed authority"]
    return validate_phase3_evidence_links(report, manifest_bytes, qualification_bytes)


def validate_phase3_report(
    report: Mapping[str, Any],
    manifest_path: Path,
    qualification_path: Path,
    curated_dir: Path,
    private_figure_dir: Path,
) -> list[str]:
    try:
        expected = build_phase3_report(manifest_path, qualification_path, curated_dir, private_figure_dir)
    except (CorpusError, OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"Phase-3 source re-admission failed: {type(exc).__name__}: {exc}"]
    if dict(report) != expected:
        return ["Phase-3 report does not exactly match the re-admitted source matrix and private figures"]
    return []


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "check"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--manifest", type=Path, required=True)
        subparser.add_argument("--qualification", type=Path, required=True)
        subparser.add_argument("--curated-dir", type=Path, required=True)
        subparser.add_argument("--private-figure-dir", type=Path, required=True)
        if command == "build":
            subparser.add_argument("--output", type=Path, required=True)
        else:
            subparser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "build":
        report = build_phase3_report(
            arguments.manifest,
            arguments.qualification,
            arguments.curated_dir,
            arguments.private_figure_dir,
        )
        _write_json(arguments.output, report)
    else:
        report = json.loads(arguments.report.read_text(encoding="utf-8"))
        failures = validate_phase3_report(
            report,
            arguments.manifest,
            arguments.qualification,
            arguments.curated_dir,
            arguments.private_figure_dir,
        )
        if failures:
            raise CorpusError("; ".join(failures))
        print("Avatar OMNIC Phase 3 acquisition reproducibility: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
