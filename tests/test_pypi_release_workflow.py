from __future__ import annotations

import json
import os
import re
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
    assert _platforms(workflow["jobs"]["backend"], "push") == NATIVE_DESKTOP_PLATFORMS
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
    tmp_path: Path, on_main: bool, annotated: bool, crlf_python: bool, workflow_bash: str
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
        [workflow_bash, "-euo", "pipefail", "-c", resolver],
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
def test_qualification_preserves_selected_artifact_path(line_ending: str, workflow_bash: str) -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["qualify"]["steps"]
    script = next(step["run"] for step in steps if "run" in step)
    selection = script.split("mkdir clean-runtime", 1)[0]
    expected = "C:/release candidate/dist/spectra_sherpa-0.6.0-py3-none-any.whl"
    # Model Windows Python stdout without installing a package during this test.
    shell = 'python() { if [[ "$*" == *" select "* ]]; then printf "%s%s" "$SELECTED_PATH" "$LINE_ENDING"; fi; };\n'
    result = subprocess.run(
        [workflow_bash, "-euo", "pipefail", "-c", shell + selection + '\nprintf "%s" "$artifact"'],
        env={**os.environ, "ARTIFACT_KIND": "wheel", "SELECTED_PATH": expected, "LINE_ENDING": line_ending},
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == expected.encode()


def test_protected_helper_survives_product_tag_checkout(tmp_path: Path, workflow_bash: str) -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = document["jobs"]["build"]["steps"]
    capture = next(step for step in steps if step.get("name") == "Preserve protected-main qualification helper")
    resolve = next(step for step in steps if step.get("name") == "Resolve and check out the exact tag ref")
    assert steps.index(capture) < steps.index(resolve)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    helper = scripts / "qualify_release_artifacts.py"
    helper.write_text("protected-main helper\n", encoding="utf-8")
    release_gate = scripts / "verify_release_ci.py"
    release_gate.write_text("protected-main release gate\n", encoding="utf-8")
    temporary = tmp_path / "runner temp"
    temporary.mkdir()
    result = subprocess.run(
        [workflow_bash, "-c", capture["run"]],
        cwd=tmp_path,
        env={**os.environ, "RUNNER_TEMP": temporary.as_posix(), "GITHUB_SHA": "a" * 40},
        text=True,
        capture_output=True,
        check=True,
    )
    helper.write_text("older-tag helper\n", encoding="utf-8")
    assert (temporary / helper.name).read_text() == "protected-main helper\n"
    release_gate.write_text("older-tag release gate\n", encoding="utf-8")
    assert (temporary / release_gate.name).read_text() == "protected-main release gate\n"
    assert "a" * 40 in result.stdout
    build = next(step["run"] for step in steps if step.get("name") == "Build one wheel and one source distribution")
    assert 'python "$RUNNER_TEMP/qualify_release_artifacts.py" create-manifest' in build
    assert 'cp "$RUNNER_TEMP/qualify_release_artifacts.py" release/' in build


# Desktop applications ship for these platforms from the public repository,
# so public CI qualifies all three on push to main, weekly and on manual
# dispatch; pull requests run on Ubuntu (docs/dev/dual-repo-ci-policy.md).
NATIVE_DESKTOP_PLATFORMS = {"ubuntu-latest", "windows-latest", "macos-latest"}
PR_PLATFORMS = {"ubuntu-latest"}
_PLATFORM_EXPRESSION = re.compile(
    r"^\$\{\{ fromJSON\(github\.event_name == 'pull_request' && '(?P<pr>\[[^']*\])' \|\| '(?P<other>\[[^']*\])'\) \}\}$"
)


def _platforms(job: dict, event: str) -> set[str]:
    """Resolve a job's OS matrix for one trigger, as GitHub evaluates it."""
    match = _PLATFORM_EXPRESSION.match(job["strategy"]["matrix"]["os"])
    assert match, "OS matrix must choose its platforms from the trigger"
    return set(json.loads(match["pr" if event == "pull_request" else "other"]))


def _public_ci() -> dict:
    import yaml

    root = Path(__file__).resolve().parents[1]
    return yaml.safe_load((root / ".github/workflows/ci.yml").read_text())


def test_public_ci_runs_prs_on_ubuntu_and_qualifies_every_platform_on_main_and_weekly() -> None:
    workflow = _public_ci()
    triggers = workflow[True]  # YAML 1.1 reads the bare key ``on`` as True.
    assert {"push", "pull_request", "schedule", "workflow_dispatch"} <= set(triggers)
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["schedule"]
    for name in ("backend", "desktop-shell"):
        job = workflow["jobs"][name]
        assert _platforms(job, "pull_request") == PR_PLATFORMS
        for event in ("push", "schedule", "workflow_dispatch"):
            assert _platforms(job, event) == NATIVE_DESKTOP_PLATFORMS
    shell = workflow["jobs"]["desktop-shell"]
    assert shell["env"]["ELECTRON_SKIP_BINARY_DOWNLOAD"] == "1"
    assert any(step.get("run") == "npm test" for step in shell["steps"])


def test_saved_model_compat_runs_on_sensitive_prs_main_and_weekly() -> None:
    import yaml

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/saved-model-compat.yml").read_text())
    triggers = workflow[True]
    import json

    assert "paths" not in triggers["pull_request"]
    paths = json.loads((root / "scripts/saved_model_compat_paths.json").read_text())
    for sensitive in (
        "src/spectra_sherpa/app/lib/fitted_state.py",
        "src/spectra_sherpa/app/services/model_application.py",
        "src/spectra_sherpa/app/services/dag/fitted_input_identity.py",
        "src/spectra_sherpa/alembic/**",
        "scripts/saved_model_upgrade_baseline.json",
    ):
        assert sensitive in paths
    assert "paths" not in (triggers["push"] or {})
    assert {"schedule", "workflow_dispatch"} <= set(triggers)
    steps = workflow["jobs"]["compat"]["steps"]
    assert any("scripts/run_saved_model_compat.sh" in step.get("run", "") for step in steps)
    assert "upgrade-check" not in _public_ci()["jobs"]

    import re

    def triggers(candidate: str) -> bool:
        for pattern in paths:
            regex = "".join(
                ".*" if token == "**" else "[^/]*" if token == "*" else re.escape(token)
                for token in re.findall(r"\*\*|\*|[^*]+", pattern)
            )
            if re.fullmatch(regex, candidate):
                return True
        return False

    # Changes to these alter contract digests, serialization or persisted
    # artifacts, so they must start the PR-time check.
    for sensitive in (
        "src/spectra_sherpa/app/services/dag/stable_execution_contract.py",
        "src/spectra_sherpa/execution_contract_vocabulary.py",
        "src/spectra_sherpa/app/services/dag/serialize.py",
        "src/spectra_sherpa/sdk/canonical_fitted_artifact.py",
        "src/spectra_sherpa/app/models/model_artifact.py",
        "src/spectra_sherpa/app/services/dag/nodes/classification/plsda_state.py",
    ):
        assert (root / sensitive).exists(), sensitive
        assert triggers(sensitive), sensitive
    assert not triggers("frontend/src/main.ts")

    runner = (root / "scripts/run_saved_model_compat.sh").read_text()
    assert "saved_model_upgrade_baseline.json" in runner
    assert "--mode round-trip" in runner
