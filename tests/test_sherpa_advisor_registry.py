from __future__ import annotations

from spectra_sherpa.app.services import sherpa_advisor


def test_get_sherpa_advisor_defaults_to_disabled_provider(monkeypatch):
    sherpa_advisor.reset_sherpa_advisor()
    monkeypatch.setattr("spectra_sherpa.app.services.spectrasherpa.spectrasherpa_config.api_key", None)

    advisor = sherpa_advisor.get_sherpa_advisor()

    assert type(advisor).__name__ == "DisabledAIProvider"
    assert advisor.is_available is False


def test_get_sherpa_advisor_uses_deployment_proxy_when_api_key_present(monkeypatch):
    sherpa_advisor.reset_sherpa_advisor()
    monkeypatch.setattr("spectra_sherpa.app.services.spectrasherpa.spectrasherpa_config.api_key", "dk_test_123")

    advisor = sherpa_advisor.get_sherpa_advisor()

    assert type(advisor).__name__ == "DeploymentAIProvider"
    assert advisor.is_available is True
