"""Tests for unified config validation (Issue #4).

Verifies that startup.validate_config() catches misconfigurations:
- site_profile=demo without enterprise mode
- LLM keys with egress disabled
- CORS origins missing in non-local modes
- Security and concurrency checks

Note: Database engine enforcement (e.g. requiring a production backend for
multi-user modes) is the deployment layer's responsibility, not the OSS core.
"""

from __future__ import annotations

from unittest.mock import patch

from spectra_sherpa.app.core.startup import (
    ConfigValidationResult,
    _validate_concurrency,
    _validate_cors,
    _validate_database_mode,
    _validate_llm_config,
    _validate_security,
    _validate_site_profile,
    validate_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeAppConfig:
    """Minimal stand-in for AppConfig for testing validators."""

    def __init__(self, mode="local", site_profile=None, egress_enabled=False, llms=None):
        self.mode = mode
        self.site_profile = site_profile
        self.egress_enabled = egress_enabled
        self._llms = llms or {}

    def get_configured_llms(self):
        return {k: v for k, v in self._llms.items() if getattr(v, "is_configured", False)}


class _FakeLLM:
    def __init__(self, is_configured=True):
        self.is_configured = is_configured


class _FakeSettings:
    def __init__(
        self,
        secret_key=None,
        api_key="secure-api-key",
        database_url="sqlite+aiosqlite:///data/test.db",
    ):
        self.secret_key = secret_key or _STRONG_SECRET
        self.api_key = api_key
        self.database_url = database_url


_DEFAULT_SECRET = "local-dev-key"
_DEFAULT_API_KEY = "local-key"
_STRONG_SECRET = "-".join(("secure", "test", "runtime", "entropy", "123456"))
_PUBLISHED_SECRET_PLACEHOLDER = "-".join(("your", "super", "secret", "key", "change", "in", "production"))
_SHORT_SECRET = "-".join(("short", "but", "not", "default"))


# ---------------------------------------------------------------------------
# Database mode validation
# ---------------------------------------------------------------------------


class TestDatabaseMode:
    """Database engine enforcement is the deployment layer's responsibility.

    The OSS core is database-agnostic (SQLAlchemy abstraction). These tests
    verify that _validate_database_mode() never blocks startup regardless of
    the database engine or app mode.
    """

    def test_enterprise_sqlite_ok(self):
        """Enterprise + SQLite must not crash — deployment layer handles enforcement."""
        cfg = _FakeAppConfig(mode="enterprise")
        stg = _FakeSettings(database_url="sqlite+aiosqlite:///data/test.db")
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
        ):
            issues = _validate_database_mode()
        assert len(issues) == 0

    def test_local_sqlite_ok(self):
        cfg = _FakeAppConfig(mode="local")
        stg = _FakeSettings(database_url="sqlite+aiosqlite:///data/test.db")
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
        ):
            issues = _validate_database_mode()
        assert len(issues) == 0

    def test_hybrid_sqlite_ok(self):
        cfg = _FakeAppConfig(mode="hybrid")
        stg = _FakeSettings(database_url="sqlite+aiosqlite:///data/test.db")
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
        ):
            issues = _validate_database_mode()
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Site profile validation
# ---------------------------------------------------------------------------


class TestSiteProfile:
    def test_demo_requires_enterprise(self):
        cfg = _FakeAppConfig(mode="local", site_profile="demo")
        with patch("spectra_sherpa.app.core.startup.app_config", cfg):
            issues = _validate_site_profile()
        errors = [issue for issue in issues if issue.level == "error"]
        assert any("enterprise" in issue.message.lower() for issue in errors)

    def test_demo_enterprise_ok(self):
        cfg = _FakeAppConfig(mode="enterprise", site_profile="demo")
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch.dict("os.environ", {"ENTERPRISE_PASSWORD": "welcome_to_spectra_sherpa"}),
        ):
            issues = _validate_site_profile()
        assert len(issues) == 0

    def test_demo_enterprise_requires_access_code(self):
        cfg = _FakeAppConfig(mode="enterprise", site_profile="demo")
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch.dict("os.environ", {}, clear=False),
        ):
            import os

            os.environ.pop("ENTERPRISE_PASSWORD", None)
            issues = _validate_site_profile()
        assert len(issues) == 1
        assert issues[0].level == "error"
        assert "ENTERPRISE_PASSWORD" in issues[0].message

    def test_no_profile_ok(self):
        cfg = _FakeAppConfig(mode="local", site_profile=None)
        with patch("spectra_sherpa.app.core.startup.app_config", cfg):
            issues = _validate_site_profile()
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# LLM config validation
# ---------------------------------------------------------------------------


class TestLLMConfig:
    def test_llm_egress_warning(self):
        cfg = _FakeAppConfig(
            mode="local",
            egress_enabled=False,
            llms={"openai": _FakeLLM(is_configured=True)},
        )
        with patch("spectra_sherpa.app.core.startup.app_config", cfg):
            issues = _validate_llm_config()
        assert len(issues) == 1
        assert issues[0].level == "warning"
        assert "egress" in issues[0].message.lower()

    def test_llm_egress_enabled_ok(self):
        cfg = _FakeAppConfig(
            mode="hybrid",
            egress_enabled=True,
            llms={"openai": _FakeLLM(is_configured=True)},
        )
        with patch("spectra_sherpa.app.core.startup.app_config", cfg):
            issues = _validate_llm_config()
        assert len(issues) == 0

    def test_no_llm_keys_ok(self):
        cfg = _FakeAppConfig(mode="local", egress_enabled=False, llms={})
        with patch("spectra_sherpa.app.core.startup.app_config", cfg):
            issues = _validate_llm_config()
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# CORS validation
# ---------------------------------------------------------------------------


class TestCORS:
    def test_cors_warning_nonlocal(self):
        cfg = _FakeAppConfig(mode="hybrid")
        with patch("spectra_sherpa.app.core.startup.app_config", cfg), patch.dict("os.environ", {}, clear=False):
            # Ensure CORS_ORIGINS is NOT set
            import os

            os.environ.pop("CORS_ORIGINS", None)
            issues = _validate_cors()
        assert len(issues) == 1
        assert issues[0].level == "warning"
        assert "CORS_ORIGINS" in issues[0].message

    def test_cors_local_ok(self):
        cfg = _FakeAppConfig(mode="local")
        with patch("spectra_sherpa.app.core.startup.app_config", cfg):
            issues = _validate_cors()
        assert len(issues) == 0

    def test_cors_explicit_ok(self):
        cfg = _FakeAppConfig(mode="enterprise")
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch.dict("os.environ", {"CORS_ORIGINS": "https://app.example.com"}),
        ):
            issues = _validate_cors()
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Security validation
# ---------------------------------------------------------------------------


class TestSecurity:
    def test_local_default_key_warning(self):
        cfg = _FakeAppConfig(mode="local")
        stg = _FakeSettings(secret_key=_DEFAULT_SECRET)
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
            patch.dict("os.environ", {}, clear=False),
        ):
            import os

            os.environ.pop("HOST", None)
            os.environ.pop("UVICORN_HOST", None)
            os.environ.pop("SPECTRA_SHERPA_ALLOW_LOCAL_NETWORK", None)
            os.environ.pop("SPECTRASHERPA_ALLOW_LOCAL_NETWORK", None)
            issues = _validate_security()
        assert len(issues) == 1
        assert issues[0].level == "warning"

    def test_local_non_loopback_bind_is_error_without_opt_in(self):
        cfg = _FakeAppConfig(mode="local")
        stg = _FakeSettings(secret_key=_STRONG_SECRET)
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
            patch.dict("os.environ", {"HOST": "0.0.0.0"}, clear=False),
        ):
            issues = _validate_security()
        errors = [i for i in issues if i.level == "error"]
        assert len(errors) == 1
        assert "Local mode is bound to non-loopback" in errors[0].message

    def test_local_non_loopback_bind_can_be_explicitly_allowed(self):
        cfg = _FakeAppConfig(mode="local")
        stg = _FakeSettings(secret_key=_STRONG_SECRET)
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
            patch.dict("os.environ", {"HOST": "0.0.0.0", "SPECTRA_SHERPA_ALLOW_LOCAL_NETWORK": "true"}),
        ):
            issues = _validate_security()
        assert not [i for i in issues if i.level == "error"]
        warnings = [i for i in issues if i.level == "warning"]
        assert len(warnings) == 1
        assert "local network access is explicitly allowed" in warnings[0].message

    def test_enterprise_default_key_error(self):
        cfg = _FakeAppConfig(mode="enterprise")
        stg = _FakeSettings(secret_key=_DEFAULT_SECRET)
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
        ):
            issues = _validate_security()
        errors = [i for i in issues if i.level == "error"]
        assert len(errors) >= 1
        assert "SECRET_KEY" in errors[0].message

    def test_enterprise_rejects_published_placeholder_secret(self):
        cfg = _FakeAppConfig(mode="enterprise")
        stg = _FakeSettings(secret_key=_PUBLISHED_SECRET_PLACEHOLDER)
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
        ):
            issues = _validate_security()
        errors = [i for i in issues if i.level == "error"]
        assert any("SECRET_KEY" in error.message for error in errors)

    def test_enterprise_rejects_short_secret(self):
        cfg = _FakeAppConfig(mode="enterprise")
        stg = _FakeSettings(secret_key=_SHORT_SECRET)
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
        ):
            issues = _validate_security()
        errors = [i for i in issues if i.level == "error"]
        assert any("at least" in error.message for error in errors)


# ---------------------------------------------------------------------------
# Concurrency validation
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_multi_worker_enterprise_error(self):
        cfg = _FakeAppConfig(mode="enterprise")
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch.dict("os.environ", {"WEB_CONCURRENCY": "4"}),
        ):
            issues = _validate_concurrency()
        assert len(issues) == 1
        assert issues[0].level == "error"
        assert "WEB_CONCURRENCY" in issues[0].message

    def test_single_worker_ok(self):
        cfg = _FakeAppConfig(mode="enterprise")
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch.dict("os.environ", {"WEB_CONCURRENCY": "1"}),
        ):
            issues = _validate_concurrency()
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Integration: validate_config()
# ---------------------------------------------------------------------------


class TestValidateConfig:
    def test_local_mode_no_errors(self):
        """Local mode with all defaults should produce no errors."""
        cfg = _FakeAppConfig(mode="local")
        stg = _FakeSettings(
            secret_key=_STRONG_SECRET,
            database_url="sqlite+aiosqlite:///data/test.db",
        )
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
            patch.dict("os.environ", {}, clear=False),
        ):
            import os

            os.environ.pop("ENTERPRISE_PASSWORD", None)
            result = validate_config()
        assert isinstance(result, ConfigValidationResult)
        assert not result.has_errors

    def test_multiple_issues_collected(self):
        """Enterprise mode with misconfigs should collect multiple issues."""
        cfg = _FakeAppConfig(mode="enterprise", site_profile="demo")
        stg = _FakeSettings(
            secret_key=_DEFAULT_SECRET,
            database_url="sqlite+aiosqlite:///data/test.db",
        )
        with (
            patch("spectra_sherpa.app.core.startup.app_config", cfg),
            patch("spectra_sherpa.app.core.startup.settings", stg),
        ):
            result = validate_config()
        # Should have at least: SECRET_KEY error (security)
        assert result.has_errors
        assert len(result.errors) >= 1
        categories = {e.category for e in result.errors}
        assert "security" in categories
