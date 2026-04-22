from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any, TypeAlias

# Force non-interactive matplotlib backend before SpectroChemPy imports it.
# The macOS backend requires the main thread, but FastAPI runs handlers
# in worker threads — 'agg' works everywhere without a display.
# matplotlib is a transitive dep of spectrochempy (optional); guard the import.
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

from spectra_sherpa.app.api.v1.api import build_api_router
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
    ensure_spectrochempy_data,
    ensure_spectrochempy_testdata,
    ensure_workflow_templates,
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


def get_cors_origins() -> list[str]:
    """
    Get CORS allowed origins based on environment and mode.

    Priority:
    1. CORS_ORIGINS env var (comma-separated list)
    2. Mode-based defaults: localhost origins for all modes

    NOTE: For hybrid/enterprise production deployments, CORS_ORIGINS must be set
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
    if app_config.mode != "local":
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
                logger.info("  → ensure_spectrochempy_data")
                ensure_spectrochempy_data()
                logger.info("  → ensure_spectrochempy_testdata")
                await ensure_spectrochempy_testdata()
                logger.info("  → ensure_workflow_templates")
                await ensure_workflow_templates()
                logger.info("Phase 2 complete")
            else:
                logger.info("Follower worker: waiting for leader to finish DB setup ...")
                # Wait for leader to finish DB schema setup (no DB writes on followers).
                await wait_for_database_ready()
                logger.info("Follower: DB ready")

            # Phase 3: per-worker setup that depends on DB being ready
            logger.info("Phase 3: tools + plugins ...")
            # Register built-in MCP tools (import triggers @register_tool decorators)
            import spectra_sherpa.app.services.tools.builtin  # noqa: F401
            from spectra_sherpa.app.services.tools import tool_registry as _tool_reg

            logger.info("Registered %d built-in tool(s)", len(_tool_reg))

            # Discover and load third-party plugins (may register additional tools)
            from spectra_sherpa.app.services.plugin_loader import discover_plugins

            discover_plugins()

            # Start network health monitoring (HYBRID mode only)
            from spectra_sherpa.app.services.network_health import start_network_health_service

            await start_network_health_service()

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

            # Phase 5: DAG worker pool for CPU-bound node execution
            import multiprocessing
            from concurrent.futures import ProcessPoolExecutor

            from spectra_sherpa.app.services.dag.executor import set_default_pool

            pool_size = settings.dag_worker_pool_size
            try:
                _dag_pool = ProcessPoolExecutor(
                    max_workers=pool_size,
                    mp_context=multiprocessing.get_context("spawn"),
                )
                set_default_pool(_dag_pool)
                logger.info("DAG worker pool: %d processes (spawn)", pool_size)
            except (PermissionError, OSError) as exc:
                logger.warning(
                    "Could not create DAG worker pool (%s). " "CPU-bound nodes will run in-process.",
                    exc,
                )
                _dag_pool = None

            logger.info("Application startup complete")
        except Exception:
            logger.critical(
                "STARTUP FAILED — lifespan exception:\n%s",
                _tb.format_exc(),
            )
            raise

        yield

        # === SHUTDOWN ===
        # Extension shutdown hooks run first so server add-ons can still
        # access core services before they are torn down.
        for hook in extra_shutdown or []:
            await hook()

        # Shut down DAG worker pool
        from spectra_sherpa.app.services.dag.executor import set_default_pool as _clear_pool

        _clear_pool(None)
        if _dag_pool is not None:
            _dag_pool.shutdown(wait=True, cancel_futures=True)
            logger.info("DAG worker pool shut down")

        await job_manager.shutdown()

        # Stop folder watch polling
        from spectra_sherpa.app.services.folder_watch_service import stop_folder_watch_service

        await stop_folder_watch_service()

        # Stop network health monitoring
        from spectra_sherpa.app.services.network_health import stop_network_health_service

        await stop_network_health_service()

    return lifespan


# ---------------------------------------------------------------------------
# Frontend SPA mount
# ---------------------------------------------------------------------------


def _mount_frontend(app: FastAPI) -> None:
    """Mount the pre-built frontend if static/ exists.

    In local/pip-installed mode the bundled SPA is served directly by
    FastAPI (no nginx needed). In Docker/cloud mode static/ won't exist
    inside the backend container, so this is a no-op.
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

    @app.get("/{path:path}")
    async def _spa_catchall(request: Request, path: str):
        # Let API and WebSocket routes take priority (already registered)
        # This only fires for paths that don't match any other route
        file_path = (static_dir / path).resolve()
        if file_path.is_file() and file_path.is_relative_to(static_dir):
            return FileResponse(str(file_path))
        return FileResponse(str(index_html))

    logger.info("Frontend SPA mounted from %s", static_dir)


# ---------------------------------------------------------------------------
# WebSocket endpoint (standalone — registered on app inside create_app)
# ---------------------------------------------------------------------------


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
    from spectra_sherpa.app.core.mode_policy import requires_ws_auth as _requires_ws_auth
    from spectra_sherpa.app.services.ws_auth import (
        authenticate_ws_message,
        require_authenticated_action,
        resolve_initial_ws_user,
        stamp_last_active,
    )
    from spectra_sherpa.app.services.ws_handlers import handle_subscribe, handle_unsubscribe

    ws_client_host = get_client_host(websocket)
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
        if not requested:
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
        # Allow workflow status channels (workflow:{workflow_id})
        if requested.startswith("workflow:"):
            return requested
        return requested

    # ---- Action dispatcher ----
    # Send a server-side ping when the connection is idle for this many seconds.
    # Clients may respond with {"action": "pong"} (or simply send any message).
    # If the write fails the connection is broken and we clean up immediately.
    _WS_IDLE_TIMEOUT = max(1.0, float(settings.ws_idle_timeout_sec))

    await ws_manager.connect(websocket)
    try:
        while True:
            try:
                payload = await asyncio.wait_for(websocket.receive_json(), timeout=_WS_IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                # Connection has been idle — probe it before assuming it is alive.
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break  # Write failed: socket is gone, fall through to disconnect
                continue

            action = payload.get("action") or payload.get("type")
            logger.info("WS action received: %s", action)

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
                ws_user = await authenticate_ws_message(
                    payload,
                    client_host=ws_client_host,
                    current_user=ws_user,
                )
                if ws_user and ws_user.id is not None:
                    job_channel = f"jobs:{ws_user.id}"
                    await stamp_last_active(ws_user)
                if require_authenticated_action(requires_auth=requires_ws_auth, ws_user=ws_user):
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    break
                await websocket.send_json({"type": "authenticated", "user_id": ws_user.id if ws_user else None})
                continue

            # Guard: reject any action before auth on enterprise connections
            if require_authenticated_action(requires_auth=requires_ws_auth, ws_user=ws_user):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                break

            if action == "subscribe":
                await handle_subscribe(websocket, payload, ws_user, _llm_rate_limiter, resolve_channel=_resolve_channel)
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
            ):
                continue
            else:
                await websocket.send_json({"type": "error", "detail": "Unknown action"})
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    extra_routers: list[RouterMount] | None = None,
    extra_startup: list[Callable[[], Awaitable[None]]] | None = None,
    extra_shutdown: list[Callable[[], Awaitable[None]]] | None = None,
    extra_middleware: list[Callable[[FastAPI], None]] | None = None,
    extra_ws_action_registrars: list[WebSocketRegistryHook] | None = None,
    include_server_routers: bool = True,
    include_actor_compat_route: bool = True,
) -> FastAPI:
    """Build and return the FastAPI application.

    All parameters are optional — called with no arguments, the result is
    identical to the previous module-level singleton.

    Repo 2 (server) calls this with extra hooks to inject cloud-only
    routers, startup tasks, and middleware without forking this module.
    """
    origins = get_cors_origins()
    _allow_all = origins == ["*"]

    mounts = _normalize_router_mounts(extra_routers)

    _app = FastAPI(
        title=settings.app_name,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=_make_lifespan(extra_startup, extra_shutdown),
    )
    from spectra_sherpa.app.services.ws_action_registry import build_default_ws_action_registry

    _app.state.ws_action_registry = build_default_ws_action_registry()
    for registrar in extra_ws_action_registrars or []:
        registrar(_app)

    # --- Middleware (last added = outermost in Starlette's onion model) ---
    # Extra middleware (e.g. EnterpriseEnforcementMiddleware) is added first
    # so that CORSMiddleware wraps it — ensuring CORS headers appear even
    # on early 401/403 rejection responses from enforcement middleware.
    for mw in extra_middleware or []:
        mw(_app)
    _app.middleware("http")(api_key_middleware)
    _app.add_middleware(RateLimitMiddleware)
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if not _allow_all else [],
        allow_origin_regex=r".*" if _allow_all else None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Routers ---
    _app.include_router(
        build_api_router(
            include_server_routers=include_server_routers,
            include_actor_compat_route=include_actor_compat_route,
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
        from spectra_sherpa.app.services.plugin_loader import plugin_load_failures

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
        if plugin_load_failures:
            content["status"] = "degraded"
            content["plugin_failure_count"] = len(plugin_load_failures)

        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    # --- WebSocket ---
    _app.add_api_websocket_route("/ws", websocket_endpoint)

    # --- Frontend SPA ---
    _mount_frontend(_app)

    return _app


# Module-level singleton: backward-compat for Gunicorn, tests, and imports.
app = create_app()
