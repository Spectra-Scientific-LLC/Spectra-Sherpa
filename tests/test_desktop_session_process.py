"""Launch the actual OSS application over its native-parent pipe contract."""

from __future__ import annotations

import json
import os
import queue
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

import spectra_sherpa
from tests.process_helpers import ReadinessLine, finish_pipe_reader, reap_children


@pytest.mark.parametrize("stop_mode", ["eof", "shutdown", "startup_failure"])
def test_real_desktop_readiness_authorization_and_shutdown(tmp_path, stop_mode):
    urlopen = build_opener(ProxyHandler({})).open
    profile = tmp_path / "profile"
    profile.mkdir()
    if stop_mode == "startup_failure":
        (profile / "spectra_platform.db").write_bytes(b"invalid database fixture")
    env = os.environ.copy()
    source = str(Path(spectra_sherpa.__file__).resolve().parent.parent)
    extra = [str(Path(item).resolve()) for item in env.get("PYTHONPATH", "").split(os.pathsep) if item]
    env["PYTHONPATH"] = os.pathsep.join([source, *extra])
    # A desktop session must bind its own profile even with a hostile/stale shell setting.
    env["DATABASE_URL"] = "sqlite+aiosqlite:///must-not-open-shell-database.db"
    secret = secrets.token_urlsafe(32)
    frames = queue.Queue()
    with (tmp_path / "startup.log").open("w") as log:
        child = subprocess.Popen(
            [sys.executable, "-m", "spectra_sherpa.desktop_launcher", "--desktop-ipc", "--data-dir", str(profile)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
            env=env,
            cwd=tmp_path,
        )
        assert child.stdin is not None and child.stdout is not None

        def read_frames():
            try:
                for line in child.stdout:
                    frames.put(line)
            finally:
                child.stdout.close()  # Reader owns the buffer until it stops.
                frames.put(None)

        reader = threading.Thread(target=read_frames, daemon=True)
        reader.start()
        try:
            child.stdin.write(json.dumps({"protocol": 1, "type": "launch", "secret": secret}) + "\n")
            child.stdin.flush()
            received = []
            for _ in range(5):
                line = frames.get(timeout=60)
                assert line is not None, "Backend exited before reporting readiness/failure"
                assert secret not in line
                frame = json.loads(line)
                received.append(frame)
                if frame["type"] in ("ready", "error"):
                    break
            assert received[0]["type"] == "starting"
            if stop_mode == "startup_failure":
                assert frame["type"] == "error"
                assert not any(item["type"] == "ready" for item in received)
                child.wait(timeout=20)
                assert child.returncode != 0
                return
            assert frame["type"] == "ready"
            endpoint = frame["endpoint"] + "/api/health"
            with pytest.raises(HTTPError) as denied:
                urlopen(endpoint, timeout=5)
            assert denied.value.code == 403
            with urlopen(Request(endpoint, headers={"X-Spectra-Desktop-Token": secret}), timeout=5) as response:
                assert response.status == 200
            with pytest.raises(HTTPError) as denied_origin:
                urlopen(
                    Request(
                        endpoint, headers={"X-Spectra-Desktop-Token": secret, "Origin": "https://unrelated.example"}
                    ),
                    timeout=5,
                )
            assert denied_origin.value.code == 403
            websocket_url = frame["endpoint"].replace("http://", "ws://") + "/ws"
            with pytest.raises(InvalidStatus) as denied_socket:
                connect(websocket_url, proxy=None, open_timeout=5)
            assert denied_socket.value.response.status_code == 403
            with connect(
                websocket_url,
                proxy=None,
                origin=frame["endpoint"],
                additional_headers={"X-Spectra-Desktop-Token": secret},
                open_timeout=5,
            ) as socket:
                assert socket.ping().wait(timeout=5)
            assert not (tmp_path / "must-not-open-shell-database.db").exists()
            if stop_mode == "shutdown":
                child.stdin.write('{"protocol":1,"type":"shutdown"}\n')
                child.stdin.flush()
            else:
                child.stdin.close()
            child.wait(timeout=20)
            assert child.returncode == 0
            assert not (profile / ".spectrasherpa-desktop.lock").exists()
        finally:
            if not child.stdin.closed:
                child.stdin.close()
            try:
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()  # Only the Popen child created by this test.
                    child.wait(timeout=10)
                    raise
            finally:
                finish_pipe_reader(reader, child.stdout)
    assert secret not in (tmp_path / "startup.log").read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows process-tree qualification runs in the native bundle lane")
def test_forced_native_parent_exit_stops_backend(tmp_path):
    """Abruptly exit a real parent; the backend must detect closed private pipes."""
    import signal
    import time

    from spectra_sherpa.desktop_launcher import DesktopInstanceLock

    env = os.environ.copy()
    source = str(Path(spectra_sherpa.__file__).resolve().parent.parent)
    extra = [str(Path(item).resolve()) for item in env.get("PYTHONPATH", "").split(os.pathsep) if item]
    env["PYTHONPATH"] = os.pathsep.join([source, *extra])
    parent_script = r"""
import json, os, pathlib, secrets, subprocess, sys
root = pathlib.Path(sys.argv[1])
with (root / "backend.log").open("w") as log:
    child = subprocess.Popen(
        [sys.executable, "-m", "spectra_sherpa.desktop_launcher", "--desktop-ipc",
         "--data-dir", str(root / "profile")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True,
    )
    child.stdin.write(json.dumps({"protocol":1,"type":"launch","secret":secrets.token_urlsafe(32)}) + "\n")
    child.stdin.flush()
    for line in child.stdout:
        frame = json.loads(line)
        if frame["type"] == "ready":
            (root / "child.json").write_text(json.dumps({"pid": child.pid, "endpoint": frame["endpoint"]}))
            os._exit(7)
        if frame["type"] == "error":
            sys.exit(2)
    sys.exit(3)
"""
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_script, str(tmp_path)], env=env, cwd=tmp_path, start_new_session=True
    )
    try:
        assert parent.wait(timeout=60) == 7
        child = json.loads((tmp_path / "child.json").read_text())
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            alive = DesktopInstanceLock._pid_is_running(child["pid"])
            # Linux CI's init may delay reaping an already exited orphan.
            status = Path(f"/proc/{child['pid']}/stat")
            if alive and sys.platform.startswith("linux") and status.exists():
                try:
                    alive = status.read_text().rsplit(")", 1)[1].split()[0] != "Z"
                except FileNotFoundError:
                    alive = False
            if not alive:
                break
            time.sleep(0.05)
        else:
            pytest.fail("Backend remained alive after its native parent exited")
        assert not (tmp_path / "profile" / ".spectrasherpa-desktop.lock").exists()
    finally:
        # This test created this isolated process group; no PID discovery or
        # listener-based cleanup is used. It cannot signal another app's group.
        try:
            os.killpg(parent.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        parent.wait(timeout=10)


def test_parent_exit_during_blocked_profile_initialization(tmp_path):
    # Exercise the launcher ordering: resolution is deliberately stuck before
    # the CLI or application is imported, and the parent closes its private pipe.
    script = """
import sys, time
from spectra_sherpa import desktop_launcher
original = desktop_launcher._resolve_data_dir
def blocked(args):
    sys.stderr.write('initialization-blocked\\n')
    sys.stderr.flush()
    time.sleep(60)
    return original(args)
desktop_launcher._resolve_data_dir = blocked
desktop_launcher.main(['--desktop-ipc'])
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    starting = ReadinessLine(child.stdout)
    blocked = ReadinessLine(child.stderr)
    try:
        child.stdin.write(json.dumps({"protocol": 1, "type": "launch", "secret": secrets.token_urlsafe(32)}) + "\n")
        child.stdin.flush()
        assert json.loads(starting.result(timeout=20))["type"] == "starting"
        assert blocked.result(timeout=20).strip() == "initialization-blocked"
        child.stdin.close()
        assert child.wait(timeout=20) == 1
    finally:
        # Avoid Popen.__exit__: it closes buffered pipes before waiting, which
        # can block behind a readiness reader if startup never produced a line.
        try:
            reap_children([child])
        finally:
            child.stdin.close()
            try:
                starting.finish()
            finally:
                blocked.finish()


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_readiness_without_newline_times_out_and_owned_child_is_reaped(channel):
    # The child has its own finite escape hatch, so a broken reader cannot
    # turn this failure-path regression into an indefinitely hung test.
    script = (
        "import sys,time; print('ready',flush=True); "
        f"sys.{channel}.write('partial'); sys.{channel}.flush(); time.sleep(5)"
    )
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ready = ReadinessLine(child.stdout)
    pending = None
    try:
        assert ready.result(timeout=5) == b"ready\n"
        pending = ReadinessLine(getattr(child, channel))
        with pytest.raises(TimeoutError):
            pending.result(timeout=0.05)
    finally:
        reap_children([child])
        try:
            if pending is not None:
                pending.finish()
        finally:
            ready.finish()
            child.stderr.close()
    assert child.returncode is not None


def test_pipe_cleanup_does_not_close_a_buffer_while_reader_is_blocked():
    # An open writer models a descendant retaining stdout after its parent
    # exits. Closing the buffer first would deadlock on the reader's lock.
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb")
    pending = ReadinessLine(stream)
    release = threading.Event()

    def hold_writer():
        try:
            release.wait(timeout=5)  # Escape hatch even if the close order regresses.
        finally:
            os.close(write_fd)

    writer = threading.Thread(target=hold_writer, daemon=True)
    writer.start()
    try:
        with pytest.raises(TimeoutError, match="Owned pipe reader"):
            pending.finish(timeout=0.05)
        assert not stream.closed
    finally:
        release.set()
        writer.join(timeout=2)
        pending.finish()
    assert stream.closed
    assert not pending.reader.is_alive()
