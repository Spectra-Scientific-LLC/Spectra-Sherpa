"""Bounded ownership helpers for test-created children and pipe readers only."""

import subprocess
import threading
from concurrent.futures import Future
from contextlib import contextmanager


def finish_pipe_reader(reader, stream, timeout=2):
    # Closing a buffered pipe while another thread reads it can block on its
    # internal lock. Never attempt that close until the reader has stopped.
    reader.join(timeout=timeout)
    if reader.is_alive():
        raise TimeoutError("Owned pipe reader did not stop; pipe may still have a writer")
    stream.close()


class ReadinessLine:
    """Read exactly one line, leaving subsequent bytes for communicate()."""

    def __init__(self, stream):
        self.stream = stream
        self._result = Future()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            self._result.set_result(self.stream.readline())
        except BaseException as exc:
            self._result.set_exception(exc)

    def result(self, timeout):
        return self._result.result(timeout=timeout)

    def finish(self, timeout=2):
        finish_pipe_reader(self.reader, self.stream, timeout=timeout)


def reap_children(children, timeout=5):
    """Stop every tracked direct child before waiting, even after partial launch."""
    errors = []
    for child in children:
        try:
            if child.poll() is None:
                child.kill()
        except ProcessLookupError:
            pass
        except Exception as exc:
            errors.append(exc)
    for child in children:
        try:
            child.wait(timeout=timeout)
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise ExceptionGroup("Failed to reap test-owned children", errors)


@contextmanager
def owned_children():
    children: list[subprocess.Popen] = []
    try:
        yield children
    finally:
        reap_children(children)
