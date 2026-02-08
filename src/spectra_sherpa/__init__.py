"""SpectraSherpa — local-first spectroscopy platform."""
from __future__ import annotations

__version__ = "1.3.3"

import importlib
import importlib.abc
import importlib.machinery
import sys


class _AppAliasFinder(importlib.abc.MetaPathFinder):
    """Redirect ``import app.*`` to ``import spectra_sherpa.app.*``.

    Only activates when ``app`` is NOT already importable on its own
    (i.e. when pip-installed to site-packages, not when running from the
    ``backend/`` source tree).
    """

    _ACTIVE: bool | None = None  # tri-state: None = not yet checked
    _PKG_DIR: str = str(__import__("pathlib").Path(__file__).resolve().parent)

    @classmethod
    def _should_activate(cls) -> bool:
        if cls._ACTIVE is not None:
            return cls._ACTIVE
        # If ``app`` is already importable without us AND lives inside our
        # package directory, don't hijack it (e.g. running from source with
        # spectra_sherpa/app on sys.path).  Any other ``app`` module
        # (e.g. spectrasherpa-server/app/) is not ours — still activate.
        try:
            sys.meta_path.remove(_finder)
            try:
                mod = importlib.import_module("app")
                mod_file = getattr(mod, "__file__", "") or ""
                if mod_file.startswith(cls._PKG_DIR):
                    cls._ACTIVE = False  # it's our own app — no alias needed
                else:
                    cls._ACTIVE = True  # foreign app module — redirect
            except ImportError:
                cls._ACTIVE = True
            finally:
                sys.meta_path.insert(0, _finder)
        except ValueError:
            cls._ACTIVE = True
        return cls._ACTIVE

    def find_module(self, fullname: str, path=None):
        """Python 3.3 compat — delegates to find_spec."""
        spec = self.find_spec(fullname, path)
        return spec.loader if spec else None

    def find_spec(self, fullname: str, path=None, target=None):
        if not self._should_activate():
            return None
        if fullname == "app" or fullname.startswith("app."):
            real = "spectra_sherpa." + fullname
            try:
                real_spec = importlib.util.find_spec(real)
            except (ModuleNotFoundError, ValueError):
                return None
            if real_spec is None:
                return None
            # Return a spec that points to the real module
            return importlib.machinery.ModuleSpec(
                fullname,
                _AliasLoader(real),
                origin=real_spec.origin,
                is_package=real_spec.submodule_search_locations is not None,
            )
        if fullname == "libs" or fullname.startswith("libs."):
            real = "spectra_sherpa." + fullname
            try:
                real_spec = importlib.util.find_spec(real)
            except (ModuleNotFoundError, ValueError):
                return None
            if real_spec is None:
                return None
            return importlib.machinery.ModuleSpec(
                fullname,
                _AliasLoader(real),
                origin=real_spec.origin,
                is_package=real_spec.submodule_search_locations is not None,
            )
        return None


class _AliasLoader(importlib.abc.Loader):
    """Load the real module and inject it under the aliased name."""

    def __init__(self, real_name: str):
        self._real = real_name

    def create_module(self, spec):
        return None  # use default semantics

    def exec_module(self, module):
        real_mod = importlib.import_module(self._real)
        module.__dict__.update(real_mod.__dict__)
        # Preserve subpackage search path so nested imports work
        if hasattr(real_mod, "__path__"):
            module.__path__ = real_mod.__path__
        module.__loader__ = self
        sys.modules[module.__name__] = module


_finder = _AppAliasFinder()
sys.meta_path.insert(0, _finder)
