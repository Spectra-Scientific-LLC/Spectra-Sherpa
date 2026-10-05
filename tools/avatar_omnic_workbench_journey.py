#!/usr/bin/env python3
"""Validate the bounded public record of the private Avatar Workbench journey."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "spectrasherpa-avatar-essential-oils-workbench-journey/1"
DATASET_ID = "avatar-essential-oils/1"
IMPLEMENTATION_COMMIT = "fae9f9ca9c4aa76b4df83a72f2b9c7d192e48f74"
MANIFEST_SHA256 = "171b74c2abca681d47d65b286629492b9435832ca3aac200504cc4ee125ca85a"
QUALIFICATION_SHA256 = "ba475f4bbca33acd81e467b264240f179d323a189159b1c68bcae26af543df03"
CANONICAL_REPORT_SHA256 = "1386ac7facdc742c1b5f9e1992fc2a1c81c57ad79596de07840a0bbcabcccf70"
DEFINITION_SHA256 = "524960aed6d2ef8294a7ffed0056f7287a38b611462c12599fc2bd7cf1222db2"
SOURCE_IDENTITY_SHA256 = "199a9b04f7abacdc0ab73eef70fec44133abcd041f87c7e1855af3b753e8fcd8"
SCIENTIFIC_IDENTITY_SHA256 = "a927940d8f14e52ff9f6228aa41527aa4142e15858feadc6ed6568052d3a20df"
CHECKED_REPORT_SHA256 = "739674ce77de138c2b7e465bbb8bb0d68e6ae0d10a4e759fdc952466d877ad28"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_report() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "dataset_version": 1,
        "status": "phase5_3b_author_operated_private_workbench_journey_complete",
        "observed_at": "2026-08-24",
        "implementation_commit": IMPLEMENTATION_COMMIT,
        "observation_authority": "author_operated_local_oss_workbench",
        "checked_inputs": {
            "source_manifest_sha256": MANIFEST_SHA256,
            "parser_qualification_sha256": QUALIFICATION_SHA256,
            "canonical_dataset_report_sha256": CANONICAL_REPORT_SHA256,
            "collection_definition_sha256": DEFINITION_SHA256,
        },
        "upload_and_inventory": {
            "upload_batch_file_counts": [11, 11, 11],
            "persisted_file_count": 33,
            "inventory_asset_count": 33,
            "parser_id": "native-omnic",
            "asset_ids": ["spectrum"],
        },
        "definition_receipt": {
            "preview_verified": True,
            "attached_and_current": True,
            "file_count": 33,
            "row_count": 33,
            "column_count": 14,
            "shape": [33, 1868],
            "dataset_id": "avatar-essential-oils/1:canonical-phase4",
            "source_manifest_sha256": SOURCE_IDENTITY_SHA256,
            "collection_definition_sha256": DEFINITION_SHA256,
            "scientific_collection_sha256": SCIENTIFIC_IDENTITY_SHA256,
            "target_present": False,
            "sample_classes_present": False,
        },
        "collection_inspection": {
            "complete_table_visible": True,
            "table_row_count": 33,
            "table_column_count": 14,
            "specimen_legend_category_count": 11,
            "block_legend_values": [1, 2, 3],
            "raw_spectrum_trace_count": 33,
            "rendered_plot_view_count": 4,
        },
        "stale_source_test": {
            "method": "temporarily_withhold_one_private_source_then_restore_the_exact_source",
            "withheld_state": "stale_modeling_blocked",
            "restored_state": "attached_and_current",
            "definition_fallback_observed": False,
        },
        "privacy_boundary": {
            "raw_source_bytes_published": False,
            "project_export_published": False,
            "screenshots_published": False,
            "private_paths_recorded": False,
            "credentials_or_account_identifiers_recorded": False,
        },
        "claim_boundary": (
            "Author-operated OSS Workbench attachment, exact collection inspection, plot grouping, and "
            "stale-source refusal for this private 33-spectrum corpus only."
        ),
        "nonclaims": [
            "non_author_physical_action_2",
            "save_restart_or_new_workspace_import",
            "pca_or_plsda_result",
            "botanical_authenticity_or_population_result",
            "redistribution_permission",
            "public_corpus_or_project_package",
        ],
    }


def validate_checked_journey(
    report_path: Path,
    manifest_path: Path,
    qualification_path: Path,
    canonical_report_path: Path,
    definition_path: Path,
) -> list[str]:
    failures: list[str] = []
    if _sha256(report_path) != CHECKED_REPORT_SHA256:
        failures.append("checked Workbench journey digest differs from the reviewed authority")
    bindings = (
        (manifest_path, MANIFEST_SHA256, "source manifest"),
        (qualification_path, QUALIFICATION_SHA256, "parser qualification"),
        (canonical_report_path, CANONICAL_REPORT_SHA256, "canonical dataset report"),
        (definition_path, DEFINITION_SHA256, "collection definition"),
    )
    for path, expected, label in bindings:
        if _sha256(path) != expected:
            failures.append(f"{label} digest differs from the exact checked input")
    try:
        report = json.loads(report_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError):
        failures.append("checked Workbench journey is not valid JSON")
        return failures
    if report != _expected_report():
        failures.append("checked Workbench journey differs from its closed reviewed projection")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--canonical-report", type=Path, required=True)
    parser.add_argument("--definition", type=Path, required=True)
    args = parser.parse_args()
    failures = validate_checked_journey(
        args.report,
        args.manifest,
        args.qualification,
        args.canonical_report,
        args.definition,
    )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("Avatar OMNIC Phase 5.3b Workbench journey: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
