"""Dependency audits include test and delivery tools and fail closed on scanner errors."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def audit():
    spec = importlib.util.spec_from_file_location("dependency_audit", PACKAGE_ROOT / "scripts/audit_dependencies.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def npm_tree(tmp_path):
    for path in ("frontend", "desktop/electron"):
        directory = tmp_path / path
        directory.mkdir(parents=True)
        (directory / "package-lock.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _report(advisory=None):
    return json.dumps(
        {
            "auditReportVersion": 2,
            "vulnerabilities": {} if advisory is None else {"tool": {"via": [{"url": advisory}]}},
        }
    )


def test_default_cli_audits_both_complete_locks(audit, npm_tree, monkeypatch):
    calls = []
    # npm's offline mode returns a misleading empty success report. Both this
    # inherited setting and a project's .npmrc must lose to the explicit flag.
    monkeypatch.setenv("NPM_CONFIG_OFFLINE", "true")
    monkeypatch.setattr(sys, "argv", ["audit", "--repo", str(npm_tree), "--skip-python"])
    monkeypatch.setattr(audit, "_require_tool", lambda name: None)

    def run(args, **kwargs):
        calls.append((args, kwargs["cwd"]))
        return subprocess.CompletedProcess(args, 0, _report(), "")

    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.main() == 0
    assert [directory for _, directory in calls] == [npm_tree / "frontend", npm_tree / "desktop/electron"]
    for args, _ in calls:
        assert "--package-lock-only" in args
        assert "--offline=false" in args
        assert "--omit=dev" not in args
        assert "--include=dev" in args
        assert "--include=optional" in args
        assert "--json" in args


@pytest.mark.parametrize("path", ["frontend", "desktop/electron"])
@pytest.mark.parametrize(
    "advisory",
    ["GHSA-834v-8h66-3h79", "GHSA-xjj6-f33q-929c", "GHSA-jr5w-w6x2-84p9"],
)
def test_dev_advisories_block_each_lock(audit, npm_tree, monkeypatch, path, advisory):
    monkeypatch.setattr(audit, "_require_tool", lambda name: None)
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 1, _report(f"https://github.com/advisories/{advisory}"), ""
        ),
    )
    with pytest.raises(SystemExit, match=advisory):
        audit.audit_npm(npm_tree / path, scope="full", ignore_file=npm_tree / "no-waivers.toml")


@pytest.mark.parametrize("path", ["frontend", "desktop/electron"])
def test_missing_lock_fails_instead_of_skipping(audit, tmp_path, monkeypatch, path):
    monkeypatch.setattr(audit, "_require_tool", lambda name: None)
    with pytest.raises(SystemExit, match="required npm audit lockfile missing"):
        audit.audit_npm(tmp_path / path, scope="full", ignore_file=tmp_path / "ignore.toml")


@pytest.mark.parametrize("returncode", [0, 1])
@pytest.mark.parametrize(
    "report",
    ["not json", "[]", "{}", '{"auditReportVersion":2,"vulnerabilities":{},"error":{"code":"E503"}}'],
)
def test_scanner_errors_fail_closed(audit, npm_tree, monkeypatch, report, returncode):
    monkeypatch.setattr(audit, "_require_tool", lambda name: None)
    monkeypatch.setattr(
        audit.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, returncode, report, "")
    )
    with pytest.raises(SystemExit, match="npm audit returned"):
        audit.audit_desktop(npm_tree, ignore_file=npm_tree / "ignore.toml")


def test_runtime_diagnostic_does_not_narrow_desktop(audit, npm_tree, monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["audit", "--repo", str(npm_tree), "--skip-python", "--frontend-scope", "runtime"])
    monkeypatch.setattr(audit, "audit_frontend", lambda repo, **kwargs: calls.append(("frontend", kwargs["scope"])))
    monkeypatch.setattr(audit, "audit_desktop", lambda repo, **kwargs: calls.append(("desktop", "full")))
    assert audit.main() == 0
    assert calls == [("frontend", "runtime"), ("desktop", "full")]


def test_runtime_diagnostic_also_forces_online_audit(audit, npm_tree, monkeypatch):
    calls = []
    monkeypatch.setenv("NPM_CONFIG_OFFLINE", "true")
    monkeypatch.setattr(audit, "_require_tool", lambda name: None)
    monkeypatch.setattr(audit, "_run", lambda args, **kwargs: calls.append(args) or 0)
    audit.audit_frontend(npm_tree, scope="runtime", ignore_file=npm_tree / "ignore.toml")
    assert len(calls) == 1
    assert "--offline=false" in calls[0]


def test_explicit_python_only_mode_skips_both_npm_locks(audit, npm_tree, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["audit", "--repo", str(npm_tree), "--skip-frontend", "--skip-desktop"])
    monkeypatch.setattr(audit, "audit_python", lambda repo, **kwargs: None)
    monkeypatch.setattr(audit, "audit_npm", lambda *args, **kwargs: pytest.fail("explicitly skipped npm audit ran"))
    assert audit.main() == 0


def test_reviewed_waiver_cannot_hide_another_advisory(audit, npm_tree, monkeypatch):
    monkeypatch.setattr(audit, "_require_tool", lambda name: None)
    monkeypatch.setattr(audit, "_load_npm_audit_ignores", lambda path: {"GHSA-834v-8h66-3h79": "test-only waiver"})
    report = json.loads(_report("https://github.com/advisories/GHSA-834v-8h66-3h79"))
    report["vulnerabilities"]["second"] = {"via": [{"url": "https://github.com/advisories/GHSA-xjj6-f33q-929c"}]}
    monkeypatch.setattr(
        audit.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 1, json.dumps(report), "")
    )
    with pytest.raises(SystemExit, match="GHSA-xjj6-f33q-929c"):
        audit.audit_desktop(npm_tree, ignore_file=npm_tree / "ignore.toml")


def test_expired_waiver_fails(audit, npm_tree):
    path = npm_tree / "ignore.toml"
    path.write_text(
        '[[npm-audit.ignore]]\nid="GHSA-834v-8h66-3h79"\nreason="test"\nexpires="2000-01-01"\n', encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="expired"):
        audit._load_npm_audit_ignores(path)


def test_scanner_failure_cannot_be_waived(audit, npm_tree, monkeypatch):
    monkeypatch.setattr(audit, "_require_tool", lambda name: None)
    monkeypatch.setattr(audit, "_load_npm_audit_ignores", lambda path: {"GHSA-834v-8h66-3h79": "test-only waiver"})
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 2, _report("https://github.com/advisories/GHSA-834v-8h66-3h79"), "scanner failed"
        ),
    )
    with pytest.raises(SystemExit, match="incomplete or failed report"):
        audit.audit_desktop(npm_tree, ignore_file=npm_tree / "ignore.toml")
