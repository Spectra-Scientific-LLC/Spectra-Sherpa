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
        "pypdf": "6.21.4",
        "nbconvert": "7.17.2",  # GHSA-pjvx-prjx-h659: extracted-output path traversal
        "setuptools": "84.1.0",  # GHSA-xmj3-9gf7-h52w: Windows legacy-wheel path escape
        "soupsieve": "2.8.4",
    }
    for package, floor in floors.items():
        assert versions[package] >= Version(floor), f"{package} regressed below its reviewed security floor"
    assert versions["spectrochempy"] == Version("0.8.1")


def test_frontend_lock_retains_current_yaml_and_expansion_floors() -> None:
    lock = json.loads(FRONTEND_LOCK.read_text(encoding="utf-8"))
    packages = lock["packages"]
    for name in ("vitest", "@vitest/mocker"):
        assert Version(packages[f"node_modules/{name}"]["version"]) >= Version("4.1.12")
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


def test_desktop_lock_retains_pointer_lock_security_patch() -> None:
    desktop = PACKAGE_ROOT / "desktop/electron"
    declaration = json.loads((desktop / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((desktop / "package-lock.json").read_text(encoding="utf-8"))
    version = lock["packages"]["node_modules/electron"]["version"]
    assert declaration["devDependencies"]["electron"] == version
    assert Version(version) >= Version("44.5.0")  # GHSA-x562-297c-g43g


def test_full_npm_locks_retain_october_23_security_patches() -> None:
    frontend = json.loads(FRONTEND_LOCK.read_text(encoding="utf-8"))
    assert Version(frontend["packages"]["node_modules/happy-dom"]["version"]) >= Version("21.0.4")
    declaration = json.loads((PACKAGE_ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    assert declaration["devDependencies"]["happy-dom"] == "^21.0.4"
    desktop = json.loads((PACKAGE_ROOT / "desktop/electron/package-lock.json").read_text(encoding="utf-8"))
    assert Version(desktop["packages"]["node_modules/electron"]["version"]) >= Version("44.9.1")
    undici = [
        Version(item["version"]) for path, item in desktop["packages"].items() if path.endswith("node_modules/undici")
    ]
    assert undici
    assert all(Version("7.30.1") <= version < Version("8") for version in undici)


def test_public_security_workflow_audits_full_frontend_and_desktop_locks() -> None:
    workflow = (PACKAGE_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "--frontend-scope full" in workflow
    command = next(line for line in workflow.splitlines() if "run: python scripts/audit_dependencies.py" in line)
    assert "--skip-desktop" not in command
    assert "--skip-frontend" not in command


def test_hitran_extra_forces_pip_to_upgrade_vulnerable_nbconvert() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["poetry"]
    dependency = project["dependencies"]["nbconvert"]
    assert dependency["optional"] is True  # no notebook stack added to base install
    assert "nbconvert" in project["extras"]["hitran"]
    assert all("nbconvert" not in names for extra, names in project["extras"].items() if extra != "hitran")
    constraint = SpecifierSet(dependency["version"])
    assert Version("7.17.1") not in constraint
    assert Version("7.17.2") in constraint
    assert Version("8.0.0") not in constraint


def test_scp_extra_forces_pip_to_upgrade_vulnerable_setuptools() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["poetry"]
    dependency = project["dependencies"]["setuptools"]
    assert dependency["optional"] is True
    assert "setuptools" in project["extras"]["scp"]
    assert all("setuptools" not in names for extra, names in project["extras"].items() if extra != "scp")
    constraint = SpecifierSet(dependency["version"])
    assert Version("84.0.0") not in constraint
    assert Version("84.1.0") in constraint
    assert Version("85.0.0") not in constraint


def test_pypdf_install_paths_exclude_versions_before_the_reviewed_security_floor() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = SpecifierSet(project["tool"]["poetry"]["dependencies"]["pypdf"])
    requirements = (PACKAGE_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    runtime = next(Requirement(line).specifier for line in requirements if line.startswith("pypdf"))
    for constraint in (declared, runtime):
        assert Version("6.16.2") not in constraint
        assert Version("6.18.1") not in constraint
        assert Version("6.20.1") not in constraint
        assert Version("6.21.0") not in constraint
        assert Version("6.21.1") not in constraint
        assert Version("6.21.2") not in constraint
        assert Version("6.21.3") not in constraint
        assert Version("6.21.4") in constraint
        assert _python_versions()["pypdf"] in constraint
        assert Version("7.0.0") not in constraint


def test_monorepo_security_workflow_blocks_all_extras_and_dev_tool_findings(monorepo_root: Path) -> None:
    workflow = SECURITY_WORKFLOW.read_text(encoding="utf-8")

    assert "--all-extras-mode block" in workflow
    assert "npm audit (frontend full lockfile)" in workflow
    # The full-lockfile gate runs through audit_dependencies.py so that only
    # reviewed, unexpired suppressions in audit-ignore.toml waive a dev-tool
    # advisory; every other dev finding still fails the job.
    assert "--frontend-scope full" in workflow
    assert "npm audit (desktop full lockfile)" in workflow
    assert "Frontend dev-tool audit findings are non-blocking" not in workflow


def test_npm_audit_suppressions_are_reviewed_and_unexpired() -> None:
    from datetime import date

    ignore_file = PACKAGE_ROOT / "scripts/audit-ignore.toml"
    entries = tomllib.loads(ignore_file.read_text(encoding="utf-8")).get("npm-audit", {}).get("ignore", [])
    # An empty list is valid when all previously suppressed dependencies are removed.
    assert isinstance(entries, list), "npm suppressions must be an explicit list, even when empty"
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
    for constraint in (declared, runtime):
        assert Version("2.1.0") not in constraint
        assert _python_versions()["sqlalchemy"] in constraint
        assert Version("2.1.1") in constraint


def test_monorepo_sqlalchemy_install_excludes_malformed_210_metadata(monorepo_root: Path) -> None:
    ci = (monorepo_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert '"sqlalchemy>=2.0.31,<3,!=2.1.0"' in ci


def test_frontend_lock_excludes_braces_and_its_retired_suppression() -> None:
    lock = json.loads(FRONTEND_LOCK.read_text(encoding="utf-8"))
    assert not any(path.split("/")[-1] == "braces" for path in lock["packages"])
    ignore = (PACKAGE_ROOT / "scripts/audit-ignore.toml").read_text(encoding="utf-8")
    assert "GHSA-vfj7-8cjw-p6xm" not in ignore
