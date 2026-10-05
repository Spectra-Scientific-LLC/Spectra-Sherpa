#!/usr/bin/env python3
"""Generate/check the public, non-raw Avatar collection-definition document."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from spectra_sherpa.app.lib.collection_definition import (
    COLLECTION_DEFINITION_SCHEMA,
    validate_collection_definition,
)
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "docs/evidence/avatar-essential-oils-v1-manifest.json"
DEFAULT_PHASE4 = REPOSITORY_ROOT / "docs/evidence/avatar-essential-oils-v1-canonical-dataset.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "docs/evidence/avatar-essential-oils-v1-collection-definition.json"
SAMPLE_TABLE_COLUMNS = (
    "sample_id",
    "specimen_id",
    "block",
    "acquisition_order",
    "analysis_role",
    "claimed_botanical_group",
    "author_reported_authenticity_status",
    "evidence_status",
    "evidence_citation_id",
    "curated_filename",
    "curated_sha256",
    "canonical_omnic_title",
    "label_status",
    "acquired_at",
)


def _json_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sample_table(files: list[dict[str, Any]]) -> dict[str, list[Any]]:
    table = {
        "sample_id": [row["sample_id"] for row in files],
        "specimen_id": [row["specimen_id"] for row in files],
        "block": [row["block"] for row in files],
        "acquisition_order": [row["acquisition_order"] for row in files],
        "analysis_role": [row["analysis_role"] for row in files],
        "claimed_botanical_group": [row["claimed_botanical_group"] for row in files],
        "author_reported_authenticity_status": [row["author_reported_authenticity_status"] for row in files],
        "evidence_status": [row["evidence_status"] for row in files],
        "evidence_citation_id": [None for _row in files],
        "curated_filename": [row["distribution_filename"] for row in files],
        "curated_sha256": [row["curated_sha256"] for row in files],
        "canonical_omnic_title": [row["canonical_omnic_title"] for row in files],
        "label_status": [row["label_status"] for row in files],
        "acquired_at": [row["acquired_at"] for row in files],
    }
    if tuple(table) != SAMPLE_TABLE_COLUMNS:
        raise ValueError("Avatar table columns are not exact")
    return table


def build_definition(manifest: dict[str, Any], phase4: dict[str, Any]) -> bytes:
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 33:
        raise ValueError("Avatar manifest must contain the exact 33-file corpus")
    if len({row.get("sample_id") for row in files}) != 33:
        raise ValueError("Avatar manifest sample identities are missing or duplicated")
    balance: dict[str, set[int]] = {}
    for row in files:
        balance.setdefault(str(row["specimen_id"]), set()).add(int(row["block"]))
    if len(balance) != 11 or any(blocks != {1, 2, 3} for blocks in balance.values()):
        raise ValueError("Avatar manifest is not the exact 11-specimen by 3-block corpus")

    phase4_dataset = phase4.get("dataset")
    phase4_table = phase4.get("sample_table")
    if not isinstance(phase4_dataset, dict) or not isinstance(phase4_table, dict):
        raise ValueError("Phase 4 canonical authority is incomplete")
    table = _sample_table(files)
    if list(phase4_table.get("columns") or []) != list(SAMPLE_TABLE_COLUMNS):
        raise ValueError("Phase 4 sample-table columns differ from the import definition")
    if phase4_table.get("sha256") != _json_sha256(table):
        raise ValueError("Phase 4 sample-table digest differs from the import definition")
    if phase4_dataset.get("target_state") != "absent" or phase4_dataset.get("sample_classes_state") != "absent":
        raise ValueError("Phase 4 unexpectedly contains target or class state")

    domain = DomainContext.model_validate(phase4_dataset["domain"]).model_dump(mode="json", exclude_none=False)
    payload = {
        "schema_version": COLLECTION_DEFINITION_SCHEMA,
        "columns": list(SAMPLE_TABLE_COLUMNS),
        "collection": {
            "dataset_id": phase4_dataset["dataset_id"],
            "title": phase4_dataset["title"],
            "units": phase4_dataset["units"],
            "data_role": phase4_dataset["data_role"],
            "domain": domain,
            "sample_axis": {"title": "Acquisition", "units": None, "values_policy": "omit"},
        },
        "rows": [
            {
                "file_name": f"raw/{row['distribution_filename']}",
                "sha256": row["curated_sha256"],
                "asset_id": row["asset_id"],
                "source_row_index": 0,
                "sample_id": row["sample_id"],
                "annotations": {column: table[column][index] for column in SAMPLE_TABLE_COLUMNS},
            }
            for index, row in enumerate(files)
        ],
    }
    return validate_collection_definition(payload).canonical_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--phase4", type=Path, default=DEFAULT_PHASE4)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    phase4 = json.loads(args.phase4.read_text())
    if phase4.get("source_manifest_sha256") != _sha256(args.manifest):
        raise ValueError("Phase 4 does not bind the current Avatar manifest")
    expected = build_definition(manifest, phase4)
    if args.command == "build":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(expected)
        print(f"Wrote {args.output} ({hashlib.sha256(expected).hexdigest()})")
        return 0
    if not args.output.is_file() or args.output.read_bytes() != expected:
        raise ValueError("checked Avatar collection definition is stale")
    print(f"Avatar collection definition: PASS ({hashlib.sha256(expected).hexdigest()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
