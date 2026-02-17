"""
Built-in tools shipped with SpectraSherpa.

Importing this package triggers registration of all built-in tools
with the global ``tool_registry``.
"""
from __future__ import annotations

from spectra_sherpa.app.services.tools.builtin import spectral  # noqa: F401
from spectra_sherpa.app.services.tools.builtin import workflow  # noqa: F401
