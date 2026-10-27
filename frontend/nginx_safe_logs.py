"""Run nginx with bounded, redacted error output and forward lifecycle signals.

nginx cannot customize error_log's format. Never persist its raw stderr: the
pipe is private to this process, and only sanitized lines reach container logs.
Access logs use the independent path-only format in nginx.conf.
"""

import os
import re
import selectors
import signal
import subprocess
import sys
import time

MAX_LINE_BYTES = 64 * 1024


def redact(line: bytes) -> str:
    text = line.decode("utf-8", errors="replace").rstrip("\r\n")
    # The native request/upstream/referrer context is not needed to diagnose
    # e.g. connect() failed. It can contain credentials even in malformed URLs.
    text = text.split(", client:", 1)[0]
    # Error messages themselves can quote client headers, filenames or URLs.
    # Preserve the diagnostic, never these untrusted quoted operands.
    # nginx does not promise to escape embedded quotes in these operands, so
    # neither a closing quote nor the remaining tail can be trusted.
    if '"' in text:
        text = text.split('"', 1)[0] + "[request operand withheld]"
    # Queries outside quotes (and fragments) have no diagnostic authority.
    text = text.split("?", 1)[0]
    text = re.sub(r"(https?://[^\s#]*)#.*", r"\1[redacted]", text)
    return text


def main(argv: list[str]) -> int:
    child = None
    pending = []

    def forward(signum, _frame):
        if child is None:
            pending.append(signum)
        else:
            try:
                child.send_signal(signum)
            except ProcessLookupError:
                pass

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT, signal.SIGHUP, signal.SIGUSR1, signal.SIGUSR2):
        signal.signal(signum, forward)
    child = subprocess.Popen(argv, stderr=subprocess.PIPE, start_new_session=True)
    for signum in pending:
        forward(signum, None)
    try:
        assert child.stderr is not None
        buffered = bytearray()
        discarding = False
        master_exited_at = None
        os.set_blocking(child.stderr.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(child.stderr, selectors.EVENT_READ)
            while True:
                if child.poll() is not None:
                    if master_exited_at is None:
                        master_exited_at = time.monotonic()
                    if time.monotonic() - master_exited_at >= 0.5:
                        break
                # A crashed master can leave a worker holding stderr open.
                # Poll its status independently; pipe EOF is not process death.
                if not selector.select(timeout=0.1):
                    continue
                data = os.read(child.stderr.fileno(), 8192)
                if not data:
                    break
                fragments = data.split(b"\n")
                for index, fragment in enumerate(fragments):
                    complete = index < len(fragments) - 1
                    if not discarding:
                        buffered.extend(fragment)
                        if len(buffered) > MAX_LINE_BYTES:
                            buffered.clear()
                            discarding = True
                            print("nginx: oversized error record withheld", file=sys.stderr, flush=True)
                        elif complete:
                            print(redact(bytes(buffered)), file=sys.stderr, flush=True)
                            buffered.clear()
                    if complete:
                        discarding = False
        if buffered and not discarding:
            print(redact(bytes(buffered)), file=sys.stderr, flush=True)
        status = child.wait()
        return status if status >= 0 else 128 - status
    finally:
        # Also clean up inherited-pipe holders after the master has exited.
        # On an ordinary graceful quit, nginx has already drained its workers.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        if child.stderr is not None:
            child.stderr.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
