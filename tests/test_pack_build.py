"""Installed source identity is exact and never imports a pack's Python."""

import hashlib
import os

import pytest
from pydantic import ValidationError

from spectra_sherpa.core import pack_build
from spectra_sherpa.core.pack_build import PackBuildError, PackFile, build_sha256, verify_installed_build
from tests.test_pack_manifest import pack


def fixture(root, content=b"raise RuntimeError('must not execute')\n"):
    root.mkdir()
    (root / "__init__.py").write_bytes(content)
    entries = (PackFile(path="__init__.py", sha256=hashlib.sha256(content).hexdigest()),)
    return entries, pack(build_sha256=build_sha256(entries))


def test_verification_reads_exact_bytes_without_executing_them(tmp_path):
    root = tmp_path / "installed"
    files, manifest = fixture(root)
    assert verify_installed_build(root, files, manifest) == manifest.reference
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "generated.pyc").write_bytes(b"transient")
    assert verify_installed_build(root, files, manifest) == manifest.reference


@pytest.mark.parametrize("change", ["changed", "extra", "missing"])
def test_changed_membership_or_bytes_are_refused(tmp_path, change):
    root = tmp_path / "installed"
    files, manifest = fixture(root)
    if change == "changed":
        (root / "__init__.py").write_text("# same public names, different implementation\n")
    elif change == "extra":
        (root / "extra.py").write_text("# undeclared\n")
    else:
        (root / "__init__.py").unlink()
    with pytest.raises(PackBuildError):
        verify_installed_build(root, files, manifest)


def test_symlinked_source_is_refused_even_when_bytes_match(tmp_path):
    root = tmp_path / "installed"
    files, manifest = fixture(root)
    outside = tmp_path / "outside.py"
    (root / "__init__.py").rename(outside)
    try:
        (root / "__init__.py").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this platform")
    with pytest.raises(PackBuildError, match="symlink"):
        verify_installed_build(root, files, manifest)


@pytest.mark.parametrize(
    "name", ["../outside.py", "/absolute.py", "dir//file.py", "./file.py", "a\\b.py", "__pycache__/x.pyc"]
)
def test_inventory_cannot_select_external_or_generated_paths(name):
    with pytest.raises(ValidationError):
        PackFile(path=name, sha256="a" * 64)


def test_duplicate_inventory_and_wrong_build_identity_fail(tmp_path):
    root = tmp_path / "installed"
    files, manifest = fixture(root)
    with pytest.raises(PackBuildError):
        build_sha256((*files, *files))
    with pytest.raises(PackBuildError):
        verify_installed_build(root, files, pack(build_sha256="b" * 64))


def test_file_byte_bound_is_enforced_even_with_matching_hash(tmp_path):
    root = tmp_path / "installed"
    files, manifest = fixture(root, b"x" * (1024 * 1024 + 1))
    with pytest.raises(PackBuildError, match="byte bound"):
        verify_installed_build(root, files, manifest)


def test_inventory_order_does_not_change_build_identity():
    first, second = PackFile(path="a.py", sha256="a" * 64), PackFile(path="b.py", sha256="b" * 64)
    assert build_sha256((first, second)) == build_sha256((second, first))


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO regression")
def test_replacement_with_fifo_is_refused_without_blocking(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    files, manifest = fixture(root)
    original = pack_build._installed_files

    def replace_after_inventory(path):
        result = original(path)
        (path / "__init__.py").unlink()
        os.mkfifo(path / "__init__.py")
        return result

    monkeypatch.setattr(pack_build, "_installed_files", replace_after_inventory)
    with pytest.raises(PackBuildError, match="regular file"):
        verify_installed_build(root, files, manifest)


@pytest.mark.skipif(os.open not in os.supports_dir_fd, reason="POSIX pinned directory regression")
def test_parent_replacement_after_path_resolution_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    root.mkdir()
    source = root / "nested"
    files, _ = fixture(source)
    files = (PackFile(path="nested/__init__.py", sha256=files[0].sha256),)
    manifest = pack(build_sha256=build_sha256(files))
    original = pack_build._read_source

    def replace_before_open(path, relative):
        outside = tmp_path / "outside"
        source.rename(outside)
        source.symlink_to(outside, target_is_directory=True)
        return original(path, relative)

    monkeypatch.setattr(pack_build, "_read_source", replace_before_open)
    with pytest.raises(PackBuildError, match="unavailable"):
        verify_installed_build(root, files, manifest)
