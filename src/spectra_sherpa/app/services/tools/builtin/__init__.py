"""
Built-in tools shipped with SpectraSherpa.

Importing this package triggers registration of all built-in tools
with the global ``tool_registry``.
"""

from __future__ import annotations

from spectra_sherpa.app.services.tools.builtin import (
    datasets,  # noqa: F401
    plugin_gen,  # noqa: F401
    spectral,  # noqa: F401
    workflow,  # noqa: F401
)
