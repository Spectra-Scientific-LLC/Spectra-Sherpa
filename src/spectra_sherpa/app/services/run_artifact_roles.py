"""Canonical assignments for execution-run artifact lifecycle roles."""

from __future__ import annotations

from collections.abc import Iterable


def attempted_artifact_fields(artifact_uids: Iterable[str]) -> dict[str, list[str]]:
    """Assign attempts and the deprecated compatibility mirror together.

    ``applied_artifact_uids`` predates the explicit attempted/succeeded roles.
    Keeping its write-through value centralized prevents it from acquiring an
    accidental fourth meaning while older databases and clients still carry
    the column.
    """

    attempted = list(artifact_uids)
    return {
        "attempted_artifact_uids": attempted,
        "applied_artifact_uids": list(attempted),
    }
