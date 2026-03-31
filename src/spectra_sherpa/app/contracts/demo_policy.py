"""Demo restriction policy injection point.

Server injects a demo policy provider during startup when ``SITE_PROFILE=demo``.
OSS code queries it to determine which capabilities are disabled, which node
types are hidden, and which templates are featured — without importing any
demo-specific business logic.

When no provider is installed (local / non-demo modes), the functions return
empty defaults that impose no restrictions.
"""

from __future__ import annotations

from typing import Callable


class DemoPolicy:
    """Read-only snapshot of demo restrictions.

    Populated by spectra-server's ``DemoContract`` at startup; OSS never
    constructs this directly.
    """

    __slots__ = ("disabled_capabilities", "hidden_node_types", "featured_templates", "upgrade_url")

    def __init__(
        self,
        *,
        disabled_capabilities: frozenset[str] = frozenset(),
        hidden_node_types: frozenset[str] = frozenset(),
        featured_templates: tuple[str, ...] = (),
        upgrade_url: str | None = None,
    ) -> None:
        self.disabled_capabilities = disabled_capabilities
        self.hidden_node_types = hidden_node_types
        self.featured_templates = featured_templates
        self.upgrade_url = upgrade_url


DemoPolicyProvider = Callable[[], DemoPolicy]

_demo_policy_provider: DemoPolicyProvider | None = None

# Re-usable empty policy for non-demo modes.
_EMPTY_POLICY = DemoPolicy()


def get_demo_policy() -> DemoPolicy:
    """Return the current demo policy, or an empty one if none is installed."""
    if _demo_policy_provider is not None:
        return _demo_policy_provider()
    return _EMPTY_POLICY


def set_demo_policy_provider(provider: DemoPolicyProvider) -> None:
    """Install a demo policy provider (called by spectra-server at startup)."""
    global _demo_policy_provider
    _demo_policy_provider = provider
