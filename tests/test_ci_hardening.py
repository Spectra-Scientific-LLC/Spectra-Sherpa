"""Negative contracts for merge and publication gates; no hosted runs needed."""

import importlib.util
import json
import os
import subprocess
import sys
from functools import partial
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / f"{name}.yml").read_text())


def run_shell(script, env, executable):
    return subprocess.run([executable, "-e", "-c", script], env={**os.environ, **env}, capture_output=True).returncode


def test_public_verdict_covers_all_jobs_and_rejects_missing_failed_skipped(workflow_bash):
    shell = partial(run_shell, executable=workflow_bash)
    jobs = workflow("ci")["jobs"]
    gate = jobs["verdict"]
    assert gate["if"] == "${{ always() }}"
    assert set(gate["needs"]) == set(jobs) - {"verdict"}
    results = {name: {"result": "success"} for name in gate["needs"]}
    script = gate["steps"][0]["run"]
    assert shell(script, {"RESULTS": json.dumps(results)}) == 0
    for name in results:
        for status in ("failure", "cancelled", "skipped", "", "neutral"):
            assert shell(script, {"RESULTS": json.dumps({**results, name: {"result": status}})}) != 0
        assert shell(script, {"RESULTS": json.dumps({k: v for k, v in results.items() if k != name})}) != 0


def test_compat_verdict_requires_proven_scope_and_success(workflow_bash):
    shell = partial(run_shell, executable=workflow_bash)
    doc = workflow("saved-model-compat")
    assert "ready_for_review" in doc[True]["pull_request"]["types"]
    gate = doc["jobs"]["verdict"]
    script = gate["steps"][0]["run"]
    good = {"SCOPE_RESULT": "success", "REQUIRED": "true", "DEFERRED": "false", "COMPAT_RESULT": "success"}
    assert shell(script, good) == 0
    assert shell(script, {**good, "REQUIRED": "false", "COMPAT_RESULT": "skipped"}) == 0
    for key, values in {
        "SCOPE_RESULT": ("failure", "skipped", "cancelled", ""),
        "REQUIRED": ("", "unknown"),
        "DEFERRED": ("true", ""),
        "COMPAT_RESULT": ("skipped", "failure", "cancelled", ""),
    }.items():
        for value in values:
            assert shell(script, {**good, key: value}) != 0


def test_compat_paths_cover_deletion_rename_and_unrelated_files():
    scope = load("ci_compat_scope")
    patterns = json.loads((ROOT / "scripts/saved_model_compat_paths.json").read_text())
    for prefix in ("", "packages/spectra-sherpa/"):
        assert scope.required([prefix + "src/spectra_sherpa/core/model_artifact.py"], patterns, prefix)
        assert scope.required(
            [prefix + "src/spectra_sherpa/core/model_artifact.py", prefix + "renamed.py"], patterns, prefix
        )
        assert scope.required([".github/workflows/saved-model-compat.yml"], patterns, prefix)
        assert not scope.required([prefix + "docs/index.md"], patterns, prefix)
        assert not scope.required([prefix + "frontend/src/main.ts"], patterns, prefix)


def test_scope_reads_current_draft_state_so_a_rerun_clears_a_draft_verdict(monkeypatch):
    scope = load("ci_compat_scope")
    url = "https://api.github.com/repos/owner/project/pulls/1"
    seen = []

    class Response:
        def __init__(self, draft):
            self.body = json.dumps({"draft": draft}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *args):
            return self.body

    def respond(draft):
        def urlopen(request, timeout):
            seen.append((request.full_url, request.get_header("Authorization"), timeout))
            return Response(draft)

        return urlopen

    # The replayed payload still says draft; the PR is ready now.
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(scope.urllib.request, "urlopen", respond(False))
    assert scope.current_draft({"url": url, "draft": True}) is False
    assert seen == [(url, "Bearer token", 30)]
    monkeypatch.setattr(scope.urllib.request, "urlopen", respond(True))
    assert scope.current_draft({"url": url, "draft": False}) is True
    monkeypatch.setattr(scope.urllib.request, "urlopen", respond(None))
    with pytest.raises(ValueError):
        scope.current_draft({"url": url, "draft": False})
    # Without a token or an API URL, fall back to the payload.
    monkeypatch.delenv("GITHUB_TOKEN")
    assert scope.current_draft({"url": url, "draft": True}) is True
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    assert scope.current_draft({"url": "https://example.invalid/pulls/1", "draft": True}) is True


SHA = "a" * 40
REPO = "owner/project"


def record(workflow_name, ident):
    return {
        "id": ident,
        "run_attempt": 1,
        "head_sha": SHA,
        "head_branch": "main",
        "event": "push",
        "path": f".github/workflows/{workflow_name}",
        "status": "completed",
        "conclusion": "success",
        "head_repository": {"full_name": REPO},
    }


def test_release_gate_checks_every_workflow_and_reloads_attempt():
    gate = load("verify_release_ci")
    records = {i: record(name, i) for i, name in enumerate(gate.WORKFLOWS, 1)}
    calls = []

    def get(path):
        calls.append(path)
        if "/workflows/" in path:
            name = path.split("/workflows/")[1].split("/")[0]
            return {"workflow_runs": [r for r in records.values() if r["path"].endswith(name)]}
        return records[int(path.rsplit("/", 1)[1])]

    assert len(gate.verify(REPO, SHA, get)) == 3
    assert len(calls) == 6
    for key, value in (
        ("head_sha", "b" * 40),
        ("head_branch", "feature"),
        ("event", "pull_request"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("conclusion", "cancelled"),
        ("conclusion", "skipped"),
        ("head_repository", {"full_name": "fork/project"}),
        ("path", ".github/workflows/fake.yml"),
    ):
        original = records[1][key]
        records[1][key] = value
        with pytest.raises(ValueError):
            gate.verify(REPO, SHA, get)
        records[1][key] = original
    with pytest.raises(ValueError):
        gate.verify(REPO, SHA, lambda path: {"workflow_runs": []})
    with pytest.raises(OSError):
        gate.verify(REPO, SHA, lambda path: (_ for _ in ()).throw(OSError("API unavailable")))


def test_release_gate_does_not_accept_older_green_run():
    gate = load("verify_release_ci")
    old = record("ci.yml", 1)
    new = {**record("ci.yml", 2), "status": "queued", "conclusion": None}

    def get(path):
        return {"workflow_runs": [old, new]} if "/workflows/" in path else new

    with pytest.raises(ValueError):
        gate.verify(REPO, SHA, get)


def test_release_guard_comes_from_workflow_revision_and_runs_before_build_and_upload():
    jobs = workflow("pypi-release")["jobs"]
    steps = jobs["build"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Preserve protected-main qualification helper") < names.index(
        "Resolve and check out the exact tag ref"
    )
    assert names.index("Require exact-tag public-main qualification") < names.index(
        "Build one wheel and one source distribution"
    )
    assert jobs["build"]["permissions"]["actions"] == "read"
    publish = jobs["publish"]
    assert publish["environment"]["name"] == "pypi"
    assert publish["steps"][-2]["name"] == "Recheck exact-commit CI after approval"
    assert publish["steps"][-1]["name"].startswith("Publish to PyPI")


@pytest.mark.parametrize("prefix", ["", "packages/spectra-sherpa/"])
@pytest.mark.parametrize("change", ["delete", "rename", "unrelated", "draft", "invalid", "missing", "unknown"])
def test_scope_cli_uses_real_git_and_fails_closed(tmp_path, prefix, change):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Local Test")
    git("config", "user.email", "test@example.invalid")
    sensitive = tmp_path / prefix / "src/spectra_sherpa/core/model_artifact.py"
    sensitive.parent.mkdir(parents=True)
    sensitive.write_text("original\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    if change == "delete":
        sensitive.unlink()
    elif change == "rename":
        sensitive.rename(tmp_path / "renamed.py")
    elif change == "unrelated":
        (tmp_path / "README.md").write_text("docs\n")
    else:
        sensitive.write_text("changed\n")
    git("add", "-A")
    git("commit", "-qm", "candidate")
    pr = {"base": {"sha": base}, "head": {"sha": git("rev-parse", "HEAD")}, "draft": change == "draft"}
    if change == "invalid":
        pr["head"]["sha"] = "--help"
    elif change == "unknown":
        pr["head"]["sha"] = "f" * 40
    elif change == "missing":
        del pr["head"]["sha"]
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": pr}))
    output = tmp_path / "output"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci_compat_scope.py"), "--prefix", prefix],
        cwd=tmp_path,
        env={**os.environ, "EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event), "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
    )
    if change in {"invalid", "missing", "unknown"}:
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        needed = change not in {"unrelated", "draft"}
        assert output.read_text() == f"required={str(needed).lower()}\ndeferred={str(change == 'draft').lower()}\n"
