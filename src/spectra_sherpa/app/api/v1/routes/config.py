"""
Configuration endpoint for frontend.

Returns client-safe configuration including:
- App mode (local, hybrid, enterprise)
- Feature flags
- LLM provider availability (checks env vars AND database)
- Rate limits (if enterprise mode)
"""

import json
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from spectra_sherpa.app.api.deps import get_current_user, get_session, get_user_from_credentials
from spectra_sherpa.app.core.app_paths import get_app_data_paths
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.core.llm_registry import PROVIDERS, get_provider
from spectra_sherpa.app.core.security import get_bearer_token_optional
from spectra_sherpa.app.models.api_key import APIKey
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.user import User

router = APIRouter(prefix="/config", tags=["config"])
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_subscription_overlay_cache: dict[str, dict] = {}


async def get_optional_current_user(
    session: AsyncSession = Depends(get_session),
    token: str | None = Depends(get_bearer_token_optional),
    api_key: str | None = Depends(api_key_header),
) -> User | None:
    """
    Resolve user context if credentials are present.

    Returns None for anonymous/public requests so /config remains publicly readable.
    """
    user = await get_user_from_credentials(session=session, api_key=api_key, token=token)
    if user is not None and hasattr(user, "is_active") and not user.is_active:
        return None
    return user


async def _check_provider_availability(
    provider_id: str,
    session: AsyncSession,
    user_id: int | None = None,
) -> bool:
    """
    Check if provider has an API key configured.
    Checks both environment variables and database.

    Args:
        provider_id: Provider identifier (e.g., 'openai')
        session: Database session

    Returns:
        True if API key is available from any source
    """
    try:
        provider = get_provider(provider_id)
    except ValueError:
        return False

    # Check environment variable
    if os.getenv(provider["env_var"]):
        return True

    # Check database (scoped to user key OR system key)
    # If user_id is None, only system keys are considered.
    query = select(APIKey.id).where(APIKey.service_name == provider_id)
    if user_id is None:
        query = query.where(APIKey.user_id.is_(None))
    else:
        query = query.where(or_(APIKey.user_id == user_id, APIKey.user_id.is_(None)))
    query = query.limit(1)

    result = await session.execute(query)
    return result.scalar_one_or_none() is not None


async def _load_subscription_overlay() -> dict | None:
    """Fetch subscription-backed config from the Sherpa server when configured."""
    from spectra_sherpa.app.services.spectrasherpa import spectrasherpa_config

    api_key = spectrasherpa_config.api_key
    if not api_key:
        return None

    base_url = spectrasherpa_config.api_base_url.rstrip("/")
    if not base_url.endswith("/api/v1"):
        base_url = f"{base_url}/api/v1"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{base_url}/config/subscription",
                headers={"X-Deployment-Key": api_key},
            )
        if response.status_code != 200:
            logger.warning("Subscription config fetch returned %s", response.status_code)
            return _subscription_overlay_cache.get(api_key)
        payload = response.json()
        _subscription_overlay_cache[api_key] = payload
        return payload
    except Exception:
        logger.warning("Failed to fetch subscription config overlay", exc_info=True)
        return _subscription_overlay_cache.get(api_key)


@router.get("")
async def get_config(
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_optional_current_user),
):
    """
    Get client-safe configuration with database-aware LLM status.

    Checks both environment variables AND database for API keys,
    providing accurate availability information to the frontend.

    Returns configuration without sensitive data (API keys).
    Used by frontend to determine available features.
    """
    # Get base config from environment
    config = app_config.to_client_safe()
    user_id = current_user.id if current_user is not None else None

    # Update LLM availability by checking actual sources
    for provider_id in PROVIDERS.keys():
        is_available = await _check_provider_availability(provider_id, session, user_id=user_id)
        if provider_id in config["llms"]:
            config["llms"][provider_id]["enabled"] = is_available

    if app_config.mode == "local":
        # Recalculate feature flags with true provider availability.
        has_llm = any(llm["enabled"] for llm in config["llms"].values())
        config["features"]["chatAssistant"] = has_llm
    else:
        # Server-backed modes use subscription entitlements, not local BYOK keys.
        for provider_config in config["llms"].values():
            provider_config["enabled"] = False

        config["features"]["chatAssistant"] = False
        config["subscription"] = {"plan": "none", "status": None, "upgrade_url": ""}

        overlay = await _load_subscription_overlay()
        if overlay:
            config["features"].update(overlay.get("features", {}))
            config["subscription"] = overlay.get("subscription")
            if overlay.get("limits") is not None:
                config["limits"] = overlay["limits"]
        elif app_config.site_profile == "demo":
            config["features"].update(
                {
                    "chatAssistant": True,
                    "sherpaAdvisor": True,
                    "sherpaPeakId": True,
                    "sherpaCodeGen": True,
                    "sherpaWriteReport": True,
                    "sherpaAgenticTools": True,
                    "sherpaDataStory": True,
                    "sherpaFullContext": True,
                }
            )
            config["subscription"] = {
                "plan": "demo",
                "status": "active",
                "upgrade_url": app_config.demo_contract.upgrade_url,
            }
            config["limits"] = {
                **config.get("limits", {}),
                "maxSherpaRequestsHour": 100,
            }

    return config


@router.get("/demo/quota")
async def get_demo_quota(
    current_user: User | None = Depends(get_optional_current_user),
):
    """
    Return remaining demo quotas without consuming tokens.

    Returns ``{"demo": false}`` when the site profile is not ``demo``.
    """
    if app_config.site_profile != "demo":
        return {"demo": False}

    from spectra_sherpa.app.core.demo_limits import (
        demo_execution_remaining,
        demo_sherpa_remaining,
    )

    user_id = current_user.id if current_user else None
    contract = app_config.demo_contract
    return {
        "demo": True,
        "executions": {
            "remaining": demo_execution_remaining(user_id),
            "limit": contract.max_executions_per_session,
        },
        "sherpa": {
            "remaining": demo_sherpa_remaining(user_id),
            "limit": contract.max_sherpa_interactions,
        },
    }


@router.get("/demo/analytics")
async def get_demo_analytics(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Demo session analytics for admin dashboard. Requires superuser.

    Returns aggregate counts from the execution_run table and
    active demo rate-limit sessions from the state file.
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin only")
    if app_config.site_profile != "demo":
        return {"demo": False}

    total_runs = (await session.execute(select(func.count(ExecutionRun.id)))).scalar() or 0

    unique_users = (await session.execute(select(func.count(func.distinct(ExecutionRun.user_id))))).scalar() or 0

    status_rows = (
        await session.execute(select(ExecutionRun.status, func.count(ExecutionRun.id)).group_by(ExecutionRun.status))
    ).all()
    status_counts = {row[0]: row[1] for row in status_rows}

    # Count active demo sessions from the file-backed rate limiter state
    active_sessions = 0
    state_path = get_app_data_paths(settings.data_dir).demo_limits_state
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            # Count user sessions (keys like "user:123" or "anon:shared")
            active_sessions = len(state)
        except (json.JSONDecodeError, IOError):
            pass

    return {
        "demo": True,
        "total_runs": total_runs,
        "unique_users": unique_users,
        "status_counts": status_counts,
        "active_sessions": active_sessions,
    }


@router.get("/mode")
async def get_mode():
    """Get current application mode (considers degradation)"""
    from spectra_sherpa.app.services.network_health import get_network_health_service

    health_service = get_network_health_service()

    return {
        "mode": app_config.mode,
        "effective_mode": health_service.get_effective_mode(),
        "is_degraded": health_service.is_degraded,
    }


@router.get("/network-status")
async def get_network_status():
    """
    Get current network connectivity status.

    Returns status of SpectraSherpa connection and degradation state.
    Useful for showing "Offline Mode" banner in the frontend.
    """
    from spectra_sherpa.app.services.network_health import get_network_health_service

    health_service = get_network_health_service()
    state = health_service.state

    return {
        "mode": app_config.mode,
        "effective_mode": health_service.get_effective_mode(),
        "is_online": health_service.is_online,
        "is_degraded": health_service.is_degraded,
        "network_state": state.to_dict(),
    }


@router.get("/llms")
async def get_configured_llms(session: AsyncSession = Depends(get_session)):
    """
    Get list of configured LLM providers with metadata.

    Returns only providers that have API keys configured
    (either in environment variables or database).
    """
    available = []

    for provider_id, provider_meta in PROVIDERS.items():
        is_available = await _check_provider_availability(provider_id, session)
        if is_available:
            available.append(
                {
                    "id": provider_id,
                    "name": provider_meta["name"],
                    "model": provider_meta["default_model"],
                    "cost_input": provider_meta["cost_per_million_input"],
                    "cost_output": provider_meta["cost_per_million_output"],
                    "supports_streaming": provider_meta["supports_streaming"],
                    "supports_vision": provider_meta["supports_vision"],
                }
            )

    return {"providers": available, "count": len(available)}


@router.get("/units")
async def get_unit_options():
    """
    Get unit dropdown options for frontend forms.

    Returns all available units for:
    - Concentration (ppm, mol/L, mg/L, etc.)
    - Pathlength (cm, m, mm)
    - Temperature (°C, K)
    - Pressure (atm, bar, kPa, torr)
    - Wavenumber (cm⁻¹, nm)
    - Measurement types (transmission, ATR, DRIFTS)
    - Reference types (background, blank, air, nitrogen)
    """
    from spectra_sherpa.app.lib.spectral.metadata import (
        FRONTEND_CONCENTRATION_UNITS,
        FRONTEND_MEASUREMENT_TYPES,
        FRONTEND_PATHLENGTH_UNITS,
        FRONTEND_PRESSURE_UNITS,
        FRONTEND_REFERENCE_TYPES,
        FRONTEND_TEMPERATURE_UNITS,
        FRONTEND_WAVENUMBER_UNITS,
    )

    return {
        "concentration": FRONTEND_CONCENTRATION_UNITS,
        "pathlength": FRONTEND_PATHLENGTH_UNITS,
        "temperature": FRONTEND_TEMPERATURE_UNITS,
        "pressure": FRONTEND_PRESSURE_UNITS,
        "wavenumber": FRONTEND_WAVENUMBER_UNITS,
        "measurement_type": FRONTEND_MEASUREMENT_TYPES,
        "reference_type": FRONTEND_REFERENCE_TYPES,
    }


# ============================================================================
# SpectraSherpa Configuration Endpoints
# ============================================================================


class SpectraSherpaTestRequest(BaseModel):
    server_url: str
    api_key: str


# SECURITY: SpectraSherpa config is ENV-ONLY to prevent runtime tampering
# No in-memory storage - configuration must come from environment variables

# Allowlist of valid SpectraSherpa server hosts (SSRF protection).
# Override via SPECTRASHERPA_ALLOWED_HOSTS env var (comma-separated).
_extra = [h.strip() for h in os.getenv("SPECTRASHERPA_ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOWED_SPECTRASHERPA_HOSTS = ["localhost", "127.0.0.1"] + _extra


def _mask_api_key(key: str | None) -> str | None:
    """Mask an API key, showing only first 4 and last 4 characters."""
    if not key or len(key) < 12:
        return "****" if key else None
    return f"{key[:4]}...{key[-4:]}"


def _is_allowed_url(url: str) -> bool:
    """Check if a URL is in the allowed hosts list (SSRF protection)."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return host in ALLOWED_SPECTRASHERPA_HOSTS
    except Exception:
        return False


def _normalize_spectrasherpa_url(url: str) -> str:
    """
    Normalize SpectraSherpa URL to ensure /api/v1 path is included.

    Handles:
    - https://your-server.example.com -> https://your-server.example.com/api/v1
    - https://your-server.example.com/api/v1 -> https://your-server.example.com/api/v1
    - https://your-server.example.com/ -> https://your-server.example.com/api/v1
    """
    url = url.rstrip("/")
    if not url.endswith("/api/v1"):
        url = f"{url}/api/v1"
    return url


@router.get("/spectrasherpa")
async def get_spectrasherpa_config():
    """
    Get current SpectraSherpa configuration.
    Returns server URL and MASKED API key (never exposes full key).

    Configuration is read-only from environment variables.
    """
    from spectra_sherpa.app.services.spectrasherpa import spectrasherpa_config

    if spectrasherpa_config.api_key:
        return {
            "serverUrl": spectrasherpa_config.api_base_url,
            "apiKey": _mask_api_key(spectrasherpa_config.api_key),
            "configured": True,
            "source": "environment",
        }

    return {"serverUrl": None, "apiKey": None, "configured": False, "source": None}


@router.post("/spectrasherpa/test")
async def test_spectrasherpa_connection(request: SpectraSherpaTestRequest):
    """
    Test a SpectraSherpa connection before saving.
    Returns user info and available managed keys if successful.

    SECURITY:
    - Only allows requests to allowlisted SpectraSherpa hosts (SSRF protection)
    """
    # SSRF Protection: Only allow requests to known SpectraSherpa hosts
    if not _is_allowed_url(request.server_url):
        return {
            "success": False,
            "error": "Server URL not in allowed hosts. Contact admin to add your SpectraSherpa instance.",
        }

    try:
        # Normalize URL to ensure /api/v1 is included
        base_url = _normalize_spectrasherpa_url(request.server_url)

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Validate deployment key
            response = await client.post(
                f"{base_url}/keys/deployment/validate", headers={"X-Deployment-Key": request.api_key}
            )

            if response.status_code == 401:
                return {"success": False, "error": "Invalid deployment key"}
            if response.status_code == 403:
                return {"success": False, "error": "Deployment key has been revoked"}
            if response.status_code != 200:
                return {"success": False, "error": f"Server returned {response.status_code}"}

            validation = response.json()

            return {
                "success": True,
                "deployment": validation,
            }

    except httpx.ConnectError:
        return {"success": False, "error": "Cannot connect to server"}
    except httpx.TimeoutException:
        return {"success": False, "error": "Connection timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/spectrasherpa/user")
async def get_spectrasherpa_user():
    """
    Get deployment key info from SpectraSherpa server.

    Returns deployment label, plan, and entitlements rather than user identity
    (deployment keys don't map to individual server users).
    """
    from spectra_sherpa.app.services.spectrasherpa import get_spectrasherpa_service

    service = get_spectrasherpa_service()
    if not service.is_configured:
        return {"error": "SpectraSherpa not configured"}

    result = await service.validate_deployment_key()
    if result.success:
        return {
            "label": result.label,
            "plan": result.plan,
            "plan_status": result.plan_status,
            "entitlements": result.entitlements,
        }
    else:
        return {"error": result.error or "Unable to validate deployment key"}


@router.get("/spectrasherpa/keys")
async def get_spectrasherpa_keys():
    """
    Get available managed LLM keys from SpectraSherpa.
    """
    from spectra_sherpa.app.services.spectrasherpa import get_spectrasherpa_service

    service = get_spectrasherpa_service()
    if not service.is_configured:
        return {"keys": [], "error": "SpectraSherpa not configured"}

    keys = await service.get_managed_llm_keys()
    return {
        "keys": [
            {
                "provider": k.provider,
                "display_name": k.provider.title(),
                "model": k.model or "default",
                "available": k.available,
            }
            for k in keys
        ]
    }


# ============================================================================
# Hybrid Mode Activation / Deactivation
# ============================================================================


class ActivateHybridRequest(BaseModel):
    server_url: str
    api_key: str


def _find_or_create_env_path() -> str:
    """Return path to the .env file, creating one if none exists."""
    from spectra_sherpa._paths import get_default_data_dir, get_env_file_search_paths, get_project_root

    for candidate in get_env_file_search_paths():
        if candidate.is_file():
            return str(candidate)

    # No .env found — create at project root (dev) or data dir (pip)
    root = get_project_root()
    if root is not None:
        env_path = root / ".env"
    else:
        data_dir = get_default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        env_path = data_dir / ".env"
    env_path.touch()
    return str(env_path)


@router.post("/activate-hybrid")
async def activate_hybrid(request: ActivateHybridRequest, http_request: Request):
    """
    Activate hybrid mode by connecting to a SpectraSherpa cloud server.

    Tests the connection, persists config to .env, hot-reloads in-memory
    singletons, and runs identity linking — all without a restart.

    Security: blocked in enterprise mode; restricted to loopback in local/hybrid.
    """
    from spectra_sherpa.app.core.mode_policy import is_enterprise, is_loopback
    from spectra_sherpa.app.core.security import get_client_host

    if is_enterprise():
        raise HTTPException(status_code=403, detail="Mode switching is disabled in enterprise mode.")
    if not is_loopback(get_client_host(http_request)):
        raise HTTPException(status_code=403, detail="Mode switching is only available from localhost.")

    import secrets

    from dotenv import set_key as dotenv_set_key

    # ── 1. SSRF validation ──
    if not _is_allowed_url(request.server_url):
        raise HTTPException(status_code=400, detail="Server URL not in allowed hosts list.")

    base_url = _normalize_spectrasherpa_url(request.server_url)

    # ── 2. Validate deployment key via /keys/deployment/validate ──
    # The key is a deployment key (not a user API key).  This endpoint
    # resolves against the DeploymentKey model and returns plan/entitlements.
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{base_url}/keys/deployment/validate",
                headers={"X-Deployment-Key": request.api_key},
            )
            if response.status_code == 401:
                raise HTTPException(status_code=400, detail="Invalid deployment key")
            if response.status_code == 403:
                raise HTTPException(status_code=400, detail="Deployment key has been revoked")
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Server validation returned {response.status_code}",
                )
    except httpx.ConnectError:
        raise HTTPException(status_code=400, detail="Cannot connect to server")
    except httpx.TimeoutException:
        raise HTTPException(status_code=400, detail="Connection timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ── 3. Find or create .env ──
    env_path = _find_or_create_env_path()

    # ── 4. Generate SECRET_KEY if still default ──
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.core.startup import DEFAULT_SECRET_KEY

    secret_key_generated = False
    if settings.secret_key == DEFAULT_SECRET_KEY:
        new_secret = secrets.token_urlsafe(32)
        dotenv_set_key(env_path, "SECRET_KEY", new_secret)
        os.environ["SECRET_KEY"] = new_secret
        secret_key_generated = True
        logger.info("Generated SECRET_KEY for hybrid mode (persisted to .env)")

    # ── 5. Persist to .env ──
    dotenv_set_key(env_path, "APP_MODE", "hybrid")
    dotenv_set_key(env_path, "SPECTRASHERPA_API_URL", base_url)
    dotenv_set_key(env_path, "SPECTRASHERPA_API_KEY", request.api_key)
    dotenv_set_key(env_path, "EGRESS_ENABLED", "true")

    # ── 6. Update os.environ ──
    os.environ["APP_MODE"] = "hybrid"
    os.environ["SPECTRASHERPA_API_URL"] = base_url
    os.environ["SPECTRASHERPA_API_KEY"] = request.api_key
    os.environ["EGRESS_ENABLED"] = "true"

    # ── 7. Mutate in-memory singletons ──
    app_config.mode = "hybrid"
    app_config.egress_enabled = True

    from spectra_sherpa.app.services.spectrasherpa import spectrasherpa_config

    spectrasherpa_config.api_base_url = base_url
    spectrasherpa_config.api_key = request.api_key

    # ── 8. Service lifecycle ──
    # No singleton reset required; network health and config state are updated below.

    # ── 9. Ensure default user egress settings ──
    from spectra_sherpa.app.core.startup import ensure_egress_defaults

    await ensure_egress_defaults()

    # ── 10. Start network health monitoring ──
    from spectra_sherpa.app.services.network_health import start_network_health_service

    await start_network_health_service()

    logger.info("Hybrid mode activated: connected to %s", base_url)

    return {
        "success": True,
        "config": app_config.to_client_safe(),
        "env_path": env_path,
        "secret_key_generated": secret_key_generated,
    }


@router.post("/deactivate-hybrid")
async def deactivate_hybrid(http_request: Request):
    """
    Revert to local mode by disconnecting from SpectraSherpa cloud.

    Clears credentials from memory and .env, reverts mode to local.

    Security: blocked in enterprise mode; restricted to loopback in local/hybrid.
    """
    from spectra_sherpa.app.core.mode_policy import is_enterprise, is_loopback
    from spectra_sherpa.app.core.security import get_client_host

    if is_enterprise():
        raise HTTPException(status_code=403, detail="Mode switching is disabled in enterprise mode.")
    if not is_loopback(get_client_host(http_request)):
        raise HTTPException(status_code=403, detail="Mode switching is only available from localhost.")

    from dotenv import set_key as dotenv_set_key

    # ── 1. Update .env ──
    from spectra_sherpa._paths import get_env_file_search_paths

    env_path = None
    for candidate in get_env_file_search_paths():
        if candidate.is_file():
            env_path = str(candidate)
            break

    if env_path:
        dotenv_set_key(env_path, "APP_MODE", "local")
        dotenv_set_key(env_path, "EGRESS_ENABLED", "false")
        dotenv_set_key(env_path, "SPECTRASHERPA_API_KEY", "")
        dotenv_set_key(env_path, "SPECTRASHERPA_API_URL", "")

    # ── 2. Update os.environ ──
    os.environ["APP_MODE"] = "local"
    os.environ["EGRESS_ENABLED"] = "false"
    os.environ.pop("SPECTRASHERPA_API_KEY", None)
    os.environ.pop("SPECTRASHERPA_API_URL", None)

    # ── 3. Mutate in-memory singletons ──
    app_config.mode = "local"
    app_config.egress_enabled = False

    from spectra_sherpa.app.services.spectrasherpa import SPECTRASHERPA_API_BASE, spectrasherpa_config

    spectrasherpa_config.api_key = None
    spectrasherpa_config.api_base_url = SPECTRASHERPA_API_BASE

    # ── 4. Service lifecycle ──
    # No singleton reset required; network health and config state are updated below.

    # ── 5. Stop network health monitoring ──
    from spectra_sherpa.app.services.network_health import stop_network_health_service

    await stop_network_health_service()

    logger.info("Reverted to local mode")

    return {"success": True, "config": app_config.to_client_safe()}
