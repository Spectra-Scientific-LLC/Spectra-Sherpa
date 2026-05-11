"""CLI entry point: ``spectra-sherpa`` command.

Usage::

    spectra-sherpa                  # Start on port 8000, open browser
    spectra-sherpa --port 8001      # Custom port
    spectra-sherpa --no-browser     # Don't auto-open browser
    spectra-sherpa --data-dir ~/my_data
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import threading
import time
import webbrowser


def _open_browser(url: str, delay: float = 2.0) -> None:
    """Open the browser after a short delay (daemon thread)."""
    time.sleep(delay)
    webbrowser.open(url)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _find_listening_pids(port: int) -> list[int]:
    """Return process IDs listening on *port* (POSIX via ``lsof``).

    Returns an empty list when no process is listening or when ``lsof``
    is unavailable.
    """
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []

    # lsof returns 1 when no matches were found.
    if result.returncode not in {0, 1}:
        return []

    self_pid = os.getpid()
    pids: set[int] = set()
    for raw in result.stdout.splitlines():
        value = raw.strip()
        if not value.isdigit():
            continue
        pid = int(value)
        if pid != self_pid:
            pids.add(pid)
    return sorted(pids)


def _safe_kill(pid: int, sig: int) -> bool:
    """Attempt to signal *pid*. Returns False on permission errors."""
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def _clear_port(
    port: int,
    *,
    grace_seconds: float,
    force_kill: bool,
) -> bool:
    """Try to free a TCP port by terminating listeners.

    Returns True when no blocking listener remains.
    """
    if shutil.which("lsof") is None:
        print(
            "Warning: KILL_PORT_ON_START is enabled but `lsof` is not available; " "skipping automatic port cleanup.",
        )
        return False

    initial = _find_listening_pids(port)
    if not initial:
        return True

    print(
        f"Port {port} is already in use by PID(s): " + ", ".join(str(pid) for pid in initial),
    )
    print("Attempting to free the port before startup...")

    for pid in initial:
        if not _safe_kill(pid, signal.SIGTERM):
            print(f"  Warning: no permission to terminate PID {pid}.")

    deadline = time.time() + max(0.0, grace_seconds)
    while time.time() < deadline:
        remaining = [pid for pid in _find_listening_pids(port) if pid in initial]
        if not remaining:
            return True
        time.sleep(0.1)

    remaining = [pid for pid in _find_listening_pids(port) if pid in initial]
    if remaining and force_kill:
        # ``SIGKILL`` is POSIX-only; fall back to ``SIGTERM`` on Windows so
        # the function degrades cleanly instead of raising ``AttributeError``.
        # In real Windows deployments the ``lsof`` guard above short-circuits
        # this branch entirely; the fallback only matters when callers stub
        # out ``lsof`` (e.g. from tests).
        force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        signal_label = "SIGKILL" if force_signal is getattr(signal, "SIGKILL", None) else "SIGTERM"
        print(
            f"Port still busy after grace period. Sending {signal_label} to PID(s): "
            + ", ".join(str(pid) for pid in remaining),
        )
        for pid in remaining:
            if not _safe_kill(pid, force_signal):
                print(f"  Warning: no permission to force-kill PID {pid}.")
        time.sleep(0.1)
        remaining = [pid for pid in _find_listening_pids(port) if pid in initial]

    if remaining:
        print(
            "Warning: port remains occupied by PID(s): " + ", ".join(str(pid) for pid in remaining),
        )
        return False

    return True


def main(argv: list[str] | None = None) -> None:
    from spectra_sherpa import __version__

    parser = argparse.ArgumentParser(
        prog="spectra-sherpa",
        description="SpectraSherpa — local spectroscopy platform",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port number (default: 8000)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open the browser automatically",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Data directory (default: ~/.spectra_sherpa/ or <repo>/data)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-restart on Python file changes (development mode)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    serve_parser = subparsers.add_parser("serve-model", help="Run a headless prediction server for a deployed workflow")
    serve_parser.add_argument("workflow_id", type=int, help="ID of the workflow to serve")
    serve_parser.add_argument(
        "--host", default="0.0.0.0", help="Bind address for the headless server (default: 0.0.0.0)"  # nosec B104
    )
    serve_parser.add_argument(
        "--port", type=int, default=8001, help="Port number for the headless server (default: 8001)"
    )

    args = parser.parse_args(argv)

    # Load .env before setting defaults, so .env values take precedence.
    from dotenv import dotenv_values

    from spectra_sherpa._paths import load_layered_env_files

    _env_files_used = load_layered_env_files()
    _env_file_used = _env_files_used[-1] if _env_files_used else None

    # Detect when a shell/direnv env var silently overrides the .env file.
    # Shell/direnv values still win over file layers, which is a common footgun.
    if _env_file_used is not None:
        _file_vals = dotenv_values(_env_file_used)
        for _key in ("APP_MODE", "SITE_PROFILE"):
            _file_val = _file_vals.get(_key)
            _env_val = os.environ.get(_key)
            if _file_val is not None and _env_val is not None and _file_val != _env_val:
                print(
                    f"Warning: {_key}={_env_val!r} (from shell/direnv) "
                    f"overrides {_key}={_file_val!r} (from {_env_file_used.name}). "
                    f"Check your shell environment or .envrc file.",
                )

    # Set environment before any app imports (only if not already set via .env)
    os.environ.setdefault("APP_MODE", "local")
    if args.data_dir:
        os.environ["DATA_DIR"] = args.data_dir

    # Limit threads for single-user local mode
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
    os.environ.setdefault("MKL_NUM_THREADS", "4")

    # Check for headless mode BEFORE browser launch to avoid unnecessary GUI on servers
    is_headless = getattr(args, "command", None) == "serve-model"

    # Early port availability check — detect conflicts BEFORE the app
    # lifespan runs its multi-phase initialisation (DB, plugins, worker
    # pool, etc.).  Failing fast here saves the user from a confusing
    # "address already in use" traceback after a long startup delay.
    mode = os.environ.get("APP_MODE", "local")
    auto_clear = mode == "local" or _env_bool("KILL_PORT_ON_START", False)
    pids_on_port = _find_listening_pids(args.port)
    if pids_on_port:
        if auto_clear:
            # Local mode (single-user desktop): auto-clear stale processes.
            # Also honours KILL_PORT_ON_START for hybrid/enterprise.
            grace = _env_float("KILL_PORT_GRACE_SECONDS", 2.0)
            force = _env_bool("KILL_PORT_FORCE", True)
            cleared = _clear_port(args.port, grace_seconds=grace, force_kill=force)
            if not cleared:
                print(
                    f"Error: Could not free port {args.port}. "
                    "Stop the existing process manually or use --port to pick another.",
                )
                raise SystemExit(1)
        else:
            # Non-local mode without KILL_PORT_ON_START: fail fast.
            pid_list = ", ".join(str(pid) for pid in pids_on_port)
            print(f"Error: Port {args.port} is already in use by PID(s): {pid_list}")
            print("  Options:")
            print(f"    - Stop the existing process(es): kill {pid_list}")
            print("    - Use a different port: spectra-sherpa --port <PORT>")
            print("    - Set KILL_PORT_ON_START=true in .env to auto-clear")
            raise SystemExit(1)

    # Auto-open browser only for normal mode (not headless)
    if not is_headless:
        url = f"http://{args.host}:{args.port}"
        if not args.no_browser:
            t = threading.Thread(target=_open_browser, args=(url,), daemon=True)
            t.start()
        print(f"Starting SpectraSherpa v{__version__}")
        print(f"  Mode:   {mode}{' (reload)' if args.reload else ''}")
        if _env_file_used:
            print(f"  Config: {_env_file_used}")
        print(f"  URL:    {url}")
        print("  Press Ctrl+C to stop.\n")
    else:
        print(f"Starting SpectraSherpa Headless Prediction Server v{__version__}")
        print(f"  Workflow ID: {args.workflow_id}")
        print(f"  Listening on: http://{args.host}:{args.port}")
        print("  Press Ctrl+C to stop.\n")

    import uvicorn

    if is_headless:
        os.environ["HEADLESS_WORKFLOW_ID"] = str(args.workflow_id)
        uvicorn.run(
            "spectra_sherpa.app.api.headless_app:app",
            host=args.host,
            port=args.port,
            workers=1,
            log_level="info",
        )
        return

    uvicorn.run(
        "spectra_sherpa.app.main:app",
        host=args.host,
        port=args.port,
        workers=1,
        log_level="info",
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
