"""
Network Health Monitoring Service

Monitors connectivity to SpectraSherpa and enables graceful degradation
to local mode when the cloud service is unreachable.

Features:
- Periodic health checks
- Automatic mode switching
- Offline log queuing
- Reconnection retry logic
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Callable, Any
import threading

from app.core.config import app_config

logger = logging.getLogger(__name__)


class ConnectionStatus(Enum):
    """Network connection status states"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    DEGRADED = "degraded"  # Partial connectivity
    CHECKING = "checking"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check"""
    status: ConnectionStatus
    message: str
    latency_ms: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict = field(default_factory=dict)


@dataclass
class NetworkState:
    """Current network state"""
    spectrasherpa_status: ConnectionStatus = ConnectionStatus.UNKNOWN
    last_check: Optional[datetime] = None
    last_connected: Optional[datetime] = None
    consecutive_failures: int = 0
    is_degraded_mode: bool = False
    degradation_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "spectrasherpa_status": self.spectrasherpa_status.value,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_connected": self.last_connected.isoformat() if self.last_connected else None,
            "consecutive_failures": self.consecutive_failures,
            "is_degraded_mode": self.is_degraded_mode,
            "degradation_reason": self.degradation_reason,
        }


class NetworkHealthService:
    """
    Service for monitoring network health and managing graceful degradation.

    In HYBRID mode, this service:
    - Periodically checks SpectraSherpa connectivity
    - Tracks connection state
    - Enables automatic fallback to local mode
    - Notifies listeners of state changes
    """

    # Configuration
    CHECK_INTERVAL_SECONDS = 60  # Check every minute
    FAILURE_THRESHOLD = 3  # Enter degraded mode after 3 consecutive failures
    RETRY_INTERVAL_DEGRADED = 30  # Retry more frequently in degraded mode

    def __init__(self):
        self._state = NetworkState()
        self._listeners: list[Callable[[NetworkState], None]] = []
        self._check_task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = threading.Lock()

    @property
    def state(self) -> NetworkState:
        """Get current network state"""
        return self._state

    @property
    def is_online(self) -> bool:
        """Check if SpectraSherpa is currently reachable"""
        return self._state.spectrasherpa_status == ConnectionStatus.CONNECTED

    @property
    def is_degraded(self) -> bool:
        """Check if operating in degraded mode"""
        return self._state.is_degraded_mode

    def add_listener(self, callback: Callable[[NetworkState], None]):
        """Add a listener for state changes"""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[NetworkState], None]):
        """Remove a state change listener"""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self):
        """Notify all listeners of state change"""
        for listener in self._listeners:
            try:
                listener(self._state)
            except Exception as e:
                logger.error(f"Error notifying network health listener: {e}")

    async def check_health(self) -> HealthCheckResult:
        """
        Perform a health check on SpectraSherpa.

        Returns:
            HealthCheckResult with current status
        """
        from app.services.spectrasherpa import get_spectrasherpa_service

        start_time = datetime.now(timezone.utc)
        spectrasherpa = get_spectrasherpa_service()

        if not spectrasherpa.is_configured:
            return HealthCheckResult(
                status=ConnectionStatus.DISCONNECTED,
                message="SpectraSherpa not configured",
                details={"reason": "no_api_key"}
            )

        try:
            self._state.spectrasherpa_status = ConnectionStatus.CHECKING
            is_healthy, message = await spectrasherpa.health_check()

            end_time = datetime.now(timezone.utc)
            latency_ms = (end_time - start_time).total_seconds() * 1000

            if is_healthy:
                return HealthCheckResult(
                    status=ConnectionStatus.CONNECTED,
                    message=message,
                    latency_ms=latency_ms
                )
            else:
                return HealthCheckResult(
                    status=ConnectionStatus.DISCONNECTED,
                    message=message,
                    latency_ms=latency_ms,
                    details={"reason": "health_check_failed"}
                )

        except Exception as e:
            logger.warning(f"Health check exception: {e}")
            return HealthCheckResult(
                status=ConnectionStatus.DISCONNECTED,
                message=str(e),
                details={"reason": "exception", "error": str(e)}
            )

    async def _update_state(self, result: HealthCheckResult):
        """Update internal state based on health check result"""
        with self._lock:
            old_status = self._state.spectrasherpa_status
            self._state.spectrasherpa_status = result.status
            self._state.last_check = result.timestamp

            if result.status == ConnectionStatus.CONNECTED:
                self._state.last_connected = result.timestamp
                self._state.consecutive_failures = 0

                # Exit degraded mode if we were in it
                if self._state.is_degraded_mode:
                    logger.info("SpectraSherpa connection restored, exiting degraded mode")
                    self._state.is_degraded_mode = False
                    self._state.degradation_reason = None
            else:
                self._state.consecutive_failures += 1

                # Enter degraded mode after threshold failures
                if (self._state.consecutive_failures >= self.FAILURE_THRESHOLD
                        and not self._state.is_degraded_mode):
                    logger.warning(
                        f"Entering degraded mode after {self._state.consecutive_failures} "
                        f"consecutive failures: {result.message}"
                    )
                    self._state.is_degraded_mode = True
                    self._state.degradation_reason = result.message

            # Notify listeners if status changed
            if old_status != result.status:
                self._notify_listeners()

    async def _health_check_loop(self):
        """Background loop for periodic health checks"""
        while self._running:
            try:
                result = await self.check_health()
                await self._update_state(result)

                # Adjust check interval based on state
                if self._state.is_degraded_mode:
                    await asyncio.sleep(self.RETRY_INTERVAL_DEGRADED)
                else:
                    await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
                await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

    async def start(self):
        """Start the health monitoring service"""
        if self._running:
            return

        # Only run in hybrid mode
        if app_config.mode != "hybrid":
            logger.info("Network health monitoring disabled (not in hybrid mode)")
            return

        self._running = True
        self._check_task = asyncio.create_task(self._health_check_loop())
        logger.info("Network health monitoring started")

        # Do an initial check
        result = await self.check_health()
        await self._update_state(result)

    async def stop(self):
        """Stop the health monitoring service"""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None
        logger.info("Network health monitoring stopped")

    def get_effective_mode(self) -> str:
        """
        Get the effective operating mode considering degradation.

        In hybrid mode, returns "local" if degraded, otherwise "hybrid".
        """
        if app_config.mode == "hybrid" and self._state.is_degraded_mode:
            return "local"
        return app_config.mode


# ============================================================================
# Singleton Instance
# ============================================================================

_service_instance: Optional[NetworkHealthService] = None


def get_network_health_service() -> NetworkHealthService:
    """Get the singleton network health service instance"""
    global _service_instance
    if _service_instance is None:
        _service_instance = NetworkHealthService()
    return _service_instance


async def start_network_health_service():
    """Start the network health service (call on app startup)"""
    service = get_network_health_service()
    await service.start()


async def stop_network_health_service():
    """Stop the network health service (call on app shutdown)"""
    global _service_instance
    if _service_instance:
        await _service_instance.stop()
        _service_instance = None
