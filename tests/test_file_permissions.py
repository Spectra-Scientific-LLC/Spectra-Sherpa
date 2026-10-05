"""Descriptor permission behavior on both desktop platforms."""

from types import SimpleNamespace

import pytest

from spectra_sherpa.app.lib import file_permissions


def test_windows_does_not_require_fchmod(monkeypatch):
    monkeypatch.setattr(file_permissions, "os", SimpleNamespace(name="nt"))
    file_permissions.restrict_file_descriptor(42)


def test_posix_restricts_the_open_descriptor(monkeypatch):
    calls = []
    monkeypatch.setattr(file_permissions, "os", SimpleNamespace(name="posix", fchmod=lambda *args: calls.append(args)))
    file_permissions.restrict_file_descriptor(42)
    assert calls == [(42, 0o600)]


def test_posix_permission_failure_is_not_suppressed(monkeypatch):
    def denied(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(file_permissions, "os", SimpleNamespace(name="posix", fchmod=denied))
    with pytest.raises(PermissionError):
        file_permissions.restrict_file_descriptor(42)


def test_collection_storage_roundtrip_and_failed_write_cleanup(monkeypatch, tmp_path):
    from spectra_sherpa.app.services import collection_definitions as storage

    path = tmp_path / "objects" / "collection-definition.json"
    definition = SimpleNamespace(canonical_bytes=b'{"fixture":true}')
    monkeypatch.setattr(storage, "collection_definition_path", lambda _: path)
    monkeypatch.setattr(storage, "validate_collection_definition", lambda _: definition)
    storage.write_collection_definition(1, {})
    assert storage.read_collection_definition(1).canonical_bytes == definition.canonical_bytes

    def denied(_):
        raise PermissionError("permission setup failed")

    monkeypatch.setattr(storage, "restrict_file_descriptor", denied)
    with pytest.raises(PermissionError):
        storage.write_collection_definition(1, {})
    assert list(path.parent.iterdir()) == [path]
    assert path.read_bytes() == definition.canonical_bytes
