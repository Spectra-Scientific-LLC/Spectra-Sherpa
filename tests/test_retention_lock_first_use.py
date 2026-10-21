"""First-use lock ordering, including the Windows branch on every platform."""

import errno
import os
import sys
from types import SimpleNamespace

import pytest

from spectra_sherpa.app.services import run_output_retention as retention


@pytest.mark.parametrize("existing_byte", [b"", b"0"])
@pytest.mark.parametrize("body_fails", [False, True])
def test_windows_lock_never_initializes_a_byte_before_ownership(tmp_path, monkeypatch, existing_byte, body_fails):
    lock_path = tmp_path / ".lock"
    lock_path.write_bytes(existing_byte)
    calls = []
    descriptors = []

    def locking(fd, mode, count):
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0
        assert count == 1
        descriptors.append(fd)
        calls.append(mode)

    def competing_writer(fd, value):
        # Deterministic negative control for the observed CI interleaving:
        # a contender saw st_size == 0, then another actor acquired byte zero.
        # Windows denies this write; POSIX normally hides the race.
        raise PermissionError(errno.EACCES, "another actor owns byte zero")

    monkeypatch.setitem(sys.modules, "fcntl", None)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(LK_LOCK=1, LK_UNLCK=2, locking=locking))
    monkeypatch.setattr(retention.os, "write", competing_writer)

    def exercise():
        with retention._storage_lock(tmp_path):
            assert calls == [1]
            if body_fails:
                raise RuntimeError("body failed")

    if body_fails:
        with pytest.raises(RuntimeError, match="body failed"):
            exercise()
    else:
        exercise()
    assert calls == [1, 2]
    assert lock_path.read_bytes() == existing_byte
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
