#!/usr/bin/env python3
"""Standalone public evidence projections; private qualification stays upstream."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
    )
    commands = [["scripts/generate_node_reference.py", *(["--check"] if args.check else [])]]
    if args.check:
        commands.extend(
            [
                ["scripts/check_user_copy.py"],
                [
                    "-m",
                    "pytest",
                    "tests/test_repository_governance.py",
                    "tests/test_generated_reference.py",
                    "--no-cov",
                    "-q",
                ],
            ]
        )
    for command in commands:
        result = subprocess.run([sys.executable, *command], cwd=ROOT, env=environment, check=False)
        if result.returncode:
            print("Failed command: " + " ".join(["python", *command]), file=sys.stderr)
            print(
                "For stale public reference tables: python scripts/generate_node_reference.py. "
                "For copy: correct wording or shrink resolved baseline entries. "
                "No private qualification receipt can be generated here.",
                file=sys.stderr,
            )
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
