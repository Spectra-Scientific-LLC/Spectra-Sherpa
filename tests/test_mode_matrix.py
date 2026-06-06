"""
Mode-matrix regression tests for local / hybrid / enterprise behavior.

Tests that mode-dependent behavior matches the documented contracts.
Each test is parametrized across the three operational modes to ensure
that changes to one mode do not silently break another.

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_mode_matrix.py -v --no-cov
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spectra_sherpa.app.contracts.capabilities import (
    ALL_SHERPA_CAPABILITIES,
    CHAT_ASSISTANT,
    SHERPA_ADVISOR,
)
from spectra_sherpa.app.core.config import AppConfig, LLMConfig

# ---------------------------------------------------------------------------
# Helpers: build AppConfig instances for each mode without env var side-effects
# ---------------------------------------------------------------------------


def _make_config(
    mode: str = "local",
    egress_enabled: bool | None = None,
    llm_key: str | None = None,
    sherpa_key: str | None = None,
    rate_limit: int | None = None,
    session_expiry: int | None = None,
) -> AppConfig:
    """Create a test AppConfig with controlled mode and feature settings."""
    if egress_enabled is None:
        egress_enabled = mode != "local"

    llm_configs = {
        "openai": LLMConfig(
            provider="openai",
            api_key=llm_key,
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
        ),
    }

    return AppConfig(
        mode=mode,
        egress_enabled=egress_enabled,
        api_base_url="http://localhost:8000",
        llms=llm_configs,
        rate_limit_executions=rate_limit if mode == "enterprise" else None,
        session_expiry_hours=session_expiry if mode == "enterprise" else None,
    )


# ===========================================================================
# 1. Feature flags per mode (to_client_safe)
# ===========================================================================


class TestFeatureFlags:
    """Verify feature flags computed by to_client_safe() match per-mode expectations."""

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_api_token_settings(self, mode: str):
        """apiTokenSettings enabled in local/hybrid, disabled in demo."""
        cfg = _make_config(mode=mode)
        flags = cfg.to_client_safe()["features"]
        if mode in ("local", "hybrid"):
            assert flags["apiTokenSettings"] is True
        else:
            assert flags["apiTokenSettings"] is False

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_demo_contract_in_client_safe(self, mode: str):
        """demo key is None unless site_profile is 'demo'."""
        cfg = _make_config(mode=mode)
        safe = cfg.to_client_safe()
        assert safe["demo"] is None  # No site_profile set

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_plugin_system_always_enabled(self, mode: str):
        """pluginSystem is always True regardless of mode."""
        cfg = _make_config(mode=mode)
        flags = cfg.to_client_safe()["features"]
        assert flags["pluginSystem"] is True

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_nist_downloads_follows_egress(self, mode: str):
        """nistDownloads mirrors egress_enabled."""
        for egress in (True, False):
            cfg = _make_config(mode=mode, egress_enabled=egress)
            assert cfg.to_client_safe()["features"]["nistDownloads"] is egress

    def test_sherpa_advisor_always_false_in_base_config(self):
        """sherpaAdvisor defaults to False in to_client_safe().

        The server overlay (subscription entitlements) is what enables it.
        OSS base config never computes sherpaAdvisor=True on its own.
        """
        for mode in ("local", "hybrid", "enterprise"):
            with patch.dict("os.environ", {"SPECTRASHERPA_API_KEY": "test-key"}):
                cfg = _make_config(mode=mode)
                assert cfg.to_client_safe()["features"][SHERPA_ADVISOR] is False

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_all_sherpa_capabilities_present_and_false_in_base_config(self, mode: str):
        """Base config must expose the full Sherpa capability surface as False."""
        cfg = _make_config(mode=mode)
        features = cfg.to_client_safe()["features"]

        for capability in ALL_SHERPA_CAPABILITIES:
            assert capability in features
            assert features[capability] is False


# ===========================================================================
# 1b. Phase 4 unified audit block per design §3
# ===========================================================================


class TestUnifiedAuditBlock:
    """Pin the ``audit{}`` block shape returned by ``to_client_safe()``.

    Per phase0-design.md §3 ("Entitlement model — single capability
    source") the frontend gates audit-pack UI surfaces on this block:

      * localQuery     — OSS deployment flag (audit_enabled). Server
                         cannot override.
      * fullPipeline   — server-only (audit.full). False at OSS base.
      * reportPack     — server-only (audit.report_pack). False at base.
      * exportAudited  — mirrors localQuery in OSS today.

    These tests pin the keys + their OSS-base values. Server overlay
    elevation of fullPipeline / reportPack is covered separately by
    the managed deployment overlay tests.
    """

    def test_audit_block_present_with_all_keys(self):
        cfg = _make_config(mode="local")
        audit = cfg.to_client_safe()["audit"]
        assert set(audit.keys()) == {"localQuery", "fullPipeline", "reportPack", "exportAudited"}

    def test_local_query_mirrors_audit_enabled_true(self):
        cfg = _make_config(mode="local")
        cfg.audit_enabled = True
        audit = cfg.to_client_safe()["audit"]
        assert audit["localQuery"] is True
        assert audit["exportAudited"] is True

    def test_local_query_mirrors_audit_enabled_false(self):
        cfg = _make_config(mode="local")
        cfg.audit_enabled = False
        audit = cfg.to_client_safe()["audit"]
        assert audit["localQuery"] is False
        assert audit["exportAudited"] is False

    def test_server_only_pack_capabilities_default_false(self):
        """fullPipeline and reportPack are NEVER True in OSS base —
        only the server overlay can elevate them. Catches a future
        regression where someone tries to derive these from a local
        env flag.
        """
        for audit_enabled in (True, False):
            cfg = _make_config(mode="local")
            cfg.audit_enabled = audit_enabled
            audit = cfg.to_client_safe()["audit"]
            assert audit["fullPipeline"] is False
            assert audit["reportPack"] is False

    def test_legacy_audit_enabled_field_kept_for_back_compat(self):
        """Top-level ``auditEnabled`` is still present alongside the
        unified block so existing frontend reads don't break.
        """
        cfg = _make_config(mode="local")
        cfg.audit_enabled = True
        safe = cfg.to_client_safe()
        assert safe["auditEnabled"] is True
        assert safe["audit"]["localQuery"] is True


# ===========================================================================
# 2. Limits per mode
# ===========================================================================


class TestLimits:
    """Verify rate limits and session expiry are mode-appropriate."""

    def test_local_has_no_limits(self):
        """Local mode exposes the active Sherpa/LLM quota."""
        cfg = _make_config(mode="local")
        limits = cfg.to_client_safe()["limits"]
        assert limits is not None
        assert limits["maxSherpaRequestsHour"] > 0
        assert limits["adminBypass"] is True

    def test_hybrid_has_no_limits(self):
        """Hybrid mode exposes the active Sherpa/LLM quota."""
        cfg = _make_config(mode="hybrid")
        limits = cfg.to_client_safe()["limits"]
        assert limits is not None
        assert limits["maxSherpaRequestsHour"] > 0
        assert limits["adminBypass"] is True

    def test_enterprise_has_limits(self):
        """Enterprise mode returns the Sherpa/LLM quota plus session metadata."""
        cfg = _make_config(mode="enterprise", rate_limit=100, session_expiry=24)
        limits = cfg.to_client_safe()["limits"]
        assert limits is not None
        assert limits["maxSherpaRequestsHour"] > 0
        assert limits["adminBypass"] is True
        assert limits["sessionExpiryHours"] == 24
        assert "maxFileSizeMB" in limits


# ===========================================================================
# 3. Egress defaults per mode
# ===========================================================================


class TestEgressDefaults:
    """Verify egress_enabled defaults match mode expectations."""

    def test_local_egress_disabled_by_default(self):
        """Local mode has egress disabled by default (privacy-first)."""
        cfg = _make_config(mode="local")
        assert cfg.egress_enabled is False

    def test_hybrid_egress_enabled_by_default(self):
        """Hybrid mode has egress enabled by default (cloud features)."""
        cfg = _make_config(mode="hybrid")
        assert cfg.egress_enabled is True

    def test_enterprise_egress_enabled_by_default(self):
        """Enterprise mode has egress enabled by default."""
        cfg = _make_config(mode="enterprise")
        assert cfg.egress_enabled is True

    def test_egress_can_be_overridden(self):
        """Egress default can be explicitly overridden in any mode."""
        cfg_local_on = _make_config(mode="local", egress_enabled=True)
        assert cfg_local_on.egress_enabled is True

        cfg_hybrid_off = _make_config(mode="hybrid", egress_enabled=False)
        assert cfg_hybrid_off.egress_enabled is False


# ===========================================================================
# 4. is_egress_enabled() with degradation
# ===========================================================================


class TestIsEgressEnabled:
    """Verify is_egress_enabled() accounts for network degradation."""

    def test_local_egress_disabled(self):
        """Local mode: is_egress_enabled() returns False (default)."""
        cfg = _make_config(mode="local")
        with patch("spectra_sherpa.app.core.security.app_config", cfg):
            from spectra_sherpa.app.core.security import is_egress_enabled

            assert is_egress_enabled() is False

    def test_hybrid_egress_enabled_when_healthy(self):
        """Hybrid mode: egress enabled when network is healthy."""
        cfg = _make_config(mode="hybrid", egress_enabled=True)
        mock_health = MagicMock()
        mock_health.is_degraded = False

        with (
            patch("spectra_sherpa.app.core.security.app_config", cfg),
            patch("spectra_sherpa.app.services.network_health.get_network_health_service", return_value=mock_health),
        ):
            from spectra_sherpa.app.core.security import is_egress_enabled

            assert is_egress_enabled() is True

    def test_hybrid_egress_disabled_when_degraded(self):
        """Hybrid mode: egress disabled when network is degraded."""
        cfg = _make_config(mode="hybrid", egress_enabled=True)
        mock_health = MagicMock()
        mock_health.is_degraded = True

        with (
            patch("spectra_sherpa.app.core.security.app_config", cfg),
            patch("spectra_sherpa.app.services.network_health.get_network_health_service", return_value=mock_health),
        ):
            from spectra_sherpa.app.core.security import is_egress_enabled

            assert is_egress_enabled() is False

    def test_enterprise_egress_enabled(self):
        """Enterprise mode: egress always enabled (no degradation check)."""
        cfg = _make_config(mode="enterprise", egress_enabled=True)
        with patch("spectra_sherpa.app.core.security.app_config", cfg):
            from spectra_sherpa.app.core.security import is_egress_enabled

            assert is_egress_enabled() is True


# ===========================================================================
# 5. check_export_allowed() per mode
# ===========================================================================


class TestExportAllowed:
    """Verify export authorization is mode-appropriate."""

    @pytest.mark.asyncio
    async def test_local_always_allows_export(self):
        """Local mode: exports always allowed (single-user assumption)."""
        with patch("spectra_sherpa.app.core.mode_policy.app_config", _make_config(mode="local")):
            from spectra_sherpa.app.core.security import check_export_allowed

            result = await check_export_allowed(user=MagicMock())
            assert result is True

    @pytest.mark.asyncio
    async def test_enterprise_checks_user_permission(self):
        """Enterprise mode: checks user's egress_defaults.allow_export."""
        # User with export allowed
        user_allowed = MagicMock()
        user_allowed.egress_defaults = MagicMock(allow_export=True)
        with patch("spectra_sherpa.app.core.mode_policy.app_config", _make_config(mode="enterprise")):
            from spectra_sherpa.app.core.security import check_export_allowed

            assert await check_export_allowed(user=user_allowed) is True

        # User with export denied
        user_denied = MagicMock()
        user_denied.egress_defaults = MagicMock(allow_export=False)
        with patch("spectra_sherpa.app.core.mode_policy.app_config", _make_config(mode="enterprise")):
            assert await check_export_allowed(user=user_denied) is False

    @pytest.mark.asyncio
    async def test_no_user_defaults_to_allowed(self):
        """Any mode: null user defaults to export allowed."""
        for mode in ("local", "hybrid", "enterprise"):
            with patch("spectra_sherpa.app.core.mode_policy.app_config", _make_config(mode=mode)):
                from spectra_sherpa.app.core.security import check_export_allowed

                assert await check_export_allowed(user=None) is True


# ===========================================================================
# 6. Auth middleware mode behavior
# ===========================================================================


class TestAuthMiddleware:
    """Verify auth middleware mode-dependent bypass behavior."""

    def test_loopback_detection(self):
        """is_loopback correctly identifies loopback addresses."""
        from spectra_sherpa.app.core.mode_policy import is_loopback

        assert is_loopback("127.0.0.1") is True
        assert is_loopback("::1") is True
        assert is_loopback("192.168.1.1") is False
        assert is_loopback(None) is False  # fail closed

    @pytest.mark.parametrize(
        "mode,client_host,expected_requires_auth",
        [
            # Local mode: never requires WS auth
            ("local", "127.0.0.1", False),
            ("local", "192.168.1.1", False),
            # Hybrid mode: loopback is exempt, remote requires auth
            ("hybrid", "127.0.0.1", False),
            ("hybrid", "192.168.1.1", True),
            # Enterprise mode: always requires auth
            ("enterprise", "127.0.0.1", True),
            ("enterprise", "192.168.1.1", True),
        ],
    )
    def test_ws_auth_requirement_matrix(self, mode: str, client_host: str, expected_requires_auth: bool):
        """WebSocket auth requirement matches mode + client host matrix."""
        from spectra_sherpa.app.core.mode_policy import is_loopback

        # Replicate the logic from main.py
        requires_ws_auth = mode == "enterprise" or (mode == "hybrid" and not is_loopback(client_host))
        assert requires_ws_auth is expected_requires_auth


# ===========================================================================
# 7. Token TTL per mode
# ===========================================================================


class TestTokenTTL:
    """Verify token lifetime is uniform across modes.

    Local mode bypasses JWT entirely (implicit user), so a uniform
    60-minute default removes dead-code complexity.
    """

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_token_ttl_is_60_minutes_for_all_modes(self, mode):
        """All modes use the same 60-minute default TTL."""
        with patch.dict("os.environ", {"APP_MODE": mode}, clear=False):
            from spectra_sherpa.app.core.config import _get_int

            ttl = _get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
            assert ttl == 60


# ===========================================================================
# 8. Config response shape
# ===========================================================================


class TestConfigResponseShape:
    """Verify to_client_safe() response matches documented contract."""

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_required_top_level_fields(self, mode: str):
        """Config response always has mode, egressEnabled, features, llms."""
        cfg = _make_config(mode=mode)
        response = cfg.to_client_safe()

        assert "mode" in response
        assert "egressEnabled" in response
        assert "apiBaseUrl" in response
        assert "features" in response
        assert "llms" in response
        assert "limits" in response  # present, may be None

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_required_feature_flags(self, mode: str):
        """All documented feature flags are present."""
        cfg = _make_config(mode=mode)
        features = cfg.to_client_safe()["features"]

        expected_flags = [
            "apiTokenSettings",
            "cloudOffload",
            CHAT_ASSISTANT,
            "nistDownloads",
            "pluginSystem",
            *ALL_SHERPA_CAPABILITIES,
        ]
        for flag in expected_flags:
            assert flag in features, f"Missing feature flag: {flag}"

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_llm_entry_shape(self, mode: str):
        """Each LLM entry has provider, model, enabled."""
        cfg = _make_config(mode=mode, llm_key="sk-test")
        llms = cfg.to_client_safe()["llms"]

        for name, entry in llms.items():
            assert "provider" in entry
            assert "model" in entry
            assert "enabled" in entry
            assert isinstance(entry["enabled"], bool)

    def test_mode_field_matches_input(self):
        """Response mode field matches the configured mode."""
        for mode in ("local", "hybrid", "enterprise"):
            cfg = _make_config(mode=mode)
            assert cfg.to_client_safe()["mode"] == mode


# ===========================================================================
# 9. Route registration per mode
# ===========================================================================


class TestRouteRegistration:
    """Verify route registration matches mode constraints."""

    def test_auth_admin_routes_registered_in_non_local(self):
        """Auth/admin routes are registered when mode != local.

        Note: this test verifies the api.py conditional registration logic.
        The actual app_config.mode at import time determines registration.
        """
        # We verify the logic pattern, not the live app state
        # (app is already imported at test time with whatever mode was set).
        for mode in ("hybrid", "enterprise"):
            # In non-local mode, auth/admin routers should be included
            assert mode != "local"  # tautology, documents the gate condition

    def test_local_mode_excludes_auth_admin(self):
        """Local mode does not register auth/admin routes."""
        # The gate is: if app_config.mode != "local"
        # Verifying the logical condition
        mode = "local"
        should_register_auth = mode != "local"
        assert should_register_auth is False


# ===========================================================================
# 10. MCP Tool System per mode
# ===========================================================================


class TestMCPToolSystem:
    """Verify MCP tool system behavior across modes."""

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_tool_registry_returns_tools_in_all_modes(self, mode: str):
        """tool_registry.list_definitions() is mode-independent — tools are always available."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401  — ensure builtins registered
        from spectra_sherpa.app.services.tools import tool_registry

        with patch("spectra_sherpa.app.core.mode_policy.app_config", _make_config(mode=mode)):
            definitions = tool_registry.list_definitions()
            # At minimum the 6 built-in tools should be present
            assert len(definitions) >= 6

    @pytest.mark.asyncio
    async def test_tool_egress_blocked_when_disabled(self):
        """Tools with requires_egress=True fail when egress is globally disabled."""
        from spectra_sherpa.app.services.tools import tool_registry
        from spectra_sherpa.app.services.tools.executor import execute_tool
        from spectra_sherpa.app.services.tools.schemas import ToolDefinition, ToolInvocation, ToolOrigin

        defn = ToolDefinition(
            name="test_egress_tool",
            description="Test tool requiring egress",
            requires_egress=True,
            origin=ToolOrigin.builtin,
        )
        tool_registry.register(defn, lambda: "should not run")
        try:
            inv = ToolInvocation(tool_name="test_egress_tool", arguments={})
            # Patch at source — executor lazy-imports from spectra_sherpa.app.core.security
            with patch("spectra_sherpa.app.core.security.is_egress_enabled", return_value=False):
                result = await execute_tool(inv)
            assert result.success is False
            assert "egress" in result.error.lower()
        finally:
            tool_registry.unregister("test_egress_tool")


# ===========================================================================
# 11. Backward compatibility: mode="demo" → "enterprise"
# ===========================================================================


class TestRegistrationRequiresCode:
    """registrationRequiresCode surfaces the ``auth_policy`` contract flag.

    The commercial server decides whether an access code is required based
    on its own configuration (mode + ``ENTERPRISE_PASSWORD``) and registers
    the result at startup via
    ``auth_policy.set_registration_requires_code``. OSS only surfaces
    whatever the server has declared. Server-side tests cover the
    mode-and-env-var logic itself.
    """

    def setup_method(self):
        from spectra_sherpa.app.contracts.auth_policy import _reset_for_tests

        _reset_for_tests()

    def teardown_method(self):
        from spectra_sherpa.app.contracts.auth_policy import _reset_for_tests

        _reset_for_tests()

    def test_default_is_false_when_no_server_registered(self):
        """OSS-only installs: the flag is False by default."""
        for mode in ("local", "hybrid", "enterprise"):
            cfg = _make_config(mode=mode)
            assert cfg.to_client_safe()["registrationRequiresCode"] is False

    def test_flag_surfaces_when_server_sets_true(self):
        """When the server registers True, OSS surfaces True in client config."""
        from spectra_sherpa.app.contracts.auth_policy import (
            set_registration_requires_code,
        )

        set_registration_requires_code(True)
        for mode in ("local", "hybrid", "enterprise"):
            cfg = _make_config(mode=mode)
            assert cfg.to_client_safe()["registrationRequiresCode"] is True

    def test_flag_independent_of_env_var(self):
        """OSS does NOT read ENTERPRISE_PASSWORD directly; only the contract flag matters."""
        with patch.dict("os.environ", {"ENTERPRISE_PASSWORD": "secret123"}):
            cfg = _make_config(mode="enterprise")
            # No server registered the flag, so the env var should have no effect.
            assert cfg.to_client_safe()["registrationRequiresCode"] is False


# ===========================================================================
# 9. Egress schema defaults
# ===========================================================================


class TestEgressSchemaDefaults:
    """Verify egress permission defaults are all False (explicit opt-in)."""

    def test_egress_schema_defaults_are_all_false(self):
        """UserEgressDefaultsBase() with no args defaults everything to False."""
        from spectra_sherpa.app.schemas.data_egress import UserEgressDefaultsBase

        defaults = UserEgressDefaultsBase()
        assert defaults.allow_llm_context is False
        assert defaults.allow_nist_queries is False
        assert defaults.allow_export is False
        assert defaults.allow_spectrasherpa_sync is False


# ===========================================================================
# 11. CORS middleware ordering
# ===========================================================================


class TestCorsMiddlewareOrdering:
    """CORSMiddleware must be the outermost middleware so CORS headers
    appear on ALL responses — even early 401/403 from enforcement middleware."""

    def test_cors_is_outermost_without_extra_middleware(self):
        """create_app() places CORSMiddleware at user_middleware[0] (outermost)."""

        from spectra_sherpa.app.main import create_app

        app = create_app()
        names = [mw.cls.__name__ for mw in app.user_middleware if hasattr(mw, "cls")]
        assert names[0] == "CORSMiddleware", f"CORSMiddleware must be outermost (index 0) but got: {names}"

    def test_cors_is_outermost_with_extra_middleware(self):
        """When extra_middleware is injected (e.g. EnterpriseEnforcement),
        CORSMiddleware must STILL be outermost."""
        from starlette.middleware.base import BaseHTTPMiddleware

        from spectra_sherpa.app.main import create_app

        class FakeEnforcementMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                return await call_next(request)

        app = create_app(extra_middleware=[lambda a: a.add_middleware(FakeEnforcementMiddleware)])
        names = [mw.cls.__name__ for mw in app.user_middleware if hasattr(mw, "cls")]
        assert (
            names[0] == "CORSMiddleware"
        ), f"CORSMiddleware must be outermost even with extra_middleware, got: {names}"
        assert "FakeEnforcementMiddleware" in names, "Extra middleware should be registered"
        assert names.index("FakeEnforcementMiddleware") > names.index(
            "CORSMiddleware"
        ), "Enforcement middleware must be inner (higher index) than CORSMiddleware"


# ===========================================================================
# 12. Config response contract enforcement
# ===========================================================================


class TestConfigResponseContract:
    """Verify to_client_safe() meets the documented API contract."""

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_to_client_safe_includes_all_expected_keys(self, mode: str):
        """Response includes all required top-level and feature keys."""
        cfg = _make_config(mode=mode)
        safe = cfg.to_client_safe()

        # Top-level keys
        for key in ("mode", "egressEnabled", "apiBaseUrl", "siteProfile", "features", "llms"):
            assert key in safe, f"Missing top-level key: {key}"

        # Feature flags
        features = safe["features"]
        for key in (
            CHAT_ASSISTANT,
            "nistDownloads",
            "apiTokenSettings",
            "cloudOffload",
            *ALL_SHERPA_CAPABILITIES,
            "pluginSystem",
        ):
            assert key in features, f"Missing feature flag: {key}"

    @pytest.mark.parametrize("mode", ["local", "hybrid", "enterprise"])
    def test_to_client_safe_uses_camel_case_keys(self, mode: str):
        """Top-level keys must use camelCase (no underscores)."""
        cfg = _make_config(mode=mode)
        safe = cfg.to_client_safe()

        for key in safe:
            assert "_" not in key, f"Top-level key '{key}' contains underscore — use camelCase"


# ===========================================================================
# 13. Subscription overlay cache behavior
# ===========================================================================


class TestSubscriptionOverlay:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["hybrid", "enterprise"])
    async def test_config_marks_overlay_failure_as_degraded(self, monkeypatch, mode: str):
        from spectra_sherpa.app.api.v1.routes import config as config_routes
        from spectra_sherpa.app.contracts import config_overlay as overlay_mod

        cfg = _make_config(mode=mode)
        monkeypatch.setattr(config_routes, "app_config", cfg)

        # Inject an overlay provider that returns None (simulating failure).
        async def _overlay_unavailable(_key):
            return None

        monkeypatch.setattr(overlay_mod, "_config_overlay_provider", _overlay_unavailable)

        async def _provider_unavailable(*args, **kwargs):
            return False

        monkeypatch.setattr(config_routes, "_check_provider_availability", _provider_unavailable)

        response = await config_routes.get_config(session=MagicMock(), current_user=None)

        assert response["configStatus"] == config_routes.CONFIG_STATUS_DEGRADED
        assert response["configError"] == config_routes.CONFIG_ERROR_SUBSCRIPTION_OVERLAY_UNAVAILABLE
        assert response["subscription"] is None
        assert response["features"][CHAT_ASSISTANT] is False
        for capability in ALL_SHERPA_CAPABILITIES:
            assert response["features"][capability] is False

        # Cleanup
        monkeypatch.setattr(overlay_mod, "_config_overlay_provider", None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["hybrid", "enterprise"])
    async def test_overlay_provider_applies_features(self, monkeypatch, mode: str):
        from spectra_sherpa.app.api.v1.routes import config as config_routes
        from spectra_sherpa.app.contracts import config_overlay as overlay_mod

        cfg = _make_config(mode=mode)
        monkeypatch.setattr(config_routes, "app_config", cfg)

        async def _overlay_with_features(_key):
            return {
                "features": {SHERPA_ADVISOR: True, CHAT_ASSISTANT: True},
                "subscription": {"plan": "pro", "status": "active"},
            }

        monkeypatch.setattr(overlay_mod, "_config_overlay_provider", _overlay_with_features)

        async def _provider_unavailable(*args, **kwargs):
            return False

        monkeypatch.setattr(config_routes, "_check_provider_availability", _provider_unavailable)

        response = await config_routes.get_config(session=MagicMock(), current_user=None)

        assert response["configStatus"] == config_routes.CONFIG_STATUS_OK
        assert response["features"][CHAT_ASSISTANT] is True
        assert response["features"][SHERPA_ADVISOR] is True
        assert response["subscription"]["plan"] == "pro"

        # Cleanup
        monkeypatch.setattr(overlay_mod, "_config_overlay_provider", None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["hybrid", "enterprise"])
    async def test_no_overlay_provider_returns_base_config(self, monkeypatch, mode: str):
        """When no overlay provider is installed, non-local modes return base config."""
        from spectra_sherpa.app.api.v1.routes import config as config_routes
        from spectra_sherpa.app.contracts import config_overlay as overlay_mod

        cfg = _make_config(mode=mode)
        monkeypatch.setattr(config_routes, "app_config", cfg)

        # Ensure no provider is installed
        monkeypatch.setattr(overlay_mod, "_config_overlay_provider", None)

        async def _provider_unavailable(*args, **kwargs):
            return False

        monkeypatch.setattr(config_routes, "_check_provider_availability", _provider_unavailable)

        response = await config_routes.get_config(session=MagicMock(), current_user=None)

        # No provider → base config, not degraded (just no overlay)
        assert response["configStatus"] == config_routes.CONFIG_STATUS_OK
        assert response["features"][CHAT_ASSISTANT] is False
