#!/usr/bin/env python3
"""Build and verify the private/public Avatar essential-oil corpus boundary.

The private inventory may contain acquisition filenames and embedded titles and
must be written only under an ignored/private location.  The public manifest
contains only canonical identities and curated-file hashes.  It deliberately
does not provide a way to publish the private crosswalk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.file_permissions import restrict_file_descriptor
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.transport import reject_spectrochempy_transport
from spectra_sherpa.io import ingest

DATASET_ID = "avatar-essential-oils/1"
PRIVATE_SCHEMA = "spectrasherpa-avatar-essential-oils-private-inventory/2"
PUBLIC_SCHEMA = "spectrasherpa-avatar-essential-oils-public-manifest/2"
PHASE2_SCHEMA = "spectrasherpa-avatar-essential-oils-parser-qualification/1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PRIVATE_WORKTREE_ROOT = REPOSITORY_ROOT / "private-input"
PHASE1_STATUS = "curated_not_yet_distribution_qualified"
PHASE1_LICENSE = "license_selection_pending"
EXTERNAL_OMNIC_COMPARATOR = {
    "project": "spectrochempy-omnic",
    "version": "0.2.1",
    "commit": "2eb6b7d3964451d35eeb0c185cb99a0cc147c7cd",
    "upstream_url": "https://github.com/spectrochempy/spectrochempy-omnic",
    "license": "CeCILL-B",
    "source_tree_sha256": "8fbb46eebf22b81ea9395894cfdb4067a6bac0790a3a2d9e7980862b0c98cf4e",
    "license_sha256": "fb5b89c84879627a3149f3c94f3620da9fd8799419e6f8ffd8179066af1efb6a",
}
PRIVACY_STATEMENT = "Supplier identity is not collected in the public corpus."
CLAIM_BOUNDARY = (
    "Technical/acquisition replicates for native ingestion, reproducibility, PCA, and closed-set "
    "specimen-ID pipeline validation; not population-level botanical or authenticity evidence."
)

_PUBLIC_ROOT_FIELDS = {
    "schema_version",
    "dataset_id",
    "dataset_version",
    "status",
    "dataset_license",
    "privacy_statement",
    "claim_boundary",
    "instrument",
    "qualified_parser_metadata_fields",
    "files",
}
_PUBLIC_FILE_FIELDS = {
    "distribution_filename",
    "curated_sha256",
    "size_bytes",
    "sample_id",
    "specimen_id",
    "block",
    "acquisition_order",
    "canonical_omnic_title",
    "label_status",
    "curation_equivalence",
    "claimed_botanical_group",
    "author_reported_authenticity_status",
    "evidence_status",
    "analysis_role",
    "format_id",
    "variant",
    "parser_id",
    "parser_version",
    "asset_id",
    "shape",
    "axis_units",
    "feature_axis_order",
    "value_units",
    "acquired_at",
    "values_sha256",
    "axis_sha256",
    "qualified_parser_metadata_sha256",
}
_PRIVATE_FILE_FIELDS = {
    "block",
    "acquisition_order",
    "specimen_id",
    "label_status",
    "archive_member",
    "source_sha256",
    "size_bytes",
    "embedded_title",
    "acquired_at",
    "format_id",
    "variant",
    "parser_id",
    "parser_version",
    "asset_id",
    "shape",
    "axis_units",
    "value_units",
    "values_sha256",
    "axis_sha256",
    "qualified_parser_metadata_sha256",
    "qualified_parser_metadata",
}

ARCHIVE_SHA256 = {
    1: "3761da196383c402d77e571348d096999ee47164e8a578360d5ab6ce902428c5",
    2: "7f58861ea416db2a522f991290c5c4ea50b539511407e02074483fc072eff2d9",
    3: "993e497ec2fd4ca837f5d3f4aefe7c5db4bc98357eaefdff0934157b43820ccb",
}

SPECIMEN_METADATA: dict[str, dict[str, str]] = {
    "MSL": {
        "claimed_botanical_group": "Lavandula latifolia",
        "author_reported_authenticity_status": "supplier_claim",
        "evidence_status": "not_applicable",
        "analysis_role": "oil",
    },
    "ELF": {
        "claimed_botanical_group": "Lavandula angustifolia",
        "author_reported_authenticity_status": "authenticated_essential_oil",
        "evidence_status": "pending_exact_citation",
        "analysis_role": "oil",
    },
    "ESL": {
        "claimed_botanical_group": "Lavandula x intermedia",
        "author_reported_authenticity_status": "authenticated_essential_oil",
        "evidence_status": "pending_exact_citation",
        "analysis_role": "oil",
    },
    "DL": {
        "claimed_botanical_group": "Lavandula angustifolia",
        "author_reported_authenticity_status": "known_non_authentic",
        "evidence_status": "pending_exact_citation",
        "analysis_role": "oil_external_challenge",
    },
    "CL": {
        "claimed_botanical_group": "Lavandula angustifolia",
        "author_reported_authenticity_status": "authenticated_essential_oil",
        "evidence_status": "pending_exact_citation",
        "analysis_role": "oil",
    },
    "ML": {
        "claimed_botanical_group": "Lavandula angustifolia",
        "author_reported_authenticity_status": "supplier_claim",
        "evidence_status": "not_applicable",
        "analysis_role": "oil",
    },
    "NRL": {
        "claimed_botanical_group": "Lavandula angustifolia",
        "author_reported_authenticity_status": "supplier_claim",
        "evidence_status": "not_applicable",
        "analysis_role": "oil",
    },
    "EWL": {
        "claimed_botanical_group": "Lavandula angustifolia",
        "author_reported_authenticity_status": "authenticated_essential_oil",
        "evidence_status": "pending_exact_citation",
        "analysis_role": "oil",
    },
    "ELS": {
        "claimed_botanical_group": "Lavandula latifolia",
        "author_reported_authenticity_status": "authenticated_essential_oil",
        "evidence_status": "pending_exact_citation",
        "analysis_role": "oil",
    },
    "ACFL": {
        "claimed_botanical_group": "Lavandula angustifolia",
        "author_reported_authenticity_status": "authenticated_essential_oil",
        "evidence_status": "pending_exact_citation",
        "analysis_role": "oil",
    },
    "PL": {
        "claimed_botanical_group": "Lavandula x intermedia",
        "author_reported_authenticity_status": "authenticated_essential_oil",
        "evidence_status": "pending_exact_citation",
        "analysis_role": "oil",
    },
}

COMMON_ORDER = ("CL", "ESL", "ELS", "ELF", "EWL", "ACFL", "DL", "ML", "MSL", "NRL", "PL")
EXPECTED_ORDER = {1: COMMON_ORDER, 2: COMMON_ORDER, 3: COMMON_ORDER}

_TITLE_TOKEN = {name: name.replace(" ", "_").replace("Acetate", "acetate") for name in SPECIMEN_METADATA}
_FILENAME_TOKEN = {name: name.replace(" ", "_") for name in SPECIMEN_METADATA}
_PRIVATE_KEY_FRAGMENTS = (
    "supplier",
    "vendor",
    "invoice",
    "purchase_order",
    "catalog_number",
    "customer_number",
    "private_source",
    "original_filename",
    "original_title",
    "correction_id",
)
_PRIVATE_VALUE_PATTERNS = (
    re.compile(r"(?:^|[\s\"'])(?:/[A-Za-z0-9_.-]+){2,}"),
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"CORR-\d+", re.IGNORECASE),
    re.compile(r"EO_Lavender_(?:Block\d+_YF\.zip|001_YF_\d+\.spa)", re.IGNORECASE),
)


class CorpusError(ValueError):
    """The corpus does not satisfy the frozen Phase-1 contract."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _array_sha256(values: Any) -> str:
    array = np.ascontiguousarray(np.asarray(values, dtype="<f8"))
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha256_bytes(payload)


def _require_private_worktree_path(path: Path) -> Path:
    """Refuse private artifacts in a trackable worktree location."""
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return resolved
    try:
        resolved.relative_to(PRIVATE_WORKTREE_ROOT)
    except ValueError as exc:
        raise CorpusError(
            f"private artifact {resolved} must be outside the repository or under {PRIVATE_WORKTREE_ROOT}"
        ) from exc
    return resolved


def _parse_unique_timestamp(value: Any, *, source_name: str) -> datetime:
    if not isinstance(value, str):
        raise CorpusError(f"{source_name}: acquisition timestamp must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CorpusError(f"{source_name}: acquisition timestamp is not parseable ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CorpusError(f"{source_name}: acquisition timestamp must be timezone-aware")
    return parsed


def _sort_inspected_by_timestamp(
    inspected: Sequence[tuple[str, Mapping[str, Any]]], *, block: int
) -> list[tuple[str, Mapping[str, Any]]]:
    timestamped = [
        (
            _parse_unique_timestamp(inspection.get("acquired_at"), source_name=member_name),
            member_name,
            inspection,
        )
        for member_name, inspection in inspected
    ]
    timestamps = [item[0] for item in timestamped]
    if len(timestamps) != len(set(timestamps)):
        raise CorpusError(f"block {block}: acquisition timestamps must be unique")
    timestamped.sort(key=lambda item: item[0])
    return [(member_name, inspection) for _timestamp, member_name, inspection in timestamped]


def _validate_private_inventory(inventory: Mapping[str, Any]) -> None:
    if inventory.get("schema_version") != PRIVATE_SCHEMA or inventory.get("dataset_id") != DATASET_ID:
        raise CorpusError("private inventory schema or dataset identity is not recognized")
    rows = inventory.get("files")
    if not isinstance(rows, list) or len(rows) != 33:
        raise CorpusError("private inventory must contain exactly 33 oil-spectrum rows")
    expected_sequence = [
        (block, order, specimen) for block in (1, 2, 3) for order, specimen in enumerate(EXPECTED_ORDER[block], start=1)
    ]
    for row, (block, order, specimen) in zip(rows, expected_sequence, strict=True):
        if not isinstance(row, Mapping):
            raise CorpusError("private inventory file rows must be objects")
        if set(row) != _PRIVATE_FILE_FIELDS:
            raise CorpusError("private inventory file row has an unknown or incomplete schema")
        if (row.get("block"), row.get("acquisition_order"), row.get("specimen_id")) != (
            block,
            order,
            specimen,
        ):
            raise CorpusError("private inventory identity/order projection changed after generation")
        if row.get("label_status") != "acquired_label_verified":
            raise CorpusError("private inventory label status changed after generation")


def canonical_filename(specimen_id: str, block: int) -> str:
    return f"{_FILENAME_TOKEN[specimen_id]}__B{block}.spa"


def canonical_title(specimen_id: str, block: int) -> str:
    return f"{block}{_TITLE_TOKEN[specimen_id]}"


def _instrument_record() -> dict[str, Any]:
    return {
        "model": "Thermo Nicolet Avatar 370",
        "software": "OMNIC 9.8.372",
        "detector": "DTGS KBr",
        "accessory": "Smart Orbit diamond ATR",
        "correction": "None",
        "operator_code": "YF",
        "sample_volume_uL": 2.0,
        "sample_scans": 16,
        "background_scans": 16,
        "resolution_cm-1": 4.0,
        "range_cm-1": [4000.0, 400.0],
        "ordinate": "absorbance",
        "background_policy": "individual background for every spectrum",
    }


def inspect_spa(path: Path) -> dict[str, Any]:
    result = ingest(path)
    if (result.format_id, result.variant, result.parser_id) != (
        "omnic",
        "spa-single-spectrum",
        "spectrasherpa.omnic",
    ):
        raise CorpusError(f"{path.name}: source did not select the qualified native OMNIC SPA parser")
    if len(result.assets) != 1 or result.assets[0].asset_id != "spectrum":
        raise CorpusError(f"{path.name}: source must contain exactly the spectrum asset")
    asset = result.assets[0]
    dataset = asset.dataset
    if tuple(dataset.shape) != (1, 1868):
        raise CorpusError(f"{path.name}: expected shape (1, 1868), got {tuple(dataset.shape)}")
    feature_axis = dataset.feature_axis
    if feature_axis is None or feature_axis.values is None:
        raise CorpusError(f"{path.name}: source has no feature-axis values")
    metadata = dict(result.raw_metadata)
    header = dict(metadata.get("header", {}))
    expected_header = {
        "point_count": 1868,
        "x_code": 1,
        "y_code": 17,
        "scan_count": 16,
        "background_scan_count": 16,
    }
    for key, expected in expected_header.items():
        if header.get(key) != expected:
            raise CorpusError(f"{path.name}: header {key}={header.get(key)!r}, expected {expected!r}")
    x = np.asarray(dataset.X, dtype=np.float64)
    axis = np.asarray(feature_axis.values, dtype=np.float64)
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(axis)):
        raise CorpusError(f"{path.name}: non-finite scientific values are not qualified")
    if not np.all(np.diff(axis) < 0):
        raise CorpusError(f"{path.name}: expected a strictly descending feature axis")
    source = result.source_members[0]
    qualified_parser_metadata = {
        "acquired_at": metadata.get("acquired_at"),
        "header": header,
        "shape": [1, 1868],
        "axis_units": str(feature_axis.units),
        "value_units": str(dataset.units),
        "data_quantity": dataset.domain.data_quantity if dataset.domain is not None else None,
    }
    return {
        "source_sha256": source.sha256,
        "size_bytes": source.size_bytes,
        "embedded_title": metadata.get("container_name"),
        "acquired_at": metadata.get("acquired_at"),
        "format_id": result.format_id,
        "variant": result.variant,
        "parser_id": result.parser_id,
        "parser_version": result.parser_version,
        "asset_id": asset.asset_id,
        "shape": [1, 1868],
        "axis_units": str(feature_axis.units),
        "value_units": str(dataset.units),
        "values_sha256": _array_sha256(x),
        "axis_sha256": _array_sha256(axis),
        "qualified_parser_metadata_sha256": _json_sha256(qualified_parser_metadata),
        "qualified_parser_metadata": qualified_parser_metadata,
    }


def _safe_archive_members(archive: zipfile.ZipFile, *, block: int) -> list[zipfile.ZipInfo]:
    members = [item for item in archive.infolist() if not item.is_dir()]
    if len(members) != 13:
        raise CorpusError(f"block {block}: expected exactly 13 files, found {len(members)}")
    names = [item.filename for item in members]
    if len(names) != len(set(names)):
        raise CorpusError(f"block {block}: archive member names are not unique")
    for item in members:
        path = Path(item.filename)
        if path.name != item.filename or path.suffix.lower() != ".spa":
            raise CorpusError(f"block {block}: unsafe or non-SPA archive member {item.filename!r}")
        if item.file_size <= 0 or item.file_size > 200 * 1024 * 1024:
            raise CorpusError(f"block {block}: invalid member size for {item.filename!r}")
    return members


def build_private_inventory(
    archives: Mapping[int, Path],
    *,
    manual_metadata_review: str = "pending",
    inspector: Callable[[Path], dict[str, Any]] = inspect_spa,
) -> dict[str, Any]:
    if set(archives) != {1, 2, 3}:
        raise CorpusError("exactly blocks 1, 2, and 3 are required")
    if manual_metadata_review not in {"pending", "passed"}:
        raise CorpusError("manual metadata review must be pending or passed")
    archive_rows: list[dict[str, Any]] = []
    file_rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="avatar-omnic-inventory-") as tmp:
        tmp_root = Path(tmp)
        for block in (1, 2, 3):
            archive_path = archives[block]
            archive_bytes = archive_path.read_bytes()
            archive_sha = _sha256_bytes(archive_bytes)
            if archive_sha != ARCHIVE_SHA256[block]:
                raise CorpusError(
                    f"block {block}: archive SHA-256 {archive_sha} does not match {ARCHIVE_SHA256[block]}"
                )
            with zipfile.ZipFile(archive_path) as handle:
                members = _safe_archive_members(handle, block=block)
                inspected: list[tuple[str, dict[str, Any]]] = []
                block_dir = tmp_root / f"block-{block}"
                block_dir.mkdir()
                for member in members:
                    path = block_dir / member.filename
                    path.write_bytes(handle.read(member))
                    inspected.append((member.filename, inspector(path)))
            inspected = list(_sort_inspected_by_timestamp(inspected, block=block))
            observed_titles = [str(item[1]["embedded_title"]) for item in inspected]
            if len(observed_titles) != len(set(observed_titles)):
                raise CorpusError(f"block {block}: embedded acquisition titles must be unique")
            title_to_specimen = {canonical_title(specimen, block): specimen for specimen in EXPECTED_ORDER[block]}
            included = {
                title_to_specimen[str(inspection["embedded_title"])]: (member_name, inspection)
                for member_name, inspection in inspected
                if str(inspection["embedded_title"]) in title_to_specimen
            }
            if set(included) != set(EXPECTED_ORDER[block]) or len(included) != 11:
                raise CorpusError(f"block {block}: source titles do not prove the exact 11 oil identities")
            if len(inspected) - len(included) != 2:
                raise CorpusError(f"block {block}: expected exactly two anonymous excluded members")
            ordered = [included[specimen] for specimen in EXPECTED_ORDER[block]]
            ordered_times = [
                _parse_unique_timestamp(inspection["acquired_at"], source_name=member_name)
                for member_name, inspection in ordered
            ]
            if any(left >= right for left, right in zip(ordered_times, ordered_times[1:])):
                raise CorpusError(f"block {block}: oil acquisition order does not match the frozen sequence")
            for order, (specimen_id, (member_name, inspection)) in enumerate(
                zip(EXPECTED_ORDER[block], ordered, strict=True), start=1
            ):
                file_rows.append(
                    {
                        "block": block,
                        "acquisition_order": order,
                        "specimen_id": specimen_id,
                        "label_status": "acquired_label_verified",
                        "archive_member": member_name,
                        **inspection,
                    }
                )
            archive_rows.append(
                {
                    "block": block,
                    "archive_name": archive_path.name,
                    "sha256": archive_sha,
                    "size_bytes": len(archive_bytes),
                    "member_count": 13,
                    "excluded_member_count": 2,
                }
            )
    if len({row["source_sha256"] for row in file_rows}) != 33:
        raise CorpusError("all 33 included oil source hashes must be unique")
    if len({row["axis_sha256"] for row in file_rows}) != 1:
        raise CorpusError("all 33 included oil sources must share the exact feature axis")
    return {
        "schema_version": PRIVATE_SCHEMA,
        "dataset_id": DATASET_ID,
        "privacy": {
            "classification": "private_acquisition_authority",
            "supplier_crosswalk_present": False,
            "manual_metadata_review": manual_metadata_review,
            "redistribution_intent": "author_approved_open_curation",
        },
        "archives": archive_rows,
        "files": file_rows,
    }


def stage_curated_files(
    inventory: Mapping[str, Any],
    archives: Mapping[int, Path],
    output: Path,
    *,
    inspector: Callable[[Path], dict[str, Any]] = inspect_spa,
) -> list[str]:
    sources = _archive_source_bytes(inventory, archives, inspector=inspector)
    privacy = inventory.get("privacy")
    if not isinstance(privacy, Mapping) or privacy.get("manual_metadata_review") != "passed":
        raise CorpusError("curated staging requires a passed private metadata/privacy review")
    if privacy.get("redistribution_intent") != "author_approved_open_curation":
        raise CorpusError("curated staging requires explicit author-approved open-curation intent")
    output = _require_private_worktree_path(output)
    output.mkdir(parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    written: list[str] = []
    for row in inventory["files"]:
        block = int(row["block"])
        specimen = str(row["specimen_id"])
        data = sources[(block, specimen)]
        name = canonical_filename(specimen, block)
        (output / name).write_bytes(data)
        os.chmod(output / name, 0o600)
        written.append(name)
    if len(written) != 33:
        raise CorpusError(f"expected to stage 33 byte-identical oil sources, staged {len(written)}")
    return sorted(written)


def _public_privacy_failures(value: Any, *, path: str = "$") -> list[str]:
    failures: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in _PRIVATE_KEY_FRAGMENTS):
                failures.append(f"private key at {path}.{key}")
            failures.extend(_public_privacy_failures(item, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            failures.extend(_public_privacy_failures(item, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        for pattern in _PRIVATE_VALUE_PATTERNS:
            if pattern.search(value):
                failures.append(f"private-looking value at {path}")
                break
    return failures


def _archive_source_bytes(
    inventory: Mapping[str, Any],
    archives: Mapping[int, Path],
    *,
    inspector: Callable[[Path], dict[str, Any]] = inspect_spa,
) -> dict[tuple[int, str], bytes]:
    _validate_private_inventory(inventory)
    if set(archives) != {1, 2, 3}:
        raise CorpusError("exactly blocks 1, 2, and 3 are required to verify curated sources")
    archive_rows = inventory.get("archives")
    if not isinstance(archive_rows, list) or len(archive_rows) != 3:
        raise CorpusError("private inventory must contain exactly three archive rows")
    archive_by_block = {row.get("block"): row for row in archive_rows if isinstance(row, Mapping)}
    if set(archive_by_block) != {1, 2, 3}:
        raise CorpusError("private inventory archive identities are incomplete")
    loaded: dict[tuple[int, str], bytes] = {}
    with tempfile.TemporaryDirectory(prefix="avatar-omnic-readmit-") as tmp:
        tmp_root = Path(tmp)
        for block in (1, 2, 3):
            archive_path = archives[block]
            archive_bytes = archive_path.read_bytes()
            archive_sha = _sha256_bytes(archive_bytes)
            if archive_sha != ARCHIVE_SHA256[block]:
                raise CorpusError(f"block {block}: frozen archive SHA-256 does not match")
            record = archive_by_block[block]
            expected_archive_record = {
                "block": block,
                "archive_name": archive_path.name,
                "sha256": archive_sha,
                "size_bytes": len(archive_bytes),
                "member_count": 13,
                "excluded_member_count": 2,
            }
            if dict(record) != expected_archive_record:
                raise CorpusError(f"block {block}: private archive record changed after generation")
            block_rows = [row for row in inventory["files"] if row["block"] == block]
            with zipfile.ZipFile(archive_path) as handle:
                members = _safe_archive_members(handle, block=block)
                member_names = {member.filename for member in members}
                included_names = {row["archive_member"] for row in block_rows}
                if not included_names < member_names or len(member_names - included_names) != 2:
                    raise CorpusError(f"block {block}: inventory/archive member linkage changed")
                block_dir = tmp_root / f"block-{block}"
                block_dir.mkdir()
                observed_for_order: list[tuple[str, Mapping[str, Any]]] = []
                for row in block_rows:
                    specimen = str(row["specimen_id"])
                    data = handle.read(str(row["archive_member"]))
                    if _sha256_bytes(data) != row["source_sha256"] or len(data) != row["size_bytes"]:
                        raise CorpusError(f"{specimen} B{block}: private source bytes do not match the inventory")
                    source_path = block_dir / str(row["archive_member"])
                    source_path.write_bytes(data)
                    observed = inspector(source_path)
                    for field in (
                        "source_sha256",
                        "size_bytes",
                        "embedded_title",
                        "acquired_at",
                        "format_id",
                        "variant",
                        "parser_id",
                        "parser_version",
                        "asset_id",
                        "shape",
                        "axis_units",
                        "value_units",
                        "values_sha256",
                        "axis_sha256",
                        "qualified_parser_metadata_sha256",
                        "qualified_parser_metadata",
                    ):
                        if observed.get(field) != row.get(field):
                            raise CorpusError(f"{specimen} B{block}: private {field} changed after inventory")
                    if _json_sha256(row["qualified_parser_metadata"]) != row["qualified_parser_metadata_sha256"]:
                        raise CorpusError(f"{specimen} B{block}: private qualified metadata digest is contradictory")
                    if observed.get("embedded_title") != canonical_title(specimen, block):
                        raise CorpusError(f"{specimen} B{block}: source title does not prove the assigned identity")
                    observed_for_order.append((str(row["archive_member"]), observed))
                    loaded[(block, specimen)] = data
                ordered_observed = _sort_inspected_by_timestamp(observed_for_order, block=block)
                if [name for name, _inspection in ordered_observed] != [
                    str(row["archive_member"]) for row in block_rows
                ]:
                    raise CorpusError(f"block {block}: source timestamp order does not prove assigned identities")
    return loaded


def build_public_manifest(
    inventory: Mapping[str, Any],
    archives: Mapping[int, Path],
    curated_dir: Path,
    *,
    inspector: Callable[[Path], dict[str, Any]] = inspect_spa,
) -> dict[str, Any]:
    private_sources = _archive_source_bytes(inventory, archives, inspector=inspector)
    privacy = inventory.get("privacy")
    if not isinstance(privacy, Mapping) or privacy.get("manual_metadata_review") != "passed":
        raise CorpusError("public candidate manifest requires a passed private metadata/privacy review")
    if privacy.get("redistribution_intent") != "author_approved_open_curation":
        raise CorpusError("public candidate manifest requires explicit author-approved open-curation intent")
    curated_dir = _require_private_worktree_path(curated_dir)
    private_rows = {(int(row["block"]), str(row["specimen_id"])): row for row in inventory.get("files", [])}
    expected_keys = {(block, specimen) for block in (1, 2, 3) for specimen in SPECIMEN_METADATA}
    if set(private_rows) != expected_keys:
        raise CorpusError("private inventory does not contain the exact 33 oil identities")
    actual_files = sorted(path.name for path in curated_dir.iterdir() if path.is_file())
    expected_files = sorted(canonical_filename(specimen, block) for block, specimen in expected_keys)
    if actual_files != expected_files:
        raise CorpusError(
            f"curated file set mismatch: missing={sorted(set(expected_files) - set(actual_files))} "
            f"extra={sorted(set(actual_files) - set(expected_files))}"
        )

    public_rows: list[dict[str, Any]] = []
    for block in (1, 2, 3):
        for order, specimen in enumerate(EXPECTED_ORDER[block], start=1):
            private = private_rows[(block, specimen)]
            filename = canonical_filename(specimen, block)
            inspection = inspector(curated_dir / filename)
            private_bytes = private_sources[(block, specimen)]
            curated_bytes = (curated_dir / filename).read_bytes()
            if _sha256_bytes(private_bytes) != private["source_sha256"]:
                raise CorpusError(f"{filename}: loaded private bytes do not match the inventory")
            if _sha256_bytes(curated_bytes) != inspection["source_sha256"]:
                raise CorpusError(f"{filename}: inspected curated hash does not match its bytes")
            expected_title = canonical_title(specimen, block)
            if inspection["embedded_title"] != expected_title:
                raise CorpusError(f"{filename}: curated embedded title must be {expected_title!r}")
            for digest_name in ("values_sha256", "axis_sha256", "qualified_parser_metadata_sha256"):
                if inspection[digest_name] != private[digest_name]:
                    raise CorpusError(f"{filename}: {digest_name} changed during curation")
            if inspection["source_sha256"] != private["source_sha256"] or curated_bytes != private_bytes:
                raise CorpusError(f"{filename}: curated source must be byte-identical to its approved source")
            public_rows.append(
                {
                    "distribution_filename": filename,
                    "curated_sha256": inspection["source_sha256"],
                    "size_bytes": inspection["size_bytes"],
                    "sample_id": f"{_FILENAME_TOKEN[specimen]}__B{block}",
                    "specimen_id": specimen,
                    "block": block,
                    "acquisition_order": order,
                    "canonical_omnic_title": expected_title,
                    "label_status": "acquired_label_verified",
                    "curation_equivalence": "byte_identical",
                    **SPECIMEN_METADATA[specimen],
                    "format_id": inspection["format_id"],
                    "variant": inspection["variant"],
                    "parser_id": inspection["parser_id"],
                    "parser_version": inspection["parser_version"],
                    "asset_id": inspection["asset_id"],
                    "shape": inspection["shape"],
                    "axis_units": inspection["axis_units"],
                    "feature_axis_order": "strictly_descending",
                    "value_units": inspection["value_units"],
                    "acquired_at": inspection["acquired_at"],
                    "values_sha256": inspection["values_sha256"],
                    "axis_sha256": inspection["axis_sha256"],
                    "qualified_parser_metadata_sha256": inspection["qualified_parser_metadata_sha256"],
                }
            )

    manifest = {
        "schema_version": PUBLIC_SCHEMA,
        "dataset_id": DATASET_ID,
        "dataset_version": 1,
        "status": PHASE1_STATUS,
        "dataset_license": PHASE1_LICENSE,
        "privacy_statement": PRIVACY_STATEMENT,
        "claim_boundary": CLAIM_BOUNDARY,
        "instrument": _instrument_record(),
        "qualified_parser_metadata_fields": [
            "acquired_at",
            "header",
            "shape",
            "axis_units",
            "value_units",
            "data_quantity",
        ],
        "files": public_rows,
    }
    failures = validate_public_manifest(manifest, curated_dir=curated_dir, inspector=inspector)
    if failures:
        raise CorpusError("public manifest validation failed: " + "; ".join(failures))
    return manifest


def validate_public_manifest(  # noqa: C901 - one closed schema gate is easier to audit as a unit
    manifest: Mapping[str, Any],
    *,
    curated_dir: Path,
    inspector: Callable[[Path], dict[str, Any]] = inspect_spa,
) -> list[str]:
    failures = _public_privacy_failures(manifest)
    if set(manifest) != _PUBLIC_ROOT_FIELDS:
        failures.append("public manifest root has an unknown or incomplete schema")
    if manifest.get("schema_version") != PUBLIC_SCHEMA:
        failures.append("unknown public manifest schema")
    if manifest.get("dataset_id") != DATASET_ID:
        failures.append("wrong dataset identity")
    if manifest.get("dataset_version") != 1:
        failures.append("wrong dataset version")
    if manifest.get("status") != PHASE1_STATUS:
        failures.append("Phase-1 manifest must remain non-distribution-qualified")
    if manifest.get("dataset_license") != PHASE1_LICENSE:
        failures.append("Phase-1 manifest license must remain pending")
    if manifest.get("privacy_statement") != PRIVACY_STATEMENT:
        failures.append("public privacy statement is not canonical")
    if manifest.get("claim_boundary") != CLAIM_BOUNDARY:
        failures.append("public claim boundary is not canonical")
    if manifest.get("instrument") != _instrument_record():
        failures.append("instrument/acquisition projection is not canonical")
    if manifest.get("qualified_parser_metadata_fields") != [
        "acquired_at",
        "header",
        "shape",
        "axis_units",
        "value_units",
        "data_quantity",
    ]:
        failures.append("qualified-parser metadata projection is not explicitly closed")
    rows = manifest.get("files")
    if not isinstance(rows, list) or len(rows) != 33:
        return [*failures, "public manifest must contain exactly 33 oil file rows"]

    expected_sequence = [
        (block, order, specimen) for block in (1, 2, 3) for order, specimen in enumerate(EXPECTED_ORDER[block], start=1)
    ]
    distribution_names: list[Any] = []
    curated_hashes: list[Any] = []
    for index, (row, (block, order, specimen)) in enumerate(zip(rows, expected_sequence, strict=True)):
        if not isinstance(row, Mapping):
            failures.append(f"public manifest file row {index} must be an object")
            continue
        if set(row) != _PUBLIC_FILE_FIELDS:
            failures.append(f"public file row {index} has an unknown or incomplete schema")
        sample_id = f"{_FILENAME_TOKEN[specimen]}__B{block}"
        exact_fields: dict[str, Any] = {
            "distribution_filename": canonical_filename(specimen, block),
            "sample_id": sample_id,
            "specimen_id": specimen,
            "block": block,
            "acquisition_order": order,
            "canonical_omnic_title": canonical_title(specimen, block),
            "label_status": "acquired_label_verified",
            "curation_equivalence": "byte_identical",
            **SPECIMEN_METADATA[specimen],
            "format_id": "omnic",
            "variant": "spa-single-spectrum",
            "parser_id": "spectrasherpa.omnic",
            "parser_version": "1",
            "asset_id": "spectrum",
            "shape": [1, 1868],
            "axis_units": "cm-1",
            "feature_axis_order": "strictly_descending",
            "value_units": "absorbance",
        }
        for field, expected in exact_fields.items():
            if row.get(field) != expected:
                failures.append(f"{sample_id}: noncanonical {field}")
        if not isinstance(row.get("size_bytes"), int) or row["size_bytes"] <= 0:
            failures.append(f"{sample_id}: invalid size_bytes")
        try:
            _parse_unique_timestamp(row.get("acquired_at"), source_name=sample_id)
        except CorpusError:
            failures.append(f"{sample_id}: invalid acquired_at")
        for field in (
            "curated_sha256",
            "values_sha256",
            "axis_sha256",
            "qualified_parser_metadata_sha256",
        ):
            if not _is_sha256(row.get(field)):
                failures.append(f"{sample_id}: invalid {field}")
        distribution_names.append(row.get("distribution_filename"))
        curated_hashes.append(row.get("curated_sha256"))
        path = curated_dir / canonical_filename(specimen, block)
        if not path.is_file():
            failures.append(f"missing curated file {path.name}")
        elif _sha256_bytes(path.read_bytes()) != row.get("curated_sha256"):
            failures.append(f"curated file digest mismatch {path.name}")
        else:
            try:
                observed = inspector(path)
            except Exception as exc:  # validation reports failure rather than hiding the row
                failures.append(f"curated file inspection failed {path.name}: {type(exc).__name__}")
            else:
                for field in (
                    "source_sha256",
                    "size_bytes",
                    "format_id",
                    "variant",
                    "parser_id",
                    "parser_version",
                    "asset_id",
                    "shape",
                    "axis_units",
                    "value_units",
                    "acquired_at",
                    "values_sha256",
                    "axis_sha256",
                    "qualified_parser_metadata_sha256",
                ):
                    manifest_field = "curated_sha256" if field == "source_sha256" else field
                    if row.get(manifest_field) != observed.get(field):
                        failures.append(f"{sample_id}: {manifest_field} does not match curated scientific bytes")

    if len(distribution_names) != len(set(distribution_names)):
        failures.append("distribution filenames must be unique")
    if len(curated_hashes) != len(set(curated_hashes)):
        failures.append("curated source hashes must be unique")
    if sum(row.get("curation_equivalence") == "byte_identical" for row in rows if isinstance(row, Mapping)) != 33:
        failures.append("exactly 33 rows must be byte-identical curated oil copies")
    if curated_dir.is_dir():
        actual = {path.name for path in curated_dir.iterdir() if path.is_file()}
        expected = {canonical_filename(specimen, block) for block, _order, specimen in expected_sequence}
        if actual != expected:
            failures.append("curated directory file set is not the exact 33-file manifest set")
    return failures


def _native_arrays(path: Path) -> tuple[np.ndarray, np.ndarray, SherpaDataset]:
    result = ingest(path)
    if (result.format_id, result.variant, result.parser_id) != (
        "omnic",
        "spa-single-spectrum",
        "spectrasherpa.omnic",
    ):
        raise CorpusError(f"{path.name}: source did not select the qualified native OMNIC SPA parser")
    if len(result.assets) != 1 or result.assets[0].asset_id != "spectrum":
        raise CorpusError(f"{path.name}: source must contain exactly the spectrum asset")
    dataset = result.assets[0].dataset
    if type(dataset) is not SherpaDataset:
        raise CorpusError(f"{path.name}: native ingestion did not return the canonical SherpaDataset type")
    reject_spectrochempy_transport(dataset, boundary=f"Avatar Phase 2 {path.name}")
    if dataset.feature_axis is None or dataset.feature_axis.values is None:
        raise CorpusError(f"{path.name}: source has no feature-axis values")
    values = np.asarray(dataset.X, dtype=np.float64)
    axis = np.asarray(dataset.feature_axis.values, dtype=np.float64)
    if values.shape != (1, 1868) or axis.shape != (1868,):
        raise CorpusError(f"{path.name}: native scientific arrays have an unexpected shape")
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(axis)):
        raise CorpusError(f"{path.name}: native scientific arrays contain non-finite values")
    if not np.all(np.diff(axis) < 0):
        raise CorpusError(f"{path.name}: native feature axis is not strictly descending")
    return values[0].copy(), axis.copy(), dataset


def _phase2_report(
    manifest_path: Path,
    curated_dir: Path,
    external_report_path: Path,
) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    failures = validate_public_manifest(manifest, curated_dir=curated_dir)
    if failures:
        raise CorpusError("Phase-1 manifest re-admission failed: " + "; ".join(failures))

    external_bytes = external_report_path.read_bytes()
    external = json.loads(external_bytes)
    if set(external) != {
        "schema_version",
        "converter",
        "source_manifest_sha256",
        "execution",
        "files",
    }:
        raise CorpusError("external converter report has an unknown or incomplete root schema")
    if external.get("schema_version") != "spectrasherpa-avatar-external-omnic-comparison/1":
        raise CorpusError("external converter report has an unknown schema version")
    if external.get("converter") != EXTERNAL_OMNIC_COMPARATOR:
        raise CorpusError("external converter identity is not the exact qualified source authority")
    if external.get("source_manifest_sha256") != _sha256_bytes(manifest_bytes):
        raise CorpusError("external converter report is not bound to the exact source manifest")
    if external.get("execution") != {
        "network_access": "python_socket_dns_blocked",
        "spectrasherpa_imported": False,
        "comparison_scope": "all_33_complete_axis_and_ordinate_arrays",
    }:
        raise CorpusError("external converter execution boundary is not the qualified isolated process")
    external_rows = external.get("files")
    if not isinstance(external_rows, list) or len(external_rows) != 33:
        raise CorpusError("external converter report must contain exactly 33 rows")
    external_by_sample: dict[str, Mapping[str, Any]] = {}
    external_fields = {
        "sample_id",
        "spa_sha256",
        "shape",
        "point_count",
        "axis_order",
        "axis_units",
        "value_units",
        "external_values_sha256",
        "external_axis_sha256",
    }
    for row in external_rows:
        if not isinstance(row, Mapping) or set(row) != external_fields:
            raise CorpusError("external converter file row has an unknown or incomplete schema")
        sample_id = row.get("sample_id")
        if not isinstance(sample_id, str) or sample_id in external_by_sample:
            raise CorpusError("external converter sample identities must be unique strings")
        external_by_sample[sample_id] = row

    structural_rows: list[dict[str, Any]] = []
    expected_sample_ids = {str(row["sample_id"]) for row in manifest["files"]}
    if set(external_by_sample) != expected_sample_ids:
        raise CorpusError("external converter report does not contain the exact 33 sample identities")
    for row in manifest["files"]:
        filename = str(row["distribution_filename"])
        sample_id = str(row["sample_id"])
        path = curated_dir / filename
        first = inspect_spa(path)
        second = inspect_spa(path)
        if first != second:
            raise CorpusError(f"{filename}: repeat native ingestion changed its scientific projection")
        values, _axis, _dataset = _native_arrays(path)
        if first["source_sha256"] != row["curated_sha256"]:
            raise CorpusError(f"{filename}: native source-member identity changed")
        for field in (
            "format_id",
            "variant",
            "parser_id",
            "parser_version",
            "asset_id",
            "shape",
            "axis_units",
            "value_units",
            "values_sha256",
            "axis_sha256",
            "qualified_parser_metadata_sha256",
        ):
            if first[field] != row[field]:
                raise CorpusError(f"{filename}: native {field} disagrees with the frozen manifest")
        peak = float(np.max(values))
        external_row = external_by_sample[sample_id]
        expected_external_fields: dict[str, Any] = {
            "spa_sha256": row["curated_sha256"],
            "shape": [1, 1868],
            "point_count": 1868,
            "axis_order": "strictly_descending",
            "axis_units": "cm^-1",
            "value_units": "absorbance",
            "external_values_sha256": row["values_sha256"],
            "external_axis_sha256": row["axis_sha256"],
        }
        for field, expected in expected_external_fields.items():
            if external_row.get(field) != expected:
                raise CorpusError(f"{sample_id}: external converter {field} disagrees with native ingestion")
        structural_rows.append(
            {
                "sample_id": sample_id,
                "curated_sha256": row["curated_sha256"],
                "structural_ingestion_passed": True,
                "repeat_ingestion_identical": True,
                "native_dataset_type": "SherpaDataset",
                "spectrochempy_transport_absent": True,
                "parser_id": first["parser_id"],
                "parser_version": first["parser_version"],
                "variant": first["variant"],
                "asset_id": first["asset_id"],
                "shape": first["shape"],
                "axis_units": first["axis_units"],
                "axis_order": "strictly_descending",
                "value_units": first["value_units"],
                "values_sha256": first["values_sha256"],
                "axis_sha256": first["axis_sha256"],
                "peak_absorbance": peak,
                "external_converter_full_array_equal": True,
            }
        )

    return {
        "schema_version": PHASE2_SCHEMA,
        "dataset_id": DATASET_ID,
        "dataset_version": 1,
        "source_manifest_sha256": _sha256_bytes(manifest_bytes),
        "status": "native_omnic_parser_qualified_for_exact_corpus",
        "structural_ingestion_passed": True,
        "structural_file_count": 33,
        "external_converter_parity_verified": True,
        "external_converter_file_count": 33,
        "external_converter_report_sha256": _sha256_bytes(external_bytes),
        "external_converter": EXTERNAL_OMNIC_COMPARATOR,
        "comparison_policy": "exact float64 full-array hashes in source order",
        "instrument_export_parity_verified": False,
        "instrument_export_status": "not_performed_instrument_unavailable",
        "files": structural_rows,
        "claim_boundary": (
            "Qualification is limited to these exact 33 Avatar SPA sources and exact agreement "
            "with the pinned external reverse-engineering reference reader. The external reader "
            "is not a Thermo vendor oracle, and this is not general OMNIC-variant coverage."
        ),
    }


def validate_phase2_evidence_links(
    report: Mapping[str, Any],
    manifest_bytes: bytes,
    external_bytes: bytes,
) -> list[str]:
    failures = _public_privacy_failures(report)
    try:
        manifest = json.loads(manifest_bytes)
        external = json.loads(external_bytes)
    except json.JSONDecodeError:
        return [*failures, "Phase-2 linked evidence is not valid JSON"]
    required_report_fields = {
        "schema_version",
        "dataset_id",
        "dataset_version",
        "source_manifest_sha256",
        "status",
        "structural_ingestion_passed",
        "structural_file_count",
        "external_converter_parity_verified",
        "external_converter_file_count",
        "external_converter_report_sha256",
        "external_converter",
        "comparison_policy",
        "instrument_export_parity_verified",
        "instrument_export_status",
        "files",
        "claim_boundary",
    }
    if set(report) != required_report_fields:
        failures.append("Phase-2 report root has an unknown or incomplete schema")
    if report.get("schema_version") != PHASE2_SCHEMA or report.get("dataset_id") != DATASET_ID:
        failures.append("Phase-2 report identity is not recognized")
    if report.get("dataset_version") != 1:
        failures.append("Phase-2 dataset version is not recognized")
    if report.get("source_manifest_sha256") != _sha256_bytes(manifest_bytes):
        failures.append("Phase-2 report is not bound to the exact public manifest")
    if report.get("external_converter_report_sha256") != _sha256_bytes(external_bytes):
        failures.append("Phase-2 report is not bound to the exact external report")
    if report.get("external_converter") != EXTERNAL_OMNIC_COMPARATOR:
        failures.append("Phase-2 report names the wrong external converter authority")
    if report.get("structural_ingestion_passed") is not True or report.get("structural_file_count") != 33:
        failures.append("Phase-2 structural result is not the exact 33-file pass")
    if (
        report.get("external_converter_parity_verified") is not True
        or report.get("external_converter_file_count") != 33
    ):
        failures.append("Phase-2 external result is not the exact 33-file pass")
    if report.get("instrument_export_parity_verified") is not False:
        failures.append("Phase-2 report must not claim an instrument-export comparison")
    if report.get("instrument_export_status") != "not_performed_instrument_unavailable":
        failures.append("Phase-2 instrument-export status is not truthful")
    if external.get("converter") != EXTERNAL_OMNIC_COMPARATOR:
        failures.append("linked external report names the wrong converter authority")
    if external.get("source_manifest_sha256") != _sha256_bytes(manifest_bytes):
        failures.append("linked external report is not bound to the public manifest")
    if external.get("execution") != {
        "network_access": "python_socket_dns_blocked",
        "spectrasherpa_imported": False,
        "comparison_scope": "all_33_complete_axis_and_ordinate_arrays",
    }:
        failures.append("linked external report overstates or changes its execution isolation")

    manifest_rows = manifest.get("files")
    external_rows = external.get("files")
    report_rows = report.get("files")
    if not all(isinstance(rows, list) and len(rows) == 33 for rows in (manifest_rows, external_rows, report_rows)):
        return [*failures, "Phase-2 linked evidence must contain exactly 33 rows in every layer"]
    manifest_by_id = {row.get("sample_id"): row for row in manifest_rows if isinstance(row, Mapping)}
    external_by_id = {row.get("sample_id"): row for row in external_rows if isinstance(row, Mapping)}
    report_by_id = {row.get("sample_id"): row for row in report_rows if isinstance(row, Mapping)}
    if not (
        len(manifest_by_id) == 33
        and set(external_by_id) == set(manifest_by_id)
        and set(report_by_id) == set(manifest_by_id)
    ):
        return [*failures, "Phase-2 sample identities are missing, duplicated, or substituted"]
    for sample_id, manifest_row in manifest_by_id.items():
        external_row = external_by_id[sample_id]
        report_row = report_by_id[sample_id]
        bindings = (
            (external_row.get("spa_sha256"), manifest_row.get("curated_sha256"), "external source"),
            (
                external_row.get("external_values_sha256"),
                manifest_row.get("values_sha256"),
                "external values",
            ),
            (
                external_row.get("external_axis_sha256"),
                manifest_row.get("axis_sha256"),
                "external axis",
            ),
            (report_row.get("curated_sha256"), manifest_row.get("curated_sha256"), "native source"),
            (report_row.get("values_sha256"), manifest_row.get("values_sha256"), "native values"),
            (report_row.get("axis_sha256"), manifest_row.get("axis_sha256"), "native axis"),
        )
        for observed, expected, field in bindings:
            if observed != expected:
                failures.append(f"{sample_id}: {field} digest is not cross-bound")
        if report_row.get("external_converter_full_array_equal") is not True:
            failures.append(f"{sample_id}: full-array equality is not true")
    return failures


def build_phase2_report(
    manifest_path: Path,
    curated_dir: Path,
    external_report_path: Path,
) -> dict[str, Any]:
    report = _phase2_report(manifest_path, curated_dir, external_report_path)
    rebuilt = _phase2_report(manifest_path, curated_dir, external_report_path)
    if report != rebuilt:
        raise CorpusError("Phase-2 qualification is not deterministic under repeat ingestion")
    failures = validate_phase2_evidence_links(
        report,
        manifest_path.read_bytes(),
        external_report_path.read_bytes(),
    )
    if failures:
        raise CorpusError("Phase-2 evidence-link validation failed: " + "; ".join(failures))
    return report


def validate_phase2_report(
    report: Mapping[str, Any],
    manifest_path: Path,
    curated_dir: Path,
    external_report_path: Path,
) -> list[str]:
    try:
        expected = build_phase2_report(manifest_path, curated_dir, external_report_path)
    except (CorpusError, OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"Phase-2 source re-admission failed: {type(exc).__name__}: {exc}"]
    if dict(report) != expected:
        return ["Phase-2 report does not exactly match the re-admitted native and external results"]
    return []


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _archive_arguments(values: Sequence[str]) -> dict[int, Path]:
    parsed: dict[int, Path] = {}
    for value in values:
        block_text, separator, path_text = value.partition("=")
        if not separator:
            raise CorpusError("archive arguments must use BLOCK=PATH")
        parsed[int(block_text)] = Path(path_text).resolve()
    return parsed


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _write_private_json(path: Path, value: Any) -> None:
    destination = _require_private_worktree_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        restrict_file_descriptor(descriptor)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _read_private_json(path: Path) -> Any:
    source = _require_private_worktree_path(path)
    return json.loads(source.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser("inventory-private")
    inventory_parser.add_argument("--archive", action="append", required=True, help="BLOCK=PATH; repeat three times")
    inventory_parser.add_argument("--manual-metadata-review", choices=("pending", "passed"), default="pending")
    inventory_parser.add_argument("--output", type=Path, required=True)
    stage_parser = subparsers.add_parser("stage-curated")
    stage_parser.add_argument("--inventory", type=Path, required=True)
    stage_parser.add_argument("--archive", action="append", required=True, help="BLOCK=PATH; repeat three times")
    stage_parser.add_argument("--output", type=Path, required=True)
    manifest_parser = subparsers.add_parser("build-public")
    manifest_parser.add_argument("--inventory", type=Path, required=True)
    manifest_parser.add_argument("--archive", action="append", required=True, help="BLOCK=PATH; repeat three times")
    manifest_parser.add_argument("--curated-dir", type=Path, required=True)
    manifest_parser.add_argument("--output", type=Path, required=True)
    check_parser = subparsers.add_parser("check-public")
    check_parser.add_argument("--manifest", type=Path, required=True)
    check_parser.add_argument("--curated-dir", type=Path, required=True)
    phase2_parser = subparsers.add_parser("build-phase2")
    phase2_parser.add_argument("--manifest", type=Path, required=True)
    phase2_parser.add_argument("--curated-dir", type=Path, required=True)
    phase2_parser.add_argument("--external-report", type=Path, required=True)
    phase2_parser.add_argument("--output", type=Path, required=True)
    check_phase2_parser = subparsers.add_parser("check-phase2")
    check_phase2_parser.add_argument("--report", type=Path, required=True)
    check_phase2_parser.add_argument("--manifest", type=Path, required=True)
    check_phase2_parser.add_argument("--curated-dir", type=Path, required=True)
    check_phase2_parser.add_argument("--external-report", type=Path, required=True)
    arguments = parser.parse_args()

    if arguments.command == "inventory-private":
        value = build_private_inventory(
            _archive_arguments(arguments.archive),
            manual_metadata_review=arguments.manual_metadata_review,
        )
        _write_private_json(arguments.output, value)
    elif arguments.command == "stage-curated":
        value = _read_private_json(arguments.inventory)
        staged = stage_curated_files(
            value,
            _archive_arguments(arguments.archive),
            arguments.output,
        )
        print(json.dumps({"staged": staged}, indent=2))
    elif arguments.command == "build-public":
        inventory = _read_private_json(arguments.inventory)
        value = build_public_manifest(
            inventory,
            _archive_arguments(arguments.archive),
            arguments.curated_dir,
        )
        _write_json(arguments.output, value)
    elif arguments.command == "check-public":
        manifest = json.loads(arguments.manifest.read_text())
        failures = validate_public_manifest(manifest, curated_dir=arguments.curated_dir)
        if failures:
            raise CorpusError("; ".join(failures))
        print("Avatar OMNIC public manifest: PASS")
    elif arguments.command == "build-phase2":
        value = build_phase2_report(
            arguments.manifest,
            arguments.curated_dir,
            arguments.external_report,
        )
        _write_json(arguments.output, value)
    else:
        report = json.loads(arguments.report.read_text())
        failures = validate_phase2_report(
            report,
            arguments.manifest,
            arguments.curated_dir,
            arguments.external_report,
        )
        if failures:
            raise CorpusError("; ".join(failures))
        print("Avatar OMNIC Phase 2 qualification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
