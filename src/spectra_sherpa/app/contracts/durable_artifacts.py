"""Optional durable-artifact hook injected by commercial server deployments."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

DurableArtifactPersister = Callable[..., Awaitable[Any]]

_persister: DurableArtifactPersister | None = None


def set_durable_artifact_persister(persister: DurableArtifactPersister | None) -> None:
    global _persister
    _persister = persister


def get_durable_artifact_persister() -> DurableArtifactPersister | None:
    return _persister
