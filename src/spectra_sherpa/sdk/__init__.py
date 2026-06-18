"""
SpectraSherpa SDK public surface.

The top-level package keeps the established node-authoring compatibility
imports while exposing two-tier domain namespaces such as ``data`` and
``preprocess``.
"""

from __future__ import annotations

from . import (
    classify,
    data,
    explore,
    model,
    node,
    pipeline,
    plot,
    preprocess,
    regression,
    report,
    select,
    templates,
    unmix,
    validate,
    workflow,
)
from ._compat import *  # noqa: F403
from ._compat import __all__ as _compat_all

__all__ = [
    *_compat_all,
    "data",
    "preprocess",
    "explore",
    "regression",
    "classify",
    "unmix",
    "select",
    "validate",
    "plot",
    "pipeline",
    "model",
    "workflow",
    "node",
    "report",
    "templates",
]
