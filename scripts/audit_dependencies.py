#!/usr/bin/env python3
"""Fail-closed dependency audit for the public Spectra-Sherpa tree.

This script intentionally audits files as they exist in the public repo
layout. It is used by public CI and by the monorepo OSS publish gate after
the curated release bundle has been materialized into the public clone.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import date
from pathlib import Path

GHSA_ID = re.compile(r"GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}")


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


def _load_npm_audit_ignores(path: Path) -> dict[str, str]:
    """Reviewed npm suppressions, fail-closed: expired entries never waive."""
    if not path.is_file():
        return {}
    data = tomllib.loads(path.read_text())
    entries = data.get("npm-audit", {}).get("ignore", [])
    if not isinstance(entries, list):
        raise SystemExit(f"{path}: [npm-audit].ignore must be a list")

    today = date.today()
    waivers: dict[str, str] = {}
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f"{path}: npm ignore entry {idx} must be a table")
        advisory_id = str(entry.get("id", "")).strip()
        reason = str(entry.get("reason", "")).strip()
        expires = str(entry.get("expires", "")).strip()
        if not advisory_id or not reason or not expires:
            raise SystemExit(f"{path}: npm ignore entry {idx} requires non-empty id, reason and expires")
        try:
            expiry = date.fromisoformat(expires)
        except ValueError:
            raise SystemExit(f"{path}: npm ignore entry {idx} has an invalid expires date: {expires!r}") from None
        if expiry <= today:
            raise SystemExit(f"{path}: npm suppression {advisory_id} expired on {expires}; re-review or remove it")
        waivers[advisory_id] = reason
        print(f"Using npm-audit suppression {advisory_id}: {reason} expires={expires}", flush=True)
    return waivers


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


def audit_npm(directory: Path, *, scope: str, ignore_file: Path) -> None:
    """Audit a committed lock, independent of installed packages or lifecycle scripts."""
    _require_tool("npm")
    if not (directory / "package-lock.json").is_file():
        raise SystemExit(f"required npm audit lockfile missing: {directory / 'package-lock.json'}")
    print(f"Auditing {directory} ({scope} lockfile)", flush=True)
    if scope == "runtime":
        _run(
            ["npm", "audit", "--offline=false", "--package-lock-only", "--omit=dev", "--audit-level=moderate"],
            cwd=directory,
        )
        return

    # Full lockfile, including dev tooling. Dev findings block by default;
    # only reviewed, unexpired suppressions in audit-ignore.toml waive an
    # advisory, and every other advisory in the report still fails the gate.
    waivers = _load_npm_audit_ignores(ignore_file)
    result = subprocess.run(
        [
            "npm",
            "audit",
            "--offline=false",
            "--package-lock-only",
            "--include=dev",
            "--include=optional",
            "--audit-level=moderate",
            "--json",
        ],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise SystemExit(f"npm audit returned an invalid JSON report for {directory}") from None
    if (
        result.returncode not in {0, 1}
        or not isinstance(report, dict)
        or report.get("error")
        or report.get("auditReportVersion") != 2
        or not isinstance(report.get("vulnerabilities"), dict)
    ):
        raise SystemExit(f"npm audit returned an incomplete or failed report for {directory}")
    if result.returncode == 0:
        return
    found = set(GHSA_ID.findall(result.stdout))
    if not found:
        # The report failed without a parseable advisory id; surface it whole.
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit("npm full-lockfile audit failed without an identifiable advisory")
    unwaived = sorted(found - waivers.keys())
    if unwaived:
        sys.stdout.write(result.stdout)
        raise SystemExit(
            "npm full-lockfile audit reported advisories without a reviewed suppression: " + ", ".join(unwaived)
        )


def audit_frontend(repo: Path, *, scope: str, ignore_file: Path) -> None:
    audit_npm(repo / "frontend", scope=scope, ignore_file=ignore_file)


def audit_desktop(repo: Path, *, ignore_file: Path) -> None:
    # Electron and its downloader are declared as dev dependencies, but ship or
    # execute in the desktop delivery chain. A runtime-only audit omits both.
    audit_npm(repo / "desktop/electron", scope="full", ignore_file=ignore_file)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Path to the public Spectra-Sherpa repository layout.",
    )
    parser.add_argument("--skip-python", action="store_true", help="Skip pip-audit checks.")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip the frontend npm audit.")
    parser.add_argument("--skip-desktop", action="store_true", help="Skip the desktop full-lockfile npm audit.")
    parser.add_argument(
        "--frontend-scope",
        choices=["runtime", "full"],
        default="full",
        help="npm audit scope: runtime omits dev dependencies; full includes them with reviewed suppressions.",
    )
    parser.add_argument(
        "--ignore-file",
        type=Path,
        default=None,
        help="TOML file with reviewed pip-audit and npm-audit suppressions. Defaults to scripts/audit-ignore.toml.",
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
        audit_frontend(repo, scope=args.frontend_scope, ignore_file=ignore_file)
    if not args.skip_desktop:
        audit_desktop(repo, ignore_file=ignore_file)
    print("Spectra-Sherpa dependency audit passed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
