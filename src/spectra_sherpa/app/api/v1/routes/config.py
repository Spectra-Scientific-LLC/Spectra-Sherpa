"""
Configuration endpoint for frontend.

Returns client-safe configuration including:
- App mode (local, hybrid, demo)
- Feature flags
- LLM provider availability (checks env vars AND database)
- Rate limits (if demo mode)
"""

import os
from fastapi import APIRouter, Depends
from fastapi.security import APIKeyHeader
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_user_from_credentials
from app.core.config import app_config
from app.core.security import is_egress_enabled, oauth2_scheme_optional
from app.core.llm_registry import PROVIDERS, get_provider
from app.models.api_key import APIKey
from app.models.user import User

router = APIRouter(prefix="/config", tags=["config"])
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_optional_current_user(
    session: AsyncSession = Depends(get_session),
    token: str | None = Depends(oauth2_scheme_optional),
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

    result = await session.execute(
        query
    )
    return result.scalar_one_or_none() is not None


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

    # Preserve egress gating from base config while reflecting true provider availability.
    has_llm = any(llm["enabled"] for llm in config["llms"].values())
    config["features"]["agenticWorkflow"] = has_llm and config["features"].get("agenticWorkflow", False)

    return config


@router.get("/mode")
async def get_mode():
    """Get current application mode (considers degradation)"""
    from app.services.network_health import get_network_health_service

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
    from app.services.network_health import get_network_health_service

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
            available.append({
                "id": provider_id,
                "name": provider_meta["name"],
                "model": provider_meta["default_model"],
                "cost_input": provider_meta["cost_per_million_input"],
                "cost_output": provider_meta["cost_per_million_output"],
                "supports_streaming": provider_meta["supports_streaming"],
                "supports_vision": provider_meta["supports_vision"],
            })

    return {
        "providers": available,
        "count": len(available)
    }


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
    from app.lib.spectral.metadata import (
        FRONTEND_CONCENTRATION_UNITS,
        FRONTEND_PATHLENGTH_UNITS,
        FRONTEND_TEMPERATURE_UNITS,
        FRONTEND_PRESSURE_UNITS,
        FRONTEND_WAVENUMBER_UNITS,
        FRONTEND_MEASUREMENT_TYPES,
        FRONTEND_REFERENCE_TYPES,
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

from pydantic import BaseModel
from typing import Optional
import httpx


class SpectraSherpaTestRequest(BaseModel):
    server_url: str
    api_key: str


class SpectraSherpaSaveRequest(BaseModel):
    server_url: str
    api_key: str


# SECURITY: SpectraSherpa config is ENV-ONLY to prevent runtime tampering
# No in-memory storage - configuration must come from environment variables

# Allowlist of valid SpectraSherpa server URLs (add your domains here)
ALLOWED_SPECTRASHERPA_HOSTS = [
    "endpoint.spectrascientific.ai",
    "api.spectrascientific.ai",
    "localhost",
    "127.0.0.1",
]


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
    - https://endpoint.spectrascientific.ai -> https://endpoint.spectrascientific.ai/api/v1
    - https://endpoint.spectrascientific.ai/api/v1 -> https://endpoint.spectrascientific.ai/api/v1
    - https://endpoint.spectrascientific.ai/ -> https://endpoint.spectrascientific.ai/api/v1
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
    from app.services.spectrasherpa import spectrasherpa_config

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
    - Requires egress to be enabled (blocked in LOCAL mode by default)
    - Only allows requests to allowlisted SpectraSherpa hosts (SSRF protection)
    """
    # Check if egress is enabled (enforces LOCAL mode restriction)
    if not is_egress_enabled():
        return {
            "success": False,
            "error": "Network egress is disabled. Enable egress or use HYBRID/DEMO mode to test SpectraSherpa connections."
        }

    # SSRF Protection: Only allow requests to known SpectraSherpa hosts
    if not _is_allowed_url(request.server_url):
        return {
            "success": False,
            "error": f"Server URL not in allowed hosts. Contact admin to add your SpectraSherpa instance."
        }

    try:
        # Normalize URL to ensure /api/v1 is included
        base_url = _normalize_spectrasherpa_url(request.server_url)

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Test auth endpoint
            response = await client.get(
                f"{base_url}/auth/me",
                headers={"X-API-Key": request.api_key}
            )

            if response.status_code == 401:
                return {"success": False, "error": "Invalid API key"}

            if response.status_code != 200:
                return {"success": False, "error": f"Server returned {response.status_code}"}

            user_data = response.json()

            # Try to get managed keys
            keys_response = await client.get(
                f"{base_url}/keys/llm",
                headers={"X-API-Key": request.api_key}
            )

            keys = []
            if keys_response.status_code == 200:
                keys = keys_response.json()

            return {
                "success": True,
                "user": user_data,
                "keys": keys,
            }

    except httpx.ConnectError:
        return {"success": False, "error": "Cannot connect to server"}
    except httpx.TimeoutException:
        return {"success": False, "error": "Connection timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/spectrasherpa")
async def save_spectrasherpa_config(request: SpectraSherpaSaveRequest):
    """
    DEPRECATED: SpectraSherpa configuration is now environment-only.

    Set SPECTRASHERPA_API_URL and SPECTRASHERPA_API_KEY environment variables
    instead of using this endpoint.

    This endpoint is disabled for security (prevents runtime config tampering).
    """
    from fastapi import HTTPException
    raise HTTPException(
        status_code=403,
        detail="SpectraSherpa configuration is environment-only. "
               "Set SPECTRASHERPA_API_URL and SPECTRASHERPA_API_KEY in your .env file."
    )


@router.delete("/spectrasherpa")
async def delete_spectrasherpa_config():
    """
    DEPRECATED: SpectraSherpa configuration is now environment-only.

    Remove SPECTRASHERPA_API_KEY from your environment to disconnect.

    This endpoint is disabled for security (prevents runtime config tampering).
    """
    from fastapi import HTTPException
    raise HTTPException(
        status_code=403,
        detail="SpectraSherpa configuration is environment-only. "
               "Remove SPECTRASHERPA_API_KEY from your .env to disconnect."
    )


@router.get("/spectrasherpa/user")
async def get_spectrasherpa_user():
    """
    Get current user info from SpectraSherpa.
    """
    from app.services.spectrasherpa import get_spectrasherpa_service

    service = get_spectrasherpa_service()
    if not service.is_configured:
        return {"error": "SpectraSherpa not configured"}

    result = await service.validate_api_key()
    if result.success and result.user is not None:
        # Keep a backward-compatible payload while using current
        # SpectraSherpaUser fields from spectrasherpa.py.
        return {
            "id": result.user.id,
            "email": result.user.email,
            "username": result.user.username,
            "display_name": result.user.username,
            "is_admin": result.user.is_admin,
            "is_active": result.user.is_active,
            "llm_quota": result.user.llm_quota,
        }
    else:
        return {"error": result.error or "Unable to fetch SpectraSherpa user"}


@router.get("/spectrasherpa/keys")
async def get_spectrasherpa_keys():
    """
    Get available managed LLM keys from SpectraSherpa.
    """
    from app.services.spectrasherpa import get_spectrasherpa_service

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
                "rate_limit": k.rate_limit,
            }
            for k in keys
        ]
    }
