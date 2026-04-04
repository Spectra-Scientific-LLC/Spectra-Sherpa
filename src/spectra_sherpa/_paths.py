"""Dual-mode path resolution for SpectraSherpa.

When running from a dev checkout (``pyproject.toml`` + ``frontend/`` exist
two levels up from the package), paths resolve relative to the repo root.
When pip-installed, user data goes to ``~/.spectra_sherpa/``.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

# The directory that contains *this* file (spectra_sherpa/)
_PACKAGE_DIR = Path(__file__).resolve().parent


def _is_dev_checkout() -> bool:
    """True when running from the repo source tree (not pip-installed)."""
    repo_root = _PACKAGE_DIR.parents[1]  # src/ -> Refactored/
    return (repo_root / "pyproject.toml").is_file() and (repo_root / "frontend").is_dir()


def get_project_root() -> Path | None:
    """Return the repo root when in a dev checkout, else None."""
    if _is_dev_checkout():
        return _PACKAGE_DIR.parents[1]
    return None


def get_package_root() -> Path:
    """Return the ``spectra_sherpa/`` directory (always valid)."""
    return _PACKAGE_DIR


def get_default_data_dir() -> Path:
    """Return the default data directory.

    - Dev checkout: ``<repo>/data``
    - Pip-installed: ``~/.spectra_sherpa/``
    - Always overridable via ``DATA_DIR`` env var.
    """
    env = os.getenv("DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    root = get_project_root()
    if root is not None:
        return root / "data"
    return Path.home() / ".spectra_sherpa"


def get_static_dir() -> Path:
    """Return the directory containing the pre-built frontend distribution."""
    return _PACKAGE_DIR / "static"


def get_env_file_search_paths() -> list[Path]:
    """Return candidate ``.env`` paths from lowest to highest precedence.

    The shared user-level ``~/.env`` acts as a global base layer. Repository-
    or workspace-specific files override it later in the list.
    """
    paths = [Path.home() / ".env", Path.cwd() / ".env"]
    data = get_default_data_dir()
    paths.append(data / ".env")
    root = get_project_root()
    if root is not None:
        paths.append(root / "backend" / ".env")  # legacy dev location
        paths.append(root / ".env")
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def get_local_env_file_search_paths() -> list[Path]:
    """Return writable local override ``.env`` paths, excluding ``~/.env``."""
    home_env = (Path.home() / ".env").expanduser().resolve()
    return [path for path in get_env_file_search_paths() if path != home_env]


def load_layered_env_files(*, preserve_existing: bool = True) -> list[Path]:
    """Load ``.env`` files in precedence order and return the files that existed.

    Later files override earlier files. Existing process environment variables
    are preserved by default so shell/direnv exports still win over file-based
    config.
    """
    protected_keys = set(os.environ) if preserve_existing else set()
    loaded_paths: list[Path] = []

    for env_path in get_env_file_search_paths():
        if not env_path.is_file():
            continue
        loaded_paths.append(env_path)
        for key, value in dotenv_values(env_path).items():
            if value is None or key in protected_keys:
                continue
            os.environ[key] = value

    return loaded_paths
