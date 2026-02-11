from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeAlias

# Force non-interactive matplotlib backend before SpectroChemPy imports it.
# The macOS backend requires the main thread, but FastAPI runs handlers
# in worker threads — 'agg' works everywhere without a display.
import matplotlib
matplotlib.use("agg")

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.api import build_api_router
from app.api.deps import get_user_from_credentials
from app.core.config import app_config, settings
from app.core.logging import configure_logging
from app.core.security import (
    _is_loopback,
    api_key_middleware,
    get_client_host,
    is_valid_api_key,
    is_valid_bearer_token,
)
from app.core.demo_enforcement import DemoEnforcementMiddleware
from app.core.startup import (
    ensure_data_dirs,
    ensure_database_ready,
    wait_for_database_ready,
    ensure_default_user,
    ensure_egress_defaults,
    link_hybrid_identity,
    reconcile_stale_jobs,
    ensure_spectrochempy_testdata,
    ensure_workflow_templates,
    validate_concurrency_settings,
    validate_security_settings,
)
from app.db.session import async_session
from app.services.job_manager import job_manager
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

RouterMount: TypeAlias = tuple[APIRouter, str | Mapping[str, Any]]


def get_cors_origins() -> list[str]:
    """
    Get CORS allowed origins based on environment and mode.

    Priority:
    1. CORS_ORIGINS env var (comma-separated list)
    2. Mode-based defaults:
       - local: Allow all origins (development convenience)
       - hybrid/demo: Localhost + configured domains

    NOTE: For hybrid/demo production deployments, CORS_ORIGINS must be set
    to your frontend domain(s). The localhost defaults are only for development.
    """
    # Check for explicit CORS configuration
    cors_env = os.getenv("CORS_ORIGINS", "").strip()
    if cors_env:
        return [origin.strip() for origin in cors_env.split(",") if origin.strip()]

    # Default origins for development
    default_origins = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]

    # In local mode, also allow the frontend to run on any port
    from app.core.mode_policy import cors_allow_all
    if cors_allow_all():
        return ["*"]

    # For hybrid/demo/cloud modes, note if CORS_ORIGINS is not explicitly set
    if app_config.mode == "demo":
        logger.warning(
            "CORS_ORIGINS not set for demo mode — using localhost defaults only. "
            "Set CORS_ORIGINS to your production frontend domain(s).",
        )
    else:
        logger.info(
            "CORS_ORIGINS not set for %s mode — using localhost defaults.",
            app_config.mode,
        )

    # For hybrid/demo/cloud modes, add production URL if configured
    if app_config.api_base_url and app_config.api_base_url not in default_origins:
        default_origins.append(app_config.api_base_url)

    return default_origins


def _try_leader_lock() -> bool:
    """Acquire a non-blocking file lock for one-time startup tasks.

    Returns True if this worker is the leader (lock acquired).
    On platforms without fcntl (Windows) returns True so startup still runs.
    """
    try:
        import fcntl
    except ImportError:
        return True

    lock_path = settings.data_dir / ".startup.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Keep fd open for process lifetime (lock released on exit)
        logger.info("Leader lock acquired: %s", lock_path)
        return True
    except OSError as exc:
        logger.warning(
            "Could not acquire leader lock %s: %s — running as follower. "
            "If no leader is running, delete the lock file and restart.",
            lock_path, exc,
        )
        return False


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

        try:
            # Phase 1: per-worker setup (safe to run in every worker)
            logger.info("Phase 1: per-worker setup ...")
            configure_logging()
            validate_security_settings()  # Fail fast if security config is invalid
            validate_concurrency_settings()  # Log concurrency model info
            ensure_data_dirs()
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
                logger.info("  → link_hybrid_identity")
                await link_hybrid_identity()
                logger.info("  → reconcile_stale_jobs")
                await reconcile_stale_jobs()
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
            import app.services.tools.builtin  # noqa: F401
            from app.services.tools import tool_registry as _tool_reg
            logger.info("Registered %d built-in tool(s)", len(_tool_reg))

            # Discover and load third-party plugins (may register additional tools)
            from app.services.plugin_loader import discover_plugins
            discover_plugins()

            # Start network health monitoring (HYBRID mode only)
            from app.services.network_health import start_network_health_service
            await start_network_health_service()
            logger.info("Phase 3 complete")

            # Phase 4: extension hooks (Repo 2 injects server-only startup here)
            if extra_startup:
                logger.info("Phase 4: %d extension hook(s) ...", len(extra_startup))
            for hook in (extra_startup or []):
                await hook()

            logger.info("Application startup complete")
        except Exception:
            logger.critical(
                "STARTUP FAILED — lifespan exception:\n%s", _tb.format_exc(),
            )
            raise

        yield

        # === SHUTDOWN ===
        # Extension shutdown hooks run first so server add-ons can still
        # access core services before they are torn down.
        for hook in (extra_shutdown or []):
            await hook()

        await job_manager.shutdown()

        # Stop network health monitoring
        from app.services.network_health import stop_network_health_service
        await stop_network_health_service()

        # Close SpectraSherpa service
        from app.services.spectrasherpa import close_spectrasherpa_service
        await close_spectrasherpa_service()

        # Close Sherpa advisor and engine
        from app.services.sherpa_advisor import close_sherpa_advisor
        await close_sherpa_advisor()
        from app.services.sherpa_engine import close_sherpa_engine
        await close_sherpa_engine()

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
    # Import rate limiter here to avoid circular imports
    from app.api.v1.routes.llm import _llm_rate_limiter
    from app.services.ws_handlers import (
        handle_llm_chat,
        handle_sherpa_chat,
        handle_sherpa_decide,
        handle_sherpa_sync,
        handle_subscribe,
        handle_tool_invoke,
        handle_tool_list,
        handle_unsubscribe,
    )

    api_key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
    auth_header = websocket.headers.get("authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else websocket.query_params.get("token")
    has_credentials = bool(token or api_key)

    # Determine if auth is required for this connection (mode-dependent).
    from app.core.mode_policy import requires_ws_auth as _requires_ws_auth
    ws_client_host = get_client_host(websocket)
    requires_ws_auth = _requires_ws_auth(ws_client_host)

    if requires_ws_auth:
        token_valid = bool(token) and is_valid_bearer_token(token)
        api_key_valid = bool(api_key) and await is_valid_api_key(api_key)
        if not (token_valid or api_key_valid):
            await websocket.accept()
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    # Resolve user for LLM operations (needed for rate limiting and egress)
    ws_user = None
    async with async_session() as session:
        # Prefer user JWT identity over machine API key when both are present.
        if token:
            ws_user = await get_user_from_credentials(session, token=token, client_host=ws_client_host)
        if ws_user is None and api_key:
            ws_user = await get_user_from_credentials(session, api_key=api_key, client_host=ws_client_host)
        if ws_user is None and not has_credentials:
            ws_user = await get_user_from_credentials(session, client_host=ws_client_host)

    # Credentials were provided but didn't resolve to a user.
    if has_credentials and ws_user is None:
        if requires_ws_auth:
            # Non-loopback / demo: reject invalid credentials.
            await websocket.accept()
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        # Loopback local/hybrid: stale credentials from prior demo usage
        # shouldn't block the implicit user. Fall back gracefully.
        logger.debug("Stale WS credentials on loopback — falling back to implicit identity")
        async with async_session() as session:
            ws_user = await get_user_from_credentials(session, client_host=ws_client_host)

    if ws_user is not None and hasattr(ws_user, "is_active") and not ws_user.is_active:
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    job_channel = f"jobs:{ws_user.id}" if ws_user and ws_user.id is not None else None

    def _resolve_channel(requested: str | None) -> str | None:
        if not requested:
            return None
        if requested == "jobs":
            return job_channel
        if requested.startswith("jobs:"):
            if ws_user and ws_user.is_superuser:
                return requested
            if requested == job_channel:
                return requested
            return None
        return requested

    # ---- Action dispatcher ----
    await ws_manager.connect(websocket)
    try:
        while True:
            payload = await websocket.receive_json()
            action = payload.get("action")
            logger.info("WS action received: %s", action)

            if action == "subscribe":
                await handle_subscribe(websocket, payload, ws_user, _llm_rate_limiter, resolve_channel=_resolve_channel)
            elif action == "unsubscribe":
                await handle_unsubscribe(websocket, payload, ws_user, _llm_rate_limiter, resolve_channel=_resolve_channel)
            elif action == "llm_chat":
                await handle_llm_chat(websocket, payload, ws_user, _llm_rate_limiter)
            elif action == "sherpa_sync":
                await handle_sherpa_sync(websocket, payload, ws_user, _llm_rate_limiter)
            elif action == "sherpa_decide":
                await handle_sherpa_decide(websocket, payload, ws_user, _llm_rate_limiter)
            elif action == "sherpa_chat":
                await handle_sherpa_chat(websocket, payload, ws_user, _llm_rate_limiter)
            elif action == "tool_list":
                await handle_tool_list(websocket, payload, ws_user, _llm_rate_limiter)
            elif action == "tool_invoke":
                await handle_tool_invoke(websocket, payload, ws_user, _llm_rate_limiter)
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
    include_server_routers: bool = True,
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
        lifespan=_make_lifespan(extra_startup, extra_shutdown),
    )

    # --- Middleware (order matters: outermost first) ---
    _app.middleware("http")(api_key_middleware)
    _app.add_middleware(DemoEnforcementMiddleware)
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if not _allow_all else [],
        allow_origin_regex=r".*" if _allow_all else None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for mw in (extra_middleware or []):
        mw(_app)

    # --- Routers ---
    _app.include_router(
        build_api_router(include_server_routers=include_server_routers),
        prefix="/api/v1",
    )
    for router, kwargs in mounts:
        _app.include_router(router, **kwargs)

    # --- Health endpoint ---
    @_app.get("/api/health")
    async def root() -> dict:
        return {"status": "ok"}

    # --- WebSocket ---
    _app.add_api_websocket_route("/ws", websocket_endpoint)

    # --- Frontend SPA ---
    _mount_frontend(_app)

    return _app


# Module-level singleton: backward-compat for Gunicorn, tests, and imports.
app = create_app()
