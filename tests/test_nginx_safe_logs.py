"""Exercise the image's actual stderr supervisor without Docker."""

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.process_helpers import ReadinessLine, reap_children

SCRIPT = Path(__file__).resolve().parents[1] / "frontend/nginx_safe_logs.py"
spec = importlib.util.spec_from_file_location("nginx_safe_logs", SCRIPT)
safe_logs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safe_logs)


def _start_supervisor(tmp_path, child):
    # The actual supervisor creates a new session for this command. Record its
    # exact group before exec, without discovering PIDs or replacing Popen.
    receipt = tmp_path / "supervised-group.json"
    bootstrap = (
        "import json,os,sys; from pathlib import Path; "
        f"p=Path({str(receipt)!r}); "
        "p.with_suffix('.pending').write_text(json.dumps([os.getpid(),os.getpgrp(),os.getppid()])); "
        "p.with_suffix('.pending').replace(p); "
        "os.execv(sys.executable,[sys.executable,'-c',sys.argv[1]])"
    )
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT), sys.executable, "-c", bootstrap, child],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    readiness = ReadinessLine(process.stdout)
    return process, readiness, receipt


def _owned_group(process, receipt):
    if not receipt.exists():
        return None
    pid, group, parent = json.loads(receipt.read_text())
    assert pid == group and pid > 1 and parent == process.pid, "Invalid test-owned child group receipt"
    return group


def _kill_owned_group(process, receipt):
    group = _owned_group(process, receipt)
    if group is not None:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _finish_supervisor(process, readiness, receipt):
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Kill the separately owned child session FIRST. The wrapper
                # can then execute its real wait/finally and reap its child.
                _kill_owned_group(process, receipt)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    reap_children([process])
    finally:
        try:
            # Also cover a wrapper that exited before cleaning inherited pipes.
            _kill_owned_group(process, receipt)
        finally:
            try:
                readiness.finish()
            finally:
                process.stderr.close()


@pytest.mark.parametrize(
    "line",
    [
        b"connect() failed (61: Connection refused) while connecting to upstream, client: local, "
        b'request: "GET /?secret HTTP/1.1", referrer: "secret"',
        b'client sent invalid header: "Authorization: secret" while reading headers, client: local',
        b'open() "/a?secret" failed (2: No such file)',
        b'client sent invalid header: "unterminated secret',
        b'upstream sent invalid header: "X-Name: "secret"" while reading response header, client: local',
        b"error fetching https://example.invalid/?secret without quotes",
        b"error fetching https://example.invalid/#secret",
    ],
)
def test_untrusted_error_operands_are_not_logged(line):
    assert "secret" not in safe_logs.redact(line)
    assert safe_logs.redact(line)


@pytest.mark.skipif(sys.platform == "win32", reason="nginx image lifecycle uses POSIX signals")
def test_oversized_record_cannot_leak_in_later_chunks_and_exit_status_survives():
    child = "import sys; sys.stderr.write('x' * 70000 + 'secret\\nconnect() failed\\n'); sys.exit(7)"
    result = subprocess.run([sys.executable, str(SCRIPT), sys.executable, "-c", child], capture_output=True, timeout=10)
    assert result.returncode == 7
    assert result.stderr == b"nginx: oversized error record withheld\nconnect() failed\n"


@pytest.mark.skipif(sys.platform == "win32", reason="nginx image lifecycle uses POSIX signals")
def test_graceful_stop_reaches_child_and_drains_last_diagnostic(tmp_path):
    child = (
        "import signal, sys, time; "
        "signal.signal(signal.SIGQUIT, lambda *_: "
        "(print('graceful shutdown', file=sys.stderr, flush=True), sys.exit(0))); "
        "print('ready', flush=True); time.sleep(30)"
    )
    process, readiness, receipt = _start_supervisor(tmp_path, child)
    try:
        assert readiness.result(timeout=5) == b"ready\n"
        process.send_signal(signal.SIGQUIT)
        _, errors = process.communicate(timeout=5)
        assert process.returncode == 0
        assert errors == b"graceful shutdown\n"
    finally:
        _finish_supervisor(process, readiness, receipt)


def test_public_image_uses_supervisor_and_original_nginx_entrypoint():
    dockerfile = (SCRIPT.parent / "Dockerfile").read_text()
    assert 'ENTRYPOINT ["python3", "/usr/local/bin/nginx_safe_logs.py", "/docker-entrypoint.sh"]' in dockerfile
    assert 'CMD ["nginx", "-e", "stderr", "-g", "daemon off;"]' in dockerfile
    assert "error_log stderr warn;" in (SCRIPT.parent / "nginx.conf").read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="nginx image lifecycle uses POSIX processes")
def test_crashed_master_does_not_leave_workers_holding_log_pipe_open(tmp_path):
    import os

    # The descendant retains both pipes after its master dies. communicate()
    # cannot see stdout EOF until it is stopped, even if the wrapper exits.
    child = (
        "import os, time; worker = os.fork(); "
        "(print(worker, flush=True), os._exit(7)) if worker else None; "
        "time.sleep(30)"
    )
    process, readiness, receipt = _start_supervisor(tmp_path, child)
    worker = None
    try:
        worker = int(readiness.result(timeout=5))
        _, errors = process.communicate(timeout=5)
        assert process.returncode == 7
        assert errors == b""
    finally:
        if worker is not None:
            try:
                os.kill(worker, signal.SIGKILL)
            except ProcessLookupError:
                pass
        _finish_supervisor(process, readiness, receipt)


@pytest.mark.skipif(sys.platform == "win32", reason="nginx image lifecycle uses POSIX signals")
def test_silent_supervisor_child_readiness_fails_without_leaking_the_supervisor(tmp_path):
    started = tmp_path / "child-started"
    child = (
        "import sys,time; from pathlib import Path; "
        f"Path({str(started)!r}).write_text('started'); "
        "sys.stdout.write('partial'); sys.stdout.flush(); time.sleep(5)"
    )
    process, readiness, receipt = _start_supervisor(tmp_path, child)
    try:
        deadline = time.monotonic() + 5
        while not started.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists(), "Supervisor did not launch the real child"
        with pytest.raises(TimeoutError):
            readiness.result(timeout=0.1)
    finally:
        _finish_supervisor(process, readiness, receipt)
    assert process.returncode is not None
    assert not readiness.reader.is_alive()


@pytest.mark.skipif(sys.platform == "win32", reason="nginx image lifecycle uses POSIX signals")
def test_forced_cleanup_reaps_sigterm_ignoring_child_and_closes_reader(tmp_path):
    started = tmp_path / "ignoring-ready"
    child = (
        "import signal,sys,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"Path({str(started)!r}).write_text('ready'); "
        "sys.stdout.write('partial'); sys.stdout.flush(); time.sleep(20)"
    )
    process, readiness, receipt = _start_supervisor(tmp_path, child)
    try:
        deadline = time.monotonic() + 5
        while not started.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists(), "Real child did not install SIGTERM ignore handler"
        group = _owned_group(process, receipt)
        assert group is not None
        with pytest.raises(TimeoutError):
            readiness.result(timeout=0.05)
        _finish_supervisor(process, readiness, receipt)
        # The real wrapper reaped the SIGKILLed child; killing only the wrapper
        # yields -9 and leaves both the child and this reader alive.
        assert process.returncode == 128 + signal.SIGKILL
        with pytest.raises(ProcessLookupError):
            os.kill(group, 0)
        with pytest.raises(ProcessLookupError):
            os.killpg(group, 0)
        assert not readiness.reader.is_alive()
        assert process.stdout.closed and process.stderr.closed
    finally:
        _finish_supervisor(process, readiness, receipt)
