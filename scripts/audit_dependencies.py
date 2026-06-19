#!/usr/bin/env python3
"""Fail-closed dependency audit for the public Spectra-Sherpa tree.

This script intentionally audits files as they exist in the public repo
layout. It is used by public CI and by the monorepo OSS publish gate after
the curated release bundle has been materialized into the public clone.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


def _run(args: list[str], cwd: Path, *, check: bool = True) -> int:
    print(f"+ {' '.join(args)}", flush=True)
    return subprocess.run(args, cwd=cwd, check=check).returncode


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"required command not found on PATH: {name}")


def _load_pip_audit_ignores(path: Path) -> list[str]:
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text())
    entries = data.get("pip-audit", {}).get("ignore", [])
    if not isinstance(entries, list):
        raise SystemExit(f"{path}: [pip-audit].ignore must be a list")

    ids: list[str] = []
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f"{path}: ignore entry {idx} must be a table")
        advisory_id = str(entry.get("id", "")).strip()
        reason = str(entry.get("reason", "")).strip()
        if not advisory_id or not reason:
            raise SystemExit(f"{path}: ignore entry {idx} requires non-empty id and reason")
        ids.append(advisory_id)
        expires = str(entry.get("expires", "")).strip()
        suffix = f" expires={expires}" if expires else ""
        print(f"Using pip-audit suppression {advisory_id}: {reason}{suffix}", flush=True)
    return ids


def _pip_audit_args(requirements: Path, ignored_vulns: list[str]) -> list[str]:
    args = ["pip-audit", "-r", str(requirements)]
    for advisory_id in ignored_vulns:
        args.extend(["--ignore-vuln", advisory_id])
    return args


def audit_python(repo: Path, *, ignore_file: Path, all_extras_mode: str) -> None:
    _require_tool("pip-audit")
    _require_tool("poetry")
    ignored_vulns = _load_pip_audit_ignores(ignore_file)

    requirements = repo / "requirements.txt"
    if requirements.is_file():
        _run(_pip_audit_args(requirements, ignored_vulns), cwd=repo)
    else:
        print("requirements.txt not present; skipping direct requirements audit.", flush=True)

    pyproject = repo / "pyproject.toml"
    poetry_lock = repo / "poetry.lock"
    if not pyproject.is_file() or not poetry_lock.is_file():
        print("pyproject.toml/poetry.lock not present; skipping Poetry all-extras audit.", flush=True)
        return

    with tempfile.TemporaryDirectory(prefix="spectra-sherpa-audit-") as tmp:
        exported = Path(tmp) / "requirements-all-extras.txt"
        _run(
            [
                "poetry",
                "export",
                "-f",
                "requirements.txt",
                "--without-hashes",
                "--all-extras",
                "-o",
                str(exported),
            ],
            cwd=repo,
        )
        rc = _run(_pip_audit_args(exported, ignored_vulns), cwd=repo, check=False)
        if rc != 0:
            message = (
                "Poetry all-extras dependency audit reported advisories. "
                "This covers optional external dependency trees and is "
                f"configured as {all_extras_mode!r}."
            )
            if all_extras_mode == "block":
                raise SystemExit(message)
            print(f"::warning::{message}", flush=True)


def audit_frontend(repo: Path) -> None:
    _require_tool("npm")
    frontend = repo / "frontend"
    if not (frontend / "package-lock.json").is_file():
        print("frontend/package-lock.json not present; skipping frontend runtime audit.", flush=True)
        return
    _run(["npm", "audit", "--omit=dev", "--audit-level=moderate"], cwd=frontend)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Path to the public Spectra-Sherpa repository layout.",
    )
    parser.add_argument("--skip-python", action="store_true", help="Skip pip-audit checks.")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip npm audit checks.")
    parser.add_argument(
        "--ignore-file",
        type=Path,
        default=None,
        help="TOML file with reviewed pip-audit suppressions. Defaults to scripts/audit-ignore.toml.",
    )
    parser.add_argument(
        "--all-extras-mode",
        choices=["warn", "block"],
        default="warn",
        help="Whether advisories found only in the Poetry all-extras audit warn or block.",
    )
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo path does not exist or is not a directory: {repo}")
    ignore_file = args.ignore_file.resolve() if args.ignore_file else repo / "scripts" / "audit-ignore.toml"

    if not args.skip_python:
        audit_python(repo, ignore_file=ignore_file, all_extras_mode=args.all_extras_mode)
    if not args.skip_frontend:
        audit_frontend(repo)
    print("Spectra-Sherpa dependency audit passed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
