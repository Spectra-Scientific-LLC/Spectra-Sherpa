#!/usr/bin/env python3
"""Promote the qualified active canonical-node inventory to five stars."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from qualify_canonical_node_baseline import (
    _RETAINED_PAIR,
    _RETAINED_PRODUCT_PROJECTION,
    _RETAINED_RECEIPTS,
    validate_retained_pair,
)

_ASSESSMENT_SCHEMA = "spectra-canonical-node-readiness-assessments/3"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def promote(repository_root: Path) -> dict[str, Any]:
    evidence = repository_root / "docs/evidence"
    assessment_path = evidence / "canonical-node-readiness-assessments.json"
    manifest = _load(evidence / "canonical-node-qualification-manifest.json")
    pair = validate_retained_pair(repository_root, manifest)
    source = _load(assessment_path)
    qualified = set(pair["qualified_node_types"])
    rows = source.get("nodes")
    if not isinstance(rows, list):
        raise ValueError("assessment nodes must be a list")
    by_node = {row["node_type"]: row for row in rows}
    if not qualified <= set(by_node):
        raise ValueError("paired qualification contains unassessed nodes")

    pair_ref = _RETAINED_PAIR
    test_count = pair.get("passed_test_count")
    if isinstance(test_count, bool) or not isinstance(test_count, int) or test_count < 1:
        raise ValueError("paired qualification has no valid passing-test count")
    pair_evidence_sentence = (
        f"Exact-tree paired Darwin/Linux qualification retained {test_count:,} identical passing tests "
        "with zero failures, errors, or skips, completing the release path."
    )
    for node_type in sorted(qualified):
        row = by_node[node_type]
        if row["stars"] != 4:
            raise ValueError(f"{node_type} is not at the qualified four-star baseline")
        if set(row["fault_patterns"]) - {"evidence_qualification_gap"}:
            raise ValueError(f"{node_type} retains a non-qualification finding")
        summary = row["summary"].replace("; final portable qualification is missing", "").rstrip()
        if not summary.endswith("."):
            summary += "."
        row.update(
            {
                "stars": 5,
                "criticality": "none",
                "summary": f"{summary} {pair_evidence_sentence}",
                "fault_patterns": [],
                "next_star_blocker": "none",
            }
        )
        if pair_ref not in row["evidence_refs"]:
            row["evidence_refs"].append(pair_ref)

    source.update(
        {
            "schema_version": _ASSESSMENT_SCHEMA,
            "audit_date": "2026-09-02",
            "baseline_commit": pair["source_revision"],
            "paired_qualification": {
                "macos_receipt": _RETAINED_RECEIPTS["Darwin"],
                "ubuntu_receipt": _RETAINED_RECEIPTS["Linux"],
                "pair_receipt": pair_ref,
                "product_projection": _RETAINED_PRODUCT_PROJECTION,
                "pair_digest": pair["pair_digest"],
            },
        }
    )
    assessment_path.write_text(json.dumps(source, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[3])
    arguments = parser.parse_args()
    promote(arguments.repository_root.resolve())


if __name__ == "__main__":
    main()
