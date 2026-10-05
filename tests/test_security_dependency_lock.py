"""Release security floors for core, optional, build, and frontend locks."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
POETRY_LOCK = PACKAGE_ROOT / "poetry.lock"
FRONTEND_LOCK = PACKAGE_ROOT / "frontend/package-lock.json"
SECURITY_WORKFLOW = REPO_ROOT / ".github/workflows/oss-security-preflight.yml"


def _python_versions() -> dict[str, Version]:
    lock = tomllib.loads(POETRY_LOCK.read_text(encoding="utf-8"))
    return {package["name"].casefold(): Version(package["version"]) for package in lock["package"]}


def test_python_lock_retains_reviewed_security_floors_and_scp_authority() -> None:
    versions = _python_versions()

    floors = {
        "click": "8.3.3",
        "jupyterlab": "4.5.10",
        "mistune": "3.3.0",
        "pillow": "12.3.0",
        "pypdf": "6.19.0",
        "setuptools": "83.0.0",
        "soupsieve": "2.8.4",
    }
    for package, floor in floors.items():
        assert versions[package] >= Version(floor), f"{package} regressed below its reviewed security floor"
    assert versions["spectrochempy"] == Version("0.8.1")


def test_frontend_lock_retains_current_yaml_and_expansion_floors() -> None:
    lock = json.loads(FRONTEND_LOCK.read_text(encoding="utf-8"))
    packages = lock["packages"]
    js_yaml = [Version(item["version"]) for path, item in packages.items() if path.endswith("node_modules/js-yaml")]
    expansions = [
        Version(item["version"]) for path, item in packages.items() if path.endswith("node_modules/brace-expansion")
    ]

    assert js_yaml
    assert all(version >= Version("4.3.1") for version in js_yaml)
    assert expansions
    for version in expansions:
        if version.major == 1:
            assert version >= Version("1.1.18")
        elif version.major == 2:
            assert version >= Version("2.1.4")
        else:
            assert version >= Version("5.0.9")


def test_pypdf_install_paths_exclude_versions_before_the_reviewed_security_floor() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = SpecifierSet(project["tool"]["poetry"]["dependencies"]["pypdf"])
    requirements = (PACKAGE_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    runtime = next(Requirement(line).specifier for line in requirements if line.startswith("pypdf"))
    for constraint in (declared, runtime):
        assert Version("6.16.2") not in constraint
        assert Version("6.18.1") not in constraint
        assert Version("6.19.0") in constraint
        assert _python_versions()["pypdf"] in constraint
        assert Version("7.0.0") not in constraint


def test_public_security_workflow_blocks_all_extras_and_dev_tool_findings() -> None:
    workflow = SECURITY_WORKFLOW.read_text(encoding="utf-8")

    assert "--all-extras-mode block" in workflow
    assert "npm audit (frontend full lockfile)" in workflow
    # The full-lockfile gate runs through audit_dependencies.py so that only
    # reviewed, unexpired suppressions in audit-ignore.toml waive a dev-tool
    # advisory; every other dev finding still fails the job.
    assert "--frontend-scope full" in workflow
    assert "Frontend dev-tool audit findings are non-blocking" not in workflow


def test_npm_audit_suppressions_are_reviewed_and_unexpired() -> None:
    from datetime import date

    ignore_file = PACKAGE_ROOT / "scripts/audit-ignore.toml"
    entries = tomllib.loads(ignore_file.read_text(encoding="utf-8")).get("npm-audit", {}).get("ignore", [])
    assert entries, "npm full-lockfile gate needs its documented risk decisions to stay explicit"
    today = date.today()
    for entry in entries:
        assert entry.get("id", "").strip(), "npm suppression requires an advisory id"
        assert entry.get("reason", "").strip(), f"npm suppression {entry.get('id')!r} requires a reason"
        expires = date.fromisoformat(str(entry.get("expires", "")))
        assert expires > today, f"npm suppression {entry['id']!r} expired on {expires}; re-review or remove it"


def test_sqlalchemy_install_paths_exclude_malformed_210_metadata() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = SpecifierSet(project["tool"]["poetry"]["dependencies"]["sqlalchemy"])
    requirements = (PACKAGE_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    runtime = next(Requirement(line).specifier for line in requirements if line.startswith("sqlalchemy"))
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert '"sqlalchemy>=2.0.31,<3,!=2.1.0"' in ci
    for constraint in (declared, runtime):
        assert Version("2.1.0") not in constraint
        assert _python_versions()["sqlalchemy"] in constraint
        assert Version("2.1.1") in constraint
