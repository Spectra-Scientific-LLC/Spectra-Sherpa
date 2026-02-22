"""
SpectraSherpa Cloud Service Stub

This module provides a minimal stub implementation for the SpectraSherpa cloud service
integration. In OSS mode, hybrid features are disabled. In hybrid/enterprise mode, this
module can be replaced by spectra-server with a full implementation.

The stub ensures that config endpoints and network health checks don't crash when
the full cloud service is unavailable.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Constants
SPECTRASHERPA_API_BASE = "https://api.spectrasherpa.ai"  # Placeholder for cloud API


class SpectraSherpaConfig(BaseModel):
    """Configuration for SpectraSherpa cloud service."""

    enabled: bool = Field(default=False, description="Whether cloud integration is enabled")
    api_base_url: str = Field(default=SPECTRASHERPA_API_BASE, description="Base URL for SpectraSherpa cloud API")
    api_key: str | None = Field(default=None, description="API key for cloud service")
    deployment_id: str | None = Field(default=None, description="Deployment/tenant ID")
    sync_enabled: bool = Field(default=False, description="Enable workflow sync")
    managed_llm_keys_enabled: bool = Field(default=False, description="Use cloud-managed LLM API keys")

    class Config:
        """Pydantic config."""

        frozen = False  # Allow updates from spectra-server


# Global config instance — initialized from env so hybrid mode persists across restarts
spectrasherpa_config = SpectraSherpaConfig(
    api_base_url=os.getenv("SPECTRASHERPA_API_URL", SPECTRASHERPA_API_BASE),
    api_key=os.getenv("SPECTRASHERPA_API_KEY") or None,
    enabled=bool(os.getenv("SPECTRASHERPA_API_KEY")),
)


class SpectraSherpaService:
    """
    Stub implementation of SpectraSherpa cloud service.

    In OSS mode, all cloud features are disabled.
    spectra-server can inject a full implementation that connects to cloud services.
    """

    def __init__(self, config: SpectraSherpaConfig | None = None):
        """Initialize stub service (OSS mode - features disabled)."""
        self.config = config or spectrasherpa_config
        logger.debug("SpectraSherpaService initialized in stub mode (OSS)")

    async def health_check(self) -> dict[str, Any]:
        """
        Check cloud service health.

        Returns:
            Health status (always unavailable in OSS stub)
        """
        return {
            "available": False,
            "status": "disabled",
            "message": "SpectraSherpa cloud integration is not available in OSS mode",
        }

    async def get_user_info(self) -> dict[str, Any] | None:
        """
        Get current user's cloud deployment info.

        Returns:
            None in OSS mode
        """
        logger.debug("SpectraSherpaService.get_user_info called (stub mode)")
        return None

    async def get_managed_llm_keys(self) -> dict[str, str]:
        """
        Get cloud-managed LLM API keys.

        Returns:
            Empty dict in OSS mode
        """
        logger.debug("SpectraSherpaService.get_managed_llm_keys called (stub mode)")
        return {}

    async def sync_workflow(self, workflow_id: int) -> bool:
        """
        Sync a workflow to cloud storage.

        Returns:
            False in OSS mode (sync disabled)
        """
        logger.debug(f"SpectraSherpaService.sync_workflow called for workflow {workflow_id} (stub mode)")
        return False

    async def activate_hybrid_mode(self, api_key: str) -> dict[str, Any]:
        """
        Activate hybrid mode (OSS stub returns error).

        Args:
            api_key: SpectraSherpa cloud API key

        Returns:
            Error dict indicating hybrid mode is not supported in OSS
        """
        logger.warning("Hybrid mode activation attempted in OSS mode (not supported)")
        return {
            "success": False,
            "error": "Hybrid mode is not available in the OSS version. Please use spectra-server for hybrid/enterprise features.",
        }

    async def deactivate_hybrid_mode(self) -> dict[str, Any]:
        """
        Deactivate hybrid mode.

        Returns:
            Success dict (no-op in OSS)
        """
        logger.debug("SpectraSherpaService.deactivate_hybrid_mode called (stub mode - no-op)")
        return {
            "success": True,
            "message": "Already in OSS mode",
        }

    async def test_connection(self) -> dict[str, Any]:
        """
        Test connection to cloud service.

        Returns:
            Error dict in OSS mode
        """
        return {
            "success": False,
            "available": False,
            "message": "SpectraSherpa cloud service is not available in OSS mode",
        }

    @property
    def is_configured(self) -> bool:
        """Whether the service has credentials configured."""
        return bool(self.config.api_key)

    async def validate_deployment_key(self) -> Any:
        """
        Validate the deployment key against the cloud service.

        Returns:
            A result object with .success, .error, .label, .plan, .plan_status, .entitlements.
            In OSS mode, always returns failure.
        """
        from types import SimpleNamespace

        return SimpleNamespace(
            success=False,
            error="Not configured in OSS mode",
            label=None,
            plan=None,
            plan_status=None,
            entitlements={},
        )

    def is_available(self) -> bool:
        """Check if cloud service is available."""
        return self.config.enabled


# Global singleton instance
_service: SpectraSherpaService | None = None


def get_spectrasherpa_service() -> SpectraSherpaService:
    """
    Get the global SpectraSherpa service instance.

    Returns:
        SpectraSherpaService stub in OSS mode, or full implementation if injected
    """
    global _service
    if _service is None:
        _service = SpectraSherpaService()
    return _service


def set_spectrasherpa_service(service: SpectraSherpaService):
    """
    Inject a custom SpectraSherpa service implementation.

    Used by spectra-server to replace the OSS stub with a full cloud-connected implementation.

    Args:
        service: Custom SpectraSherpaService instance
    """
    global _service
    _service = service
    logger.info("SpectraSherpaService: custom implementation injected")


def reset_spectrasherpa_service():
    """Reset to OSS stub mode (for testing)."""
    global _service
    _service = None
