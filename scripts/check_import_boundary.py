#!/usr/bin/env python3
"""Enforce one-way dependency: OSS must never import from spectra-server.

Guarded imports (inside ``try: ... except ImportError``) are allowed —
these are runtime feature probes, not hard dependencies.

Usage (CI):
    python scripts/check_import_boundary.py

Exit code 0 = clean, 1 = violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Root of the OSS source tree to scan.
OSS_SRC = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa"

FORBIDDEN_RE = re.compile(r"^\s*(from|import)\s+spectrasherpa_server\b")


def _is_inside_try_except(lines: list[str], lineno: int) -> bool:
    """Heuristic: walk backwards up to 5 lines looking for a bare ``try:``."""
    for i in range(lineno - 1, max(lineno - 6, -1), -1):
        stripped = lines[i].strip()
        if stripped == "try:":
            return True
        if stripped and not stripped.startswith("#"):
            # Stop at the first non-comment, non-blank line that isn't try:
            break
    return False


def check_file(path: Path) -> list[str]:
    violations: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return violations
    for lineno_0, line in enumerate(lines):
        if FORBIDDEN_RE.search(line):
            if not _is_inside_try_except(lines, lineno_0):
                violations.append(f"{path}:{lineno_0 + 1}: {line.strip()}")
    return violations


def main() -> int:
    if not OSS_SRC.is_dir():
        print(f"ERROR: OSS source directory not found: {OSS_SRC}", file=sys.stderr)
        return 1

    violations: list[str] = []
    for py_file in sorted(OSS_SRC.rglob("*.py")):
        violations.extend(check_file(py_file))

    if violations:
        print("Import boundary violations (OSS must not import from spectra-server):\n")
        for v in violations:
            print(f"  {v}")
        print(f"\n{len(violations)} violation(s) found.")
        return 1

    print("Import boundary check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
