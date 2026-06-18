"""Workflow namespace for the public SDK."""

from __future__ import annotations

from ._errors import planned


def load(*args, **kwargs):
    raise planned("ss.workflow.load")


__all__ = ["load"]
