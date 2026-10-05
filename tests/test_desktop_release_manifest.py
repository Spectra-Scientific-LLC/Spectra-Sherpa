"""Publication refuses wrong bytes, wrong source or incomplete target sets."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("desktop_release_manifest", PACKAGE / "desktop/release_manifest.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
TAG = "spectra-sherpa-v0.6.0"
SHA = "a" * 40


def dependency_fixture():
    return {
        "schema_version": 1,
        "build_environment": {
            "scope": "resolved_build_environment_not_bundle_inventory",
            "distributions": {"numpy": "2.2.6", "scikit-learn": "1.7.2"},
        },
        "scientific_runtime": {
            "scope": "canonical_profile_runtime_attestation",
            "profile_id": "synthetic-profile",
            "profile_digest": "b" * 64,
            "distributions": {"numpy": "2.2.6", "scikit-learn": "1.7.2"},
        },
    }


def fixtures(root):
    for target, (_, _, _, ext) in release.TARGETS.items():
        directory = root / target
        directory.mkdir()
        asset = directory / f"SpectraSherpa-0.6.0-{target}{ext}"
        asset.write_bytes(target.encode())
        (directory / f"{target}.manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "shell": "electron",
                    "electron_version": json.loads((PACKAGE / "desktop/electron/package.json").read_text())[
                        "devDependencies"
                    ]["electron"],
                    "python_version": "3.11.9",
                    "dependency_provenance": dependency_fixture(),
                    "target": target,
                    "version": "0.6.0",
                    "tag": TAG,
                    "source_commit": SHA,
                    "asset": asset.name,
                    "size": asset.stat().st_size,
                    "sha256": release.digest(asset),
                }
            )
        )


def test_complete_set_publishes_only_assets_checksums_and_combined_manifest(tmp_path):
    fixtures(tmp_path)
    result = release.validate(tmp_path, TAG, SHA)
    assert len(result) == len(release.TARGETS) + 2
    assert len((tmp_path / "SHA256SUMS").read_text().splitlines()) == len(release.TARGETS)
    assert len(json.loads((tmp_path / "desktop-manifest.json").read_text())) == len(release.TARGETS)


@pytest.mark.parametrize(
    "defect", ["missing", "duplicate", "bytes", "commit", "traversal", "extra", "browser", "runtime"]
)
def test_publication_refuses_inconsistent_candidates(tmp_path, defect):
    fixtures(tmp_path)
    receipt = next(tmp_path.rglob("*.manifest.json"))
    record = json.loads(receipt.read_text())
    asset = receipt.parent / record["asset"]
    if defect == "missing":
        receipt.unlink()
    elif defect == "duplicate":
        (receipt.parent / "copy.manifest.json").write_text(receipt.read_text())
    elif defect == "bytes":
        asset.write_bytes(b"changed")
    elif defect == "commit":
        record["source_commit"] = "b" * 40
        receipt.write_text(json.dumps(record))
    elif defect == "runtime":
        record["electron_version"] = "1.0.0"
        receipt.write_text(json.dumps(record))
    elif defect == "browser":
        record["shell"] = "browser"
        receipt.write_text(json.dumps(record))
    elif defect == "traversal":
        record["asset"] = "../../secret"
        receipt.write_text(json.dumps(record))
    else:
        (tmp_path / "credential.p12").write_text("synthetic forbidden extra")
    with pytest.raises(ValueError):
        release.validate(tmp_path, TAG, SHA)


def test_release_lane_uses_complete_native_matrix_and_stages_draft_until_acceptance():
    text = (PACKAGE / ".github/workflows/desktop-release.yml").read_text()
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    targets = {row["target"] for row in workflow["jobs"]["build"]["strategy"]["matrix"]["include"]}
    assert targets | {"ubuntu-x86_64"} == set(release.TARGETS)
    assert "--clobber" not in text
    assert 'if [ "$SOURCE_COMMIT" != "$GITHUB_SHA" ]' in text
    assert text.index("release_manifest.py validate") < text.index('gh release create "$TAG" --draft')
    assert "--draft=false" not in text
    assert "clean-machine signed acceptance" in text
    assert "github.event_name == 'push'" in workflow["jobs"]["upload"]["if"]
    upload_steps = workflow["jobs"]["upload"]["steps"]
    setup = next(step for step in upload_steps if step.get("uses", "").startswith("actions/setup-python@"))
    assert setup["with"]["python-version"] == "3.11.9"


def test_macos_source_crypto_uses_static_openssl_in_both_build_lanes():
    paths = [PACKAGE / ".github/workflows/desktop-release.yml"]
    monorepo_lane = PACKAGE.parent.parent / ".github/workflows/desktop-bundle.yml"
    if monorepo_lane.exists():
        paths.append(monorepo_lane)
    for path in paths:
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        steps = workflow["jobs"].get("build", workflow["jobs"].get("bundle-smoke"))["steps"]
        linkage = next(step for step in steps if step.get("name") == "Configure isolated macOS cryptography linkage")
        install = next(step for step in steps if step.get("name") == "Install local bundle build dependencies")
        assert steps.index(linkage) < steps.index(install)
        assert linkage["if"] == "runner.os == 'macOS'"
        assert "OPENSSL_STATIC=1" in linkage["run"]
        assert "brew --prefix openssl@3" in linkage["run"]
        assert "PIP_NO_CACHE_DIR=1" in linkage["run"]


def test_native_release_qualifies_before_hardening_and_signs_installed_shell():
    workflow = yaml.load((PACKAGE / ".github/workflows/desktop-release.yml").read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["build"]["steps"]
    named = {step.get("name"): step for step in steps}
    package = named["Package and qualify native application"]
    script = package["run"]
    assert script.index("run smoke:lifecycle") < script.index('harden.cjs "$FUSE_TARGET"')
    assert script.index('harden.cjs "$FUSE_TARGET" --verify') < script.index("hardened-smoke.cjs")
    assert steps.index(package) < steps.index(named["Sign Executable (Windows)"])
    assert steps.index(package) < steps.index(named["Codesign and Notarize (macOS)"])
    assert "Sign-DesktopNativeExecutables" in named["Sign Executable (Windows)"]["run"]
    assert "-NativeShell -Signed" in named["Package Windows Installer"]["run"]
    assert "--native-shell" in named["Codesign and Notarize (macOS)"]["run"]
    assert "verify_windows_identity.ps1" in named["Verify Windows Installer"]["run"]
    assert "hardened-smoke.cjs" in named["Verify Windows Installer"]["run"]
    assert "/Volumes/SpectraSherpa/SpectraSherpa.app" in named["Verify macOS Installer"]["run"]
    assert "SPECTRA_DESKTOP_NATIVE_BACKEND" in named["Build initial unsigned bundle"]["env"]


def test_windows_identity_receipt_is_inside_retained_signing_evidence():
    workflow = yaml.load((PACKAGE / ".github/workflows/desktop-release.yml").read_text(), Loader=yaml.BaseLoader)
    named = {step.get("name"): step for step in workflow["jobs"]["build"]["steps"]}
    retained = named["Retain signing evidence"]["with"]["path"]
    assert retained == "desktop/signing-evidence/"
    assert f"Set-Content {retained}native-install-identity.json" in named["Verify Windows Installer"]["run"]


@pytest.mark.parametrize("defect", ["missing", "scope", "version", "empty", "identity"])
def test_publication_refuses_unsubstantiated_dependency_evidence(tmp_path, defect):
    fixtures(tmp_path)
    receipt = next(tmp_path.rglob("*.manifest.json"))
    record = json.loads(receipt.read_text())
    evidence = record["dependency_provenance"]
    if defect == "missing":
        del record["dependency_provenance"]
    elif defect == "scope":
        evidence["build_environment"]["scope"] = "exact_bundle_inventory"
    elif defect == "version":
        evidence["scientific_runtime"]["distributions"]["numpy"] = "0.0.1"
    elif defect == "empty":
        evidence["build_environment"]["distributions"] = {}
    else:
        evidence["scientific_runtime"]["profile_digest"] = "unknown"
    receipt.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        release.validate(tmp_path, TAG, SHA)


def test_dependency_inventory_records_resolved_versions_without_claiming_bundle_contents(monkeypatch):
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location(
        "runtime_provenance", PACKAGE / "desktop/verify_runtime_attestation.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    distributions = [SimpleNamespace(metadata={"Name": "scikit_learn"}, version="1.7.2")]
    monkeypatch.setattr(runtime.importlib.metadata, "distributions", lambda: distributions)
    attestation = SimpleNamespace(
        profile_id="synthetic-profile",
        profile_digest="b" * 64,
        distributions=[SimpleNamespace(distribution="scikit-learn", version="1.7.2")],
    )
    evidence = runtime.dependency_provenance(attestation)
    release.validate_dependency_provenance(evidence)
    assert evidence["build_environment"]["distributions"] == {"scikit-learn": "1.7.2"}
    distributions.append(SimpleNamespace(metadata={"Name": "scikit-learn"}, version="1.6.0"))
    with pytest.raises(RuntimeError, match="Ambiguous"):
        runtime.dependency_provenance(attestation)


def test_release_retains_attested_inventory_in_bundled_provenance():
    text = (PACKAGE / ".github/workflows/desktop-release.yml").read_text()
    assert "verify_runtime_attestation.py --output desktop/runtime-provenance.json" in text
    assert '"dependency_provenance": json.loads(Path("desktop/runtime-provenance.json").read_text' in text
