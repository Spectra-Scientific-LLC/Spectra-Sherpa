"""
Configuration endpoint for frontend.

Returns client-safe configuration including:
- Core or explicitly registered runtime mode
- Feature flags
- LLM provider availability (checks env vars AND database)
- Rate limits (if enterprise mode)
"""

import logging
import os
import socket
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from spectra_sherpa.app.api.deps import api_key_header, get_current_user, get_session, get_user_from_credentials
from spectra_sherpa.app.contracts.capabilities import CHAT_ASSISTANT
from spectra_sherpa.app.contracts.llm_catalog import provider_route_catalog_dicts
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.core.security import get_bearer_token_optional


# Provider metadata comes from the injectable LLM provider catalog
# contract. _providers() reads it live, so a server that injects a
# replacement catalog at startup is reflected here at request time
# without the OSS tree changing. The OSS default is byte-identical to
# the historical inline dict.
def _providers() -> dict[str, dict[str, Any]]:
    return provider_route_catalog_dicts()


def _get_provider(provider_id: str) -> dict[str, Any]:
    """Look up provider metadata by ID."""
    catalog = _providers()
    if provider_id not in catalog:
        raise ValueError(f"Unknown provider: {provider_id}")
    return catalog[provider_id]


from spectra_sherpa.app.models.api_key import APIKey
from spectra_sherpa.app.models.user import User

router = APIRouter(prefix="/config", tags=["config"])
CONFIG_STATUS_OK = "ok"
CONFIG_STATUS_DEGRADED = "degraded"
CONFIG_ERROR_SUBSCRIPTION_OVERLAY_UNAVAILABLE = "subscription_overlay_unavailable"


async def get_optional_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    token: str | None = Depends(get_bearer_token_optional),
    api_key: str | None = Depends(api_key_header),
) -> User | None:
    """
    Resolve user context if credentials are present.

    Returns None for anonymous/public requests so /config remains publicly readable.

    Audit Item 4: this public route previously called
    ``get_user_from_credentials`` without the client host, so the extension
    credential-free fallback (``_resolve_user``) saw ``client_host=None``
    and granted implicit local identity on a *public* endpoint,
    weakening the extension boundary.  Pass the real client host so the
    fallback can only fire for an actual loopback caller.
    """
    from spectra_sherpa.app.core.security import get_client_host

    user = await get_user_from_credentials(
        session=session,
        api_key=api_key,
        token=token,
        client_host=get_client_host(request),
    )
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
    for provider_id in _providers().keys():
        is_available = await _check_provider_availability(provider_id, session, user_id=user_id)
        if provider_id in config["llms"]:
            config["llms"][provider_id]["enabled"] = is_available

    if app_config.mode == "local":
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
        overlay = await overlay_provider(None)
        if overlay:
            config["features"].update(overlay.get("features", {}))
            config["uiExtensions"] = overlay.get("uiExtensions", [])
            config["implicitIdentity"] = overlay.get("implicitIdentity") is True
            if overlay.get("advisorContextPolicy") == "receipt":
                config["advisorContextPolicy"] = "receipt"
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
            if isinstance(overlay.get("capabilities"), dict):
                config["capabilities"] = {
                    **config.get("capabilities", {}),
                    **{key: bool(value) for key, value in overlay["capabilities"].items()},
                }
        else:
            config["configStatus"] = CONFIG_STATUS_DEGRADED
            config["configError"] = CONFIG_ERROR_SUBSCRIPTION_OVERLAY_UNAVAILABLE
    # No overlay provider in local-only installs — base config is correct as-is.

    return config


@router.get("/mode")
async def get_mode():
    from spectra_sherpa.app.contracts.runtime_status import runtime_status

    state = runtime_status(app_config.mode)
    return {key: state[key] for key in ("mode", "effective_mode", "is_degraded")}


@router.get("/network-status")
async def get_network_status():
    from spectra_sherpa.app.contracts.runtime_status import runtime_status

    return runtime_status(app_config.mode)


@router.get("/llms")
async def get_configured_llms(session: AsyncSession = Depends(get_session)):
    """
    Get list of configured LLM providers with metadata.

    Returns only providers that have API keys configured
    (either in environment variables or database).
    """
    available = []

    for provider_id, provider_meta in _providers().items():
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


# SECURITY: SpectraSherpa config is ENV-ONLY to prevent runtime tampering
# No in-memory storage - configuration must come from environment variables

# Allowlist of valid SpectraSherpa server hosts (SSRF protection).
# Override via SPECTRASHERPA_ALLOWED_HOSTS env var (comma-separated).
_extra = [h.strip().lower() for h in os.getenv("SPECTRASHERPA_ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOWED_SPECTRASHERPA_HOSTS = ["localhost", "127.0.0.1", "::1"] + _extra


def _is_allowed_url(url: str) -> bool:
    """Check if a SpectraSherpa URL is safe to contact.

    Explicitly configured hosts are always allowed. Otherwise, HTTPS public
    hostnames are allowed for user-configured providers, while direct IPs and
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
            if host == "localhost" or "." not in host:
                return False
            try:
                infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
            except socket.gaierror:
                return False
            resolved: list[str] = [info[4][0] for info in infos]
            if not resolved:
                return False
            return all(ip_address(addr).is_global for addr in resolved)

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


# ============================================================================
# Local configuration persistence
# ============================================================================


def _find_or_create_env_path() -> str:
    """Return path to the .env file, creating one if none exists."""
    from spectra_sherpa._paths import (
        get_default_data_dir,
        get_local_env_file_search_paths,
        get_project_root,
    )
    from spectra_sherpa.app.core.desktop_policy import refuse_linked_configuration

    for candidate in get_local_env_file_search_paths():
        if candidate.is_file():
            refuse_linked_configuration(candidate)
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


# ── BYO Chat Config (local mode) ────────────────────────────────────────────


class ByoChatConfigRequest(BaseModel):
    endpoint_url: str
    endpoint_key: str = ""
    model: str = "deepseek-chat"
    provider: str = "openai_compatible"
    allow_private_endpoint: bool = False


def _normalized_byo_endpoint(url: str) -> str:
    """Return the stable identity used to decide whether a key may be reused.

    A transport is not a credential boundary: OpenAI-compatible endpoints can
    belong to entirely different vendors.  Keep host case-insensitive and
    remove only a syntactic trailing slash, while retaining the path because
    deployments can isolate credentials below one host.
    """
    parsed = urlsplit(url.strip())
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, ""))


@router.get("/byo-chat-config")
async def get_byo_chat_config(http_request: Request):
    """Return current BYO chat endpoint configuration (key masked). Local mode only."""
    from spectra_sherpa.app.core.mode_policy import is_local

    if not is_local() or not _can_manage_byo_chat(http_request):
        raise HTTPException(status_code=404, detail="Not found.")

    from spectra_sherpa.app.services import basic_chat

    config = basic_chat.get_config()
    return {
        "provider": config.provider,
        "endpoint_url": config.url,
        "model": config.model,
        "has_key": bool(config.key),
        "allow_private_endpoint": config.allow_private_endpoint,
        "configured": basic_chat.is_configured(),
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
    provider = request.provider.strip() or "openai_compatible"
    # Testing follows the same credential-boundary rule as saving: a blank
    # field may reuse a saved key only for the same transport *and* endpoint.
    # A single OpenAI-compatible transport serves multiple vendors.
    same_endpoint = _normalized_byo_endpoint(configured.url) == _normalized_byo_endpoint(request.endpoint_url)
    endpoint_key = request.endpoint_key.strip() or (
        configured.key if configured.provider == provider and same_endpoint else ""
    )
    success, message = await basic_chat.test_connection(
        request.endpoint_url,
        endpoint_key,
        request.model,
        provider=provider,
        allow_private_endpoint=request.allow_private_endpoint,
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

    url = request.endpoint_url.strip().rstrip("/")
    if not url:
        raise HTTPException(status_code=400, detail="endpoint_url is required.")
    provider = request.provider.strip() or "openai_compatible"
    allow_private_endpoint = bool(request.allow_private_endpoint)
    ok, reason = basic_chat.validate_endpoint_url(
        url,
        provider=provider,
        allow_private_endpoint=allow_private_endpoint,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    endpoint_key = request.endpoint_key.strip()
    # A blank key may reuse the saved credential only for the same transport
    # and endpoint. Reusing a DeepSeek key for a newly selected OpenAI or
    # Anthropic URL, for example, would silently disclose it to the wrong
    # vendor.
    current_chat_config = basic_chat.get_config()
    provider_changed = current_chat_config.provider != provider
    endpoint_changed = _normalized_byo_endpoint(current_chat_config.url) != _normalized_byo_endpoint(url)
    existing_key = current_chat_config.key if not provider_changed and not endpoint_changed else ""
    try:
        requires_key = basic_chat.get_chat_provider(provider).requires_key
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if requires_key and not endpoint_key and not existing_key:
        raise HTTPException(status_code=400, detail="endpoint_key is required.")
    model = request.model.strip() or "deepseek-chat"

    env_path = _find_or_create_env_path()
    dotenv_set_key(env_path, "CHAT_ENDPOINT_URL", url)
    dotenv_set_key(env_path, "CHAT_ENDPOINT_PROVIDER", provider)
    dotenv_set_key(env_path, "CHAT_ENDPOINT_ALLOW_PRIVATE", "true" if allow_private_endpoint else "false")
    if endpoint_key:
        basic_chat.persist_endpoint_key(env_path, endpoint_key)
    elif provider_changed or endpoint_changed:
        # A key belongs to one configured endpoint. In particular, keyless
        # providers and a new vendor behind a shared transport must not
        # inherit an old credential.
        basic_chat.persist_endpoint_key(env_path, "")
    dotenv_set_key(env_path, "CHAT_ENDPOINT_MODEL", model)

    os.environ["CHAT_ENDPOINT_URL"] = url
    os.environ["CHAT_ENDPOINT_PROVIDER"] = provider
    os.environ["CHAT_ENDPOINT_ALLOW_PRIVATE"] = "true" if allow_private_endpoint else "false"
    if endpoint_key:
        os.environ["CHAT_ENDPOINT_KEY"] = endpoint_key
    elif provider_changed or endpoint_changed:
        # Keep an explicit empty runtime value: get_config intentionally
        # supports module-level defaults for startup settings.
        os.environ["CHAT_ENDPOINT_KEY"] = ""
    os.environ["CHAT_ENDPOINT_MODEL"] = model

    logger.info("BYO chat endpoint configured: provider=%s url=%s model=%s", provider, url, model)
    return {"success": True, "configured": True}
