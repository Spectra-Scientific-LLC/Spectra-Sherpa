#!/usr/bin/env python3
"""Generate/check the explicit SCP and NDDataset reachability disposition.

The inventory is source-derived.  Classification is deliberately closed by
repository area: a matching symbol in a new area fails until a maintainer
states whether it is optional science, a dependency gate, or a test-only
compatibility/containment proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs" / "evidence" / "scp-ingestion-reachability.json"
SEARCH_ROOTS = (
    ROOT / "packages" / "spectra-sherpa" / "src",
    ROOT / "packages" / "spectra-sherpa" / "tests",
    ROOT / "packages" / "spectra-server" / "src",
    ROOT / "packages" / "spectra-server" / "tests",
)
MARKERS = {
    "spectrochempy_import": re.compile(r"\b(?:import|from)\s+spectrochempy\b"),
    "scp_compat": re.compile(r"\bscp_compat\b"),
    "scp_adapter": re.compile(r"\bscp_adapter\b"),
    "optional_adapter": re.compile(r"\bspectrochempy_adapter\b"),
    "scp_extract_hook": re.compile(r"\bfrom_scp\b"),
    "nddataset": re.compile(r"\bNDDataset\b"),
    "scp_requirement": re.compile(r"\b(?:require_scp|requires_scp)\b"),
    "legacy_reader_dispatch": re.compile(r"\bget_reader_for_extension\b"),
}

_OPTIONAL_ALGORITHM_FILES = {
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/efa_nodes.py",
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/mcr_nodes.py",
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/simplisma_nodes.py",
    "packages/spectra-sherpa/src/spectra_sherpa/interoperability/spectrochempy_adapter.py",
}
_OPTIONAL_DEPENDENCY_GATE_FILES = {
    "packages/spectra-sherpa/src/spectra_sherpa/app/api/v1/routes/workflows/catalog.py",
    "packages/spectra-sherpa/src/spectra_sherpa/app/schemas/workflows.py",
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/node_base.py",
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/node_catalog_contract.py",
}


def _classification(relative: str) -> str:
    if "/tests/" in relative:
        return "historical_test_update"
    if relative in _OPTIONAL_ALGORITHM_FILES:
        return "algorithm_keep_optional"
    if relative in _OPTIONAL_DEPENDENCY_GATE_FILES:
        return "optional_dependency_gate"
    raise RuntimeError(f"Unclassified retained SCP/NDDataset coupling: {relative}")


def _records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for root in SEARCH_ROOTS:
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(text.encode()).hexdigest()
            for line_number, line in enumerate(text.splitlines(), 1):
                matched = [name for name, pattern in MARKERS.items() if pattern.search(line)]
                if not matched:
                    continue
                records.append(
                    {
                        "path": relative,
                        "line": line_number,
                        "markers": matched,
                        "classification": _classification(relative),
                        "source_sha256": digest,
                    }
                )
    return records


def document() -> dict[str, object]:
    records = _records()
    counts: dict[str, int] = {}
    for record in records:
        name = str(record["classification"])
        counts[name] = counts.get(name, 0) + 1
    return {
        "schema_version": "spectrasherpa-scp-ingestion-reachability/2",
        "classification_vocabulary": [
            "algorithm_keep_optional",
            "optional_dependency_gate",
            "historical_test_update",
        ],
        "counts": dict(sorted(counts.items())),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(document(), indent=2, sort_keys=True) + "\n"
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(rendered)
        print(OUTPUT.relative_to(ROOT))
        return 0
    if not OUTPUT.is_file() or OUTPUT.read_text() != rendered:
        raise SystemExit(f"stale reachability evidence: run {Path(__file__).name} --write")
    print("SCP ingestion reachability evidence is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
