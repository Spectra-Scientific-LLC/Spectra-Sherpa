#!/usr/bin/env python3
"""Refuse accidental publication of unreviewed/internal documentation.

The inventory records audience admission, not scientific qualification.
Run: python scripts/check_public_docs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES = {"vision_audit_062425.md", "tenancy-org-layer-design.md"}
INTERNAL_MARKERS = (
    "SPECTRA-" + "COMMERCIAL-DOC",
    "Internal product and engagement planning note",
    "Proprietary architecture planning note",
    "Status: **Draft for review**",
    "**Status:** proposed target arrangement",
)


def check(root: Path) -> list[str]:
    manifest = json.loads((root / "docs-publication.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        return ["Unsupported docs-publication schema"]
    pages = manifest["pages"]
    actual = {p.relative_to(root).as_posix() for p in (root / "docs").rglob("*.md")}
    failures = []
    if len(pages) != len(set(pages)):
        failures.append("Duplicate publication inventory paths")
    for name in sorted(actual - set(pages)):
        failures.append(f"Unreviewed publication path: {name}")
    for name in sorted(set(pages) - actual):
        failures.append(f"Missing inventoried page: {name}")
    for name in sorted(actual):
        path = Path(name)
        if path.name in FORBIDDEN_NAMES or any(p in {"plan", "plans", "product-archive"} for p in path.parts):
            failures.append(f"Internal document in OSS: {name}")
        text = (root / name).read_text(encoding="utf-8")
        for marker in INTERNAL_MARKERS:
            if marker in text:
                failures.append(f"Internal/aspirational marker in {name}: {marker}")
    return failures


def main() -> int:
    failures = check(ROOT)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        print("Remove internal material; review new page scope before updating docs-publication.json.", file=sys.stderr)
        return 1
    print("Public documentation inventory and scope markers pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
