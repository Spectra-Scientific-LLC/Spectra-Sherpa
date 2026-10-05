"""Private, per-launch desktop transport; ordinary pip/browser mode is unchanged.

The native parent owns stdin/stdout pipes. No secret appears in argv, URLs,
environment variables or the readiness response. Closing the parent's pipe is
also the process-ownership signal: only this backend receives the shutdown.
"""

from __future__ import annotations

import hmac
import io
import json
import os
import re
import threading
from typing import Any, TextIO

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 4096
AUTH_HEADER = b"x-spectra-desktop-token"


class DesktopProtocolError(ValueError):
    pass


def _windows_pipe(incoming: TextIO):
    """Access the inherited pipe without holding the Windows CRT stdin lock.

    A background TextIO read can deadlock NumPy/OpenBLAS DLL initialization
    (numpy/numpy#24290). PeekNamedPipe observes ownership without that lock.
    """
    if os.name != "nt" or isinstance(incoming, io.StringIO):
        return None
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel.PeekNamedPipe.restype = wintypes.BOOL
    return kernel, msvcrt.get_osfhandle(incoming.fileno())


class DesktopAccess:
    """Authenticate every HTTP/WS request, including static UI and health."""

    def __init__(self, app: Any, secret: str, on_failure: Any = None):
        self.app = app
        self.active = True
        self.secret = secret.encode("ascii")
        self.on_failure = on_failure

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        kind = scope["type"]
        if kind == "lifespan":

            async def lifespan_send(message):
                if message["type"] == "lifespan.startup.failed" and self.on_failure:
                    # Emit a bounded reason; never relay a traceback over the protocol.
                    detail = (str(message.get("message", "Startup failed")).strip().splitlines() or ["Startup failed"])[
                        -1
                    ]
                    self.on_failure("startup_failed", detail)
                await send(message)

            await self.app(scope, receive, lifespan_send)
            return
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.lower(), []).append(value)
        port = scope.get("server", (None, None))[1]
        authority = f"127.0.0.1:{port}".encode("ascii")
        tokens = headers.get(AUTH_HEADER, [])
        admitted = (
            self.active
            and len(tokens) == 1
            and hmac.compare_digest(tokens[0], self.secret)
            and headers.get(b"host") == [authority]
            and headers.get(b"origin", [b"http://" + authority]) == [b"http://" + authority]
        )
        if not admitted:
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")],
                    }
                )
                await send(
                    {"type": "http.response.body", "body": b'{"detail":"Desktop session authorization required"}'}
                )
            return
        await self.app(scope, receive, send)


class DesktopSession:
    def __init__(self, incoming: TextIO, outgoing: TextIO):
        self._winpipe = _windows_pipe(incoming)
        self.incoming = incoming
        self.outgoing = outgoing
        self.secret = ""
        self.credential_key: str | None = None
        self._write_lock = threading.Lock()
        self._failed = False
        self._finished = threading.Event()
        self._parent_gone = threading.Event()
        self._control_lock = threading.Lock()
        self._monitor_started = False
        self._stop_server = None

    def initialize(self) -> None:
        if self._winpipe is None:
            frame = self.incoming.readline(MAX_FRAME_BYTES + 1)
        else:
            # Do not buffer a later shutdown frame while consuming launch.
            import ctypes
            from ctypes import wintypes

            kernel, handle = self._winpipe
            value = ctypes.create_string_buffer(1)
            received = wintypes.DWORD()
            raw = bytearray()
            while len(raw) <= MAX_FRAME_BYTES:
                if not kernel.ReadFile(handle, value, 1, ctypes.byref(received), None) or not received.value:
                    break
                raw.extend(value.raw)
                if value.raw == b"\n":
                    break
            try:
                frame = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise DesktopProtocolError("Invalid desktop launch encoding") from None
        if len(frame.encode("utf-8")) > MAX_FRAME_BYTES or not frame.endswith("\n"):
            raise DesktopProtocolError("Missing or oversized desktop launch frame")
        try:
            launch = json.loads(frame)
        except ValueError:
            raise DesktopProtocolError("Invalid desktop launch frame") from None
        if not isinstance(launch, dict) or launch.get("protocol") != PROTOCOL_VERSION or launch.get("type") != "launch":
            raise DesktopProtocolError("Unsupported desktop launch protocol")
        secret = launch.get("secret")
        if not isinstance(secret, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", secret):
            raise DesktopProtocolError("Desktop launch requires a per-session secret")
        self.secret = secret
        # Optional OS-protected credential key from the native shell. Absent
        # when the platform keystore is unavailable.
        credential_key = launch.get("credential_key")
        if credential_key is not None and (
            not isinstance(credential_key, str) or not re.fullmatch(r"[\x21-\x7e]{16,256}", credential_key)
        ):
            raise DesktopProtocolError("Invalid desktop credential key")
        self.credential_key = credential_key
        self.emit("starting", phase="initializing_profile")

    def start_parent_monitor(self) -> None:
        """Arm ownership before importing or initializing the application."""
        with self._control_lock:
            if self._monitor_started:
                return
            self._monitor_started = True

        def parent_control() -> None:
            # EOF, shutdown, or malformed control all revoke the owned session.
            try:
                if self._winpipe is None:
                    self.incoming.readline(MAX_FRAME_BYTES + 1)
                else:
                    import ctypes
                    from ctypes import wintypes

                    kernel, handle = self._winpipe
                    available = wintypes.DWORD()
                    while not self._finished.is_set():
                        # Any control byte or broken pipe revokes this launch.
                        if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                            break
                        if available.value:
                            break
                        self._finished.wait(0.1)
                    if self._finished.is_set():
                        return
            except (OSError, ValueError):
                pass
            with self._control_lock:
                self._parent_gone.set()
                if self._stop_server is not None:
                    self._stop_server()
            if not self._finished.wait(15):
                # Exit this process only, including if an application import hangs.
                os._exit(1)

        threading.Thread(target=parent_control, daemon=True, name="desktop-parent-control").start()

    def finish(self) -> None:
        self._finished.set()

    def emit(self, kind: str, **fields: Any) -> None:
        payload = {"protocol": PROTOCOL_VERSION, "type": kind, **fields}
        while True:
            frame = json.dumps(payload, ensure_ascii=True)
            if self.secret:
                frame = frame.replace(self.secret, "[redacted]")
            if len(frame.encode("utf-8")) + 1 <= MAX_FRAME_BYTES:
                break
            message = payload.get("message")
            if not isinstance(message, str) or not message:
                raise DesktopProtocolError("Outgoing desktop frame exceeds the byte limit")
            payload["message"] = message[: len(message) // 2]
        with self._write_lock:
            self.outgoing.write(frame + "\n")
            self.outgoing.flush()

    def fail(self, code: str, message: str) -> None:
        if not self._failed:
            self._failed = True
            self.emit("error", code=code, message=message[:1024])

    def run(self, app: str, **kwargs: Any) -> None:
        self.start_parent_monitor()
        import uvicorn
        from uvicorn.importer import import_from_string

        from spectra_sherpa import __version__

        session = self

        class OwnedServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started and not self.should_exit:
                    actual = self.servers[0].sockets[0].getsockname()
                    session.emit("ready", endpoint=f"http://127.0.0.1:{actual[1]}", version=__version__)

        # The CLI still owns configuration and canonical application construction.
        protected = DesktopAccess(import_from_string(app), self.secret, self.fail)
        kwargs.pop("workers", None)
        kwargs.pop("reload", None)
        config = uvicorn.Config(protected, **kwargs, timeout_graceful_shutdown=10, access_log=False)
        server = OwnedServer(config)

        def stop_server() -> None:
            protected.active = False
            server.should_exit = True

        with self._control_lock:
            self._stop_server = stop_server
            if self._parent_gone.is_set():
                stop_server()
                self.finish()
                raise SystemExit(1)
        try:
            server.run()
        except (Exception, SystemExit):
            self.fail("startup_failed", "Backend could not start or bind its loopback endpoint; inspect the local log.")
            raise
        finally:
            self.finish()
        if not server.started and not self._failed:
            self.fail("startup_failed", "Backend did not become ready; inspect the local startup log.")
        self.emit("stopped")
        if not server.started:
            raise SystemExit(1)
