"""Tests for the Demo Contract and demo_guard route guard."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.deps import demo_guard
from spectra_sherpa.app.core.config import AppConfig, DemoContract


class TestDemoGuard:
    """demo_guard blocks disabled capabilities in demo profile."""

    def test_blocks_disabled_capability(self, monkeypatch: pytest.MonkeyPatch) -> None:
        contract = DemoContract(disabled_capabilities=["data_upload"])
        fake_config = SimpleNamespace(site_profile="demo", demo_contract=contract)
        monkeypatch.setattr(
            "spectra_sherpa.app.api.deps.app_config", fake_config
        )
        guard = demo_guard("data_upload")
        with pytest.raises(HTTPException) as exc_info:
            guard()
        assert exc_info.value.status_code == 403

    def test_allows_enabled_capability(self, monkeypatch: pytest.MonkeyPatch) -> None:
        contract = DemoContract(disabled_capabilities=["data_upload"])
        fake_config = SimpleNamespace(site_profile="demo", demo_contract=contract)
        monkeypatch.setattr(
            "spectra_sherpa.app.api.deps.app_config", fake_config
        )
        guard = demo_guard("some_other_thing")
        # Should not raise
        guard()

    def test_non_demo_profile_allows_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        contract = DemoContract(disabled_capabilities=["data_upload"])
        fake_config = SimpleNamespace(site_profile="production", demo_contract=contract)
        monkeypatch.setattr(
            "spectra_sherpa.app.api.deps.app_config", fake_config
        )
        guard = demo_guard("data_upload")
        # Should not raise even for disabled capability
        guard()

    def test_no_profile_allows_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        contract = DemoContract(disabled_capabilities=["data_upload"])
        fake_config = SimpleNamespace(site_profile=None, demo_contract=contract)
        monkeypatch.setattr(
            "spectra_sherpa.app.api.deps.app_config", fake_config
        )
        guard = demo_guard("data_upload")
        guard()

    def test_403_response_has_contract_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        contract = DemoContract(
            disabled_capabilities=["data_upload"],
            upgrade_url="https://example.com/pricing",
            upgrade_message="Upgrade now!",
            available_plans=["hybrid", "enterprise"],
        )
        fake_config = SimpleNamespace(site_profile="demo", demo_contract=contract)
        monkeypatch.setattr(
            "spectra_sherpa.app.api.deps.app_config", fake_config
        )
        guard = demo_guard("data_upload")
        with pytest.raises(HTTPException) as exc_info:
            guard()

        detail = exc_info.value.detail
        assert detail["upgrade_url"] == "https://example.com/pricing"
        assert detail["available_plans"] == ["hybrid", "enterprise"]
        assert detail["blocked_capability"] == "data_upload"
        assert detail["message"] == "Upgrade now!"


class TestDemoContractConfig:
    """DemoContract integration with AppConfig.to_client_safe()."""

    def test_demo_contract_in_client_config_when_demo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "spectra_sherpa.app.core.config.app_config",
            AppConfig(mode="enterprise", site_profile="demo"),
        )
        from spectra_sherpa.app.core.config import app_config

        result = app_config.to_client_safe()
        assert result["demo"] is not None
        assert "featured_datasets" in result["demo"]
        assert "disabled_capabilities" in result["demo"]
        assert "upgrade_url" in result["demo"]

    def test_demo_contract_absent_when_not_demo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "spectra_sherpa.app.core.config.app_config",
            AppConfig(mode="local"),
        )
        from spectra_sherpa.app.core.config import app_config

        result = app_config.to_client_safe()
        assert result["demo"] is None

    def test_demo_contract_absent_for_production_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "spectra_sherpa.app.core.config.app_config",
            AppConfig(mode="enterprise", site_profile="production"),
        )
        from spectra_sherpa.app.core.config import app_config

        result = app_config.to_client_safe()
        assert result["demo"] is None


class TestDemoContractDefaults:
    """DemoContract has sensible defaults."""

    def test_default_featured_datasets(self) -> None:
        contract = DemoContract()
        assert "diesel_nir" in contract.featured_datasets
        assert "corn_m5" in contract.featured_datasets
        assert len(contract.featured_datasets) == 5

    def test_default_disabled_capabilities(self) -> None:
        contract = DemoContract()
        assert "data_upload" in contract.disabled_capabilities
        assert "project_import" in contract.disabled_capabilities
        assert "llm_config" in contract.disabled_capabilities
        assert "api_key_management" in contract.disabled_capabilities

    def test_default_limits(self) -> None:
        contract = DemoContract()
        assert contract.max_executions_per_session == 25
        assert contract.max_sherpa_interactions == 20

    def test_featured_templates_match_known_ids(self) -> None:
        """featured_templates must reference IDs that exist in the frontend TEMPLATES map."""
        contract = DemoContract()
        # These are the template IDs defined in frontend/src/stores/workflow.ts
        known_template_ids = {
            "pca", "pls_regression", "project1", "ir_opus_analysis",
            "preprocessing", "peak_detection", "exploratory_analysis",
            "classification", "anomaly_detection", "compare_models",
            "calibration_transfer", "data_fusion",
        }
        for tmpl_id in contract.featured_templates:
            assert tmpl_id in known_template_ids, (
                f"featured_template '{tmpl_id}' does not match any known frontend template ID"
            )


class TestDemoAnalyticsEndpoint:
    """GET /config/demo/analytics requires superuser and demo profile."""

    @pytest.fixture
    def _demo_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_config = SimpleNamespace(site_profile="demo")
        monkeypatch.setattr(
            "spectra_sherpa.app.api.v1.routes.config.app_config", fake_config
        )

    @pytest.fixture
    def _non_demo_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_config = SimpleNamespace(site_profile="production")
        monkeypatch.setattr(
            "spectra_sherpa.app.api.v1.routes.config.app_config", fake_config
        )

    @pytest.mark.asyncio
    async def test_non_superuser_gets_403(self, _demo_config) -> None:
        from spectra_sherpa.app.api.v1.routes.config import get_demo_analytics

        user = SimpleNamespace(is_superuser=False)
        with pytest.raises(HTTPException) as exc_info:
            await get_demo_analytics(current_user=user, session=None)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_non_demo_returns_false(self, _non_demo_config) -> None:
        from spectra_sherpa.app.api.v1.routes.config import get_demo_analytics

        user = SimpleNamespace(is_superuser=True)
        result = await get_demo_analytics(current_user=user, session=None)
        assert result == {"demo": False}
