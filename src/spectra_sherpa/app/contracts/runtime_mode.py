"""Explicit product runtime policy, without importing or discovering extensions.

An extension registers its policy before constructing core configuration. Merely
installing a distribution never enables a mode or relaxes authentication.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeModePolicy:
    name: str
    implicit_loopback_identity: bool = False
    rate_limits: bool = True


_policies: dict[str, RuntimeModePolicy] = {}


def register_runtime_mode(policy: RuntimeModePolicy) -> None:
    if not policy.name or policy.name in {"local", "enterprise"}:
        raise ValueError("An extension cannot replace a core runtime mode")
    existing = _policies.get(policy.name)
    if existing is not None and existing != policy:
        raise ValueError(f"Runtime mode {policy.name!r} already has a different policy")
    _policies[policy.name] = policy


def runtime_mode_policy(name: str) -> RuntimeModePolicy | None:
    return _policies.get(name)


def validate_runtime_mode(name: str) -> str:
    if name not in {"local", "enterprise"} and name not in _policies:
        raise ValueError(
            f"Unsupported APP_MODE={name!r}. Use local for OSS, or the owning product's "
            "entry point to install its runtime policy."
        )
    return name
