from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from spectra_sherpa.app import main


@dataclass
class _FakeAlgo:
    node_type: str
    project_id: int = 1
    slug: str = "algo"


class _FakeResult:
    def __init__(self, algos):
        self._algos = algos

    def scalars(self):
        return self

    def all(self):
        return list(self._algos)


class _FakeSession:
    def __init__(self, algos):
        self._algos = algos

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):  # noqa: ARG002
        return _FakeResult(self._algos)


@pytest.mark.asyncio
async def test_custom_algo_startup_succeeds_when_reload_succeeds(monkeypatch, tmp_path):
    algo = _FakeAlgo(node_type="ualgo.1.ok")

    monkeypatch.setattr(main, "async_session", lambda: _FakeSession([algo]))
    monkeypatch.setattr(
        "spectra_sherpa.app.services.custom_algo_codegen.get_plugin_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.custom_algo_codegen.get_plugin_path",
        lambda _algo: Path(tmp_path / f"{_algo.slug}.py"),
    )

    reloaded: list[str] = []

    def _reload(_algo):
        reloaded.append(_algo.node_type)

    monkeypatch.setattr(
        "spectra_sherpa.app.services.custom_algo_codegen.reload_into_registry",
        _reload,
    )

    await main._load_custom_algo_plugins_or_raise()
    assert reloaded == ["ualgo.1.ok"]


@pytest.mark.asyncio
async def test_custom_algo_startup_fails_fast_with_node_type_context(monkeypatch, tmp_path):
    broken = _FakeAlgo(node_type="ualgo.2.broken")

    monkeypatch.setattr(main, "async_session", lambda: _FakeSession([broken]))
    monkeypatch.setattr(
        "spectra_sherpa.app.services.custom_algo_codegen.get_plugin_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.custom_algo_codegen.get_plugin_path",
        lambda _algo: Path(tmp_path / f"{_algo.slug}.py"),
    )

    def _reload(_algo):
        raise RuntimeError("syntax error in generated plugin")

    monkeypatch.setattr(
        "spectra_sherpa.app.services.custom_algo_codegen.reload_into_registry",
        _reload,
    )

    with pytest.raises(RuntimeError) as exc_info:
        await main._load_custom_algo_plugins_or_raise()

    msg = str(exc_info.value)
    assert "Custom algo startup failed" in msg
    assert "ualgo.2.broken" in msg
