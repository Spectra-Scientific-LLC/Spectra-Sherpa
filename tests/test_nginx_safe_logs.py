"""Exercise the image's actual stderr supervisor without Docker."""

import importlib.util
import signal
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "frontend/nginx_safe_logs.py"
spec = importlib.util.spec_from_file_location("nginx_safe_logs", SCRIPT)
safe_logs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safe_logs)


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
def test_graceful_stop_reaches_child_and_drains_last_diagnostic():
    child = (
        "import signal, sys, time; "
        "signal.signal(signal.SIGQUIT, lambda *_: "
        "(print('graceful shutdown', file=sys.stderr, flush=True), sys.exit(0))); "
        "print('ready', flush=True); time.sleep(30)"
    )
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT), sys.executable, "-c", child], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        assert process.stdout.readline() == b"ready\n"
        process.send_signal(signal.SIGQUIT)
        _, errors = process.communicate(timeout=5)
        assert process.returncode == 0
        assert errors == b"graceful shutdown\n"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def test_public_image_uses_supervisor_and_original_nginx_entrypoint():
    dockerfile = (SCRIPT.parent / "Dockerfile").read_text()
    assert 'ENTRYPOINT ["python3", "/usr/local/bin/nginx_safe_logs.py", "/docker-entrypoint.sh"]' in dockerfile
    assert 'CMD ["nginx", "-e", "stderr", "-g", "daemon off;"]' in dockerfile
    assert "error_log stderr warn;" in (SCRIPT.parent / "nginx.conf").read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="nginx image lifecycle uses POSIX processes")
def test_crashed_master_does_not_leave_workers_holding_log_pipe_open():
    import os

    # The descendant retains both pipes after its master dies. communicate()
    # cannot see stdout EOF until it is stopped, even if the wrapper exits.
    child = (
        "import os, time; worker = os.fork(); "
        "(print(worker, flush=True), os._exit(7)) if worker else None; "
        "time.sleep(30)"
    )
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT), sys.executable, "-c", child], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    worker = None
    try:
        worker = int(process.stdout.readline())
        _, errors = process.communicate(timeout=5)
        assert process.returncode == 7
        assert errors == b""
    finally:
        if worker is not None:
            try:
                os.kill(worker, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
