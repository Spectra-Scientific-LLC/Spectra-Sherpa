"""
SpectraSherpa Cloud Service Integration

This service handles authentication and data exchange with the SpectraSherpa
cloud platform for HYBRID mode deployments.

Features:
- API key validation with SpectraSherpa
- User account linking (local <-> SpectraSherpa)
- Managed LLM key retrieval
- Log mirroring (audit trail sync)
- Workflow/settings synchronization
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field

from app.core.config import app_config, settings

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

SPECTRASHERPA_API_BASE = "https://endpoint.spectrascientific.ai/api/v1"
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
        import os
        return cls(
            api_base_url=os.getenv("SPECTRASHERPA_API_URL", SPECTRASHERPA_API_BASE),
            api_key=os.getenv("SPECTRASHERPA_API_KEY"),
            timeout=float(os.getenv("SPECTRASHERPA_TIMEOUT", SPECTRASHERPA_TIMEOUT))
        )


# Global config instance
spectrasherpa_config = SpectraSherpaConfig.from_env()


# ============================================================================
# Response Models
# ============================================================================

@dataclass
class SpectraSherpaUser:
    """User info from SpectraSherpa"""
    id: str
    email: str
    display_name: str
    organization: Optional[str] = None
    tier: str = "free"  # free, pro, enterprise
    features: dict = None

    def __post_init__(self):
        if self.features is None:
            self.features = {}


@dataclass
class ManagedLLMKey:
    """LLM API key managed by SpectraSherpa"""
    provider: str  # openai, anthropic, deepseek, gemini
    api_key: str
    model: Optional[str] = None
    rate_limit: Optional[int] = None  # requests per minute
    expires_at: Optional[datetime] = None


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
            # Health endpoint is at the server root, not under /api/v1
            base = self.config.api_base_url.rstrip("/")
            # Strip /api/v1 suffix to get the server root URL
            if base.endswith("/api/v1"):
                health_url = base[: -len("/api/v1")] + "/health"
            else:
                health_url = base + "/health"
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
                    email=data["email"],
                    display_name=data.get("display_name", data["email"]),
                    organization=data.get("organization"),
                    tier=data.get("tier", "free"),
                    features=data.get("features", {})
                )

                return AuthResult(success=True, user=user)

        except httpx.HTTPStatusError as e:
            logger.warning(f"SpectraSherpa auth failed: {e}")
            return AuthResult(success=False, error=f"Authentication failed: {e.response.status_code}")
        except Exception as e:
            logger.error(f"SpectraSherpa auth error: {e}")
            return AuthResult(success=False, error=str(e))

    async def get_managed_llm_keys(self, force_refresh: bool = False) -> list[ManagedLLMKey]:
        """
        Get managed LLM API keys from SpectraSherpa.

        Keys are cached for 1 hour to reduce API calls.

        Args:
            force_refresh: Force refresh even if cache is valid

        Returns:
            List of ManagedLLMKey objects
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

            if response.status_code == 401:
                logger.warning("SpectraSherpa API key invalid for LLM key fetch")
                return []

            if response.status_code == 403:
                # User's tier doesn't include managed keys
                logger.info("SpectraSherpa tier doesn't include managed LLM keys")
                return []

            response.raise_for_status()
            data = response.json()

            keys = []
            for key_data in data.get("keys", []):
                expires_at = None
                if key_data.get("expires_at"):
                    expires_at = datetime.fromisoformat(key_data["expires_at"].replace("Z", "+00:00"))

                keys.append(ManagedLLMKey(
                    provider=key_data["provider"],
                    api_key=key_data["api_key"],
                    model=key_data.get("model"),
                    rate_limit=key_data.get("rate_limit"),
                    expires_at=expires_at
                ))

            # Cache for 1 hour
            self._cached_keys = keys
            self._cache_expires = datetime.now(timezone.utc).replace(
                minute=0, second=0, microsecond=0
            )
            from datetime import timedelta
            self._cache_expires += timedelta(hours=1)

            logger.info(f"Fetched {len(keys)} managed LLM keys from SpectraSherpa")
            return keys

        except Exception as e:
            logger.error(f"Failed to fetch managed LLM keys: {e}")
            # Return cached keys as fallback
            return self._cached_keys

    async def sync_user_preferences(self, user_id: int, preferences: dict[str, Any]) -> bool:
        """
        Sync user preferences to SpectraSherpa cloud.

        Args:
            user_id: Local user ID
            preferences: Dictionary of preferences to sync

        Returns:
            True if sync successful
        """
        if not self.is_configured:
            return False

        try:
            client = await self._get_client()
            response = await client.put(
                "/sync/preferences",
                json={
                    "local_user_id": user_id,
                    "preferences": preferences,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            )

            if response.status_code == 401:
                logger.warning("SpectraSherpa API key invalid for preference sync")
                return False

            response.raise_for_status()
            return True

        except Exception as e:
            logger.error(f"Failed to sync preferences: {e}")
            return False

    async def get_user_preferences(self, user_id: int) -> Optional[dict[str, Any]]:
        """
        Get user preferences from SpectraSherpa cloud.

        Args:
            user_id: Local user ID

        Returns:
            Dictionary of preferences or None if not found
        """
        if not self.is_configured:
            return None

        try:
            client = await self._get_client()
            response = await client.get(
                "/sync/preferences",
                params={"local_user_id": user_id}
            )

            if response.status_code == 404:
                return None

            response.raise_for_status()
            return response.json().get("preferences")

        except Exception as e:
            logger.error(f"Failed to get preferences: {e}")
            return None


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
