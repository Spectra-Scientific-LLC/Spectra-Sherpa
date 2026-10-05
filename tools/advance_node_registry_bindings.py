#!/usr/bin/env python3
"""Advance current node-governance bindings after a census regeneration.

The retention decision and readiness assessment are reviewed authorities, not
generated projections.  A contract-only census change may advance their
registry binding only when their node inventories still describe the exact
current registry.  Historical plan records are deliberately outside this
tool's scope.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _node_types(rows: object, *, path: Path) -> set[str]:
    if not isinstance(rows, list):
        raise ValueError(f"{path} node inventory must be a list")
    node_types = {
        row.get("node_type") for row in rows if isinstance(row, dict) and isinstance(row.get("node_type"), str)
    }
    if len(node_types) != len(rows):
        raise ValueError(f"{path} node inventory is malformed or duplicated")
    return node_types


def advance_bindings(repository_root: Path, *, check: bool) -> None:
    census_path = repository_root / "docs/evidence/m4-node-contract-census.json"
    retention_path = repository_root / "docs/plan/canonical-node-retention-decisions.json"
    assessment_path = repository_root / "docs/evidence/canonical-node-readiness-assessments.json"

    census = _load_object(census_path)
    retention = _load_object(retention_path)
    assessment = _load_object(assessment_path)
    registry_digest = census.get("registry_digest")
    if not isinstance(registry_digest, str) or re.fullmatch(r"[0-9a-f]{64}", registry_digest) is None:
        raise ValueError("current census registry digest is malformed")

    current_nodes = _node_types(census.get("nodes"), path=census_path)
    retained_nodes = retention.get("retained_node_types")
    if not isinstance(retained_nodes, list) or retained_nodes != sorted(current_nodes):
        raise ValueError("retention decision does not describe the exact current registry")

    assessed_nodes = _node_types(assessment.get("nodes"), path=assessment_path)
    retired_nodes = assessment.get("retired_node_types")
    if not isinstance(retired_nodes, list):
        raise ValueError("readiness assessment retired-node inventory is malformed")
    if assessed_nodes - set(retired_nodes) != current_nodes:
        raise ValueError("readiness assessment does not describe the exact current registry")

    prior_bindings = {
        retention.get("registry_digest"),
        assessment.get("registry_digest"),
    }
    if len(prior_bindings) != 1:
        raise ValueError("retention and readiness authorities disagree before advancement")
    prior_binding = next(iter(prior_bindings))
    if not isinstance(prior_binding, str) or re.fullmatch(r"[0-9a-f]{64}", prior_binding) is None:
        raise ValueError("prior node-governance binding is malformed")
    if check:
        if prior_bindings != {registry_digest}:
            raise ValueError("node-governance bindings are stale")
        return

    for path, document in (
        (retention_path, retention),
        (assessment_path, assessment),
    ):
        document["registry_digest"] = registry_digest
        path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[3]
    advance_bindings(repository_root, check=arguments.check)


if __name__ == "__main__":
    main()
