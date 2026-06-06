from __future__ import annotations

from urllib.error import URLError

from spectra_sherpa import cli


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_health_url_targets_api_health() -> None:
    assert cli._health_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000/api/v1/health"


def test_open_browser_waits_for_server_before_opening(monkeypatch) -> None:
    calls = {"probe": 0, "opened": []}

    def fake_urlopen(url: str, timeout: float):
        calls["probe"] += 1
        if calls["probe"] < 3:
            raise URLError("not ready")
        return _Response()

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: calls["opened"].append(url))

    cli._open_browser("http://127.0.0.1:8000")

    assert calls["probe"] == 3
    assert calls["opened"] == ["http://127.0.0.1:8000"]
