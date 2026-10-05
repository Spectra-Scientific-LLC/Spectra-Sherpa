"""Actual byte and handle behavior, exercised on every supported OS."""

import os
import socket

import pytest

from spectra_sherpa.core.file_io import open_regular_readonly


def test_snapshot_preserves_crlf_and_control_z_and_survives_leaf_rename(tmp_path):
    source = tmp_path / "source.json"
    payload = b'{"line":"value"}\r\n\x1aexact bytes\r\n'
    source.write_bytes(payload)
    descriptor = open_regular_readonly(source)
    try:
        source.rename(tmp_path / "original.json")
        source.write_bytes(b"replacement")
        assert os.read(descriptor, 1000) == payload
    finally:
        os.close(descriptor)


def test_snapshot_refuses_link_and_directory(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"must not read")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        open_regular_readonly(link)
    with pytest.raises(OSError):
        open_regular_readonly(tmp_path)


def test_offline_guard_allows_socketpair_but_denies_application_connections(deny_inference_network):
    left, right = socket.socketpair()
    try:
        left.sendall(b"wake")
        assert right.recv(4) == b"wake"
    finally:
        left.close()
        right.close()
    for method in ("connect", "connect_ex"):
        with socket.socket() as client:
            with pytest.raises(AssertionError, match="Offline inference"):
                getattr(client, method)(("127.0.0.1", 1))
            with pytest.raises(AssertionError, match="Offline inference"):
                getattr(client, method)(("192.0.2.1", 443))
