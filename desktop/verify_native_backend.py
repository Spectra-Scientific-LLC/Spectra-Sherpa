#!/usr/bin/env python3
"""Exercise private frozen-backend readiness independently of any native shell."""

from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import subprocess
import tempfile
import threading
from collections import deque
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


def verify(executable: Path, stop_mode: str = "eof") -> None:
    secret = secrets.token_urlsafe(32)
    frames: queue.Queue[str | None] = queue.Queue()
    diagnostics: deque[str] = deque(maxlen=100)
    with tempfile.TemporaryDirectory(prefix="sherpa-handshake-") as profile:
        child = subprocess.Popen(
            [str(executable.resolve()), "--desktop-ipc", "--data-dir", profile],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "SPECTRA_DESKTOP_STARTUP_TRACE": "1"},
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        def output():
            for line in child.stdout:
                frames.put(line)
            frames.put(None)

        def errors():
            for line in child.stderr:
                diagnostics.append(line.replace(secret, "[redacted]")[:512])

        threading.Thread(target=output, daemon=True).start()
        threading.Thread(target=errors, daemon=True).start()
        try:
            child.stdin.write(json.dumps({"protocol": 1, "type": "launch", "secret": secret}) + "\n")
            child.stdin.flush()
            ready = None
            for _ in range(5):
                line = frames.get(timeout=90)
                if line is None:
                    raise RuntimeError("Frozen backend exited before readiness")
                frame = json.loads(line)
                print("Frozen backend phase:", frame.get("type"), flush=True)
                if frame.get("type") == "error":
                    raise RuntimeError(str(frame.get("message", "Startup failure")).replace(secret, "[redacted]"))
                if frame.get("type") == "ready":
                    ready = frame
                    break
            if ready is None:
                raise RuntimeError("Frozen backend did not report readiness")
            url = urlsplit(ready["endpoint"])
            if (
                url.scheme != "http"
                or url.hostname != "127.0.0.1"
                or not url.port
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in ("", "/")
            ):
                raise RuntimeError("Frozen backend returned a non-private endpoint")
            endpoint = ready["endpoint"].rstrip("/") + "/api/health"
            opener = build_opener(ProxyHandler({}))
            with opener.open(Request(endpoint, headers={"X-Spectra-Desktop-Token": secret}), timeout=5) as response:
                assert response.status == 200
            try:
                opener.open(endpoint, timeout=5)
                raise AssertionError("Unauthenticated frozen backend admitted a request")
            except HTTPError as error:
                assert error.code == 403
            print("Frozen backend readiness and HTTP authorization passed", flush=True)
            if stop_mode == "shutdown":
                child.stdin.write('{"protocol":1,"type":"shutdown"}\n')
                child.stdin.flush()
                child.wait(timeout=20)
        except Exception:
            print("Frozen backend stderr (bounded, launch secret redacted):", flush=True)
            print("".join(diagnostics), flush=True)
            log = Path(profile) / "logs" / "desktop.log"
            if log.is_file():
                lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
                print("\n".join(line.replace(secret, "[redacted]")[:512] for line in lines), flush=True)
            raise
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()  # Only this explicitly spawned process.
                child.wait(timeout=10)
            child.stdout.close()
            child.stderr.close()
        if child.returncode != 0:
            raise RuntimeError("Frozen backend did not stop cleanly")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    executable = parser.parse_args().executable
    for mode in ("eof", "shutdown"):
        verify(executable, mode)
