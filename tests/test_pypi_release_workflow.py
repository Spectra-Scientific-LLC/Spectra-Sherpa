from __future__ import annotations

from pathlib import Path

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
