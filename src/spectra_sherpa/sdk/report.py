"""Reporting namespace for the public SDK."""

from __future__ import annotations

from ._errors import planned


def validation_pack(*args, **kwargs):
    raise planned("ss.report.validation_pack")


__all__ = ["validation_pack"]
