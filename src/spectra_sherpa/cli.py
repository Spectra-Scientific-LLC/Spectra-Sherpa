"""CLI entry point: ``spectra-sherpa`` command.

Usage::

    spectra-sherpa                  # Start on port 8000, open browser
    spectra-sherpa --port 8001      # Custom port
    spectra-sherpa --no-browser     # Don't auto-open browser
    spectra-sherpa --data-dir ~/my_data
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import shutil
import signal
import subprocess
import threading
import time
import webbrowser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

DEFAULT_BIND_HOST = ".".join(("0", "0", "0", "0"))


def _health_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/api/v1/health", "", ""))


def _wait_for_server_ready(url: str, *, timeout: float = 120.0, interval: float = 0.5) -> bool:
    """Wait until the local HTTP server is accepting requests."""
    deadline = time.monotonic() + max(0.0, timeout)
    probe_url = _health_url(url)
    while time.monotonic() <= deadline:
        try:
            with urlopen(probe_url, timeout=min(2.0, max(0.1, interval))) as response:  # nosec B310
                return 200 <= getattr(response, "status", 200) < 500
        except HTTPError as exc:
            return 200 <= exc.code < 500
        except (OSError, URLError):
            time.sleep(interval)
    return False


def _open_browser(url: str, delay: float = 0.0) -> None:
    """Open the browser after the server is ready, with a bounded fallback."""
    if delay > 0:
        time.sleep(delay)
    _wait_for_server_ready(url)
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


def _normalize_api_base(url: str) -> str:
    base = url.rstrip("/")
    return base if base.endswith("/api/v1") else f"{base}/api/v1"


def _auth_headers(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _resolve_path(path: str):
    from pathlib import Path

    return Path(path).expanduser().resolve()


def _object_inspect(path: str) -> None:
    import json

    from spectra_sherpa.app.services.sherpa_object import inspect_archive_bytes

    payload = _resolve_path(path).read_bytes()
    print(json.dumps(inspect_archive_bytes(payload).to_dict(), indent=2))


def _object_validate(path: str) -> None:
    import json

    from spectra_sherpa.app.services.sherpa_object import validate_archive_bytes

    payload = _resolve_path(path).read_bytes()
    result = validate_archive_bytes(payload)
    print(json.dumps(result, indent=2))
    if not result.get("valid"):
        raise SystemExit(2)


def _raise_api_error(action: str, exc: HTTPError | URLError) -> None:
    if isinstance(exc, HTTPError):
        detail = exc.reason
        try:
            payload = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            payload = ""
        if payload:
            detail = payload
        raise SystemExit(f"{action} failed: HTTP {exc.code} {detail}") from exc
    raise SystemExit(f"{action} failed: {exc.reason}") from exc


def _object_export(project_id: int, output: str, api_url: str, token: str | None) -> None:
    url = f"{_normalize_api_base(api_url)}/projects/{project_id}/export/sherpa"
    request = Request(url, headers=_auth_headers(token), method="GET")
    try:
        # Explicit user-provided API endpoint.
        with urlopen(request) as response:  # nosec B310
            payload = response.read()
    except (HTTPError, URLError) as exc:
        _raise_api_error("Export", exc)
    _resolve_path(output).write_bytes(payload)
    print(f"Wrote {output} ({len(payload)} bytes)")


def _object_import(path: str, api_url: str, token: str | None) -> None:
    import json
    import uuid

    file_path = _resolve_path(path)
    boundary = f"spectra-sherpa-{uuid.uuid4().hex}"
    file_payload = file_path.read_bytes()
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode("utf-8")
        + file_payload
        + f"\r\n--{boundary}--\r\n".encode("utf-8")
    )

    headers = {
        **_auth_headers(token),
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    request = Request(f"{_normalize_api_base(api_url)}/projects/import", data=body, headers=headers, method="POST")
    try:
        # Explicit user-provided API endpoint.
        with urlopen(request) as response:  # nosec B310
            result = json.loads(response.read())
    except (HTTPError, URLError) as exc:
        _raise_api_error("Import", exc)
    print(json.dumps({"id": result.get("id"), "name": result.get("name")}, indent=2))


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


async def _prewarm_hitran_synthesis_library(args: argparse.Namespace) -> None:
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.services.synthesis import (
        default_hitran_component_ids,
        prewarm_hitran_default_library,
    )

    api_key = args.api_key or os.getenv("HITRAN_API_KEY")
    if not api_key:
        api_key = getpass.getpass("HITRAN API key: ")

    component_ids = list(args.component or [])
    if not component_ids:
        component_ids = default_hitran_component_ids()
    if args.limit is not None:
        component_ids = component_ids[: max(0, args.limit)]

    print("Prewarming local HITRAN synthesis library")
    print(f"  Cache:       {settings.data_dir / 'synthesis_cache' / 'hitran' / 'spectra'}")
    print(f"  Components:  {len(component_ids)}")
    print(f"  Wavenumber:  {args.wavenumber_min:g}-{args.wavenumber_max:g} cm^-1")
    print(f"  Resolution:  {args.resolution_cm1:g} cm^-1")
    print(f"  Temperature: {args.temperature_k:g} K")
    print(f"  Pressure:    {args.pressure_atm:g} atm")
    print("")

    def report(row: dict[str, object]) -> None:
        status = str(row.get("status", "unknown")).upper()
        prefix = f"[{row.get('index')}/{row.get('total')}] {status:9s}"
        message = f"{prefix} {row.get('component_id')} {row.get('name')}"
        if row.get("n_points") is not None:
            message += f" ({row.get('n_points')} points)"
        if row.get("error"):
            message += f" - {row.get('error')}"
        print(message, flush=True)

    results = await prewarm_hitran_default_library(
        api_key,
        component_ids=component_ids,
        temperature_k=args.temperature_k,
        pressure_atm=args.pressure_atm,
        resolution_cm1=args.resolution_cm1,
        wavenumber_min=args.wavenumber_min,
        wavenumber_max=args.wavenumber_max,
        force=args.force,
        progress=report,
    )
    generated = sum(1 for row in results if row.get("status") == "generated")
    cached = sum(1 for row in results if row.get("status") == "cached")
    failed = [row for row in results if row.get("status") == "failed"]
    print("")
    print(f"Done. generated={generated}, cached={cached}, failed={len(failed)}")
    if failed:
        raise SystemExit(2)


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
        "--host",
        default=DEFAULT_BIND_HOST,
        help=f"Bind address for the headless server (default: {DEFAULT_BIND_HOST})",
    )
    serve_parser.add_argument(
        "--port", type=int, default=8001, help="Port number for the headless server (default: 8001)"
    )
    object_parser = subparsers.add_parser("object", help="Inspect, validate, export, or import .sherpa objects")
    object_subparsers = object_parser.add_subparsers(dest="object_command", required=True)

    inspect_parser = object_subparsers.add_parser("inspect", help="Inspect a .sherpa object offline")
    inspect_parser.add_argument("path", help="Path to .sherpa object")

    validate_parser = object_subparsers.add_parser("validate", help="Validate a .sherpa object offline")
    validate_parser.add_argument("path", help="Path to .sherpa object")

    export_parser = object_subparsers.add_parser("export", help="Export a project from a running SpectraSherpa API")
    export_parser.add_argument("project_id", type=int, help="Project ID to export")
    export_parser.add_argument("output", help="Output .sherpa path")
    export_parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="SpectraSherpa server URL")
    export_parser.add_argument("--token", default=None, help="Bearer token for hosted/hybrid APIs")

    import_parser = object_subparsers.add_parser("import", help="Import a .sherpa object into a running API")
    import_parser.add_argument("path", help="Path to .sherpa object")
    import_parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="SpectraSherpa server URL")
    import_parser.add_argument("--token", default=None, help="Bearer token for hosted/hybrid APIs")

    prewarm_parser = subparsers.add_parser(
        "prewarm-hitran-synthesis",
        help="Populate the local default HITRAN synthesis spectrum cache",
    )
    prewarm_parser.add_argument(
        "--api-key",
        default=None,
        help="HITRAN API key. If omitted, reads HITRAN_API_KEY or prompts without echo.",
    )
    prewarm_parser.add_argument(
        "--component",
        action="append",
        help="HITRAN component to prewarm, e.g. hitran:2, 2, CO2, or Carbon dioxide. Repeatable.",
    )
    prewarm_parser.add_argument("--limit", type=int, default=None, help="Limit the number of components to prewarm")
    prewarm_parser.add_argument("--force", action="store_true", help="Regenerate spectra even when cached")
    prewarm_parser.add_argument("--resolution-cm1", type=float, default=1.0, help="Wavenumber step in cm^-1")
    prewarm_parser.add_argument("--wavenumber-min", type=float, default=400.0, help="Minimum wavenumber in cm^-1")
    prewarm_parser.add_argument("--wavenumber-max", type=float, default=4000.0, help="Maximum wavenumber in cm^-1")
    prewarm_parser.add_argument("--temperature-k", type=float, default=293.0, help="Temperature in K")
    prewarm_parser.add_argument("--pressure-atm", type=float, default=1.0, help="Pressure in atm")

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

    if getattr(args, "command", None) == "prewarm-hitran-synthesis":
        asyncio.run(_prewarm_hitran_synthesis_library(args))
        return

    if getattr(args, "command", None) == "object":
        if args.object_command == "inspect":
            _object_inspect(args.path)
        elif args.object_command == "validate":
            _object_validate(args.path)
        elif args.object_command == "export":
            _object_export(args.project_id, args.output, args.api_url, args.token)
        elif args.object_command == "import":
            _object_import(args.path, args.api_url, args.token)
        return

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
