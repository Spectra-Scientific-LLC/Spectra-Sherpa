"""
Configuration endpoint for frontend.

Returns client-safe configuration including:
- App mode (local, hybrid, enterprise)
- Feature flags
- LLM provider availability (checks env vars AND database)
- Rate limits (if enterprise mode)
"""

import logging
import os
from ipaddress import ip_address
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from spectra_sherpa.app.api.deps import get_current_user, get_session, get_user_from_credentials
from spectra_sherpa.app.contracts.capabilities import CHAT_ASSISTANT
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.core.security import get_bearer_token_optional

# Provider metadata previously lived in core/llm_registry.py (moved to server).
# Kept inline here for the /config endpoint's availability checks.
PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "default_model": "gpt-4o",
        "env_var": "OPENAI_API_KEY",
        "supports_streaming": True,
        "cost_per_million_input": 2.50,
        "cost_per_million_output": 10.00,
        "supports_vision": True,
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic",
        "default_model": "claude-sonnet-4-6",
        "env_var": "ANTHROPIC_API_KEY",
        "supports_streaming": True,
        "cost_per_million_input": 3.00,
        "cost_per_million_output": 15.00,
        "supports_vision": True,
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "env_var": "DEEPSEEK_API_KEY",
        "supports_streaming": True,
        "cost_per_million_input": 0.27,
        "cost_per_million_output": 1.10,
        "supports_vision": False,
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini",
        "default_model": "gemini-1.5-pro",
        "env_var": "GEMINI_API_KEY",
        "supports_streaming": True,
        "cost_per_million_input": 1.25,
        "cost_per_million_output": 5.00,
        "supports_vision": True,
    },
    "custom_llm": {
        "id": "custom_llm",
        "name": "Custom LLM",
        "default_model": "custom-model",
        "env_var": "CUSTOM_LLM_API_KEY",
        "supports_streaming": True,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "supports_vision": False,
    },
}


def _get_provider(provider_id: str) -> dict[str, Any]:
    """Look up provider metadata by ID."""
    if provider_id not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_id}")
    return PROVIDERS[provider_id]


from spectra_sherpa.app.models.api_key import APIKey
from spectra_sherpa.app.models.user import User

router = APIRouter(prefix="/config", tags=["config"])
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
CONFIG_STATUS_OK = "ok"
CONFIG_STATUS_DEGRADED = "degraded"
CONFIG_ERROR_SUBSCRIPTION_OVERLAY_UNAVAILABLE = "subscription_overlay_unavailable"


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
        provider = _get_provider(provider_id)
    except ValueError:
        return False

    # Check environment variable
    if os.getenv(provider["env_var"]):
        return True

    # Check database — BYOK (per-user) keys only.
    # System-wide keys are managed by server extensions and resolved via
    # the injected ExtraKeyResolver at runtime, not at availability check.
    if user_id is not None:
        query = select(APIKey.id).where(APIKey.service_name == provider_id, APIKey.user_id == user_id).limit(1)
        result = await session.execute(query)
        if result.scalar_one_or_none() is not None:
            return True

    # Check server-injected resolver for additional availability
    from spectra_sherpa.app.contracts.key_resolver import get_extra_key_resolver

    if get_extra_key_resolver() is not None:
        # If a server resolver is installed, assume system keys may be available.
        # The actual key lookup happens at request time, not here.
        return True

    return False


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
    config["configStatus"] = CONFIG_STATUS_OK
    config["configError"] = None

    # Update LLM availability by checking actual sources
    for provider_id in PROVIDERS.keys():
        is_available = await _check_provider_availability(provider_id, session, user_id=user_id)
        if provider_id in config["llms"]:
            config["llms"][provider_id]["enabled"] = is_available

    from spectra_sherpa.app.core.mode_policy import is_local

    if is_local():
        # In OSS local mode, the chat surface is the BYO endpoint proxy only.
        # Legacy provider-key presence no longer enables the chat assistant.
        from spectra_sherpa.app.services.basic_chat import is_configured as byo_chat_configured

        for provider_config in config["llms"].values():
            provider_config["enabled"] = False

        config["features"][CHAT_ASSISTANT] = byo_chat_configured()
    else:
        # Server-backed modes use subscription entitlements, not local BYOK keys.
        for provider_config in config["llms"].values():
            provider_config["enabled"] = False

        config["features"][CHAT_ASSISTANT] = False
        config["subscription"] = None

        # Delegate overlay assembly to the injected provider.
        from spectra_sherpa.app.contracts.config_overlay import get_config_overlay_provider

        overlay_provider = get_config_overlay_provider()
        if overlay_provider is not None:
            from spectra_sherpa.app.services.spectrasherpa import spectrasherpa_config

            overlay = await overlay_provider(spectrasherpa_config.api_key)
            if overlay:
                config["features"].update(overlay.get("features", {}))
                config["subscription"] = overlay.get("subscription")
                if overlay.get("limits") is not None:
                    config["limits"] = overlay["limits"]
                if overlay.get("demo") is not None:
                    config["demo"] = overlay["demo"]
                # Phase 4 — server elevates audit pack capabilities
                # (fullPipeline, reportPack) when the deployment's
                # plan entitles them. localQuery and exportAudited
                # remain governed by the OSS deployment flag and are
                # NOT overridable by the server overlay (per design §3
                # — audit.basic is a deployment capability, not a plan
                # entitlement).
                overlay_audit = overlay.get("audit")
                if overlay_audit is not None and isinstance(config.get("audit"), dict):
                    if "fullPipeline" in overlay_audit:
                        config["audit"]["fullPipeline"] = bool(overlay_audit["fullPipeline"])
                    if "reportPack" in overlay_audit:
                        config["audit"]["reportPack"] = bool(overlay_audit["reportPack"])
                # Explicit merge of server-owned auth-policy flags. The
                # base shape defaults both to False (see
                # AppConfig.to_client_safe); the overlay may override
                # per-request, and the names are listed here so a future
                # overlay-structure change does not silently drop them.
                if "registrationEnabled" in overlay:
                    config["registrationEnabled"] = bool(overlay["registrationEnabled"])
                if "registrationRequiresCode" in overlay:
                    config["registrationRequiresCode"] = bool(overlay["registrationRequiresCode"])
            else:
                config["configStatus"] = CONFIG_STATUS_DEGRADED
                config["configError"] = CONFIG_ERROR_SUBSCRIPTION_OVERLAY_UNAVAILABLE
        # No overlay provider in local-only installs — base config is correct as-is.

    return config


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
_extra = [h.strip().lower() for h in os.getenv("SPECTRASHERPA_ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOWED_SPECTRASHERPA_HOSTS = ["localhost", "127.0.0.1", "::1"] + _extra


def _mask_api_key(key: str | None) -> str | None:
    """Mask an API key, showing only first 4 and last 4 characters."""
    if not key or len(key) < 12:
        return "****" if key else None
    return f"{key[:4]}...{key[-4:]}"


def _is_allowed_url(url: str) -> bool:
    """Check if a SpectraSherpa URL is safe to contact.

    Explicitly configured hosts are always allowed. Otherwise, HTTPS public
    hostnames are allowed for hybrid cloud onboarding, while direct IPs and
    non-HTTPS URLs remain restricted unless allowlisted.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if host in ALLOWED_SPECTRASHERPA_HOSTS:
            return True
        if parsed.scheme != "https":
            return False

        try:
            ip = ip_address(host)
        except ValueError:
            # Public DNS hostnames are accepted for remote SpectraSherpa.
            return host != "localhost" and "." in host

        return ip.is_global
    except Exception:
        return False


def _csv_env(name: str) -> set[str]:
    return {item.strip().lower() for item in os.getenv(name, "").split(",") if item.strip()}


def _is_private_address(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ip_address(host).is_private
    except ValueError:
        return False


def _can_manage_byo_chat(http_request: Request) -> bool:
    """Local BYO chat config may mutate .env, so LAN access is explicit opt-in."""
    from spectra_sherpa.app.core.mode_policy import is_loopback
    from spectra_sherpa.app.core.security import get_client_host

    host = (get_client_host(http_request) or "").lower()
    if is_loopback(host):
        return True
    if host in _csv_env("SPECTRASHERPA_LOCAL_CONFIG_HOSTS"):
        return True
    allow_private = os.getenv("SPECTRASHERPA_ALLOW_PRIVATE_CONFIG_CLIENTS", "").strip().lower()
    return allow_private in {"1", "true", "yes", "y", "on"} and _is_private_address(host)


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
    except Exception as exc:
        # Log the full exception server-side; return a generic message so
        # internal details (stack frames, filesystem paths, library versions)
        # don't flow back to the client.
        logger.exception("Deployment key validation failed: %s", exc)
        return {"success": False, "error": "Deployment key validation failed."}


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
    from spectra_sherpa._paths import (
        get_default_data_dir,
        get_local_env_file_search_paths,
        get_project_root,
    )

    for candidate in get_local_env_file_search_paths():
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
    from spectra_sherpa._paths import get_local_env_file_search_paths

    env_path = None
    for candidate in get_local_env_file_search_paths():
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


# ── BYO Chat Config (local mode) ────────────────────────────────────────────


class ByoChatConfigRequest(BaseModel):
    endpoint_url: str
    endpoint_key: str
    model: str = "deepseek-chat"


@router.get("/byo-chat-config")
async def get_byo_chat_config(http_request: Request):
    """Return current BYO chat endpoint configuration (key masked). Local mode only."""
    from spectra_sherpa.app.core.mode_policy import is_local

    if not is_local() or not _can_manage_byo_chat(http_request):
        raise HTTPException(status_code=404, detail="Not found.")

    from spectra_sherpa.app.services import basic_chat

    config = basic_chat.get_config()
    return {
        "endpoint_url": config.url,
        "model": config.model,
        "has_key": bool(config.key),
        "configured": bool(config.url and config.key),
    }


@router.post("/byo-chat-config/test")
async def test_byo_chat_config(
    request: ByoChatConfigRequest,
    http_request: Request,
    user=Depends(get_current_user),
):
    """Test a BYO chat endpoint before saving it. Local mode only."""
    from spectra_sherpa.app.core.mode_policy import is_local
    from spectra_sherpa.app.services import basic_chat

    if not is_local():
        raise HTTPException(status_code=404, detail="Not found.")
    if not _can_manage_byo_chat(http_request):
        raise HTTPException(
            status_code=403,
            detail=(
                "BYO chat config is only available from localhost unless "
                "SPECTRASHERPA_LOCAL_CONFIG_HOSTS or "
                "SPECTRASHERPA_ALLOW_PRIVATE_CONFIG_CLIENTS is configured."
            ),
        )

    configured = basic_chat.get_config()
    endpoint_key = request.endpoint_key.strip() or configured.key
    success, message = await basic_chat.test_connection(
        request.endpoint_url,
        endpoint_key,
        request.model,
    )
    return {"success": success, "message": message}


@router.post("/byo-chat-config")
async def save_byo_chat_config(
    request: ByoChatConfigRequest,
    http_request: Request,
    user=Depends(get_current_user),
):
    """Persist BYO chat endpoint config to .env. Local mode only."""
    from dotenv import set_key as dotenv_set_key

    from spectra_sherpa.app.core.mode_policy import is_local

    if not is_local():
        raise HTTPException(status_code=404, detail="Not found.")
    if not _can_manage_byo_chat(http_request):
        raise HTTPException(
            status_code=403,
            detail=(
                "BYO chat config is only available from localhost unless "
                "SPECTRASHERPA_LOCAL_CONFIG_HOSTS or "
                "SPECTRASHERPA_ALLOW_PRIVATE_CONFIG_CLIENTS is configured."
            ),
        )

    url = request.endpoint_url.strip().rstrip("/")
    if not url:
        raise HTTPException(status_code=400, detail="endpoint_url is required.")
    endpoint_key = request.endpoint_key.strip()
    existing_key = os.getenv("CHAT_ENDPOINT_KEY", "")
    if not endpoint_key and not existing_key:
        raise HTTPException(status_code=400, detail="endpoint_key is required.")
    model = request.model.strip() or "deepseek-chat"

    env_path = _find_or_create_env_path()
    dotenv_set_key(env_path, "CHAT_ENDPOINT_URL", url)
    if endpoint_key:
        dotenv_set_key(env_path, "CHAT_ENDPOINT_KEY", endpoint_key)
    dotenv_set_key(env_path, "CHAT_ENDPOINT_MODEL", model)

    os.environ["CHAT_ENDPOINT_URL"] = url
    if endpoint_key:
        os.environ["CHAT_ENDPOINT_KEY"] = endpoint_key
    os.environ["CHAT_ENDPOINT_MODEL"] = model

    logger.info("BYO chat endpoint configured: %s / %s", url, model)
    return {"success": True, "configured": True}
