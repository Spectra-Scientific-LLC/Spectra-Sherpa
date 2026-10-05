#!/usr/bin/env python3
"""Run focused node tests or verify a node through retained qualification authorities."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "docs" / "evidence"
MANIFEST_PATH = EVIDENCE_ROOT / "canonical-node-qualification-manifest.json"
READINESS_TOOL = PACKAGE_ROOT / "tools" / "generate_node_readiness_audit.py"
QUALIFICATION_TOOL = PACKAGE_ROOT / "tools" / "qualify_canonical_node_baseline.py"


def _load_registry() -> Any:
    from spectra_sherpa.app.services.dag import node_registry

    return node_registry


def _known_node_types() -> list[str]:
    return sorted(metadata.node_type for metadata in _load_registry().list_nodes())


def _require_node(node_type: str) -> None:
    known = _known_node_types()
    if node_type not in known:
        examples = ", ".join(known[:5])
        raise SystemExit(
            f"Unknown NODE {node_type!r}. Use the canonical dotted node type, for example "
            f"NODE=model.pca or NODE=preprocess.normalize. Registered examples: {examples}."
        )


def _manifest() -> dict[str, Any] | None:
    if not MANIFEST_PATH.is_file():
        return None
    value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), list):
        raise SystemExit(f"Qualification manifest is invalid: {MANIFEST_PATH}")
    return value


def _manifest_row(node_type: str) -> dict[str, Any] | None:
    manifest = _manifest()
    if manifest is None:
        return None
    rows = [row for row in manifest["nodes"] if row.get("node_type") == node_type]
    if not rows:
        return None
    if len(rows) != 1:
        raise SystemExit(f"Qualification manifest contains duplicate rows for {node_type!r}.")
    return rows[0]


def _test_files(node_type: str) -> list[Path]:
    row = _manifest_row(node_type)
    if row is not None:
        paths = [REPOSITORY_ROOT / entry["path"] for entry in row["evidence_files"]]
    else:
        token = node_type.encode("utf-8")
        paths = [path for path in sorted((PACKAGE_ROOT / "tests").rglob("test_*.py")) if token in path.read_bytes()]
    paths = sorted(set(paths))
    if not paths:
        raise SystemExit(
            f"No focused tests name {node_type!r}. Add an exact scientific-oracle test "
            "that names the canonical node type."
        )
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(f"Node evidence test file is missing: {', '.join(missing)}")
    return paths


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=PACKAGE_ROOT, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def run_tests(node_type: str) -> None:
    _require_node(node_type)
    paths = _test_files(node_type)
    print(f"Focused tests for {node_type}: {', '.join(str(path.relative_to(PACKAGE_ROOT)) for path in paths)}")
    _run([sys.executable, "-m", "pytest", *[str(path) for path in paths], "--no-cov", "-q"])


def qualify(node_type: str) -> None:
    _require_node(node_type)
    run_tests(node_type)
    row = _manifest_row(node_type)
    if row is None:
        raise SystemExit(
            "Focused node qualification requires the maintainer evidence authorities from the integration monorepo. "
            "Run 'make test-node NODE=<canonical.type>' here, then submit the change for paired-platform qualification."
        )
    _run([sys.executable, str(READINESS_TOOL), "--check"])
    _run([sys.executable, str(QUALIFICATION_TOOL), "check", "--manifest", str(MANIFEST_PATH)])
    print(
        f"Local qualification authorities and evidence tests passed for {node_type}. "
        "Any implementation or contract change still requires regenerated readiness evidence "
        "and a new Darwin/Linux pair."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("test", "qualify"))
    parser.add_argument("--node", required=True, help="Canonical dotted node type, for example model.pca")
    args = parser.parse_args()
    if args.command == "test":
        run_tests(args.node)
    else:
        qualify(args.node)


if __name__ == "__main__":
    main()
