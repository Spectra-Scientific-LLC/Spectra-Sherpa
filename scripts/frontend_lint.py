#!/usr/bin/env python3
"""Run the existing installed frontend lint without downloading or staging anything."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    entry = ROOT / "frontend/node_modules/eslint/bin/eslint.js"
    if not entry.is_file():
        raise SystemExit("Install the locked frontend tools first: cd frontend && npm ci")
    return subprocess.run(
        ["node", str(entry), "src/", "--max-warnings", "300"],
        cwd=ROOT / "frontend",
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
