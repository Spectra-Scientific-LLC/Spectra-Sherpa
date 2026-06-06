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

    Populated by the server extension's demo contract at startup; OSS never
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
    """Install a demo policy provider (called by a server extension at startup)."""
    global _demo_policy_provider
    _demo_policy_provider = provider


# ---------------------------------------------------------------------------
# Audit Item 2: demo execution-quota enforcement hook.
#
# The server's per-session execution counter (demo_limits) existed but had
# no call sites, so public demo users could run unlimited workflows.  OSS
# execution entrypoints call ``consume_demo_execution_quota`` (a
# check-and-consume); the server installs a provider wired to
# ``demo_limits.check_demo_execution``.  With no provider installed
# (non-demo / OSS local) it is unlimited and not enforced.
# ---------------------------------------------------------------------------

# Provider takes the user id (or None) and returns ``(allowed, remaining)``.
DemoExecutionQuotaProvider = Callable[[int | None], "tuple[bool, int]"]

_demo_execution_quota_provider: DemoExecutionQuotaProvider | None = None


def consume_demo_execution_quota(user_id: int | None) -> tuple[bool, int]:
    """Atomically check-and-consume one demo execution slot.

    ``(True, -1)`` when no provider is installed (non-demo / OSS local) —
    unlimited, not enforced.  Otherwise the provider (server) returns
    ``(allowed, remaining)`` and has already consumed a slot when allowed.
    """
    if _demo_execution_quota_provider is not None:
        return _demo_execution_quota_provider(user_id)
    return (True, -1)


def set_demo_execution_quota_provider(provider: DemoExecutionQuotaProvider) -> None:
    """Install the demo execution-quota provider (server extension, startup)."""
    global _demo_execution_quota_provider
    _demo_execution_quota_provider = provider


# Provider set for successful-upload quotas. Upload routes reserve before
# reading/processing the body, then either consume on success or release on
# validation/transaction failure. With no provider installed (OSS local and
# non-demo server modes), all three helpers are no-ops/unlimited.
DemoUploadReserveProvider = Callable[[int | None], "tuple[bool, int]"]
DemoUploadConsumeProvider = Callable[[int | None], int]
DemoUploadReleaseProvider = Callable[[int | None], None]

_demo_upload_reserve_provider: DemoUploadReserveProvider | None = None
_demo_upload_consume_provider: DemoUploadConsumeProvider | None = None
_demo_upload_release_provider: DemoUploadReleaseProvider | None = None


def reserve_demo_upload_quota(user_id: int | None) -> tuple[bool, int]:
    """Reserve one demo upload slot, or allow unlimited when not installed."""
    if _demo_upload_reserve_provider is not None:
        return _demo_upload_reserve_provider(user_id)
    return (True, -1)


def consume_reserved_demo_upload_quota(user_id: int | None) -> int:
    """Count a successful upload against a previously reserved slot."""
    if _demo_upload_consume_provider is not None:
        return _demo_upload_consume_provider(user_id)
    return -1


def release_demo_upload_quota_reservation(user_id: int | None) -> None:
    """Release a reserved upload slot after a failed upload/import."""
    if _demo_upload_release_provider is not None:
        _demo_upload_release_provider(user_id)


def set_demo_upload_quota_providers(
    *,
    reserve: DemoUploadReserveProvider,
    consume_reserved: DemoUploadConsumeProvider,
    release: DemoUploadReleaseProvider,
) -> None:
    """Install demo upload-quota providers (server extension, startup)."""
    global _demo_upload_reserve_provider, _demo_upload_consume_provider, _demo_upload_release_provider
    _demo_upload_reserve_provider = reserve
    _demo_upload_consume_provider = consume_reserved
    _demo_upload_release_provider = release


# ---------------------------------------------------------------------------
# Demo rate-limit error-detail provider.
#
# The server's ``demo_limit_error_detail`` knows the contract's rolling
# caps (limit_per_hour / limit_per_day) and the configured upgrade URL.
# OSS quota gates need that structured payload to emit 429s the SPA can
# consume (the banner refreshes its limit refs from the detail). With no
# provider installed (non-demo / OSS local), 429 paths fall back to a
# minimal, OSS-only detail.
# ---------------------------------------------------------------------------

DemoLimitDetailProvider = Callable[[str, int], dict]

_demo_limit_detail_provider: DemoLimitDetailProvider | None = None


def demo_limit_error_detail(limit_type: str, remaining: int) -> dict:
    """Return the structured 429 detail for a demo rate-limit rejection."""
    if _demo_limit_detail_provider is not None:
        return _demo_limit_detail_provider(limit_type, remaining)
    return {
        "limit_type": limit_type,
        "remaining": remaining,
        "message": "Demo rate limit reached.",
    }


def set_demo_limit_detail_provider(provider: DemoLimitDetailProvider) -> None:
    """Install the demo rate-limit detail provider (server extension, startup)."""
    global _demo_limit_detail_provider
    _demo_limit_detail_provider = provider
