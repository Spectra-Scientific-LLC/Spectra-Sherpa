"""
Plugin discovery and loading for SpectraSherpa.

On startup, this module scans for third-party plugins and registers
them with the DAG node registry and/or the MCP tool registry.

Plugin locations (checked in order):
1. ``~/.spectra_sherpa/plugins/``     — user plugins (pip-installed or manual)
2. ``<data_dir>/plugins/``            — data-dir plugins
3. Python packages with the ``spectrasherpa.plugins`` entry-point group

Each plugin is a Python package containing one or more modules that use
decorator-based registration.  The act of importing triggers registration:

- ``@register_node``  — registers a DAG workflow node
- ``@register_tool``  — registers an MCP-compatible tool

Example plugin layout::

    ~/.spectra_sherpa/plugins/
    └── my_plugin/
        ├── __init__.py          # imports node/tool modules
        ├── nodes.py             # @register_node classes
        └── tools.py             # @register_tool functions

Security
--------
Only ``.py`` files and directories with ``__init__.py`` are loaded.
Plugin code runs with the same privileges as the main app — the user
is responsible for trusting plugins they install.

All plugin imports run inside ``tool_registry.plugin_context()`` which
forces ``origin=plugin`` on every tool registered during loading —
regardless of whether the plugin uses ``@register_tool`` or
``register_plugin_tool()``.  This ensures plugin tools always get
trust boundary constraints (no ``scope=internal``, forced
``requires_user=True``).
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import logging
import sys
import threading
from pathlib import Path

from spectra_sherpa._paths import get_default_data_dir

logger = logging.getLogger(__name__)

# Serialises all plugin (re-)imports so concurrent saves don't race.
_reload_lock = threading.Lock()

ENTRY_POINT_GROUP = "spectrasherpa.plugins"


def _get_plugin_dirs() -> list[Path]:
    """Return directories to scan for plugin packages."""
    dirs: list[Path] = []

    # 1. User home plugins directory
    home_plugins = Path.home() / ".spectra_sherpa" / "plugins"
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


def reload_plugin_by_path(file_path: Path) -> bool:
    """Import (or re-import) a single plugin ``.py`` file by absolute path.

    Uses a deterministic module name derived from the filename to ensure
    re-import replaces the previous module object.  Thread-safe via
    ``_reload_lock`` — concurrent saves serialise here.

    Returns True on success, False on failure (logged, never raised).
    """
    if not file_path.is_file():
        logger.error("reload_plugin_by_path: file does not exist: %s", file_path)
        return False

    module_name = f"_custom_algo_{file_path.stem}"

    with _reload_lock:
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                logger.error("Could not create module spec for %s", file_path)
                return False

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            logger.info("Loaded plugin file: %s as %s", file_path, module_name)
            return True
        except Exception:
            # Clean up partial module from sys.modules
            sys.modules.pop(module_name, None)
            logger.exception("Failed to load plugin file: %s", file_path)
            return False


def discover_plugins() -> int:
    """
    Discover and load all available plugins.

    Called once at application startup from the lifespan handler.
    Returns the total number of plugins loaded.

    Plugin loading is best-effort: individual failures are logged
    but never crash the application.
    """
    total = 0

    # All plugin imports run inside plugin_context() so that any tool
    # registered (via @register_tool or direct register()) automatically
    # gets origin=plugin and the associated trust constraints.
    from spectra_sherpa.app.services.tools import tool_registry

    with tool_registry.plugin_context():
        # Filesystem plugins
        for plugin_dir in _get_plugin_dirs():
            count = _load_directory_plugins(plugin_dir)
            total += count

        # Entry-point plugins
        total += _load_entrypoint_plugins()

    if total > 0:
        logger.info("Loaded %d plugin(s) total", total)
        logger.info("Tool registry now has %d tool(s) after plugin discovery", len(tool_registry))
    else:
        logger.debug("No plugins found")

    return total
