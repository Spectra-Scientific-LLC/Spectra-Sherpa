from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pypi-release.yml"


def _section(source: str, start: str, end: str | None = None) -> str:
    value = source.split(start, 1)[1]
    return value if end is None else value.split(end, 1)[0]


def test_pypi_build_resolves_an_exact_tag_and_has_no_oidc_authority() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    build = _section(source, "  build:\n", "  qualify:\n")

    assert '"refs/tags/${RELEASE_TAG}:refs/tags/${RELEASE_TAG}"' in build
    assert "DISPATCH_REF: ${{ github.ref }}" in build
    assert '"$DISPATCH_REF" != "refs/heads/main"' in build
    assert 'git rev-parse "refs/tags/${RELEASE_TAG}^{commit}"' in build
    assert "git merge-base --is-ancestor" in build
    assert "fetch-depth: 0" in build
    assert "persist-credentials: false" in build
    assert "id-token: write" not in build
    assert '"build==1.4.4"' in build
    assert '"twine==6.2.0"' in build
    assert 'node-version: "22"' in build
    assert "npm ci" in build
    assert "npm run build" in build
    assert build.index("npm run build") < build.index("python -m build")


def test_exact_artifact_id_crosses_all_supported_qualification_rows() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    qualify = _section(source, "  qualify:\n", "  publish:\n")

    assert "artifact-ids: ${{ needs.build.outputs.artifact_id }}" in qualify
    assert "merge-multiple: true" in qualify
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in qualify
    assert 'python: ["3.11", "3.12"]' in qualify
    assert "kind: [wheel, sdist]" in qualify
    assert "verify-manifest" in qualify
    assert "pip check" in qualify
    assert "--no-index" in qualify
    assert "--no-deps" in qualify
    assert "--no-build-isolation" in qualify
    assert "--no-cache-dir" in qualify
    assert "pip uninstall --yes spectra-sherpa" in qualify
    assert "spectra-sherpa --help" in qualify
    assert " smoke " in qualify.replace("\n", " ")


def test_oidc_publish_job_cannot_build_and_fails_loudly_on_duplicates() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    publish = _section(source, "  publish:\n")

    assert "needs: [build, qualify]" in publish
    assert "name: pypi" in publish
    assert "id-token: write" in publish
    assert "git ls-remote" in publish
    assert '"$current" != "$EXPECTED_COMMIT"' in publish
    assert "artifact-ids: ${{ needs.build.outputs.artifact_id }}" in publish
    assert "merge-multiple: true" in publish
    assert "actions/checkout" not in publish
    assert "python -m build" not in publish
    assert "pip install" not in publish
    assert "skip-existing" not in publish
    assert "attestations: true" in publish
    assert "print-hash: true" in publish


def test_release_workflow_serializes_each_tag_and_keeps_default_permissions_read_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "group: pypi-release-${{ inputs.tag }}" in source
    assert "cancel-in-progress: false" in source
    before_jobs = source.split("jobs:\n", 1)[0]
    assert "permissions:\n  contents: read" in before_jobs


def test_public_ci_install_profiles_exist_in_package_metadata() -> None:
    import tomllib

    import yaml

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    extras = metadata["tool"]["poetry"]["extras"]
    profiles = [
        profile
        for job in workflow["jobs"].values()
        for profile in job.get("strategy", {}).get("matrix", {}).get("install_profile", [])
    ]
    assert profiles
    assert set(profiles) == {"base", "postgres"}
    assert all(profile == "base" or profile in extras for profile in profiles)


@pytest.mark.parametrize("on_main", [True, False])
@pytest.mark.parametrize("annotated", [True, False])
@pytest.mark.parametrize("crlf_python", [True, False])
def test_release_resolver_checks_real_tag_ancestry(
    tmp_path: Path, on_main: bool, annotated: bool, crlf_python: bool
) -> None:
    """Exercise the workflow shell against a release older than the checkout."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["build"]["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    resolver = next(step for step in steps if step.get("id") == "release")["run"]
    if crlf_python:
        resolver = 'python() { printf "0.6.0\\r\\n"; };\n' + resolver

    def git(root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "--initial-branch=main")
    git(origin, "config", "user.name", "Release test")
    git(origin, "config", "user.email", "release@example.invalid")
    (origin / "pyproject.toml").write_text('[tool.poetry]\nversion = "0.6.0"\n', encoding="utf-8")
    git(origin, "add", "pyproject.toml")
    git(origin, "commit", "-m", "Initial source")
    if not on_main:
        git(origin, "switch", "-c", "unmerged")
        (origin / "unmerged.txt").write_text("Not on main\n", encoding="utf-8")
        git(origin, "add", "unmerged.txt")
        git(origin, "commit", "-m", "Unmerged release source")
    release_commit = git(origin, "rev-parse", "HEAD")
    tag = "spectra-sherpa-v0.6.0"
    git(origin, "tag", *(["-a", "-m", "Release"] if annotated else []), tag)
    git(origin, "switch", "main")
    (origin / "later.txt").write_text("Post-release maintenance\n", encoding="utf-8")
    git(origin, "add", "later.txt")
    git(origin, "commit", "-m", "Main advances after release")

    clone = tmp_path / "checkout"
    depth = checkout["with"]["fetch-depth"]
    clone_args = ["clone", "--no-tags", "--branch", "main"]
    if depth:
        clone_args.extend(["--depth", str(depth)])
    git(tmp_path, *clone_args, origin.as_uri(), str(clone))
    output = tmp_path / "outputs"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", resolver],
        cwd=clone,
        env={**os.environ, "RELEASE_TAG": tag, "GITHUB_OUTPUT": output.as_posix()},
        capture_output=True,
        text=True,
    )
    if on_main:
        assert result.returncode == 0, result.stdout + result.stderr
        assert git(clone, "rev-parse", "HEAD") == release_commit
        assert output.read_text().splitlines() == [f"source_commit={release_commit}", "version=0.6.0"]
    else:
        assert result.returncode != 0
        assert "Release tag must be an ancestor" in result.stdout
        assert not output.exists()


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_qualification_preserves_selected_artifact_path(line_ending: str) -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["qualify"]["steps"]
    script = next(step["run"] for step in steps if "run" in step)
    selection = script.split("mkdir clean-runtime", 1)[0]
    expected = "C:/release candidate/dist/spectra_sherpa-0.6.0-py3-none-any.whl"
    # Model Windows Python stdout without installing a package during this test.
    shell = 'python() { if [[ "$*" == *" select "* ]]; then printf "%s%s" "$SELECTED_PATH" "$LINE_ENDING"; fi; };\n'
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", shell + selection + '\nprintf "%s" "$artifact"'],
        env={**os.environ, "ARTIFACT_KIND": "wheel", "SELECTED_PATH": expected, "LINE_ENDING": line_ending},
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == expected.encode()
