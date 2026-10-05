from __future__ import annotations

import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOL = PACKAGE_ROOT / "scripts" / "qualify_release_artifacts.py"


def _module():
    spec = importlib.util.spec_from_file_location("qualify_release_artifacts", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_distributions(dist: Path, *, version: str = "0.6.0") -> tuple[Path, Path]:
    tool = _module()
    dist.mkdir()
    wheel = dist / f"spectra_sherpa-{version}-py3-none-any.whl"
    sdist = dist / f"spectra_sherpa-{version}.tar.gz"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("spectra_sherpa/__init__.py", "")
        archive.writestr("spectra_sherpa/static/index.html", '<script src="/assets/app.js"></script>')
        archive.writestr("spectra_sherpa/static/assets/app.js", "console.log('qualified');")
        for notice in tool.REQUIRED_NOTICES:
            archive.writestr(f"spectra_sherpa-{version}.dist-info/{notice}", "license")
    with tarfile.open(sdist, "w:gz") as archive:
        files = {
            "spectra_sherpa/__init__.py": b"",
            "src/spectra_sherpa/static/index.html": b'<script src="/assets/app.js"></script>',
            "src/spectra_sherpa/static/assets/app.js": b"console.log('qualified');",
            **{notice: b"license" for notice in tool.REQUIRED_NOTICES},
        }
        for name, payload in files.items():
            info = tarfile.TarInfo(f"spectra_sherpa-{version}/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return wheel, sdist


def test_manifest_binds_exact_wheel_sdist_tag_and_commit(tmp_path: Path) -> None:
    tool = _module()
    dist = tmp_path / "dist"
    _write_distributions(dist)
    manifest = tmp_path / "artifact-manifest.json"

    created = tool.create_manifest(
        dist=dist,
        output=manifest,
        release_tag="spectra-sherpa-v0.6.0",
        source_commit="a" * 40,
    )
    verified = tool.verify_manifest(dist=dist, manifest_path=manifest)

    assert verified == created
    assert created["schema_version"] == "spectra-sherpa-release-artifacts/1"
    assert {record["kind"] for record in created["artifacts"]} == {"wheel", "sdist"}
    assert tool.select_artifact(dist=dist, manifest_path=manifest, kind="wheel").suffix == ".whl"


def test_manifest_refuses_byte_change_and_extra_artifact(tmp_path: Path) -> None:
    tool = _module()
    dist = tmp_path / "dist"
    wheel, _ = _write_distributions(dist)
    manifest = tmp_path / "artifact-manifest.json"
    tool.create_manifest(
        dist=dist,
        output=manifest,
        release_tag="spectra-sherpa-v0.6.0",
        source_commit="b" * 40,
    )

    wheel.write_bytes(wheel.read_bytes() + b"changed")
    with pytest.raises(tool.QualificationError, match="identity differs"):
        tool.verify_manifest(dist=dist, manifest_path=manifest)

    wheel.write_bytes(wheel.read_bytes()[:-7])
    (dist / "unexpected.txt").write_text("not publishable", encoding="utf-8")
    with pytest.raises(tool.QualificationError, match="exactly one wheel and one"):
        tool.verify_manifest(dist=dist, manifest_path=manifest)


def test_archive_validation_refuses_traversal(tmp_path: Path) -> None:
    tool = _module()
    dist = tmp_path / "dist"
    wheel, _ = _write_distributions(dist)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("../escape", "bad")
    with pytest.raises(tool.QualificationError, match="unsafe archive member"):
        tool.create_manifest(
            dist=dist,
            output=tmp_path / "manifest.json",
            release_tag="spectra-sherpa-v0.6.0",
            source_commit="c" * 40,
        )


def test_distribution_set_refuses_ignored_directory_or_link(tmp_path: Path) -> None:
    tool = _module()
    dist = tmp_path / "dist"
    _write_distributions(dist)
    (dist / "unreviewed").mkdir()
    with pytest.raises(tool.QualificationError, match="only two regular"):
        tool.create_manifest(
            dist=dist,
            output=tmp_path / "manifest.json",
            release_tag="spectra-sherpa-v0.6.0",
            source_commit="e" * 40,
        )


def test_archive_validation_refuses_duplicate_member(tmp_path: Path) -> None:
    tool = _module()
    dist = tmp_path / "dist"
    wheel, _ = _write_distributions(dist)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("spectra_sherpa/__init__.py", "duplicate")
    with pytest.raises(tool.QualificationError, match="duplicate member"):
        tool.create_manifest(
            dist=dist,
            output=tmp_path / "manifest.json",
            release_tag="spectra-sherpa-v0.6.0",
            source_commit="f" * 40,
        )


def test_manifest_schema_and_release_identity_are_closed(tmp_path: Path) -> None:
    tool = _module()
    dist = tmp_path / "dist"
    _write_distributions(dist)
    manifest = tmp_path / "artifact-manifest.json"
    tool.create_manifest(
        dist=dist,
        output=manifest,
        release_tag="spectra-sherpa-v0.6.0",
        source_commit="d" * 40,
    )
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["unreviewed"] = True
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(tool.QualificationError, match="closed current schema"):
        tool.verify_manifest(dist=dist, manifest_path=manifest)

    with pytest.raises(tool.QualificationError, match="exact spectra-sherpa"):
        tool.create_manifest(
            dist=dist,
            output=manifest,
            release_tag="main",
            source_commit="d" * 40,
        )


def test_frontend_qualification_binds_clean_build_wheel_and_sdist(tmp_path: Path) -> None:
    tool = _module()
    dist = tmp_path / "dist"
    _write_distributions(dist)
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    (bundle / "assets/app.js").write_text("console.log('qualified');", encoding="utf-8")

    tool.verify_frontend_distributions(dist=dist, bundle=bundle)


def test_frontend_qualification_refuses_archive_drift(tmp_path: Path) -> None:
    tool = _module()
    dist = tmp_path / "dist"
    wheel, _sdist = _write_distributions(dist)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("spectra_sherpa/static/assets/unreviewed.js", "console.log('drift');")

    with pytest.raises(tool.QualificationError, match="frontend bundles differ"):
        tool.verify_frontend_distributions(dist=dist)


def test_frontend_regeneration_comparison_refuses_byte_drift(tmp_path: Path) -> None:
    tool = _module()
    left = tmp_path / "left"
    right = tmp_path / "right"
    for root in (left, right):
        (root / "assets").mkdir(parents=True)
        (root / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
        (root / "assets/app.js").write_text("console.log('same');", encoding="utf-8")

    tool.compare_frontend_directories(left=left, right=right)
    (right / "assets/app.js").write_text("console.log('changed');", encoding="utf-8")
    with pytest.raises(tool.QualificationError, match="frontend bundles differ"):
        tool.compare_frontend_directories(left=left, right=right)


def test_frontend_archive_requires_the_exact_installable_package_path(tmp_path: Path) -> None:
    tool = _module()
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>", encoding="utf-8")
    (bundle / "assets/app.js").write_text("console.log('qualified');", encoding="utf-8")

    wheel = tmp_path / "spectra_sherpa-0.6.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("spectra_sherpa/static/index.html", "<html></html>")
        archive.writestr("spectra_sherpa/static/assets/app.js", "console.log('qualified');")
        archive.writestr("wrong/location/spectra_sherpa/static/index.html", "<html></html>")
        archive.writestr(
            "wrong/location/spectra_sherpa/static/assets/app.js",
            "console.log('qualified');",
        )
    with pytest.raises(tool.QualificationError, match="outside the exact installable path"):
        tool.verify_frontend_archive(artifact=wheel, bundle=bundle)

    sdist = tmp_path / "spectra_sherpa-0.6.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        for name, payload in {
            "spectra_sherpa-0.6.0/src/spectra_sherpa/static/index.html": b"<html></html>",
            "spectra_sherpa-0.6.0/src/spectra_sherpa/static/assets/app.js": b"console.log('qualified');",
            "wrong/location/src/spectra_sherpa/static/index.html": b"<html></html>",
            "wrong/location/src/spectra_sherpa/static/assets/app.js": b"console.log('qualified');",
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    with pytest.raises(tool.QualificationError, match="outside the exact installable path"):
        tool.verify_frontend_archive(artifact=sdist, bundle=bundle)
