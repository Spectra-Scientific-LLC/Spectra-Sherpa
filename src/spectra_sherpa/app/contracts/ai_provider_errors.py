"""Protocol-contract exception types for the AI service provider boundary.

These exceptions are part of the AIServiceProvider contract: server
implementations raise them, and OSS callers (e.g. ws_handlers.py) catch them.
Relocated from services/ai_provider_errors.py in the ADR-0001 boundary cleanup.
"""

from __future__ import annotations


class SubscriptionRequiredError(Exception):
    """Raised when a feature requires a subscription that the user does not have."""

    def __init__(self, detail: str = "Subscription required"):
        self.detail = detail
        super().__init__(detail)


class SherpaAuthorizationError(Exception):
    """Raised when the deployment key is invalid, revoked, or unauthorized."""

    def __init__(self, detail: str = "Sherpa authorization failed"):
        self.detail = detail
        super().__init__(detail)
