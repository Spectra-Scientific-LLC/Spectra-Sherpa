from __future__ import annotations

import importlib
from pathlib import Path

from spectra_sherpa.app.api.v1.routes.health import health_check
from spectra_sherpa.app.services import plugin_loader


def test_discover_plugins_records_failures(monkeypatch, tmp_path: Path) -> None:
    bad_plugin = tmp_path / "broken_plugin.py"
    bad_plugin.write_text("raise RuntimeError('broken on import')\n", encoding="utf-8")

    monkeypatch.setattr(plugin_loader, "_get_plugin_dirs", lambda: [tmp_path])
    monkeypatch.setattr(plugin_loader, "_load_entrypoint_plugins", lambda: 0)

    plugin_loader.plugin_load_failures.clear()
    importlib.invalidate_caches()

    loaded = plugin_loader.discover_plugins()

    assert loaded == 0
    assert plugin_loader.plugin_load_failures
    assert plugin_loader.plugin_load_failures[0]["plugin"] == "broken_plugin"
    assert "broken on import" in plugin_loader.plugin_load_failures[0]["reason"]


async def test_health_reports_plugin_discovery_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        plugin_loader,
        "plugin_load_failures",
        [{"plugin": "broken_plugin", "reason": "broken on import"}],
    )

    result = await health_check()

    assert result["status"] == "degraded"
    assert result["plugin_failure_count"] == 1
