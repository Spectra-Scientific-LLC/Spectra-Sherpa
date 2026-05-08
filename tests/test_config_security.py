from __future__ import annotations

from spectra_sherpa.app.api.v1.routes import config
from spectra_sherpa.app.services import basic_chat


def test_spectrasherpa_url_allows_https_public_cloud_host() -> None:
    assert config._is_allowed_url("https://cloud.spectrascientific.com")
    assert config._is_allowed_url("https://cloud.spectrascientific.com/api/v1")


def test_spectrasherpa_url_blocks_untrusted_private_and_plain_http_targets() -> None:
    assert not config._is_allowed_url("http://cloud.spectrascientific.com")
    assert not config._is_allowed_url("https://192.168.1.100")
    assert not config._is_allowed_url("https://169.254.169.254")


def test_byo_chat_config_is_read_at_request_time(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_ENDPOINT_URL", "https://example.test/v1")
    monkeypatch.setenv("CHAT_ENDPOINT_KEY", "test-key")
    monkeypatch.setenv("CHAT_ENDPOINT_MODEL", "test-model")

    runtime_config = basic_chat.get_config()

    assert runtime_config.url == "https://example.test/v1"
    assert runtime_config.key == "test-key"
    assert runtime_config.model == "test-model"
    assert basic_chat.is_configured()
