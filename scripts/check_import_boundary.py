#!/usr/bin/env python3
"""Enforce one-way dependency: OSS never imports a private product package.

Even guarded imports violate explicit composition. Private products install
neutral core hooks; installing a private package must not activate it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Root of the OSS source tree to scan.
OSS_SRC = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa"

FORBIDDEN_MODULES = {"spectrasherpa_" + "server", "spectra_" + "hybrid", "spectra_" + "hybrid_contracts"}


def check_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    violations: list[str] = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        names = (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        )
        if (
            isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            )
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.append(node.args[0].value)
        if any(name.split(".")[0] in FORBIDDEN_MODULES for name in names):
            violations.append(f"{path}:{node.lineno}: private product import")
    return violations


def main() -> int:
    if not OSS_SRC.is_dir():
        print(f"ERROR: OSS source directory not found: {OSS_SRC}", file=sys.stderr)
        return 1

    violations: list[str] = []
    for py_file in sorted(OSS_SRC.rglob("*.py")):
        violations.extend(check_file(py_file))

    if violations:
        print("Import boundary violations (OSS must not import private product packages):\n")
        for v in violations:
            print(f"  {v}")
        print(f"\n{len(violations)} violation(s) found.")
        return 1

    print("Import boundary check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
