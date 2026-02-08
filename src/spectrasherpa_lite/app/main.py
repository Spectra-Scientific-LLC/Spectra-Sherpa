from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Force non-interactive matplotlib backend before SpectroChemPy imports it.
# The macOS backend requires the main thread, but FastAPI runs handlers
# in worker threads — 'agg' works everywhere without a display.
import matplotlib
matplotlib.use("agg")

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.api import api_router
from app.api.deps import get_user_from_credentials
from app.core.config import app_config, settings
from app.core.logging import configure_logging
from app.core.security import api_key_middleware, is_valid_api_key, check_egress_permission
from app.core.demo_enforcement import DemoEnforcementMiddleware
from app.core.startup import (
    ensure_data_dirs,
    ensure_database_ready,
    ensure_default_user,
    ensure_egress_defaults,
    reconcile_stale_jobs,
    ensure_spectrochempy_testdata,
    ensure_workflow_templates,
    validate_concurrency_settings,
    validate_security_settings,
)
from app.db.session import async_session
from app.services.job_manager import job_manager
from app.services.llm import LLMService
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)


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
    if app_config.mode == "local":
        # For local development, we're permissive
        return ["*"]

    # For hybrid/demo/cloud modes, warn if CORS_ORIGINS is not explicitly set
    logger.warning(
        "CORS_ORIGINS not set for %s mode — using localhost defaults only. "
        "Set CORS_ORIGINS to your production frontend domain(s).",
        app_config.mode,
    )

    # For hybrid/demo/cloud modes, add production URL if configured
    if app_config.api_base_url and app_config.api_base_url not in default_origins:
        default_origins.append(app_config.api_base_url)

    return default_origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    # === STARTUP ===
    configure_logging()
    validate_security_settings()  # Fail fast if security config is invalid
    validate_concurrency_settings()  # Log concurrency model info
    ensure_data_dirs()
    await ensure_database_ready()
    await ensure_default_user()
    await ensure_egress_defaults()
    await reconcile_stale_jobs()
    await ensure_spectrochempy_testdata()
    await ensure_workflow_templates()

    # Discover and load third-party plugins
    from app.services.plugin_loader import discover_plugins
    discover_plugins()

    # Start network health monitoring (HYBRID mode only)
    from app.services.network_health import start_network_health_service
    await start_network_health_service()

    yield

    # === SHUTDOWN ===
    await job_manager.shutdown()

    # Stop network health monitoring
    from app.services.network_health import stop_network_health_service
    await stop_network_health_service()

    # Close SpectraSherpa service
    from app.services.spectrasherpa import close_spectrasherpa_service
    await close_spectrasherpa_service()

    # Close Sherpa advisor
    from app.services.sherpa_advisor import close_sherpa_advisor
    await close_sherpa_advisor()


# Determine CORS settings based on mode
cors_origins = get_cors_origins()
cors_allow_all = cors_origins == ["*"]

app = FastAPI(
    title=settings.app_name,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.middleware("http")(api_key_middleware)
app.add_middleware(DemoEnforcementMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if not cors_allow_all else [],
    allow_origin_regex=r".*" if cors_allow_all else None,  # Allow all in local mode
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")


def _mount_frontend(app: FastAPI) -> None:
    """Mount the pre-built frontend if static/ exists.

    In local/pip-installed mode the bundled SPA is served directly by
    FastAPI (no nginx needed). In Docker/cloud mode static/ won't exist
    inside the backend container, so this is a no-op.
    """
    from spectrasherpa_lite._paths import get_static_dir

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
        file_path = static_dir / path
        if file_path.is_file() and ".." not in path:
            return FileResponse(str(file_path))
        return FileResponse(str(index_html))

    logger.info("Frontend SPA mounted from %s", static_dir)


_mount_frontend(app)


@app.get("/api/health")
async def root() -> dict:
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    # Import rate limiter here to avoid circular imports
    from app.api.v1.routes.llm import _llm_rate_limiter

    api_key: str | None = None
    token: str | None = None

    # Local mode: skip auth validation entirely (implicit admin)
    if app_config.mode != "local":
        api_key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
        auth_header = websocket.headers.get("authorization", "")
        token = auth_header[7:] if auth_header.startswith("Bearer ") else None

        if not await is_valid_api_key(api_key or token):
            await websocket.accept()
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    # Resolve user for LLM operations (needed for rate limiting and egress)
    ws_user = None
    async with async_session() as session:
        ws_user = await get_user_from_credentials(session, api_key=api_key, token=token)

    await ws_manager.connect(websocket)
    try:
        while True:
            payload = await websocket.receive_json()
            action = payload.get("action")

            if action == "subscribe":
                channel = payload.get("channel")
                if not channel:
                    await websocket.send_json(
                        {"type": "error", "detail": "Missing channel"}
                    )
                    continue
                await ws_manager.subscribe(websocket, channel)
                await websocket.send_json({"type": "subscribed", "channel": channel})
            elif action == "unsubscribe":
                channel = payload.get("channel")
                if not channel:
                    await websocket.send_json(
                        {"type": "error", "detail": "Missing channel"}
                    )
                    continue
                await ws_manager.unsubscribe(websocket, channel)
                await websocket.send_json({"type": "unsubscribed", "channel": channel})
            elif action == "llm_chat":
                message = payload.get("message") or ""
                if not message:
                    await websocket.send_json(
                        {"type": "error", "detail": "Missing message"}
                    )
                    continue

                # Check egress permission (LLM requires network access)
                async with async_session() as permission_session:
                    allowed = await check_egress_permission(
                        ws_user,
                        "allow_llm_context",
                        data_type="metadata",
                        destination="llm_context",
                        session=permission_session,
                    )
                if not allowed:
                    await websocket.send_json(
                        {"type": "error", "detail": "LLM access is disabled for this user or mode"}
                    )
                    continue

                # Check rate limit (same as HTTP endpoint)
                user_key = f"user_{ws_user.id}" if ws_user and ws_user.id else "anonymous"
                if not _llm_rate_limiter.allow(user_key):
                    await websocket.send_json(
                        {"type": "error", "detail": "LLM rate limit exceeded. Try again later."}
                    )
                    continue

                conversation_id = payload.get("conversation_id")
                metadata = payload.get("metadata")
                async with async_session() as session:
                    service = LLMService(session, user=ws_user)
                    try:
                        convo_id, stream = await service.stream_chat(
                            message=message,
                            conversation_id=conversation_id,
                            metadata=metadata,
                        )
                    except ValueError as exc:
                        await websocket.send_json(
                            {"type": "error", "detail": str(exc)}
                        )
                        continue
                    await websocket.send_json(
                        {"type": "llm_start", "conversation_id": convo_id}
                    )
                    async for chunk in stream:
                        await websocket.send_json(
                            {
                                "type": "llm_chunk",
                                "conversation_id": convo_id,
                                "chunk": chunk,
                            }
                        )
                    await websocket.send_json(
                        {"type": "llm_done", "conversation_id": convo_id}
                    )
            elif action == "sherpa_sync":
                # Forward workflow state to cloud Sherpa advisor
                from app.services.sherpa_advisor import get_sherpa_advisor
                from app.schemas.sherpa import EgressTier, WorkflowStateSync

                advisor = get_sherpa_advisor()
                if not advisor.is_available:
                    await websocket.send_json(
                        {"type": "sherpa_status", "payload": {"connected": False, "reason": "not_configured"}}
                    )
                    continue

                # Check egress permission for spectrasherpa sync
                async with async_session() as permission_session:
                    allowed = await check_egress_permission(
                        ws_user,
                        "allow_spectrasherpa_sync",
                        data_type="workflow",
                        destination="spectrasherpa",
                        session=permission_session,
                    )
                if not allowed:
                    await websocket.send_json(
                        {"type": "error", "detail": "Sherpa sync not permitted for this user"}
                    )
                    continue

                try:
                    sync_data = payload.get("payload", {})
                    tier = EgressTier(sync_data.pop("tier", "structure"))
                    sync_msg = WorkflowStateSync(**sync_data)
                    recommendations = await advisor.sync_workflow(sync_msg, tier=tier)
                    await websocket.send_json({
                        "type": "sherpa_recommendations",
                        "payload": [r.model_dump(mode="json") for r in recommendations],
                    })
                except Exception as exc:
                    await websocket.send_json(
                        {"type": "error", "detail": f"Sherpa sync failed: {exc}"}
                    )

            elif action == "sherpa_decide":
                # Forward user decision on a Sherpa suggestion
                from app.services.sherpa_advisor import get_sherpa_advisor
                from app.schemas.sherpa import UserDecision

                advisor = get_sherpa_advisor()
                try:
                    decision = UserDecision(**payload.get("payload", {}))
                    delivered = await advisor.send_decision(decision)
                    await websocket.send_json({
                        "type": "sherpa_decision_ack",
                        "payload": {"delivered": delivered, "suggestion_id": decision.suggestion_id},
                    })
                except Exception as exc:
                    await websocket.send_json(
                        {"type": "error", "detail": f"Sherpa decision failed: {exc}"}
                    )

            else:
                await websocket.send_json(
                    {"type": "error", "detail": "Unknown action"}
                )
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
