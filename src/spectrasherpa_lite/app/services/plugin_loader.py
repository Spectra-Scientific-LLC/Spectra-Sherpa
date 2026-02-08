"""
Plugin discovery and loading for SpectraSherpa Lite.

On startup, this module scans for third-party node plugins and registers
them with the DAG node registry.

Plugin locations (checked in order):
1. ``~/.spectrasherpa/plugins/``      — user plugins (pip-installed or manual)
2. ``<data_dir>/plugins/``            — data-dir plugins
3. Python packages with the ``spectrasherpa.plugins`` entry-point group

Each plugin is a Python package containing one or more modules that import
from ``spectrasherpa_lite.sdk`` and use ``@register_node`` to register
their nodes.  The act of importing the module triggers registration.

Example plugin layout::

    ~/.spectrasherpa/plugins/
    └── my_plugin/
        ├── __init__.py          # imports node modules
        └── nodes.py             # @register_node classes

Security
--------
Only ``.py`` files and directories with ``__init__.py`` are loaded.
Plugin code runs with the same privileges as the main app — the user
is responsible for trusting plugins they install.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import logging
import sys
from pathlib import Path

from spectrasherpa_lite._paths import get_default_data_dir

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "spectrasherpa.plugins"


def _get_plugin_dirs() -> list[Path]:
    """Return directories to scan for plugin packages."""
    dirs: list[Path] = []

    # 1. User home plugins directory
    home_plugins = Path.home() / ".spectrasherpa" / "plugins"
    if home_plugins.is_dir():
        dirs.append(home_plugins)

    # 2. Data-dir plugins (may overlap with home in pip-installed mode)
    data_plugins = get_default_data_dir() / "plugins"
    if data_plugins.is_dir() and data_plugins.resolve() != home_plugins.resolve():
        dirs.append(data_plugins)

    return dirs


def _load_directory_plugins(plugin_dir: Path) -> int:
    """
    Load plugins from a filesystem directory.

    Each subdirectory with ``__init__.py`` is treated as a plugin package.
    Standalone ``.py`` files (not starting with ``_``) are also loaded.

    Returns the number of plugins successfully loaded.
    """
    loaded = 0

    # Add plugin dir to sys.path temporarily if not present
    dir_str = str(plugin_dir)
    added_to_path = False
    if dir_str not in sys.path:
        sys.path.insert(0, dir_str)
        added_to_path = True

    try:
        for item in sorted(plugin_dir.iterdir()):
            if item.name.startswith("_") or item.name.startswith("."):
                continue

            if item.is_dir() and (item / "__init__.py").exists():
                # Package plugin
                module_name = item.name
                try:
                    importlib.import_module(module_name)
                    logger.info("Loaded plugin package: %s (from %s)", module_name, plugin_dir)
                    loaded += 1
                except Exception:
                    logger.exception("Failed to load plugin package: %s", module_name)

            elif item.is_file() and item.suffix == ".py":
                # Single-file plugin
                module_name = item.stem
                try:
                    importlib.import_module(module_name)
                    logger.info("Loaded plugin module: %s (from %s)", module_name, plugin_dir)
                    loaded += 1
                except Exception:
                    logger.exception("Failed to load plugin module: %s", module_name)
    finally:
        # Clean up sys.path to avoid pollution
        if added_to_path and dir_str in sys.path:
            sys.path.remove(dir_str)

    return loaded


def _load_entrypoint_plugins() -> int:
    """
    Load plugins registered via Python entry points.

    Plugins can declare themselves in their ``pyproject.toml``::

        [project.entry-points."spectrasherpa.plugins"]
        my_plugin = "my_plugin"

    Returns the number of plugins successfully loaded.
    """
    loaded = 0

    try:
        eps = importlib.metadata.entry_points()
        # Python 3.12+ returns a SelectableGroups; 3.9-3.11 returns a dict
        if hasattr(eps, "select"):
            plugin_eps = eps.select(group=ENTRY_POINT_GROUP)
        else:
            plugin_eps = eps.get(ENTRY_POINT_GROUP, [])

        for ep in plugin_eps:
            try:
                ep.load()
                logger.info("Loaded entry-point plugin: %s", ep.name)
                loaded += 1
            except Exception:
                logger.exception("Failed to load entry-point plugin: %s", ep.name)
    except Exception:
        logger.exception("Error scanning for entry-point plugins")

    return loaded


def discover_plugins() -> int:
    """
    Discover and load all available plugins.

    Called once at application startup from the lifespan handler.
    Returns the total number of plugins loaded.

    Plugin loading is best-effort: individual failures are logged
    but never crash the application.
    """
    total = 0

    # Filesystem plugins
    for plugin_dir in _get_plugin_dirs():
        count = _load_directory_plugins(plugin_dir)
        total += count

    # Entry-point plugins
    total += _load_entrypoint_plugins()

    if total > 0:
        logger.info("Loaded %d plugin(s) total", total)
    else:
        logger.debug("No plugins found")

    return total
