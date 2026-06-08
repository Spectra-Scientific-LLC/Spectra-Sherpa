from __future__ import annotations

import importlib
import os

from spectra_sherpa.app.api.v1.routes.config import _find_or_create_env_path


def test_get_env_file_search_paths_places_home_env_first(monkeypatch, tmp_path):
    from spectra_sherpa import _paths

    home_dir = tmp_path / "home"
    cwd_dir = tmp_path / "cwd"
    data_dir = tmp_path / "data"
    project_root = tmp_path / "repo"
    home_dir.mkdir()
    cwd_dir.mkdir()
    data_dir.mkdir()
    (project_root / "backend").mkdir(parents=True)

    monkeypatch.setattr(_paths.Path, "home", lambda: home_dir)
    monkeypatch.setattr(_paths.Path, "cwd", lambda: cwd_dir)
    monkeypatch.setattr(_paths, "get_default_data_dir", lambda: data_dir)
    monkeypatch.setattr(_paths, "get_project_root", lambda: project_root)

    paths = _paths.get_env_file_search_paths()

    assert paths == [
        (home_dir / ".env").resolve(),
        (cwd_dir / ".env").resolve(),
        (data_dir / ".env").resolve(),
        (project_root / "backend" / ".env").resolve(),
        (project_root / ".env").resolve(),
    ]


def test_load_layered_env_files_uses_home_as_base_and_local_as_override(monkeypatch, tmp_path):
    from spectra_sherpa import _paths

    home_env = tmp_path / "home.env"
    local_env = tmp_path / "local.env"
    home_env.write_text("DEMO_MAX_SHERPA_INTERACTIONS=200\nAPP_MODE=enterprise\n")
    local_env.write_text("DEMO_MAX_SHERPA_INTERACTIONS=250\n")

    monkeypatch.setattr(_paths, "get_env_file_search_paths", lambda: [home_env, local_env])
    monkeypatch.delenv("DEMO_MAX_SHERPA_INTERACTIONS", raising=False)
    monkeypatch.delenv("APP_MODE", raising=False)

    loaded = _paths.load_layered_env_files()

    assert loaded == [home_env, local_env]
    assert os.environ["DEMO_MAX_SHERPA_INTERACTIONS"] == "250"
    assert os.environ["APP_MODE"] == "enterprise"


def test_load_layered_env_files_preserves_existing_environment(monkeypatch, tmp_path):
    from spectra_sherpa import _paths

    home_env = tmp_path / "home.env"
    local_env = tmp_path / "local.env"
    home_env.write_text("APP_MODE=enterprise\n")
    local_env.write_text("APP_MODE=hybrid\n")

    monkeypatch.setattr(_paths, "get_env_file_search_paths", lambda: [home_env, local_env])
    monkeypatch.setenv("APP_MODE", "local")

    _paths.load_layered_env_files()

    assert os.environ["APP_MODE"] == "local"


def test_find_or_create_env_path_ignores_home_env_for_writes(monkeypatch, tmp_path):
    home_env = tmp_path / "home.env"
    repo_env = tmp_path / "repo.env"
    home_env.write_text("APP_MODE=enterprise\n")
    repo_env.write_text("APP_MODE=hybrid\n")

    monkeypatch.setattr(
        "spectra_sherpa._paths.get_local_env_file_search_paths",
        lambda: [repo_env],
    )

    assert _find_or_create_env_path() == str(repo_env)


def test_core_config_loads_layered_env_files(monkeypatch):
    import spectra_sherpa.app.core.config as config
    from spectra_sherpa import _paths

    calls: list[bool] = []

    def _fake_loader(*, preserve_existing: bool = True):
        calls.append(preserve_existing)
        return []

    monkeypatch.setattr("spectra_sherpa._paths.load_layered_env_files", _fake_loader)

    importlib.reload(config)

    assert calls == [True]
    monkeypatch.undo()
    importlib.reload(_paths)
    importlib.reload(config)


def test_core_config_reload_preserves_settings_identity(monkeypatch):
    import spectra_sherpa.app.core.config as config

    original_settings = config.settings
    original_app_config = config.app_config

    try:
        monkeypatch.setenv("MAX_FILE_SIZE_MB", "123")
        monkeypatch.setenv("APP_MODE", "hybrid")

        importlib.reload(config)

        assert config.settings is original_settings
        assert config.settings.max_file_size_mb == 123
        assert config.app_config is original_app_config
        assert config.app_config.mode == "hybrid"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
