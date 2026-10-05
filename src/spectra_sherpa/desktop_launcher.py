"""Desktop bundle entry point for the local SpectraSherpa workbench.

It delegates to :mod:`spectra_sherpa.cli`, preserving the same FastAPI app,
migrations, data-dir policy, and loopback-only gateway as the supported CLI.
"""

from __future__ import annotations

import argparse
import errno
import os
import socket
import sys
import time
from collections.abc import Sequence
from pathlib import Path

LOOPBACK_HOST = "127.0.0.1"
_MISSING = object()


def _windows_pid_is_running(pid: int) -> bool:
    """Read-only Windows probe: os.kill(pid, 0) terminates on Windows."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only; no termination authority.
    if not handle:
        # Invalid PID is absence; access denied/unknown errors never justify stealing a lock.
        return ctypes.get_last_error() != 87
    try:
        return kernel.WaitForSingleObject(handle, 0) != 0  # Signaled process handle means exited.
    finally:
        kernel.CloseHandle(handle)


class DesktopInstanceAlreadyRunning(RuntimeError):
    """Raised when another desktop workbench owns the same data directory."""


class DesktopInstanceLock:
    """Exclusive desktop lock with stale-PID recovery.

    The normal application startup lock permits follower processes because it
    only coordinates one-time setup. A desktop workbench instead needs one
    server per local data directory. ``O_EXCL`` makes acquisition atomic on
    every supported target, while the PID permits recovery after a crash.
    """

    filename = ".spectrasherpa-desktop.lock"
    initialization_grace_seconds = 5.0

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / self.filename
        self._fd: int | None = None

    @staticmethod
    def _pid_is_running(pid: int | None) -> bool:
        if pid is None or pid <= 0:
            return False
        if sys.platform == "win32":
            return _windows_pid_is_running(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # Do not steal a lock whose process exists but belongs to another
            # user/session.
            return True
        except OSError as exc:
            return exc.errno != errno.ESRCH
        return True

    def _holder_pid(self) -> int | None:
        try:
            return int(self.path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _is_initializing(self) -> bool:
        """Whether a just-created lock may still be receiving its PID.

        ``O_EXCL`` claims the pathname atomically, but writing the PID follows
        that creation. A competing launcher must not mistake that tiny window
        for a stale, empty file and unlink a live owner's lock. An abandoned
        empty file becomes recoverable after this short grace period.
        """
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return False
        return 0 <= age < self.initialization_grace_seconds

    def acquire(self) -> None:
        """Acquire the lock or raise with the active holder's PID."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                self._fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                holder_pid = self._holder_pid()
                if self._pid_is_running(holder_pid):
                    raise DesktopInstanceAlreadyRunning(str(holder_pid) if holder_pid else "another process")
                if holder_pid is None and self._is_initializing():
                    raise DesktopInstanceAlreadyRunning("another process")
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                continue

            os.write(self._fd, f"{os.getpid()}\n".encode("ascii"))
            return

        # A concurrent launcher replaced a stale lock between our unlink and
        # exclusive create. Report that ownership instead of retrying forever.
        holder_pid = self._holder_pid()
        raise DesktopInstanceAlreadyRunning(str(holder_pid) if holder_pid else "another process")

    def release(self) -> None:
        """Release the held lock; a process crash is recovered on next launch."""
        if self._fd is None:
            return
        try:
            os.close(self._fd)
        finally:
            self._fd = None
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def choose_loopback_port() -> int:
    """Return an available IPv4 loopback port without probing other processes.

    The reservation is released before Uvicorn starts, so another process can
    still win the narrow race. The launcher tells the CLI to fail cleanly in
    that case rather than performing its normal stale-port cleanup.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind((LOOPBACK_HOST, 0))
        return int(reservation.getsockname()[1])


def _build_cli_args(args: argparse.Namespace) -> list[str]:
    port = args.port if args.port is not None else choose_loopback_port()
    cli_args = ["--host", LOOPBACK_HOST, "--port", str(port)]
    if args.data_dir:
        cli_args.extend(["--data-dir", args.data_dir])
    if args.no_browser:
        cli_args.append("--no-browser")
    return cli_args


def _resolve_data_dir(args: argparse.Namespace) -> Path:
    if args.data_dir:
        return Path(args.data_dir).expanduser().resolve()

    from spectra_sherpa._paths import get_default_data_dir

    return get_default_data_dir()


def windows_profile_acl_warning(
    data_dir: Path, *, platform: str | None = None, user_profile: str | None = None
) -> str | None:
    """Return a warning when the private data directory escapes the Windows profile.

    On Windows the workbench's private files (local database, stored endpoint
    keys) rely on the containing profile's inherited ACL — POSIX mode bits
    cannot establish a Windows ACL. The default data directory lives under
    ``%USERPROFILE%``, which carries that restricted ACL. A custom
    ``--data-dir`` outside the profile inherits whatever ACL its parent has,
    which the application cannot inspect portably, so the prerequisite is
    surfaced here instead of being assumed.
    """
    if (platform if platform is not None else sys.platform) != "win32":
        return None
    profile = user_profile if user_profile is not None else os.environ.get("USERPROFILE")
    if not profile:
        return None
    try:
        Path(os.path.normcase(str(data_dir))).relative_to(os.path.normcase(str(Path(profile))))
    except ValueError:
        return (
            f"The data directory {data_dir} is outside the Windows user profile. "
            "Private workbench files inherit this location's ACL; restrict it to "
            "your user, or omit --data-dir to use the protected profile default."
        )
    return None


def _protect_profile_credentials(data_dir: Path) -> None:
    from spectra_sherpa.app.core.desktop_policy import LinkedConfigurationRefused
    from spectra_sherpa.app.services.basic_chat import protect_plaintext_endpoint_key
    from spectra_sherpa.app.services.encryption import retire_plaintext_master_key

    env_path = data_dir / ".env"
    try:
        protect_plaintext_endpoint_key([env_path])
        retire_plaintext_master_key(env_path)
    except LinkedConfigurationRefused:
        pass  # a linked .env is never written; saving settings reports why


def main(argv: Sequence[str] | None = None) -> None:
    """Start a self-contained local workbench through the established CLI."""
    from spectra_sherpa import __version__

    parser = argparse.ArgumentParser(
        prog="SpectraSherpa",
        description="Launch the local, offline-capable SpectraSherpa workbench.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Loopback port (defaults to an available ephemeral port)",
    )
    parser.add_argument("--data-dir", default=None, help="Local application-data directory")
    parser.add_argument("--no-browser", action="store_true", help="Start without opening a browser")
    parser.add_argument("--desktop-ipc", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"SpectraSherpa {__version__}")
    args = parser.parse_args(argv)
    session = None
    original_stdout = sys.stdout
    if args.desktop_ipc:
        from spectra_sherpa.desktop_session import DesktopSession

        if sys.stdin is None:
            raise SystemExit("Native launch requires a pipe-enabled backend build")
        session = DesktopSession(sys.stdin, original_stdout)
        # Reserve stdout exclusively for bounded protocol frames, before any app import.
        sys.stdout = sys.stderr
        try:
            session.initialize()
            session.start_parent_monitor()
            if session.credential_key is not None:
                from spectra_sherpa.app.services.encryption import set_process_master_key

                set_process_master_key(session.credential_key)
                session.credential_key = None
        except ValueError as exc:
            session.fail("invalid_launch", str(exc))
            sys.stdout = original_stdout
            raise SystemExit(1) from None
        args.no_browser = True
        args.port = 0
    data_dir = _resolve_data_dir(args)
    acl_warning = windows_profile_acl_warning(data_dir)
    if acl_warning:
        # stderr only: in desktop-ipc mode stdout is reserved for protocol frames.
        print(f"WARNING: {acl_warning}", file=sys.stderr)

    # A desktop artifact is always the local workbench. These values are set
    # before the CLI loads .env layers, so a neighboring enterprise .env cannot
    # turn the bundle into a networked server.
    overrides = {
        "APP_MODE": "local",
        "SITE_PROFILE": None,
        "SPECTRA_SHERPA_DESKTOP": "1",
        "SPECTRA_SHERPA_PRESERVE_PORT": "1",
        "LOG_FILE_PATH": str(data_dir / "logs" / "desktop.log"),
        # The one profile this launch owns; configuration is read only from it.
        "DATA_DIR": str(data_dir),
    }
    # No hosted-service connection exists in the desktop product.
    from spectra_sherpa.app.core.desktop_policy import HOSTED_SERVICE_ENV

    overrides.update({name: None for name in HOSTED_SERVICE_ENV})
    if session is not None:
        from spectra_sherpa.app.core.app_paths import get_app_data_paths

        overrides.update(
            {
                "DATA_DIR": str(data_dir),
                "DATABASE_URL": f"sqlite+aiosqlite:///{get_app_data_paths(data_dir).database}",
                "SITE_PROFILE": "",
            }
        )
    previous = {name: os.environ.get(name, _MISSING) for name in overrides}
    try:
        for name, value in overrides.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

        from spectra_sherpa.cli import main as cli_main

        instance_lock = DesktopInstanceLock(data_dir)
        try:
            instance_lock.acquire()
        except DesktopInstanceAlreadyRunning as exc:
            if session is not None:
                session.fail("profile_in_use", "This profile is already open. Close its existing app before retrying.")
            print(
                "SpectraSherpa is already running for this local data directory "
                f"(PID {exc}). Close it first or choose a different --data-dir.",
            )
            raise SystemExit(1) from None
        try:
            # Only after exclusive ownership: with an OS-protected key, move this
            # profile's credentials (and nothing else) out of plaintext.
            _protect_profile_credentials(data_dir)
            if session is None:
                cli_main(_build_cli_args(args))
            else:
                cli_main(_build_cli_args(args), _server_runner=session.run)
        finally:
            instance_lock.release()
    except Exception as exc:
        if session is not None:
            session.fail("startup_failed", str(exc))
        raise
    finally:
        if session is not None:
            session.finish()
        sys.stdout = original_stdout
        for name, value in previous.items():
            if value is _MISSING:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":  # pragma: no cover - exercised through the bundle
    main()
