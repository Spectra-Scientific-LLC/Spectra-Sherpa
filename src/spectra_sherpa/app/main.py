from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypeAlias
from urllib.parse import urlparse

# Force a non-interactive matplotlib backend for server-side rendering.
try:
    import matplotlib

    matplotlib.use("agg")
except (ImportError, AttributeError):
    pass

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from spectra_sherpa.app.api.v1.api import build_api_router
from spectra_sherpa.app.contracts.application_lifecycle import ApplicationLifespan, compose_lifespan
from spectra_sherpa.app.core.app_paths import get_app_data_paths
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.core.logging import configure_logging
from spectra_sherpa.app.core.rate_limit_middleware import RateLimitMiddleware
from spectra_sherpa.app.core.security import (
    api_key_middleware,
    get_client_host,
)
from spectra_sherpa.app.core.startup import (
    ensure_data_dirs,
    ensure_database_ready,
    ensure_default_user,
    ensure_egress_defaults,
    ensure_workflow_templates,
    reconcile_orphan_model_artifacts,
    reconcile_stale_jobs,
    validate_config,
    wait_for_database_ready,
)
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.services.job_manager import job_manager
from spectra_sherpa.app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

RouterMount: TypeAlias = tuple[APIRouter, str | Mapping[str, Any]]
WebSocketRegistryHook: TypeAlias = Callable[[FastAPI], None]
WebSocketAdmissionProvider: TypeAlias = Callable[[str, str | None, int | None], Awaitable["WebSocketAdmissionDecision"]]


@dataclass(frozen=True)
class WebSocketAdmissionDecision:
    """Import-light result returned by an optional hosted transport authority."""

    allowed: bool
    reason: str | None = None
    retry_after_seconds: int = 0


def get_cors_origins() -> list[str]:
    """
    Get CORS allowed origins based on environment and mode.

    Priority:
    1. CORS_ORIGINS env var (comma-separated list)
    2. Mode-based defaults: localhost origins for all modes

    NOTE: For managed production deployments, CORS_ORIGINS must be set
    to your frontend domain(s). The localhost defaults are only for development.
    """
    # Check for explicit CORS configuration
    cors_env = os.getenv("CORS_ORIGINS", "").strip()
    if cors_env:
        return [origin.strip() for origin in cors_env.split(",") if origin.strip()]

    # Default origins: localhost on standard dev/prod ports.
    # All modes use localhost-only CORS to prevent cross-origin data
    # exfiltration from malicious websites targeting the local server.
    default_origins = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]

    # In non-local modes without explicit CORS_ORIGINS, warn loudly.
    # Local mode is fine with localhost defaults (single-user desktop).
    from spectra_sherpa.app.core.mode_policy import is_multi_user

    if is_multi_user():
        logger.critical(
            "CORS_ORIGINS not set for %s mode — falling back to localhost-only "
            "origins. Set CORS_ORIGINS to your production domain(s) before "
            "exposing this service to the network.",
            app_config.mode,
        )

    # Add production URL if configured
    if app_config.api_base_url and app_config.api_base_url not in default_origins:
        default_origins.append(app_config.api_base_url)

    return default_origins


def _host_from_url(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.hostname:
        return parsed.hostname
    if "://" not in value:
        parsed = urlparse(f"//{value}")
        return parsed.hostname
    return None


def get_trusted_hosts(origins: list[str] | None = None) -> list[str]:
    """Build the Host-header allowlist used by Starlette.

    ``TRUSTED_HOSTS`` is the operator override.  Otherwise we derive a
    conservative list from local development defaults, ``DOMAIN``,
    ``API_BASE_URL``, and the configured CORS origins.  This mitigates
    Host-header poisoning in Starlette while keeping local OSS use simple.
    """
    hosts_env = os.getenv("TRUSTED_HOSTS", "").strip()
    if hosts_env:
        hosts = []
        for value in hosts_env.split(","):
            value = value.strip()
            if not value:
                continue
            hosts.append(value if value == "*" else (_host_from_url(value) or value))
        return hosts

    # Trusted-host middleware allowlist, not a socket bind.
    hosts = {"localhost", "127.0.0.1", ".".join(("0", "0", "0", "0")), "test", "testserver"}
    for value in (
        os.getenv("DOMAIN", ""),
        os.getenv("API_BASE_URL", ""),
        app_config.api_base_url,
        *(origins or []),
    ):
        value = value.strip()
        if not value or value == "*":
            continue
        host = _host_from_url(value)
        if host:
            hosts.add(host)

    return sorted(hosts)


def _try_leader_lock() -> bool:
    """Acquire a non-blocking file lock for one-time startup tasks.

    Returns True if this worker is the leader (lock acquired).
    On platforms without fcntl (Windows) returns True so startup still runs.

    The lock holder's PID is written to the file for diagnostic purposes.
    ``fcntl.flock()`` is process-scoped — the OS releases it automatically
    when the holder exits, even on crash, so stale *files* are harmless.
    """
    try:
        import fcntl
    except ImportError:
        return True

    lock_path = get_app_data_paths(settings.data_dir).startup_lock
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = -1
    try:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Write our PID for diagnostics (other workers can read it)
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode())
        # Keep fd open for process lifetime (lock released on close/exit)
        logger.info("Leader lock acquired: %s (PID %d)", lock_path, os.getpid())
        return True
    except OSError:
        # Read the holder PID for a helpful log message
        holder_pid = _read_lock_pid(lock_path)
        if holder_pid:
            logger.warning(
                "Leader lock held by PID %d — running as follower.",
                holder_pid,
            )
        else:
            logger.warning(
                "Could not acquire leader lock %s — running as follower.",
                lock_path,
            )
        # Close the fd we opened (we didn't acquire the lock)
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        return False


def _read_lock_pid(lock_path) -> int | None:
    """Read the PID written to the lock file, if any."""
    try:
        content = lock_path.read_text().strip()
        return int(content) if content.isdigit() else None
    except (OSError, ValueError):
        return None


def _normalize_router_mounts(extra_routers: list[RouterMount] | None) -> list[tuple[APIRouter, dict[str, Any]]]:
    """Normalize extension router declarations for ``include_router``.

    Accepted forms:
    - ``(router, "/prefix")`` (legacy shorthand)
    - ``(router, {"prefix": "/x", "tags": [...]})`` (full control)
    """
    normalized: list[tuple[APIRouter, dict[str, Any]]] = []
    for idx, item in enumerate(extra_routers or []):
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError(
                f"extra_routers[{idx}] must be a (router, config) 2-tuple",
            )

        router, config = item
        if isinstance(config, str):
            normalized.append((router, {"prefix": config}))
        elif isinstance(config, Mapping):
            normalized.append((router, dict(config)))
        else:
            raise TypeError(
                f"extra_routers[{idx}] config must be a prefix string or mapping, got {type(config).__name__}",
            )

    return normalized


# ---------------------------------------------------------------------------
# Lifespan factory
# ---------------------------------------------------------------------------


def _make_lifespan(
    extra_startup: list[Callable[[], Awaitable[None]]] | None = None,
    extra_shutdown: list[Callable[[], Awaitable[None]]] | None = None,
):
    """Return an ASGI lifespan context manager.

    *extra_startup* / *extra_shutdown* are async callables invoked after
    core phases complete (startup) or before core teardown finishes
    (shutdown).  Repo 2 uses these to register server-only hooks without
    forking this module.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # === STARTUP ===
        import traceback as _tb

        _dag_pool = None

        try:
            # Phase 1: per-worker setup (safe to run in every worker)
            logger.info("Phase 1: per-worker setup ...")
            configure_logging()
            # Unified config validation (security, concurrency, database, mode, LLM, CORS)
            _config_result = validate_config()
            for _w in _config_result.warnings:
                logger.warning("[Config] %s: %s", _w.category, _w.message)
            if _config_result.has_errors:
                for _e in _config_result.errors:
                    logger.critical("[Config] %s: %s", _e.category, _e.message)
                raise SystemExit(1)
            ensure_data_dirs()

            # Initialize model artifact storage (safe in every worker — only creates dirs)
            from spectra_sherpa.app.services.model_store import init_model_store

            init_model_store(settings.data_dir)

            # Canonical fitted-state artifacts are distinct from legacy model
            # artifacts and have their own private, content-addressed reader.
            from spectra_sherpa.app.services.canonical_artifact_store import init_canonical_artifact_store

            init_canonical_artifact_store(settings.data_dir)

            # Audit subsystem (ISO 17025 readiness — phase 1):
            #   * Mint process_boot_id once per app boot; pairs with
            #     app_monotonic_ns on each event for strict within-process
            #     forensic ordering even when wall clocks skew.
            #   * Install the before_flush listener so audit events written
            #     by service-code emit() calls commit in the same DB
            #     transaction as the business mutation (fail-closed when
            #     audit_enabled=True).
            from spectra_sherpa.app.services.audit import (
                init_process_boot_id,
                install_audit_flush_listener,
            )

            init_process_boot_id()
            install_audit_flush_listener()

            logger.info("Phase 1 complete")

            # Phase 2: DB-mutating tasks — only the leader worker runs these.
            # Other workers skip (the leader will have completed before requests arrive
            # because Gunicorn's --preload or sequential worker spawn ensures ordering).
            is_leader = _try_leader_lock()
            if is_leader:
                logger.info("Phase 2: leader one-time startup tasks ...")
                logger.info("  → ensure_database_ready")
                await ensure_database_ready()
                # Restore logging config (Alembic's fileConfig may reset root→WARN)
                configure_logging()
                logger.info("  → ensure_default_user")
                await ensure_default_user()
                logger.info("  → ensure_egress_defaults")
                await ensure_egress_defaults()
                logger.info("  → reconcile_stale_jobs")
                await reconcile_stale_jobs()
                logger.info("  → reconcile_orphan_model_artifacts")
                await reconcile_orphan_model_artifacts()
                logger.info("  → ensure_workflow_templates")
                await ensure_workflow_templates()
                logger.info("Phase 2 complete")
            else:
                logger.info("Follower worker: waiting for leader to finish DB setup ...")
                # Wait for leader to finish DB schema setup (no DB writes on followers).
                await wait_for_database_ready()
                logger.info("Follower: DB ready")

            # Phase 3: per-worker setup that depends on DB being ready
            logger.info("Phase 3: built-in tools ...")
            # Register built-in MCP tools (import triggers @register_tool decorators)
            import spectra_sherpa.app.services.tools.builtin  # noqa: F401
            from spectra_sherpa.app.services.tools import tool_registry as _tool_reg

            logger.info("Registered %d built-in tool(s)", len(_tool_reg))

            # Start folder watch polling service
            from spectra_sherpa.app.services.folder_watch_service import start_folder_watch_service

            await start_folder_watch_service()

            # Load the type registry (JSON schemas for port type validation)
            from pathlib import Path as _Path

            from spectra_sherpa.app.types import type_registry as _type_reg

            _type_reg.load(_Path(__file__).parent / "types")
            logger.info("Type registry: %d types loaded", len(_type_reg._types))

            logger.info("Phase 3 complete")

            # Phase 4: extension hooks (Repo 2 injects server-only startup here)
            if extra_startup:
                logger.info("Phase 4: %d extension hook(s) ...", len(extra_startup))
            for hook in extra_startup or []:
                await hook()

            # Phase 5: bounded, individually cancellable scientific workers.
            from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool, set_default_pool

            pool_size = settings.dag_worker_pool_size
            _dag_pool = IsolatedWorkerPool(max_workers=pool_size)
            set_default_pool(_dag_pool)
            logger.info("DAG worker capacity: %d isolated spawned processes", pool_size)

            logger.info("Application startup complete")
        except Exception:
            logger.critical(
                "STARTUP FAILED — lifespan exception:\n%s",
                _tb.format_exc(),
            )
            raise

        try:
            yield
        finally:
            # Register independent cleanup operations in reverse order. A failing
            # extension shutdown must not strand core workers or services.
            from spectra_sherpa.app.services.dag.executor import set_default_pool as _clear_pool
            from spectra_sherpa.app.services.folder_watch_service import stop_folder_watch_service

            async with AsyncExitStack() as cleanup:
                cleanup.push_async_callback(stop_folder_watch_service)
                cleanup.push_async_callback(job_manager.shutdown)
                if _dag_pool is not None:
                    cleanup.callback(_dag_pool.shutdown, wait=True, cancel_futures=True)
                cleanup.callback(_clear_pool, None)
                for hook in reversed(extra_shutdown or []):
                    cleanup.push_async_callback(hook)

    return lifespan


# ---------------------------------------------------------------------------
# Frontend SPA mount
# ---------------------------------------------------------------------------


def _mount_frontend(app: FastAPI) -> None:
    """Mount the release-generated frontend if static/ exists.

    In local/pip-installed mode the bundled SPA is served directly by
    FastAPI (no nginx needed). A source-only developer checkout before a
    frontend build has no static directory, so this is a no-op.
    """
    from spectra_sherpa._paths import get_static_dir

    static_dir = get_static_dir()
    index_html = static_dir / "index.html"
    if not index_html.is_file():
        logger.debug("No static/index.html found — frontend not mounted (Docker/cloud mode)")
        return

    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def _missing_api(path: str):
        # Unknown API endpoints must never become SPA HTML or a misleading
        # 405 from the GET-only page fallback in a bundled installation.
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    @app.get("/{path:path}")
    async def _spa_catchall(request: Request, path: str):
        # Let API and WebSocket routes take priority (already registered)
        # This only fires for paths that don't match any other route
        file_path = (static_dir / path).resolve()
        if file_path.is_file() and file_path.is_relative_to(static_dir):
            return FileResponse(str(file_path))
        return FileResponse(str(index_html))

    logger.info("Frontend SPA mounted from %s", static_dir)


async def _authorize_workflow_channel(requested: str, ws_user: Any) -> str | None:
    """Audit Item 1 (Critical): gate ``workflow:{id}`` WS subscription.

    ``workflow:{id}`` carries another user's node ids, statuses, timing,
    and error strings during execution.  Returns ``requested`` only when
    ``ws_user`` owns that workflow or is an admin; ``None`` otherwise —
    including for an unknown id, which is denied without confirming
    existence.  Extracted to module scope so the security boundary is
    directly unit-testable.
    """
    if ws_user is None:
        return None
    try:
        wf_id = int(requested.split(":", 1)[1])
    except (TypeError, ValueError):
        return None

    from sqlalchemy import select

    from spectra_sherpa.app.contracts.auth_resolver import is_admin_user
    from spectra_sherpa.app.db.session import async_session
    from spectra_sherpa.app.models.workflow import Workflow

    async with async_session() as session:
        from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
        from spectra_sherpa.app.contracts.scientific_access import require_scientific_access

        if uses_managed_project_access():
            workflow = await session.get(Workflow, wf_id, populate_existing=True)
            if workflow is None:
                return None
            try:
                await require_scientific_access(session, ws_user.id, workflow.project_id, "read")
            except Exception:
                return None
            return requested
        owner_id = (await session.execute(select(Workflow.user_id).where(Workflow.id == wf_id))).scalar_one_or_none()
    if owner_id is None:
        return None
    if owner_id == ws_user.id or await is_admin_user(ws_user):
        return requested
    return None


# ---------------------------------------------------------------------------
# WebSocket endpoint (standalone — registered on app inside create_app)
# ---------------------------------------------------------------------------


async def _admit_websocket_transport_event(
    websocket: WebSocket,
    *,
    event: str,
    client_host: str | None,
    user: Any,
) -> bool:
    provider: WebSocketAdmissionProvider | None = getattr(
        websocket.app.state,
        "websocket_admission_provider",
        None,
    )
    if provider is None:
        return True
    try:
        decision = await provider(
            event,
            client_host,
            int(user.id) if user is not None and user.id is not None else None,
        )
    except Exception:
        logger.exception("WebSocket transport admission failed closed")
        decision = WebSocketAdmissionDecision(
            allowed=False,
            reason="transport_authority_unavailable",
            retry_after_seconds=1,
        )
    if decision.allowed:
        return True
    await websocket.send_json(
        {
            "type": "error",
            "detail": "Managed trial transport admission refused",
            "reason": decision.reason,
            "retry_after_seconds": max(1, int(decision.retry_after_seconds)),
        }
    )
    await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
    return False


async def _cancel_ws_requests(registry, websocket):
    if registry is not None:
        await registry.requests.close(websocket)


async def websocket_endpoint(websocket: WebSocket) -> None:
    # Build a local WS rate limiter (the llm route module is no longer in OSS).
    from spectra_sherpa.app.core.app_paths import get_app_data_paths
    from spectra_sherpa.app.services.rate_limiter import RateLimiter

    _llm_rate_limiter = RateLimiter(
        max_calls=settings.max_llm_requests_per_hour,
        period_sec=3600,
        state_path=get_app_data_paths(settings.data_dir).llm_rate_limits_state,
    )

    # Determine if auth is required for this connection (mode-dependent).
    from spectra_sherpa.app.contracts.auth_resolver import user_allows_compute
    from spectra_sherpa.app.core.mode_policy import (
        blocks_local_network_client,
    )
    from spectra_sherpa.app.core.mode_policy import (
        requires_ws_auth as _requires_ws_auth,
    )
    from spectra_sherpa.app.core.request_id import mint_request_id, use_request_id
    from spectra_sherpa.app.services.ws_auth import (
        authenticate_ws_message,
        require_authenticated_action,
        require_live_ws_session,
        resolve_initial_ws_user,
        stamp_last_active,
    )
    from spectra_sherpa.app.services.ws_handlers import handle_subscribe, handle_unsubscribe

    ws_client_host = get_client_host(websocket)
    if blocks_local_network_client(ws_client_host):
        logger.warning("Blocked non-loopback local-mode websocket client_host=%r", ws_client_host)
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    requires_ws_auth = _requires_ws_auth(ws_client_host)

    # ── Phase 1: resolve implicit local identity only ──
    # Remote connections start unauthenticated and must send a first-message
    # authenticate action before any privileged WebSocket action.
    ws_user = await resolve_initial_ws_user(
        websocket,
        client_host=ws_client_host,
        requires_auth=requires_ws_auth,
    )

    if ws_user is not None and hasattr(ws_user, "is_active") and not ws_user.is_active:
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await stamp_last_active(ws_user)

    job_channel = f"jobs:{ws_user.id}" if ws_user and ws_user.id is not None else None
    ws_registry = getattr(websocket.app.state, "ws_action_registry", None)

    async def _resolve_channel(requested: str | None) -> str | None:
        # handle_subscribe retains this resolver as the per-delivery authorizer.
        if not requested or not await require_live_ws_session(websocket):
            return None
        if requested == "jobs":
            return job_channel
        if requested.startswith("jobs:"):
            # v0.4.1 Phase 2: is_superuser moved to ManagedUserAccount;
            # OSS asks the server-registered admin resolver instead of
            # reading an attribute that no longer exists on the OSS
            # User model. Local mode has no superusers, so is_admin_user
            # returns False there (correct default).
            from spectra_sherpa.app.contracts.auth_resolver import is_admin_user

            if ws_user and await is_admin_user(ws_user):
                return requested
            if requested == job_channel:
                return requested
            return None
        # Audit Item 1 (Critical): workflow status channels are
        # ownership-gated (see _authorize_workflow_channel).
        if requested.startswith("workflow:"):
            return await _authorize_workflow_channel(requested, ws_user)
        # The core only produces events for job and workflow channels. Do not
        # treat an arbitrary client-supplied name as a future extension point:
        # once a producer broadcasts on such a channel, every prior subscriber
        # would receive its payload without an ownership decision. A new
        # channel family requires a core change here with explicit actor-aware
        # authorization; the action registry does not authorize channels.
        return None

    # ---- Action dispatcher ----
    # Send a server-side ping when the connection is idle for this many seconds.
    # Clients may respond with {"action": "pong"} (or simply send any message).
    # If the write fails the connection is broken and we clean up immediately.
    _WS_IDLE_TIMEOUT = max(1.0, float(settings.ws_idle_timeout_sec))

    await ws_manager.connect(websocket)
    try:
        if not await _admit_websocket_transport_event(
            websocket,
            event="connect",
            client_host=ws_client_host,
            user=ws_user,
        ):
            return
        while True:
            try:
                payload = await asyncio.wait_for(websocket.receive_json(), timeout=_WS_IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                if not await require_live_ws_session(websocket):
                    break
                # Connection has been idle — probe it before assuming it is alive.
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break  # Write failed: socket is gone, fall through to disconnect
                continue

            # Bind a per-message request_id so every log line emitted by
            # the dispatch path (and the action handlers it calls) is
            # correlatable. Inbound ``request_id`` from the client wins;
            # otherwise mint one. Symmetric to the HTTP middleware.
            inbound_id = payload.get("request_id") if isinstance(payload, dict) else None
            with use_request_id(str(inbound_id) if inbound_id else mint_request_id()):
                action = payload.get("action") or payload.get("type")
                logger.info("WS action received: %s", action)

                if not await _admit_websocket_transport_event(
                    websocket,
                    event=str(action or "unknown"),
                    client_host=ws_client_host,
                    user=ws_user,
                ):
                    return

                if not await require_live_ws_session(websocket):
                    break

                if action == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue
                if action == "pong":
                    continue

                # ── First-message auth (canonical path for browsers) ──
                # Clients send credentials as the first WebSocket frame instead
                # of via URL query params.  Preferred because it keeps tokens
                # out of server logs and browser history.
                if action == "authenticate":
                    await _cancel_ws_requests(ws_registry, websocket)
                    # Reauthentication cannot carry the previous actor's channels.
                    await ws_manager.disconnect(websocket)
                    ws_user = await authenticate_ws_message(
                        payload,
                        client_host=ws_client_host,
                        current_user=ws_user,
                    )
                    if ws_user and ws_user.id is not None:
                        job_channel = f"jobs:{ws_user.id}"
                        await stamp_last_active(ws_user)
                    if ws_user is None:
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        break
                    if not await user_allows_compute(ws_user):
                        await websocket.send_json({"type": "error", "detail": "Managed trial access is not active"})
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        break
                    # Remember the bearer token supplied during authentication so
                    # subsequent protected actions can revalidate it against the
                    # current session authority (expiry, revocation, active account).
                    websocket.state.ws_auth_token = payload.get("token")
                    websocket.state.ws_auth_api_key = payload.get("api_key")
                    websocket.state.ws_auth_user_id = ws_user.id if ws_user else None
                    await websocket.send_json({"type": "authenticated", "user_id": ws_user.id if ws_user else None})
                    continue

                # Guard: reject any action before auth on enterprise connections
                if require_authenticated_action(requires_auth=requires_ws_auth, ws_user=ws_user):
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    break
                if not await user_allows_compute(ws_user):
                    await websocket.send_json({"type": "error", "detail": "Managed trial access is not active"})
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    break

                if action == "subscribe":
                    await handle_subscribe(
                        websocket, payload, ws_user, _llm_rate_limiter, resolve_channel=_resolve_channel
                    )
                elif action == "unsubscribe":
                    await handle_unsubscribe(
                        websocket, payload, ws_user, _llm_rate_limiter, resolve_channel=_resolve_channel
                    )
                elif ws_registry is not None and await ws_registry.dispatch(
                    action,
                    websocket,
                    payload,
                    ws_user,
                    _llm_rate_limiter,
                    background=True,
                ):
                    continue
                else:
                    await websocket.send_json({"type": "error", "detail": "Unknown action"})
    except WebSocketDisconnect:
        pass
    finally:
        await _cancel_ws_requests(ws_registry, websocket)
        await ws_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    api_router: APIRouter | None = None,
    extra_routers: list[RouterMount] | None = None,
    extra_startup: list[Callable[[], Awaitable[None]]] | None = None,
    extra_shutdown: list[Callable[[], Awaitable[None]]] | None = None,
    extra_lifespans: list[ApplicationLifespan] | None = None,
    extra_middleware: list[Callable[[FastAPI], None]] | None = None,
    extra_ws_action_registrars: list[WebSocketRegistryHook] | None = None,
    websocket_admission_provider: WebSocketAdmissionProvider | None = None,
    include_server_routers: bool = True,
    include_actor_compat_route: bool = True,
    include_websocket: bool = True,
    include_frontend: bool = True,
) -> FastAPI:
    """Build and return the FastAPI application.

    All parameters are optional — called with no arguments, the result is
    identical to the previous module-level singleton.

    Repo 2 (server) calls this with extra hooks to inject cloud-only
    routers, startup tasks, and middleware without forking this module.
    Product factories may supply app-scoped ``extra_lifespans`` to own paired
    startup/cleanup after core startup. No implementation is auto-discovered.
    """
    origins = get_cors_origins()
    _allow_all = origins == ["*"]

    mounts = _normalize_router_mounts(extra_routers)

    _app = FastAPI(
        title=settings.app_name,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=compose_lifespan(_make_lifespan(extra_startup, extra_shutdown), extra_lifespans or ()),
    )
    from spectra_sherpa.app.services.ws_action_registry import build_default_ws_action_registry

    _app.state.ws_action_registry = build_default_ws_action_registry()

    from fastapi.responses import JSONResponse

    from spectra_sherpa.app.services.encryption import CredentialStorageUnavailable

    async def _credential_storage_unavailable(_request, exc: CredentialStorageUnavailable):
        # Persistent credential operations are refused; analysis stays available.
        return JSONResponse(status_code=409, content={"detail": str(exc), "code": "credential_storage_unavailable"})

    _app.add_exception_handler(CredentialStorageUnavailable, _credential_storage_unavailable)

    from spectra_sherpa.app.core.desktop_policy import LinkedConfigurationRefused

    async def _linked_configuration(_request, exc: LinkedConfigurationRefused):
        return JSONResponse(status_code=409, content={"detail": str(exc), "code": "linked_configuration_refused"})

    _app.add_exception_handler(LinkedConfigurationRefused, _linked_configuration)
    _app.state.websocket_admission_provider = websocket_admission_provider
    for registrar in extra_ws_action_registrars or []:
        registrar(_app)

    # --- Middleware ---
    # Starlette's ``add_middleware`` prepends to ``user_middleware`` (so the
    # LAST-registered middleware becomes the OUTERMOST wrapper and runs FIRST
    # on an incoming request). The v0.4.1 Phase 2 JWT handshake requires a
    # specific inbound order:
    #
    #     CORS  →  RequestIDMiddleware  →  extra_middleware (EEM)
    #           →  RateLimitMiddleware  →  api_key_middleware  →  route
    #
    # EEM must run BEFORE ``api_key_middleware`` so the Bearer-token stamp
    # (``request.state.authenticated``) is in place by the time the OSS
    # gateway checks it — otherwise every managed-auth Bearer request 401s
    # at the gateway even though the server validated the token. Register
    # innermost-first so this inbound order falls out of the prepend
    # semantics. CORS stays outermost so its headers wrap early 401/403s
    # from any inner middleware. RequestIDMiddleware sits just inside CORS
    # so every middleware downstream (and every route logger) sees the
    # request ID via the ``request_id`` ContextVar / log filter.
    from spectra_sherpa.app.core.request_id import RequestIDMiddleware
    from spectra_sherpa.app.services.audit import AuditMiddleware

    # AuditMiddleware is registered FIRST so Starlette's prepend semantics
    # place it INNERMOST — it runs after api_key_middleware has populated
    # ``request.state.user`` / ``request.state.api_key`` and after
    # RequestIDMiddleware has bound the request id, so the AuditContext
    # this middleware sets carries the correct actor + request id for
    # every event emitted during the request. No-op when audit is
    # disabled — see ``app_config.audit_enabled``.
    _app.add_middleware(AuditMiddleware)
    _app.middleware("http")(api_key_middleware)
    _app.add_middleware(RateLimitMiddleware)
    for mw in extra_middleware or []:
        mw(_app)
    _app.add_middleware(RequestIDMiddleware)
    _app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_trusted_hosts(origins))
    if _allow_all:
        # A reflected/wildcard origin combined with
        # ``allow_credentials=True`` lets ANY site issue credentialed
        # cross-origin requests and read the response.  Browsers forbid
        # ``*`` + credentials anyway; make that explicit and refuse to
        # send credentialed CORS in wildcard mode.  Operators that need
        # credentialed cross-origin must set an explicit CORS_ORIGINS
        # allowlist.  Not a hard startup failure — wildcard is a valid
        # convenience for non-credentialed/dev use — but loudly warned.
        logger.warning(
            "CORS_ORIGINS='*' — wildcard origin reflection is enabled with "
            "credentials DISABLED. Set an explicit CORS_ORIGINS allowlist for "
            "any deployment that relies on credentialed cross-origin requests."
        )
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if not _allow_all else [],
        allow_origin_regex=r".*" if _allow_all else None,
        allow_credentials=not _allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Routers ---
    _app.include_router(
        (
            api_router
            if api_router is not None
            else build_api_router(
                include_server_routers=include_server_routers,
                include_actor_compat_route=include_actor_compat_route,
            )
        ),
        prefix="/api/v1",
    )
    for router, kwargs in mounts:
        _app.include_router(router, **kwargs)

    # --- Health endpoint ---
    @_app.get("/api/health")
    async def root() -> dict:
        return {"status": "ok"}

    @_app.get("/api/ready")
    async def ready() -> JSONResponse:
        try:
            async with async_session() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            logger.warning("Readiness check failed: database unavailable", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "unready",
                    "database": "unavailable",
                },
            )

        content: dict[str, Any] = {
            "status": "ok",
            "database": "ok",
        }
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    # --- WebSocket ---
    if include_websocket:
        _app.add_api_websocket_route("/ws", websocket_endpoint)

    # --- Frontend SPA ---
    if include_frontend:
        _mount_frontend(_app)

    return _app


# Module-level singleton: backward-compat for Gunicorn, tests, and imports.
app = create_app()
