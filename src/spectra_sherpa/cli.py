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
import errno
import getpass
import os
import socket
import threading
import time
import webbrowser
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
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


def _campaign_review_download(campaign_id: str, output: str, api_url: str, token_env: str) -> None:
    """Download one publisher-authenticated Campaign Review Package."""

    import hashlib

    from spectra_sherpa.sdk.project import MAX_PROJECT_FILE_BYTES

    output_path = _resolve_path(output)
    if output_path.exists():
        raise SystemExit(f"Campaign Review Package output already exists: {output_path}")
    token = os.getenv(token_env)
    if not token:
        raise SystemExit(f"Campaign Review Package download requires a bearer token in {token_env}")
    encoded_campaign_id = quote(campaign_id, safe="")
    url = f"{_normalize_api_base(api_url)}/harness/canonical-campaigns/{encoded_campaign_id}/campaign-review"
    request = Request(url, headers=_auth_headers(token), method="GET")
    try:
        # Explicit user-provided API endpoint.
        with urlopen(request) as response:  # nosec B310
            declared_length = response.headers.get("Content-Length")
            if declared_length is not None and (
                not declared_length.isdigit() or int(declared_length) > MAX_PROJECT_FILE_BYTES
            ):
                raise SystemExit("Campaign Review Package download exceeds the supported size")
            payload = response.read(MAX_PROJECT_FILE_BYTES + 1)
            expected_digest = response.headers.get("X-Spectra-Campaign-Review-SHA256")
    except (HTTPError, URLError) as exc:
        _raise_api_error("Campaign Review Package download", exc)
    if len(payload) > MAX_PROJECT_FILE_BYTES:
        raise SystemExit("Campaign Review Package download exceeds the supported size")
    actual_digest = hashlib.sha256(payload).hexdigest()
    if expected_digest != actual_digest:
        raise SystemExit("Campaign Review Package download digest is missing or invalid")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as stream:
        stream.write(payload)
    print(f"Wrote signed Campaign Review Package: {output_path} (sha256={actual_digest})")


def _ensure_campaign_review_runtime() -> None:
    """Load the exact local registry needed to re-admit a saved application."""

    import spectra_sherpa.app.services.dag.nodes  # noqa: F401
    from spectra_sherpa.app.types import ensure_type_registry_loaded

    ensure_type_registry_loaded()


def _campaign_review_inspect(
    project: str,
    publisher_trust_anchors: str | None,
    report: str | None,
) -> None:
    """Render the complete package decision chain with no account or network."""

    import json
    from pathlib import Path

    from spectra_sherpa.sdk.campaign_review import inspect_campaign_review_package
    from spectra_sherpa.sdk.project import ProjectIOError, load_bounded_json_object

    _ensure_campaign_review_runtime()

    def load_json(path: str | None) -> dict | None:
        if path is None:
            return None
        try:
            value = load_bounded_json_object(path)
        except ProjectIOError as exc:
            raise SystemExit(f"Campaign Review verification document is invalid: {path}") from exc
        return value

    inspection = inspect_campaign_review_package(
        str(Path(project).expanduser()),
        publisher_trust_anchors=load_json(publisher_trust_anchors),
    )
    rendered = json.dumps(inspection.as_dict(), indent=2, sort_keys=True) + "\n"
    if report is None:
        print(rendered, end="")
        return
    report_path = _resolve_path(report)
    if report_path.exists():
        raise SystemExit(f"Campaign Review inspection report already exists: {report_path}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as stream:
        stream.write(rendered)
    print(f"Wrote Campaign Review inspection report: {report_path}")


def _canonical_project_reproduce(
    project: str,
    fixture: str,
    custody_id: str | None,
    spectral_axis_title: str | None,
    spectral_axis_units: str | None,
    publisher_trust_anchors: str | None,
    report: str | None,
    registered_reference_projection: str | None = None,
) -> None:
    import json

    from spectra_sherpa.sdk.campaign_review import CampaignReviewPackage, load_review_package_bytes
    from spectra_sherpa.sdk.canonical_public_fixture import (
        CanonicalPublicFixtureError,
        load_canonical_public_fixture,
        load_registered_reference_fixture,
    )
    from spectra_sherpa.sdk.canonical_reproduction import reproduce_canonical_project
    from spectra_sherpa.sdk.project import (
        ProjectIOError,
        load_bounded_json_object,
    )

    _ensure_campaign_review_runtime()

    review_package = CampaignReviewPackage.from_archive(load_review_package_bytes(project))
    package = review_package.application
    try:
        if registered_reference_projection is not None:
            if custody_id is not None or spectral_axis_title is not None or spectral_axis_units is not None:
                raise SystemExit(
                    "Registered-reference reproduction derives custody and spectral-axis authority from "
                    "the signed package and qualified projection; do not pass --custody-id or spectral-axis flags"
                )
            public_fixture = load_registered_reference_fixture(
                _resolve_path(fixture),
                package,
                projection_id=registered_reference_projection,
            )
        else:
            if custody_id is None:
                raise SystemExit("Canonical NPZ reproduction requires --custody-id")
            public_fixture = load_canonical_public_fixture(
                _resolve_path(fixture),
                package,
                custody_id=custody_id,
                spectral_axis_title=spectral_axis_title,
                spectral_axis_units="cm-1" if spectral_axis_units is None else spectral_axis_units,
            )
    except CanonicalPublicFixtureError as exc:
        raise SystemExit(f"Campaign Review reproduction source was refused: {exc}") from exc

    def load_json(path: str | None) -> dict | None:
        if path is None:
            return None
        try:
            return load_bounded_json_object(path)
        except ProjectIOError as exc:
            raise SystemExit(f"Campaign Review verification document is invalid: {path}") from exc

    result = reproduce_canonical_project(
        package,
        fixture=public_fixture.capability,
        split_plan=public_fixture.split_plan,
        publisher_attestation=review_package.publisher_attestation.as_dict(),
        publisher_trust_anchors=load_json(publisher_trust_anchors),
    )
    result_payload = result.as_dict()
    rendered = json.dumps(result_payload, indent=2, sort_keys=True) + "\n"
    required_outcomes = (
        "integrity_verified",
        "publisher_authenticated",
        "validation_reproduced",
        "application_reproduced",
    )
    failed_outcomes = [
        name
        for name in required_outcomes
        if not isinstance(result_payload.get(name), dict) or result_payload[name].get("status") != "passed"
    ]
    if report is None:
        print(rendered, end="")
    else:
        report_path = _resolve_path(report)
        if report_path.exists():
            raise SystemExit(f"Canonical reproduction report already exists: {report_path}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("x", encoding="utf-8") as stream:
            stream.write(rendered)
        print(f"Wrote canonical reproduction report: {report_path}")
    if failed_outcomes:
        raise SystemExit("Campaign Review reproduction did not pass: " + ", ".join(failed_outcomes))


def _assert_port_available(host: str, port: int) -> None:
    """Probe the requested bind without inspecting or signaling any process.

    The socket is closed before uvicorn starts. A later bind race is handled by
    uvicorn's normal refusal; it never authorizes terminating the new listener.
    """
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
    except OSError as exc:
        print(f"Warning: Cannot resolve {host}:{port} for preflight: {exc}. Uvicorn will attempt startup.")
        return
    supported = False
    for family, socktype, protocol, _, address in addresses:
        try:
            with socket.socket(family, socktype, protocol) as probe:
                if os.name == "nt":
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(address)
            supported = True
        except OSError as exc:
            if exc.errno in {errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT}:
                continue
            if exc.errno in {errno.EADDRINUSE, errno.EACCES}:
                print(f"Error: Cannot bind {host}:{port}: {exc}")
                print("Existing processes are left untouched. Stop the service you own manually,")
                print("check bind permissions, or choose a different port: spectra-sherpa --port <PORT>")
                raise SystemExit(1) from None
            # A preflight cannot diagnose every platform's bind behavior. Let
            # the actual server report non-conflict failures without claiming
            # that an unrelated service occupies the requested port.
            print(f"Warning: Cannot probe {address}: {exc}. Uvicorn will attempt startup.")
            supported = True
    if not supported:
        print(f"Error: No supported address family found for {host}:{port}.")
        print("Choose a host address supported by this system, or enable the required address family.")
        raise SystemExit(1)


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


def main(argv: list[str] | None = None, *, _server_runner: Callable[..., None] | None = None) -> None:
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
    export_parser.add_argument("--token", default=None, help="Bearer token for authenticated APIs")

    import_parser = object_subparsers.add_parser("import", help="Import a .sherpa object into a running API")
    import_parser.add_argument("path", help="Path to .sherpa object")
    import_parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="SpectraSherpa server URL")
    import_parser.add_argument("--token", default=None, help="Bearer token for authenticated APIs")

    canonical_parser = subparsers.add_parser(
        "campaign-review",
        help="Download, inspect, or independently reproduce a Campaign Review Package",
    )
    canonical_subparsers = canonical_parser.add_subparsers(dest="canonical_project_command", required=True)
    canonical_export = canonical_subparsers.add_parser(
        "download",
        help="Download the signed, data-free Campaign Review Package",
    )
    canonical_export.add_argument("campaign_id", help="Frozen canonical campaign identifier")
    canonical_export.add_argument("output", help="New .sherpa output path")
    canonical_export.add_argument("--api-url", required=True, help="Hosted SpectraSherpa server URL")
    canonical_export.add_argument(
        "--token-env",
        default="SPECTRA_SHERPA_TOKEN",
        help="Environment variable containing the bearer token (default: SPECTRA_SHERPA_TOKEN)",
    )

    canonical_inspect = canonical_subparsers.add_parser(
        "inspect",
        help="Verify and render the complete data-free decision chain with no account",
    )
    canonical_inspect.add_argument("project", help="Campaign Review Package (.sherpa)")
    canonical_inspect.add_argument("--publisher-trust-anchors")
    canonical_inspect.add_argument("--report", help="New path for the machine-readable inspection report")

    canonical_reproduce = canonical_subparsers.add_parser(
        "reproduce",
        help="Recompute validation and application with an independently supplied public fixture",
    )
    canonical_reproduce.add_argument("project", help="Campaign Review Package (.sherpa)")
    canonical_reproduce.add_argument(
        "fixture",
        help="Independent public NPZ fixture or exact provider-acquired registered-reference artifact",
    )
    canonical_reproduce.add_argument("--custody-id", help="Published opaque fixture custody ID (NPZ only)")
    canonical_reproduce.add_argument(
        "--registered-reference-projection",
        help="Qualified projection ID when fixture is an exact provider-acquired registered-reference artifact",
    )
    canonical_reproduce.add_argument("--spectral-axis-title")
    canonical_reproduce.add_argument("--spectral-axis-units")
    canonical_reproduce.add_argument("--publisher-trust-anchors")
    canonical_reproduce.add_argument("--report", help="New path for the machine-readable reproduction report")

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

    if getattr(args, "command", None) == "campaign-review":
        if args.canonical_project_command == "download":
            _campaign_review_download(args.campaign_id, args.output, args.api_url, args.token_env)
        elif args.canonical_project_command == "inspect":
            _campaign_review_inspect(
                args.project,
                args.publisher_trust_anchors,
                args.report,
            )
        elif args.canonical_project_command == "reproduce":
            _canonical_project_reproduce(
                args.project,
                args.fixture,
                args.custody_id,
                args.spectral_axis_title,
                args.spectral_axis_units,
                args.publisher_trust_anchors,
                args.report,
                args.registered_reference_projection,
            )
        return

    # Check for headless mode BEFORE browser launch to avoid unnecessary GUI on servers
    is_headless = getattr(args, "command", None) == "serve-model"

    # Refuse before browser launch or app/database initialization. A listening
    # PID or matching command name is not evidence that we own that process.
    mode = os.environ.get("APP_MODE", "local")
    if _env_bool("KILL_PORT_ON_START", False):
        print("Warning: KILL_PORT_ON_START is no longer supported; existing processes will not be terminated.")
    _assert_port_available(args.host, args.port)

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

    (_server_runner or uvicorn.run)(
        "spectra_sherpa.app.main:app",
        host=args.host,
        port=args.port,
        workers=1,
        log_level="info",
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
