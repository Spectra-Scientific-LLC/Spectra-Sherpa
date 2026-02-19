"""Dual-mode path resolution for SpectraSherpa.

When running from a dev checkout (``pyproject.toml`` + ``frontend/`` exist
two levels up from the package), paths resolve relative to the repo root.
When pip-installed, user data goes to ``~/.spectra_sherpa/``.
"""

from __future__ import annotations

import os
from pathlib import Path

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
    """Return candidate paths for ``.env`` files (first match wins).

    1. Current working directory
    2. Data directory
    3. Package root (for dev checkouts)
    """
    paths = [Path.cwd() / ".env"]
    data = get_default_data_dir()
    paths.append(data / ".env")
    root = get_project_root()
    if root is not None:
        paths.append(root / "backend" / ".env")  # legacy dev location
        paths.append(root / ".env")
    return paths
