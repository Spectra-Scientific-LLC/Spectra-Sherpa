"""
SpectraSherpa Server Integration

Handles authentication and data exchange with a SpectraSherpa server
for hybrid mode deployments.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field

from spectra_sherpa.app.core.config import app_config, settings

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

SPECTRASHERPA_API_BASE = os.getenv("SPECTRASHERPA_API_URL", "")
SPECTRASHERPA_TIMEOUT = 10.0  # seconds


class SpectraSherpaConfig(BaseModel):
    """Configuration for SpectraSherpa integration"""
    api_base_url: str = Field(
        default=SPECTRASHERPA_API_BASE,
        description="Base URL for SpectraSherpa API"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="SpectraSherpa API key for this deployment"
    )
    timeout: float = Field(
        default=SPECTRASHERPA_TIMEOUT,
        description="HTTP request timeout in seconds"
    )

    @classmethod
    def from_env(cls) -> "SpectraSherpaConfig":
        return cls(
            api_base_url=os.getenv("SPECTRASHERPA_API_URL", SPECTRASHERPA_API_BASE),
            api_key=os.getenv("SPECTRASHERPA_API_KEY"),
            timeout=float(os.getenv("SPECTRASHERPA_TIMEOUT", str(SPECTRASHERPA_TIMEOUT)))
        )


# Global config instance
spectrasherpa_config = SpectraSherpaConfig.from_env()


# ============================================================================
# Response Models
# ============================================================================

@dataclass
class SpectraSherpaUser:
    """User info from SpectraSherpa server (/auth/me response)."""
    id: int
    email: str
    username: str
    is_admin: bool = False
    is_active: bool = True
    llm_quota: int = 100


@dataclass
class ManagedLLMKey:
    """LLM key metadata from Spectra-Server (metadata-only, no raw secrets)."""
    provider: str  # openai, anthropic, deepseek, gemini
    model: Optional[str] = None
    available: bool = False


@dataclass
class AuthResult:
    """Result of SpectraSherpa authentication"""
    success: bool
    user: Optional[SpectraSherpaUser] = None
    error: Optional[str] = None
    managed_keys: list[ManagedLLMKey] = None

    def __post_init__(self):
        if self.managed_keys is None:
            self.managed_keys = []


@dataclass
class DeploymentValidation:
    """Result of deployment key validation via /keys/deployment/validate."""
    success: bool
    label: str = ""
    plan: str = "none"
    plan_status: Optional[str] = None
    entitlements: Optional[dict[str, Any]] = None
    error: Optional[str] = None


# ============================================================================
# Service Implementation
# ============================================================================

class SpectraSherpaService:
    """
    Service for interacting with SpectraSherpa cloud platform.

    This service handles:
    - API key validation
    - User authentication and linking
    - Managed LLM key retrieval
    - Health checks
    """

    def __init__(self, config: Optional[SpectraSherpaConfig] = None):
        self.config = config or spectrasherpa_config
        self._client: Optional[httpx.AsyncClient] = None
        self._cached_user: Optional[SpectraSherpaUser] = None
        self._cached_keys: list[ManagedLLMKey] = []
        self._cache_expires: Optional[datetime] = None

    @property
    def is_configured(self) -> bool:
        """Check if SpectraSherpa integration is configured"""
        return self.config.api_key is not None and len(self.config.api_key) > 0

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.api_base_url,
                timeout=self.config.timeout,
                headers={
                    "X-API-Key": self.config.api_key,
                    "User-Agent": f"SpectraScientific/{settings.app_version}",
                    "X-Client-Mode": app_config.mode,
                }
            )
        return self._client

    async def close(self):
        """Close HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> tuple[bool, str]:
        """
        Check if SpectraSherpa service is reachable.

        Returns:
            Tuple of (is_healthy, message)
        """
        if not self.is_configured:
            return False, "SpectraSherpa API key not configured"

        try:
            client = await self._get_client()
            # Health endpoint is at /api/health (registered on the FastAPI app,
            # not under the /api/v1 router).  Strip the /api/v1 suffix from the
            # configured base URL so we hit the correct path.
            base = self.config.api_base_url.rstrip("/")
            if base.endswith("/api/v1"):
                health_url = base[: -len("/api/v1")] + "/api/health"
            else:
                health_url = base + "/api/health"
            response = await client.get(health_url)

            if response.status_code == 200:
                return True, "SpectraSherpa service is healthy"
            elif response.status_code == 401:
                return False, "SpectraSherpa API key is invalid"
            else:
                return False, f"SpectraSherpa returned status {response.status_code}"

        except httpx.ConnectError:
            return False, "Cannot connect to SpectraSherpa service"
        except httpx.TimeoutException:
            return False, "SpectraSherpa service timed out"
        except Exception as e:
            logger.warning(f"SpectraSherpa health check failed: {e}")
            return False, f"Health check failed: {str(e)}"

    async def validate_api_key(self, api_key: Optional[str] = None) -> AuthResult:
        """
        Validate a SpectraSherpa API key and get user info.

        Args:
            api_key: API key to validate (uses configured key if not provided)

        Returns:
            AuthResult with user info if valid
        """
        key_to_validate = api_key or self.config.api_key

        if not key_to_validate:
            return AuthResult(success=False, error="No API key provided")

        try:
            # Create a temporary client with the key to validate
            async with httpx.AsyncClient(
                base_url=self.config.api_base_url,
                timeout=self.config.timeout,
                headers={
                    "X-API-Key": key_to_validate,
                    "User-Agent": f"SpectraScientific/{settings.app_version}",
                }
            ) as client:
                response = await client.get("/auth/me")

                if response.status_code == 401:
                    return AuthResult(success=False, error="Invalid API key")

                response.raise_for_status()
                data = response.json()

                user = SpectraSherpaUser(
                    id=data["id"],
                    email=data.get("email", ""),
                    username=data.get("username", data.get("email", "")),
                    is_admin=data.get("is_admin", data.get("is_superuser", False)),
                    is_active=data.get("is_active", True),
                    llm_quota=data.get("llm_quota", 100),
                )

                return AuthResult(success=True, user=user)

        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                logger.info("SpectraSherpa /auth/me returned %s (server-side — identity linking unavailable)", e.response.status_code)
            else:
                logger.warning("SpectraSherpa auth failed: %s", e)
            return AuthResult(success=False, error=f"Authentication failed: {e.response.status_code}")
        except Exception as e:
            logger.error(f"SpectraSherpa auth error: {e}")
            return AuthResult(success=False, error=str(e))

    async def validate_deployment_key(self, api_key: Optional[str] = None) -> DeploymentValidation:
        """Validate a deployment key via POST /keys/deployment/validate.

        This is the primary validation path for hybrid activation.
        Returns plan, entitlements, and label for the deployment key.
        """
        key_to_validate = api_key or self.config.api_key

        if not key_to_validate:
            return DeploymentValidation(success=False, error="No deployment key provided")

        try:
            async with httpx.AsyncClient(
                base_url=self.config.api_base_url,
                timeout=self.config.timeout,
                headers={
                    "X-Deployment-Key": key_to_validate,
                    "User-Agent": f"SpectraScientific/{settings.app_version}",
                }
            ) as client:
                response = await client.post("/keys/deployment/validate")

                if response.status_code == 401:
                    return DeploymentValidation(success=False, error="Invalid deployment key")
                if response.status_code == 403:
                    return DeploymentValidation(success=False, error="Deployment key has been revoked")

                response.raise_for_status()
                data = response.json()

                return DeploymentValidation(
                    success=True,
                    label=data.get("label", ""),
                    plan=data.get("plan", "none"),
                    plan_status=data.get("plan_status"),
                    entitlements=data.get("entitlements"),
                )

        except httpx.HTTPStatusError as e:
            logger.warning("Deployment key validation failed: %s", e)
            return DeploymentValidation(success=False, error=f"Validation failed: {e.response.status_code}")
        except Exception as e:
            logger.error("Deployment key validation error: %s", e)
            return DeploymentValidation(success=False, error=str(e))

    async def get_managed_llm_keys(self, force_refresh: bool = False) -> list[ManagedLLMKey]:
        """
        Get managed LLM key metadata from Spectra-Server.

        Returns metadata only (provider, model, availability) — raw API keys
        are never returned by the server. This is used to display which
        providers are available on the server, not to extract secrets.

        Keys are cached for 1 hour to reduce API calls.
        """
        if not self.is_configured:
            return []

        # Check cache
        now = datetime.now(timezone.utc)
        if not force_refresh and self._cache_expires and now < self._cache_expires:
            return self._cached_keys

        try:
            client = await self._get_client()
            response = await client.get("/keys/llm")

            if response.status_code in (401, 403):
                return []

            response.raise_for_status()
            data = response.json()

            keys = []
            for key_data in data.get("keys", []):
                keys.append(ManagedLLMKey(
                    provider=key_data["provider"],
                    model=key_data.get("model"),
                    available=key_data.get("available", False),
                ))

            # Cache for 1 hour
            self._cached_keys = keys
            from datetime import timedelta
            self._cache_expires = datetime.now(timezone.utc) + timedelta(hours=1)

            logger.info(f"Fetched {len(keys)} managed LLM key metadata from Spectra-Server")
            return keys

        except Exception as e:
            logger.error(f"Failed to fetch managed LLM key metadata: {e}")
            return self._cached_keys


# ============================================================================
# Singleton Instance
# ============================================================================

_service_instance: Optional[SpectraSherpaService] = None


def get_spectrasherpa_service() -> SpectraSherpaService:
    """Get the singleton SpectraSherpa service instance"""
    global _service_instance
    if _service_instance is None:
        _service_instance = SpectraSherpaService()
    return _service_instance


async def close_spectrasherpa_service():
    """Close the singleton service (call on app shutdown)"""
    global _service_instance
    if _service_instance:
        await _service_instance.close()
        _service_instance = None


async def reset_spectrasherpa_service():
    """Close and reset singleton so next access picks up new config."""
    global _service_instance
    if _service_instance:
        await _service_instance.close()
        _service_instance = None
