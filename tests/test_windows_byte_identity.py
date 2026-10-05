"""Byte custody must not inherit Windows CRT text translation."""

from types import SimpleNamespace

import pytest

from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.types import ParserLimits


@pytest.mark.parametrize("reader", ["source", "model", "sdk"])
def test_project_readers_preserve_crlf_and_ctrl_z(tmp_path, reader):
    from spectra_sherpa.app.api.v1.routes.projects import (
        _read_bounded_regular_model_member,
        _read_bounded_regular_source,
    )
    from spectra_sherpa.sdk.project import read_bounded_regular_file

    payload = b"header\r\n\x00\x1aafter-eof\r\n"
    path = tmp_path / "native.bin"
    path.write_bytes(payload)
    if reader == "source":
        actual = _read_bounded_regular_source(path, expected_size=len(payload))
    elif reader == "model":
        actual = _read_bounded_regular_model_member(path, max_bytes=len(payload))
    else:
        actual = read_bounded_regular_file(path, max_bytes=len(payload), label="fixture")
    assert actual == payload


def test_windows_snapshot_identity_does_not_compare_incompatible_ctime(monkeypatch):
    from spectra_sherpa.io import base

    monkeypatch.setattr(base, "os", SimpleNamespace(name="nt"))
    first = dict(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_ctime_ns=5)
    assert BoundedSource._identity(SimpleNamespace(**first)) == BoundedSource._identity(
        SimpleNamespace(**{**first, "st_ctime_ns": 99})
    )
    for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns"):
        assert BoundedSource._identity(SimpleNamespace(**first)) != BoundedSource._identity(
            SimpleNamespace(**{**first, field: 99})
        )


def test_snapshot_still_rejects_changed_bytes(tmp_path):
    from spectra_sherpa.ingestion_errors import UnreadableSpectrumError

    path = tmp_path / "source.bin"
    path.write_bytes(b"before")
    with BoundedSource(path, limits=ParserLimits()) as source:
        path.write_bytes(b"after!")
        with pytest.raises(UnreadableSpectrumError, match="source bytes changed"):
            source.verify_unchanged()


def test_posix_snapshot_identity_keeps_metadata_change_check(monkeypatch):
    from spectra_sherpa.io import base

    monkeypatch.setattr(base, "os", SimpleNamespace(name="posix"))
    first = dict(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_ctime_ns=5)
    assert BoundedSource._identity(SimpleNamespace(**first)) != BoundedSource._identity(
        SimpleNamespace(**{**first, "st_ctime_ns": 99})
    )
