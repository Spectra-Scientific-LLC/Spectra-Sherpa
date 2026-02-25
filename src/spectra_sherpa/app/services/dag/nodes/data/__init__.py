"""Data source nodes for loading spectral data.

All data source nodes attach SpectraMeta metadata for traceability.
"""

# Re-export for backward compatibility (tests monkeypatch these attributes)
from spectra_sherpa.app.lib.scp_compat import HAS_SCP  # noqa: F401

from . import (  # noqa: F401
    loaders,
    references,
    source,
    synthetic,
    transforms,
)
from .source import DataSourceNode

__all__ = ["DataSourceNode", "HAS_SCP"]
